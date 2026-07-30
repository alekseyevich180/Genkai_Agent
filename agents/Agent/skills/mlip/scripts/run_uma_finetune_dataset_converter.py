#!/usr/bin/env python3
"""Run FAIRChem's converter with an LMDB map size compatible with Genkai."""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import runpy
import sys
from pathlib import Path
from typing import Any

import lmdb


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Compatibility wrapper for create_uma_finetune_dataset.py"
    )
    parser.add_argument("--converter", required=True, type=Path)
    return parser.parse_known_args()


def main() -> int:
    args, converter_args = parse_args()
    converter = args.converter.resolve()
    if not converter.is_file():
        raise SystemExit(f"ERROR: converter does not exist: {converter}")

    map_size = int(
        os.environ.get("UMA_FINETUNE_LMDB_MAP_SIZE_BYTES", str(16 * 1024**3))
    )
    if map_size <= 0:
        raise SystemExit("ERROR: UMA_FINETUNE_LMDB_MAP_SIZE_BYTES must be positive")

    start_method = mp.get_start_method(allow_none=True)
    if start_method is None:
        mp.set_start_method("fork")
    elif start_method != "fork":
        raise SystemExit(
            "ERROR: LMDB compatibility wrapper requires Linux multiprocessing=fork"
        )

    original_open = lmdb.open

    def open_with_compatible_map_size(*open_args: Any, **kwargs: Any) -> Any:
        requested = kwargs.get("map_size")
        if requested is not None and int(requested) > map_size:
            kwargs["map_size"] = map_size
        return original_open(*open_args, **kwargs)

    lmdb.open = open_with_compatible_map_size
    print(
        "FAIRChem ASE-LMDB compatibility: "
        f"maximum writable map_size={map_size} bytes",
        flush=True,
    )

    sys.argv = [str(converter), *converter_args]
    runpy.run_path(str(converter), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
