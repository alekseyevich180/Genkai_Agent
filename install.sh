#!/usr/bin/env bash
# Install SAGE (the surface-modeling branch of Genkai) into a Python virtual environment.
#
# The checkout this script lives in is installed in editable mode, so `git pull` updates the code
# without reinstalling. Run it again after dependencies change.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./install.sh [options]

  (no options)              install Genkai, detect existing MLIPs, generate config and task files
  --configure-only          reuse Genkai; update configuration/project runtime dependencies only
  --config FILE             MLIP configuration file (default: genkai.yaml next to this script)
  --mace-python PATH        Python of an already installed MACE environment
  --mace-model PATH         local MACE checkpoint
  --mace-launcher PATH      optional environment activation wrapper
  --uma-python PATH         Python of an already installed UMA environment
  --uma-model NAME_OR_PATH  UMA model name or local checkpoint (default: uma-s-1p2)
  --uma-launcher PATH       optional environment activation wrapper
  --default-mlip mace|uma   default MLIP profile
  --device cpu|cuda         default device of newly configured profiles (default: cuda)
  --non-interactive         accept detected environments; never prompt
  --skip-prepare            write config/tasks without preparing MLIP project dependencies
  --mlip                    compatibility alias: connect existing MLIPs; never install them
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
  ./install.sh --mace-python /path/to/env/bin/python --mace-model /path/to/model.model
  ./install.sh --uma-python /path/to/env/bin/python --default-mlip uma

This script never installs MLIPs, PyTorch, CUDA or models. Install your MLIP yourself first.
Genkai creates separate project runtimes that inherit the installed backend.
EOF
}

PYTHON=""
VENV=""
INSTALLER="auto"
CONFIGURE_ONLY=0
CONFIG=""
SETUP_ARGS=()
MATERIALS_PROJECT=0
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
        --mlip) shift ;;
        --configure-only) CONFIGURE_ONLY=1; shift ;;
        --config) CONFIG="${2:?--config needs a value}"; shift 2 ;;
        --mace-python|--mace-model|--mace-launcher|--uma-python|--uma-model|--uma-launcher|--default-mlip|--device)
            SETUP_ARGS+=("$1" "${2:?option needs a value}"); shift 2 ;;
        --non-interactive|--skip-prepare) SETUP_ARGS+=("$1"); shift ;;
        --materials-project) MATERIALS_PROJECT=1; shift ;;
        --torch-index-url) echo "ERROR: MLIP/PyTorch installation is no longer part of install.sh. Configure your existing environment with --mace-python or --uma-python." >&2; exit 2 ;;
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
CONFIG="${CONFIG:-$ROOT/genkai.yaml}"

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
if [[ $MATERIALS_PROJECT -eq 1 ]]; then extras="$extras,materials-project"; fi


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

if [[ $CONFIGURE_ONLY -eq 1 && ! -x "$VPY" && $DRY_RUN -eq 0 ]]; then
    die "Genkai is not installed in $VENV; run ./install.sh first"
fi
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
if [[ $CONFIGURE_ONLY -eq 0 ]]; then
    pip_install -e "$ROOT_ARG[$extras]"
fi

# --- check -------------------------------------------------------------------
if [[ $SKIP_CHECK -eq 0 && $DRY_RUN -eq 0 ]]; then
    echo
    echo "Checking the installation ..."
    "$BIN/genkai-surface" methods >/dev/null || die "genkai-surface does not run"
    "$VPY" -c 'import genkai, importlib.metadata as m; print("  genkai", m.version("genkai"), "from", genkai.__file__)'
    (cd "$ROOT" && "$VPY" -m pytest -q -p no:cacheprovider tests/modeling/test_surface_jobs.py) \
        || die "the quick test failed; see the output above"
fi

# The setup command only inherits existing backends and installs Genkai's base dependencies.
[[ $OFFLINE -eq 1 ]] && SETUP_ARGS+=(--offline)
[[ $NO_BUILD_ISOLATION -eq 1 ]] && SETUP_ARGS+=(--no-build-isolation)
[[ $SKIP_CHECK -eq 1 ]] && SETUP_ARGS+=(--skip-check)
if [[ ! -t 0 || ! -t 1 ]]; then SETUP_ARGS+=(--non-interactive); fi
run "$VPY" -m genkai.modeling.surface.setup --config "$CONFIG" --installer "$INSTALLER" ${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}

cat <<EOF

Done. Next steps:
  $ROOT/genkai methods
  $ROOT/genkai doctor                                      # check MLIP profiles, no model loading
  Edit $CONFIG and tasks/<method>.yaml, then:
  $ROOT/genkai check tasks/<method>.yaml
  $ROOT/genkai run tasks/<method>.yaml

No MLIP, PyTorch, CUDA or model was installed. Existing user task files were preserved.
EOF
