"""Exercise the real writer/reader hand-off without contacting an LLM."""

import importlib
import hashlib
import json

import pytest

from genkai.literature.surface.artifacts import run_surface_extraction
from genkai.modeling.checklist import _read_json_records
from genkai.modeling.mapping import _load_relations


def test_writer_emits_one_record_per_line_and_can_be_registered(tmp_path, monkeypatch):
    module = importlib.import_module(
        "genkai.literature.surface.extraction.extract_surface_relations"
    )
    source = tmp_path / "input.json"
    source.write_text(json.dumps({
        "a": {"Title": "氧化物", "Text": "First line\nSecond line"},
        "b": {"Title": "Second paper", "Text": "CO adsorption"},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(module, "chat_completion", lambda *a, **k: '{"materials":["CeO2"]}')
    output = tmp_path / "relations.jsonl"
    module.extract_relations(str(source), str(output))

    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["title"] == "氧化物"
    assert records[0]["text"] == "First line\nSecond line"
    artifact = run_surface_extraction(output, tmp_path / "run")
    assert artifact.metadata["record_count"] == 2


@pytest.mark.parametrize("layout", ["jsonl", "pretty-stream", "array"])
def test_saved_readers_accept_legacy_records_and_register_canonical_jsonl(tmp_path, layout):
    records = [
        {"id": "a", "title": "A", "extraction": {"materials": ["CeO2"]}},
        {"id": "b", "title": "B", "extraction": {"materials": ["SnO2"]}},
    ]
    if layout == "array":
        text = json.dumps(records, indent=2)
    else:
        indent = 2 if layout == "pretty-stream" else None
        text = "\n\n".join(json.dumps(record, indent=indent) for record in records)
    source = tmp_path / "legacy.jsonl"
    source.write_text(text + "\n", encoding="utf-8")
    before = source.read_bytes()

    assert [row["id"] for row in _load_relations(str(source))] == ["a", "b"]
    assert _read_json_records(str(source)) == records
    root = tmp_path / "run"
    artifact = run_surface_extraction(source, root)
    assert artifact.metadata["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert [json.loads(line) for line in (root / artifact.path).read_text(
        encoding="utf-8"
    ).splitlines()] == records
    assert source.read_bytes() == before


@pytest.mark.parametrize("content", [
    '{"id":"ok","extraction":{}}\n{"broken":',
    '{"extraction":{}}\n42\n',
    '{"extraction":[]}\n',
])
def test_invalid_saved_extraction_does_not_create_a_run(tmp_path, content):
    source = tmp_path / "bad.jsonl"
    source.write_text(content, encoding="utf-8")
    root = tmp_path / "run"
    with pytest.raises(ValueError):
        run_surface_extraction(source, root)
    assert not root.exists()
