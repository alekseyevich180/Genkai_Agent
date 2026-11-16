#!/usr/bin/env bash
# Install SAGE (the surface-modeling branch of Genkai) into a Python virtual environment.
#
# The checkout this script lives in is installed in editable mode, so `git pull` updates the code
# without reinstalling. Run it again after dependencies change.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./install.sh [options]

  (no options)              modeling + tests: structure generation with the mock calculator
  --mlip                    also install fairchem-core (UMA) for the MLIP screening tests
  --torch-index-url URL     install torch from this index first, matching the server CUDA,
                            e.g. https://download.pytorch.org/whl/cu121 (use with --mlip)
  --materials-project       also install mp-api (downloads from Materials Project; needs MP_API_KEY)
  --python PY               interpreter for the venv (default: python3.12, python3.11, python3, python)
  --venv DIR                venv location (default: .venv next to this script)
  --installer auto|uv|pip   package installer (default: auto = uv when available, else pip)
  --system-site-packages    let the venv see packages of the base Python (e.g. a site-provided torch)
  --no-build-isolation      build with the setuptools/wheel already in the venv
  --offline                 do not contact package indexes (uv --offline / pip --no-index)
  --skip-check              skip the post-install check
  --dry-run                 print the commands without running them
  -h, --help                show this help

Examples
  ./install.sh
  ./install.sh --mlip --torch-index-url https://download.pytorch.org/whl/cu121
  ./install.sh --mlip --system-site-packages      # reuse a torch provided by the cluster module
EOF
}

PYTHON=""
VENV=""
INSTALLER="auto"
MLIP=0
MATERIALS_PROJECT=0
TORCH_INDEX=""
SYSTEM_SITE=0
NO_BUILD_ISOLATION=0
OFFLINE=0
SKIP_CHECK=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python) PYTHON="${2:?--python needs a value}"; shift 2 ;;
        --venv) VENV="${2:?--venv needs a value}"; shift 2 ;;
        --installer) INSTALLER="${2:?--installer needs a value}"; shift 2 ;;
        --mlip) MLIP=1; shift ;;
        --materials-project) MATERIALS_PROJECT=1; shift ;;
        --torch-index-url) TORCH_INDEX="${2:?--torch-index-url needs a value}"; shift 2 ;;
        --system-site-packages) SYSTEM_SITE=1; shift ;;
        --no-build-isolation) NO_BUILD_ISOLATION=1; shift ;;
        --offline) OFFLINE=1; shift ;;
        --skip-check) SKIP_CHECK=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-$ROOT/.venv}"

run() {
    echo "+ $*" >&2
    if [[ $DRY_RUN -eq 0 ]]; then
        "$@"
    fi
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

python_ok() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

# --- interpreter -------------------------------------------------------------
if [[ -z "$PYTHON" ]]; then
    for candidate in python3.12 python3.11 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then
            PYTHON="$candidate"
            break
        fi
    done
    [[ -n "$PYTHON" ]] || die "no Python >= 3.11 found; load a Python module or pass --python /path/to/python3.12"
else
    command -v "$PYTHON" >/dev/null 2>&1 || [[ -x "$PYTHON" ]] || die "--python $PYTHON not found"
    python_ok "$PYTHON" || die "$PYTHON is older than Python 3.11"
fi

# --- installer ---------------------------------------------------------------
case "$INSTALLER" in
    auto) if command -v uv >/dev/null 2>&1; then INSTALLER="uv"; else INSTALLER="pip"; fi ;;
    uv) command -v uv >/dev/null 2>&1 || die "--installer uv given but uv is not on PATH" ;;
    pip) ;;
    *) die "--installer must be auto, uv or pip" ;;
esac

extras="test"
if [[ $MLIP -eq 1 ]]; then extras="$extras,mlip"; fi
if [[ $MATERIALS_PROJECT -eq 1 ]]; then extras="$extras,materials-project"; fi

if [[ -n "$TORCH_INDEX" && $MLIP -eq 0 ]]; then
    echo "NOTE: --torch-index-url only matters together with --mlip; installing torch anyway." >&2
