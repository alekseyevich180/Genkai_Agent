from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from paperread.surface.experience.parameter_registry import (
    DEFAULT_MATERIAL_CLASS_DIR,
    DEFAULT_REGISTRY_MARKDOWN_PATH,
    DEFAULT_REGISTRY_PATH,
    build_surface_parameter_registry,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a reusable surface parameter registry from paperread material-class experience files."
    )
    parser.add_argument(
        "--material-class-dir",
        default=str(DEFAULT_MATERIAL_CLASS_DIR),
        help="Directory containing paperread material_classes/*.json files.",
    )
    parser.add_argument(
        "--output-json",
        default=str(DEFAULT_REGISTRY_PATH),
        help="Output JSON registry path.",
    )
    parser.add_argument(
        "--output-md",
        default=str(DEFAULT_REGISTRY_MARKDOWN_PATH),
        help="Output Markdown registry path.",
    )
    args = parser.parse_args()

    registry = build_surface_parameter_registry(
        material_class_dir=Path(args.material_class_dir),
        output_json_path=Path(args.output_json),
        output_markdown_path=Path(args.output_md),
    )
    print(json.dumps({
        "json_path": str(Path(args.output_json)),
        "markdown_path": str(Path(args.output_md)),
        "class_count": len(registry.get("class_profiles", {})),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
