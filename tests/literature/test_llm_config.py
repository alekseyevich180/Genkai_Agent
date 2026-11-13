from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[2]


def _reload_llm_module():
    sys.modules.pop("genkai.llm", None)
    return importlib.import_module("genkai.llm")


def test_llm_module_imports_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    module = _reload_llm_module()

    assert module.get_api_key() == ""


def test_model_provider_prefix_is_normalized(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    module = _reload_llm_module()

    assert module.get_model() == "gpt-4o-mini"


def test_openai_client_is_constructed_lazily(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")

    with patch("openai.OpenAI") as constructor:
        module = _reload_llm_module()
        constructor.assert_not_called()

        module.make_client()

    constructor.assert_called_once_with(api_key="")


def test_old_genkai_api_config_import_has_no_source_consumers() -> None:
    consumers = []
    for source_root in (ROOT / "paperread", ROOT / "src"):
        for path in source_root.rglob("*.py"):
            if "genkai_api_config" in path.read_text(encoding="utf-8"):
                consumers.append(path.relative_to(ROOT).as_posix())

    assert consumers == []
