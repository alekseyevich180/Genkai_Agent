#!/usr/bin/env bash
# Generic GENKAI PJM launcher for an UMA/fairchem Python calculation.
# Submit with: pjsub submit_uma_calculation.sh

#PJM -N uma_calc
#PJM -L rscgrp=b-batch
#PJM -L gpu=1
#PJM -L elapse=72:00:00
#PJM -j
#PJM -S

set -euo pipefail

runtime_dir="${UMA_RUNTIME_DIR:-/home/pj24001724/ku40000345/wu/UMA-campare}"
venv_dir="${UMA_VENV_DIR:-${runtime_dir}/.venv_uma}"
python_bin="${UMA_PYTHON_BIN:-${venv_dir}/bin/python}"

###############################################################################
# CALCULATION CONFIGURATION
# Override these values with UMA_* environment variables passed by pjsub -x.
###############################################################################

# The work directory is also the output directory. Submit from a dedicated,
# self-contained run directory to keep inputs, results, and PJM logs together.
work_dir="${UMA_WORK_DIR:-${PJM_O_WORKDIR:-${MATCLAW_SESSION_DIR:-${PWD}}}}"

# Python file relative to work_dir, or an absolute path.
python_script="${UMA_PYTHON_SCRIPT:-run_gpu.py}"

# Used for preflight validation and logging. The target Python script must use
# the same device itself (for example through its own --device argument).
device="${UMA_DEVICE:-cuda}"

# Controls host-side PyTorch/OpenMP work.
threads="${UMA_THREADS:-40}"

# Optional simple space-separated override for automation. Prefer a task config
# or entrypoint edit when an individual argument contains spaces.
python_args=()
if [[ -n "${UMA_PYTHON_ARGS:-}" ]]; then
    read -r -a python_args <<< "${UMA_PYTHON_ARGS}"
fi

###############################################################################
# ENVIRONMENT AND PREFLIGHT
###############################################################################

# Activate the virtual environment without relying on an interactive shell.
export VIRTUAL_ENV="${venv_dir}"
export PATH="${venv_dir}/bin:${PATH}"
unset PYTHONHOME || true

export FAIRCHEM_CACHE_DIR="${runtime_dir}/.fairchem_cache"
export MPLCONFIGDIR="${runtime_dir}/.matplotlib_cache"
if [[ "${UMA_ALLOW_DOWNLOAD:-0}" == "1" ]]; then
    export HF_HUB_OFFLINE=0
else
    export HF_HUB_OFFLINE=1
fi
export OMP_NUM_THREADS="${threads}"
export OMP_STACKSIZE="${UMA_OMP_STACKSIZE:-64M}"
export MKL_NUM_THREADS="${threads}"
export OPENBLAS_NUM_THREADS="${threads}"
export NUMEXPR_NUM_THREADS="${threads}"

if [[ ! -x "${python_bin}" ]]; then
    echo "ERROR: Python环境不存在：${python_bin}" >&2
    exit 1
fi
if [[ ! -d "${work_dir}" ]]; then
    echo "ERROR: 工作/输出目录不存在：${work_dir}" >&2
    exit 1
fi

work_dir="$(cd "${work_dir}" && pwd -P)"
if [[ "${python_script}" = /* ]]; then
    entrypoint="${python_script}"
else
    entrypoint="${work_dir}/${python_script}"
fi
if [[ ! -f "${entrypoint}" ]]; then
    echo "ERROR: Python入口不存在：${entrypoint}" >&2
    exit 1
fi

echo "UMA calculation preflight"
echo "  runtime    : ${runtime_dir}"
echo "  venv       : ${venv_dir}"
echo "  work_dir   : ${work_dir}"
echo "  output_dir : ${work_dir}"
echo "  python     : ${python_bin}"
echo "  entrypoint : ${entrypoint}"
echo "  device     : ${device}"
echo "  threads    : ${threads}"
echo "  OMP stack  : ${OMP_STACKSIZE} per thread"
echo "  cache      : ${FAIRCHEM_CACHE_DIR}"
printf '  command    :'
printf ' %q' "${python_bin}" -u "${entrypoint}" "${python_args[@]}"
printf '\n'

# Pre-submit/local validation without starting the calculation:
# UMA_DRY_RUN=1 bash submit_uma_calculation.sh
if [[ "${UMA_DRY_RUN:-0}" == "1" ]]; then
    echo "DRY RUN PASS: 未启动计算，也未提交后台任务"
    exit 0
fi

if [[ "${device}" == "cuda" ]]; then
    "${python_bin}" -c \
        'import torch; assert torch.cuda.is_available(), "CUDA不可用"; print("CUDA:", torch.cuda.get_device_name(0))'
fi

cd "${work_dir}"
exec "${python_bin}" -u "${entrypoint}" "${python_args[@]}"
