#!/usr/bin/env bash
# Generic Genkai PJM launcher for UMA/fairchem fine-tuning or checkpoint resume.
# Submit with: pjsub submit_uma_finetuning.sh

#PJM -N uma_finetune
#PJM -L rscgrp=b-batch
#PJM -L gpu=1
#PJM -L elapse=72:00:00
#PJM -j
#PJM -S

set -euo pipefail

runtime_dir="${UMA_RUNTIME_DIR:-/home/pj24001724/ku40000345/wu/UMA-campare}"
venv_dir="${UMA_VENV_DIR:-${runtime_dir}/.venv_uma}"
python_bin="${UMA_PYTHON_BIN:-${venv_dir}/bin/python}"
fairchem_bin="${UMA_FINETUNE_BIN:-${venv_dir}/bin/fairchem}"

work_dir="${UMA_FINETUNE_WORK_DIR:-${PJM_O_WORKDIR:-${MATCLAW_SESSION_DIR:-${PWD}}}}"
if [[ ! -d "${work_dir}" ]]; then
    echo "ERROR: 微调项目目录不存在：${work_dir}" >&2
    exit 1
fi
work_dir="$(cd "${work_dir}" && pwd -P)"

mode="${UMA_FINETUNE_MODE:-train}"
config_file="${UMA_FINETUNE_CONFIG:-${work_dir}/data/lmdb/uma_sm_finetune_template.yaml}"
run_dir="${UMA_FINETUNE_RUN_DIR:-${work_dir}/runs}"
device="${UMA_FINETUNE_DEVICE:-cuda}"
threads="${UMA_FINETUNE_THREADS:-40}"
epochs="${UMA_FINETUNE_EPOCHS:-}"
steps="${UMA_FINETUNE_STEPS:-}"
learning_rate="${UMA_FINETUNE_LR:-}"
batch_size="${UMA_FINETUNE_BATCH_SIZE:-}"
max_neighbors="${UMA_FINETUNE_MAX_NEIGHBORS:-}"
run_id="${UMA_FINETUNE_ID:-}"
base_model_path="${UMA_FINETUNE_BASE_MODEL_PATH:-}"
base_model_sha256="${UMA_FINETUNE_BASE_MODEL_SHA256:-}"

case "${mode}" in
    train|resume) ;;
    *)
        echo "ERROR: UMA_FINETUNE_MODE 必须是 train 或 resume" >&2
        exit 1
        ;;
esac
case "${device,,}" in
    cuda|cpu) ;;
    *)
        echo "ERROR: UMA_FINETUNE_DEVICE 必须是 cuda 或 cpu" >&2
        exit 1
        ;;
