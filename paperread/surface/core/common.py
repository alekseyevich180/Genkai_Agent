from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import openai


for _parent in Path(__file__).resolve().parents:
    if (_parent / "genkai_api_config.py").is_file():
        sys.path.insert(0, str(_parent))
        break

from genkai_api_config import get_model, install_openai_compat


install_openai_compat(openai)


def chat_completion(prompt: str, model: str | None = None, temperature: float = 0) -> str:
    delays = (5, 15, 45)
    last_error: Exception | None = None
    for attempt in range(len(delays) + 1):
        try:
            response = openai.ChatCompletion.create(
                model=model or get_model(),
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )
            return response.choices[0].message["content"]
        except Exception as exc:  # noqa: BLE001 - compatibility wrapper exposes provider-specific errors.
            last_error = exc
            error_name = exc.__class__.__name__.lower()
            error_text = str(exc).lower()
            retryable = any(
                token in error_name or token in error_text
                for token in ("ratelimit", "rate limit", "timeout", "connect", "temporar")
            )
            if not retryable or attempt >= len(delays):
                raise
            time.sleep(delays[attempt])
    raise RuntimeError("chat completion failed") from last_error


def load_records(input_path: str) -> list[dict[str, Any]]:
    with open(input_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    records: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        items = payload.items()
    elif isinstance(payload, list):
        items = [(str(idx), entry) for idx, entry in enumerate(payload, start=1)]
    else:
        raise ValueError("Input JSON must be either a list or a dict.")

    for record_id, entry in items:
        if not isinstance(entry, dict):
            continue
        title = (
            entry.get("Title")
            or entry.get("title")
            or entry.get("name")
            or ""
        )
        raw_text = (
            entry.get("Procedure")
            or entry.get("procedure")
            or entry.get("Text")
            or entry.get("text")
            or entry.get("Abstract")
            or entry.get("abstract")
            or entry.get("content")
            or ""
        )
        if isinstance(raw_text, list):
            texts = [str(item).strip() for item in raw_text if str(item).strip()]
        else:
            texts = [str(raw_text).strip()] if str(raw_text).strip() else []

        if not texts and title:
            texts = [title]

        records.append({"id": str(record_id), "title": str(title).strip(), "texts": texts})
    return records


def parse_markdown_table(table_text: str, expected_columns: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw_line in table_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.split("|")[1:-1]]
        if not parts:
            continue
        if all(set(part) <= {"-", ":"} for part in parts):
            continue
        if parts == expected_columns:
            continue
        if len(parts) != len(expected_columns):
            continue
        rows.append(dict(zip(expected_columns, parts)))
    return rows


def extract_json_block(text: str) -> Any:
    fenced = re.search(r"```json\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    for pattern in (r"(\{.*\})", r"(\[.*\])"):
        match = re.search(pattern, text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(1))
    raise ValueError("Could not locate a valid JSON block in model output.")