fi

echo "SAGE install"
echo "  checkout : $ROOT"
echo "  venv     : $VENV"
echo "  python   : $PYTHON ($("$PYTHON" -c 'import sys; print(sys.version.split()[0])'))"
echo "  installer: $INSTALLER"
echo "  extras   : $extras"

# --- virtual environment -----------------------------------------------------
# Windows (Git Bash) venvs use Scripts/ instead of bin/.
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) BIN="$VENV/Scripts"; VPY="$BIN/python.exe"; ROOT_ARG="$(cygpath -m "$ROOT")" ;;
    *) BIN="$VENV/bin"; VPY="$BIN/python"; ROOT_ARG="$ROOT" ;;
esac

if [[ -x "$VPY" ]]; then
    echo "Reusing the existing virtual environment $VENV"
else
    venv_args=()
    [[ $SYSTEM_SITE -eq 1 ]] && venv_args+=(--system-site-packages)
    if [[ "$INSTALLER" == "uv" ]]; then
        [[ $OFFLINE -eq 1 ]] && venv_args+=(--offline)
        run uv venv --python "$PYTHON" ${venv_args[@]+"${venv_args[@]}"} "$VENV"
    else
        run "$PYTHON" -m venv ${venv_args[@]+"${venv_args[@]}"} "$VENV"
    fi
fi

pip_install() {
    local args=()
    [[ $NO_BUILD_ISOLATION -eq 1 ]] && args+=(--no-build-isolation)
    if [[ "$INSTALLER" == "uv" ]]; then
        [[ $OFFLINE -eq 1 ]] && args+=(--offline)
        run uv pip install --python "$VPY" ${args[@]+"${args[@]}"} "$@"
    else
        [[ $OFFLINE -eq 1 ]] && args+=(--no-index)
        run "$VPY" -m pip install ${args[@]+"${args[@]}"} "$@"
    fi
}

# --- packages ----------------------------------------------------------------
if [[ -n "$TORCH_INDEX" ]]; then
    pip_install torch --index-url "$TORCH_INDEX"
fi
pip_install -e "$ROOT_ARG[$extras]"

# --- check -------------------------------------------------------------------
if [[ $SKIP_CHECK -eq 0 && $DRY_RUN -eq 0 ]]; then
    echo
    echo "Checking the installation ..."
    "$BIN/genkai-surface" methods >/dev/null || die "genkai-surface does not run"
    "$VPY" -c 'import genkai, importlib.metadata as m; print("  genkai", m.version("genkai"), "from", genkai.__file__)'
    (cd "$ROOT" && "$VPY" -m pytest -q -p no:cacheprovider tests/modeling/test_surface_jobs.py) \
        || die "the quick test failed; see the output above"
    if [[ $MLIP -eq 1 ]]; then
        "$VPY" - <<'EOF' || die "fairchem-core is not importable"
import importlib.metadata as m

import torch

from genkai.modeling.surface.calculators import available_uma_tasks

print("  fairchem-core", m.version("fairchem-core"), "| torch", torch.__version__,
      "| CUDA available:", torch.cuda.is_available())
tasks = available_uma_tasks()
print("  UMA task heads:", ", ".join(tasks) if tasks else "none found")
print("  No UMA model was downloaded or loaded. The first UMA run downloads the checkpoint from")
print("  Hugging Face, which usually needs an accepted model licence and HF_TOKEN (or `hf auth login` / `huggingface-cli login`).")
EOF
    fi
fi

cat <<EOF

Done. Next steps:
  source "$BIN/activate"
  genkai-surface methods                                   # what can be built
  genkai-surface run examples/surface_jobs/05_sam_sno2_butanoic.yaml
  python scripts/run_modeling_smoke.py                     # all methods, mock calculator (~5 min)
  python -m pytest -q                                      # tests
EOF
if [[ $MLIP -eq 1 ]]; then
    cat <<'EOF'
MLIP (only where real calculations are authorized; choose the UMA task head first):
  python scripts/run_modeling_smoke.py --profile server --device cuda --uma-task <task head>
EOF
fi
