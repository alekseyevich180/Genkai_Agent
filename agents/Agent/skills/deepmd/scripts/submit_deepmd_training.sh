#!/usr/bin/env bash
# Generic Genkai PJM launcher for DeePMD-kit training and model operations.
# Submit with: pjsub submit_deepmd_training.sh

#PJM -N deepmd_train
#PJM -L rscgrp=a-pj24001724
#PJM -L node=1
#PJM --mpi proc=1
#PJM -L elapse=168:00:00
#PJM -j
#PJM -S

set -euo pipefail

runtime_dir="${DEEPMD_RUNTIME_DIR:-/home/pj24001724/ku40000345/wu/deepmd_kit}"
training_root="${DEEPMD_TRAINING_ROOT:-/home/pj24001724/ku40000345/wu/deepmd_train}"
venv_dir="${DEEPMD_VENV_DIR:-${runtime_dir}/dp_venv}"
dp_bin="${DEEPMD_BIN:-${venv_dir}/bin/dp}"
python_module="${DEEPMD_PYTHON_MODULE:-python/3.12.11}"

###############################################################################
# CALCULATION CONFIGURATION
# Override these values with comma-separated DEEPMD_* variables via pjsub -x.
###############################################################################

# Use a dedicated directory containing the input JSON, data references, models,
# and outputs for one task.
work_dir="${DEEPMD_WORK_DIR:-${PJM_O_WORKDIR:-${MATCLAW_SESSION_DIR:-${PWD}}}}"

command="${DEEPMD_COMMAND:-train}"
backend="${DEEPMD_BACKEND:-tensorflow}"
threads="${DEEPMD_THREADS:-15}"

# Simple whitespace-separated arguments only. Use a copied configuration file
# or task-specific launcher when an argument itself contains whitespace.
command_args=()
if [[ -n "${DEEPMD_ARGS:-}" ]]; then
    read -r -a command_args <<< "${DEEPMD_ARGS}"
fi

# Space-separated files or directories that must exist before execution.
# Paths may be absolute or relative to work_dir.
required_paths=()
if [[ -n "${DEEPMD_REQUIRED_PATHS:-}" ]]; then
    read -r -a required_paths <<< "${DEEPMD_REQUIRED_PATHS}"
fi

###############################################################################
# PREFLIGHT
###############################################################################

if [[ ! -d "${runtime_dir}" ]]; then
    echo "ERROR: DeePMD runtime directory does not exist: ${runtime_dir}" >&2
    exit 1
fi
if [[ ! -d "${training_root}" ]]; then
    echo "ERROR: DeePMD training root does not exist: ${training_root}" >&2
    exit 1
fi
if [[ ! -f "${venv_dir}/bin/activate" ]]; then
    echo "ERROR: DeePMD virtual environment does not exist: ${venv_dir}" >&2
    exit 1
fi
if [[ ! -d "${work_dir}" ]]; then
    echo "ERROR: Work/output directory does not exist: ${work_dir}" >&2
    exit 1
fi
if [[ ! "${threads}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: DEEPMD_THREADS must be a positive integer, got: ${threads}" >&2
    exit 1
fi

work_dir="$(cd "${work_dir}" && pwd -P)"

for required_path in "${required_paths[@]}"; do
    if [[ "${required_path}" = /* ]]; then
        resolved_required_path="${required_path}"
    else
        resolved_required_path="${work_dir}/${required_path}"
    fi
    if [[ ! -e "${resolved_required_path}" ]]; then
        echo "ERROR: Required input path does not exist: ${resolved_required_path}" >&2
        exit 1
    fi
done

backend_args=()
case "${backend}" in
    tensorflow|tf)
        ;;
    pytorch|pt)
        backend_args=(--pt)
        ;;
    jax)
        backend_args=(--jax)
        ;;
    paddle|pd)
        backend_args=(--pd)
        ;;
    *)
        echo "ERROR: DEEPMD_BACKEND must be tensorflow, pytorch, jax, or paddle; got: ${backend}" >&2
        exit 1
        ;;
esac

if [[ ! -x "${dp_bin}" ]]; then
    echo "ERROR: DeePMD executable does not exist: ${dp_bin}" >&2
    exit 1
fi
if [[ -z "${command}" ]]; then
    echo "ERROR: DEEPMD_COMMAND must not be empty" >&2
    exit 1
fi
executable="${dp_bin}"
run_args=("${backend_args[@]}" "${command}" "${command_args[@]}")

echo "DeePMD training/model-operation preflight"
echo "  runtime       : ${runtime_dir}"
echo "  training_root : ${training_root}"
echo "  python_module : ${python_module}"
echo "  venv          : ${venv_dir}"
echo "  work_dir      : ${work_dir}"
echo "  output_dir    : ${work_dir}"
echo "  backend       : ${backend}"
echo "  command       : ${command}"
echo "  threads       : ${threads}"
if [[ "${#required_paths[@]}" -gt 0 ]]; then
    printf '  required      :'
    printf ' %q' "${required_paths[@]}"
    printf '\n'
fi
printf '  exec          :'
printf ' %q' "${executable}" "${run_args[@]}"
printf '\n'

# Validate paths and the exact command without loading modules or computing.
if [[ "${DEEPMD_DRY_RUN:-0}" == "1" ]]; then
    echo "DRY RUN PASS: no module was loaded and no calculation was started"
    exit 0
fi

###############################################################################
# ENVIRONMENT AND EXECUTION
###############################################################################

# This reproduces deepmd_kit/use.sh with an absolute venv path. The absolute
# path avoids depending on the caller's HOME value in agent or batch shells.
module purge
module load "${python_module}"
# shellcheck disable=SC1091
source "${venv_dir}/bin/activate"

export VIRTUAL_ENV="${venv_dir}"
export PATH="${venv_dir}/bin:${PATH}"
unset PYTHONHOME || true

export OMP_NUM_THREADS="${threads}"
export DP_INTRA_OP_PARALLELISM_THREADS="${threads}"
export DP_INTER_OP_PARALLELISM_THREADS=1
export TF_NUM_INTRAOP_THREADS="${threads}"
export TF_NUM_INTEROP_THREADS=1
export TF_INTRA_OP_PARALLELISM_THREADS="${threads}"
export TF_INTER_OP_PARALLELISM_THREADS=1
export MKL_NUM_THREADS="${threads}"
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

cd "${work_dir}"
exec "${executable}" "${run_args[@]}"
