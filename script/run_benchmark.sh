#!/usr/bin/env bash
# Benchmark wrapper for MatCreator.
#
# Contract: ./run_benchmark.sh <workspace_dir> <prompt_file> <output_file>
#
# Environment variables (optional):
#   LLM_MODEL    - Model name
#   LLM_API_KEY  - API key
#   LLM_BASE_URL - API base URL
#   MAX_TURNS    - Max agent turns (default: 50)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WORKSPACE="$1"
PROMPT_FILE="$2"
OUTPUT_FILE="$3"

PROMPT=$(cat "$PROMPT_FILE")

# Use the matcreator CLI in non-interactive mode, output JSON
python3 "$SCRIPT_DIR/start_agent.py" run \
    --workspace "$WORKSPACE" \
    -p "$PROMPT" \
    --output-format json \
    --max-turns "${MAX_TURNS:-50}" \
    -o "$OUTPUT_FILE"
