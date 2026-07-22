#!/usr/bin/env bash
# Generic Genkai PJM launcher for a MACE Python calculation.
# Submit with: pjsub submit_mace_calculation.sh

#PJM -N mace_calc
#PJM -L rscgrp=b-batch
#PJM -L gpu=1
#PJM -L elapse=72:00:00
#PJM -j
#PJM -S

set -euo pipefail

runtime_dir="${MACE_RUNTIME_DIR:-/home/pj24001724/ku40000345/wu/MACE}"
venv_dir="${MACE_VENV_DIR:-${runtime_dir}/.venv}"
python_bin="${MACE_PYTHON_BIN:-${venv_dir}/bin/python}"

###############################################################################
# CALCULATION CONFIGURATION
# Override these values with comma-separated MACE_* variables via pjsub -x.
###############################################################################

# Keep one calculation and all of its outputs in one self-contained directory.
work_dir="${MACE_WORK_DIR:-${PJM_O_WORKDIR:-${MATCLAW_SESSION_DIR:-${PWD}}}}"

# May be relative to work_dir or absolute. The bundled generic entrypoint is the
# default; a task-specific Python program can be supplied by Genkai_Agent.
python_script="${MACE_PYTHON_SCRIPT:-${runtime_dir}/scripts/run_mace_calculation.py}"

device="${MACE_DEVICE:-cuda}"
model="${MACE_MODEL:-small}"
threads="${MACE_THREADS:-40}"

# Simple whitespace-separated arguments only. For complex values, use a copied
# task configuration or a task-specific Python entrypoint.
python_args=()
if [[ -n "${MACE_PYTHON_ARGS:-}" ]]; then
    read -r -a python_args <<< "${MACE_PYTHON_ARGS}"
fi

###############################################################################
# ENVIRONMENT AND PREFLIGHT
###############################################################################

export VIRTUAL_ENV="${venv_dir}"
export PATH="${venv_dir}/bin:${PATH}"
unset PYTHONHOME || true

# Keep model and plotting caches in the shared MACE installation.
export XDG_CACHE_HOME="${MACE_CACHE_DIR:-${runtime_dir}/.cache}"
export MPLCONFIGDIR="${MACE_MPLCONFIGDIR:-${runtime_dir}/.matplotlib-cache}"
export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1
export MACE_DEVICE="${device}"
export MACE_MODEL="${model}"
export MACE_OUTPUT_DIR="${work_dir}"

export OMP_NUM_THREADS="${threads}"
export OMP_STACKSIZE="${MACE_OMP_STACKSIZE:-64M}"
export MKL_NUM_THREADS="${threads}"
export OPENBLAS_NUM_THREADS="${threads}"
export NUMEXPR_NUM_THREADS="${threads}"

if [[ ! -x "${python_bin}" ]]; then
    echo "ERROR: MACE Python environment does not exist: ${python_bin}" >&2
    exit 1
fi
if [[ ! -d "${work_dir}" ]]; then
    echo "ERROR: Work/output directory does not exist: ${work_dir}" >&2
    exit 1
fi

work_dir="$(cd "${work_dir}" && pwd -P)"
export MACE_OUTPUT_DIR="${work_dir}"
if [[ "${python_script}" = /* ]]; then
    entrypoint="${python_script}"
else
    entrypoint="${work_dir}/${python_script}"
fi
if [[ ! -f "${entrypoint}" ]]; then
    echo "ERROR: Python entrypoint does not exist: ${entrypoint}" >&2
    exit 1
fi
if [[ "${device}" != "cpu" && "${device}" != "cuda" ]]; then
    echo "ERROR: MACE_DEVICE must be cpu or cuda, got: ${device}" >&2
    exit 1
fi
if [[ ! "${threads}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: MACE_THREADS must be a positive integer, got: ${threads}" >&2
    exit 1
fi

echo "MACE calculation preflight"
echo "  runtime    : ${runtime_dir}"
echo "  venv       : ${venv_dir}"
echo "  work_dir   : ${work_dir}"
echo "  output_dir : ${work_dir}"
echo "  python     : ${python_bin}"
echo "  entrypoint : ${entrypoint}"
echo "  model      : ${model}"
echo "  device     : ${device}"
echo "  threads    : ${threads}"
echo "  OMP stack  : ${OMP_STACKSIZE} per thread"
echo "  cache      : ${XDG_CACHE_HOME}/mace"
printf '  command    :'
printf ' %q' "${python_bin}" -u "${entrypoint}" "${python_args[@]}"
printf '\n'

# Validate paths and the exact command without computing or submitting.
if [[ "${MACE_DRY_RUN:-0}" == "1" ]]; then
    echo "DRY RUN PASS: no calculation was started"
    exit 0
fi

if [[ "${device}" == "cuda" ]]; then
    "${python_bin}" -c \
        'import torch; assert torch.cuda.is_available(), "CUDA is unavailable"; print("CUDA:", torch.cuda.get_device_name(0))'
fi

cd "${work_dir}"
exec "${python_bin}" -u "${entrypoint}" "${python_args[@]}"
