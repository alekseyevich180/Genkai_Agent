#!/usr/bin/env bash
# Developer helper; all paths and model settings come from the user configuration.
set -euo pipefail

if [[ $# -lt 2 || ${1:-} == --help ]]; then
  echo "Usage: bash scripts/mlip-python.sh <profile> <python arguments>"
  echo "Example: bash scripts/mlip-python.sh mace -m genkai.modeling.surface.sam_search --help"
  if [[ ${1:-} == --help ]]; then exit 0; else exit 2; fi
fi

genkai_backend=$1
shift
genkai_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPATH="$genkai_root/src${PYTHONPATH:+:$PYTHONPATH}"

genkai_python="${GENKAI_PYTHON:-$genkai_root/.venv/bin/python}"
if [[ ! -x "$genkai_python" && -x "$genkai_root/.venv/Scripts/python.exe" ]]; then
  genkai_python="$genkai_root/.venv/Scripts/python.exe"
fi
if [[ ! -x "$genkai_python" ]]; then
  echo "Run ./install.sh first, or set GENKAI_PYTHON to the Genkai interpreter." >&2
  exit 2
fi
exec "$genkai_python" -m genkai.modeling.surface.mlip_config \
  --config "${GENKAI_CONFIG:-$genkai_root/genkai.yaml}" "$genkai_backend" "$@"
