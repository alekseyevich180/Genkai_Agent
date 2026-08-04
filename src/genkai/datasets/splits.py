"""Dataset split grouping and leakage checks."""

from __future__ import annotations

from typing import Any


def find_cross_split_duplicates(
    split_fingerprints: dict[str, dict[str, list[str]]],
) -> list[dict[str, Any]]:
    duplicates: list[dict[str, Any]] = []
    split_names = list(split_fingerprints)
    for left_index, left in enumerate(split_names):
        for right in split_names[left_index + 1 :]:
            shared = sorted(
                set(split_fingerprints[left]).intersection(split_fingerprints[right])
            )
            for fingerprint in shared:
                duplicates.append(
                    {
                        "fingerprint": fingerprint,
                        "splits": [left, right],
                        "left_locations": split_fingerprints[left][fingerprint],
                        "right_locations": split_fingerprints[right][fingerprint],
                    }
                )
    return duplicates