esac
if [[ ! "${threads}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: UMA_FINETUNE_THREADS 必须是正整数" >&2
    exit 1
fi
if [[ -n "${epochs}" && -n "${steps}" ]]; then
    echo "ERROR: UMA_FINETUNE_EPOCHS 和 UMA_FINETUNE_STEPS 只能设置一个" >&2
    exit 1
fi
if [[ ! -x "${python_bin}" ]]; then
    echo "ERROR: Python 环境不存在：${python_bin}" >&2
    exit 1
fi
if [[ ! -x "${fairchem_bin}" ]]; then
    echo "ERROR: fairchem CLI 不存在：${fairchem_bin}" >&2
    exit 1
fi
if [[ "${config_file}" != /* ]]; then
    config_file="${work_dir}/${config_file}"
fi
if [[ ! -f "${config_file}" ]]; then
    echo "ERROR: 微调配置不存在：${config_file}" >&2
    exit 1
fi
if [[ -n "${base_model_path}" || -n "${base_model_sha256}" ]]; then
    if [[ -z "${base_model_path}" || -z "${base_model_sha256}" ]]; then
        echo "ERROR: UMA checkpoint path and SHA-256 must be provided together" >&2
        exit 1
    fi
    if [[ "${base_model_path}" != /* ]]; then
        base_model_path="${work_dir}/${base_model_path}"
    fi
    if [[ ! -f "${base_model_path}" ]]; then
        echo "ERROR: verified UMA base checkpoint does not exist: ${base_model_path}" >&2
        exit 1
    fi
    actual_base_model_sha256="$(sha256sum "${base_model_path}" | awk '{print $1}')"
    if [[ "${actual_base_model_sha256}" != "${base_model_sha256}" ]]; then
        echo "ERROR: UMA base checkpoint SHA-256 mismatch: ${base_model_path}" >&2
        exit 1
    fi
fi
if [[ "${run_dir}" != /* ]]; then
    run_dir="${work_dir}/${run_dir}"
fi

hydra_args=()
if [[ -n "${epochs}" ]]; then
    hydra_args+=("epochs=${epochs}" "steps=null")
elif [[ -n "${steps}" ]]; then
    hydra_args+=("epochs=null" "steps=${steps}")
fi
if [[ -n "${learning_rate}" ]]; then
    hydra_args+=("lr=${learning_rate}")
fi
if [[ -n "${batch_size}" ]]; then
    hydra_args+=("batch_size=${batch_size}")
fi
if [[ -n "${max_neighbors}" ]]; then
    hydra_args+=("max_neighbors=${max_neighbors}")
fi
if [[ -n "${run_id}" ]]; then
    hydra_args+=("job.run_name=${run_id}")
fi
if [[ -n "${base_model_path}" ]]; then
    hydra_args+=(
        "runner.train_eval_unit.model.checkpoint_location=${base_model_path}"
    )
fi
if [[ -n "${UMA_FINETUNE_ARGS:-}" ]]; then
    read -r -a extra_hydra_args <<< "${UMA_FINETUNE_ARGS}"
    hydra_args+=("${extra_hydra_args[@]}")
fi

command=("${fairchem_bin}" -c "${config_file}")
launch_overrides=("job.device_type=${device^^}")
if [[ "${mode}" == "train" ]]; then
    launch_overrides+=("job.run_dir=${run_dir}")
fi
launch_overrides+=("${hydra_args[@]}")
command+=("${launch_overrides[@]}")
hydra_check=(
    "${python_bin}" "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/validate_uma_finetune_launch.py"
    --config "${config_file}"
    --mode "${mode}"
)
if [[ -n "${base_model_path}" ]]; then
    hydra_check+=(
        --expected-checkpoint "${base_model_path}"
        --expected-checkpoint-sha256 "${base_model_sha256}"
    )
fi
for override in "${launch_overrides[@]}"; do
    hydra_check+=(--override "${override}")
done

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
if [[ "${UMA_FINETUNE_WANDB:-0}" != "1" ]]; then
    export WANDB_MODE=disabled
fi
export OMP_NUM_THREADS="${threads}"
export OMP_STACKSIZE="${UMA_OMP_STACKSIZE:-64M}"
export MKL_NUM_THREADS="${threads}"
export OPENBLAS_NUM_THREADS="${threads}"
export NUMEXPR_NUM_THREADS="${threads}"

if [[
    "${mode}" == "train"
    && "${HF_HUB_OFFLINE}" == "1"
    && -z "${base_model_path}"
]]; then
    base_model="$(
        sed -n 's/^[[:space:]]*base_model_name:[[:space:]]*//p' "${config_file}" \
            | head -n 1 \
            | tr -d "\"'"
    )"
    if [[ -n "${base_model}" ]]; then
        shopt -s nullglob
        model_paths=(
            "${FAIRCHEM_CACHE_DIR}"/models--facebook--UMA/snapshots/*/checkpoints/"${base_model}.pt"
        )
        shopt -u nullglob
        if [[ "${#model_paths[@]}" -eq 0 ]]; then
            echo "ERROR: 离线缓存中没有基础模型 ${base_model}" >&2
            echo "       仅在用户批准下载后设置 UMA_ALLOW_DOWNLOAD=1" >&2
            exit 1
        fi
    fi
fi

echo "UMA fine-tuning preflight"
echo "  mode        : ${mode}"
echo "  runtime     : ${runtime_dir}"
echo "  venv        : ${venv_dir}"
echo "  work_dir    : ${work_dir}"
echo "  config      : ${config_file}"
echo "  run_dir     : ${run_dir}"
echo "  python      : ${python_bin}"
echo "  fairchem    : ${fairchem_bin}"
echo "  base_model  : ${base_model_path:-configured by YAML}"
echo "  device      : ${device}"
echo "  threads     : ${threads}"
echo "  cache       : ${FAIRCHEM_CACHE_DIR}"
echo "  offline     : ${HF_HUB_OFFLINE}"
echo "  wandb_mode  : ${WANDB_MODE:-configured by YAML/environment}"
printf '  command     :'
printf ' %q' "${command[@]}"
printf '\n'
printf '  hydra_check :'
printf ' %q' "${hydra_check[@]}"
printf '\n'

"${hydra_check[@]}"

if [[ "${UMA_FINETUNE_DRY_RUN:-0}" == "1" ]]; then
    echo "DRY RUN PASS: 未启动训练，也未提交后台任务"
    exit 0
fi

if [[ "${device,,}" == "cuda" ]]; then
    "${python_bin}" -c \
        'import torch
assert torch.cuda.is_available(), "CUDA不可用"
print("CUDA:", torch.cuda.get_device_name(0))'
fi

mkdir -p "${run_dir}"
cd "${work_dir}"
exec "${command[@]}"
