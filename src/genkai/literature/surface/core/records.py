"""Read surface relation records, including the historical pretty-JSON format."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_relation_records(path: str | Path) -> list[dict[str, Any]]:
    """Read JSONL or migrate concatenated JSON objects / a JSON array in memory.

    Validate the entire input before consumers create artifacts. New writers use
    one object per line; accepting old layouts here does not rewrite the source.
    """
    content = Path(path).read_text(encoding="utf-8-sig")
    records: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(content):
        while index < len(content) and content[index].isspace():
            index += 1
        if index == len(content):
            break
        payload, index = decoder.raw_decode(content, index)
        for record in payload if isinstance(payload, list) else [payload]:
            if not isinstance(record, dict):
                raise ValueError(f"Surface relation record must be a JSON object: {path}")
            if "extraction" in record and not isinstance(record["extraction"], dict):
                raise ValueError(f"Surface relation extraction must be a JSON object: {path}")
            records.append(record)
    return records
