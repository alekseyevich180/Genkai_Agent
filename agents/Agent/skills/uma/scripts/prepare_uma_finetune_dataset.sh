#!/usr/bin/env bash
# Audit ASE inputs, convert them to ASE-LMDB, and generate UMA fine-tuning YAML.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
skill_dir="$(cd "${script_dir}/.." && pwd -P)"

runtime_dir="${UMA_RUNTIME_DIR:-/home/pj24001724/ku40000345/wu/UMA-campare}"
venv_dir="${UMA_VENV_DIR:-${runtime_dir}/.venv_uma}"
python_bin="${UMA_PYTHON_BIN:-${venv_dir}/bin/python}"
config_root="${UMA_FINETUNE_CONFIG_ROOT:-${skill_dir}/assets/fairchem-core-2.21.0}"

work_dir="${UMA_FINETUNE_WORK_DIR:-${MATCLAW_SESSION_DIR:-${PWD}}}"
if [[ ! -d "${work_dir}" ]]; then
    echo "ERROR: 微调项目目录不存在：${work_dir}" >&2
    exit 1
fi
work_dir="$(cd "${work_dir}" && pwd -P)"

train_dir="${UMA_FINETUNE_TRAIN_DIR:-${work_dir}/data/train}"
val_dir="${UMA_FINETUNE_VAL_DIR:-${work_dir}/data/val}"
test_dir="${UMA_FINETUNE_TEST_DIR:-${work_dir}/data/test}"
output_dir="${UMA_FINETUNE_OUTPUT_DIR:-${work_dir}/data/lmdb}"
audit_report="${UMA_FINETUNE_AUDIT_REPORT:-${work_dir}/metadata/uma_finetune_data_audit.json}"
verify_report="${UMA_FINETUNE_VERIFY_REPORT:-${work_dir}/metadata/uma_finetune_dataset_verification.json}"
uma_task="${UMA_FINETUNE_TASK:-oc25}"
regression_tasks="${UMA_FINETUNE_REGRESSION_TASKS:-ef}"
base_model="${UMA_FINETUNE_BASE_MODEL:-uma-s-1p2}"
num_workers="${UMA_FINETUNE_NUM_WORKERS:-1}"
min_distance="${UMA_FINETUNE_MIN_DISTANCE:-0.6}"
reject_distance="${UMA_FINETUNE_REJECT_DISTANCE:-0.4}"
lmdb_map_size="${UMA_FINETUNE_LMDB_MAP_SIZE_BYTES:-17179869184}"

if [[ "${train_dir}" != /* ]]; then
    train_dir="${work_dir}/${train_dir}"
fi
if [[ "${val_dir}" != /* ]]; then
    val_dir="${work_dir}/${val_dir}"
fi
if [[ "${test_dir}" != /* ]]; then
    test_dir="${work_dir}/${test_dir}"
fi
if [[ "${output_dir}" != /* ]]; then
    output_dir="${work_dir}/${output_dir}"
fi
if [[ "${audit_report}" != /* ]]; then
    audit_report="${work_dir}/${audit_report}"
fi
if [[ "${verify_report}" != /* ]]; then
    verify_report="${work_dir}/${verify_report}"
fi

case "${uma_task}" in
    omol|odac|oc20|oc25|omat|omc) ;;
    *)
        echo "ERROR: fairchem-core 2.21.0 便捷转换器不支持 UMA task：${uma_task}" >&2
        echo "       当前可用：omol、odac、oc20、oc25、omat、omc；oc22 需要单独验证配置。" >&2
        exit 1
        ;;
esac
case "${regression_tasks}" in
    e|ef|efs) ;;
    *)
        echo "ERROR: UMA_FINETUNE_REGRESSION_TASKS 必须是 e、ef 或 efs" >&2
        exit 1
        ;;
esac
if [[ ! "${num_workers}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: UMA_FINETUNE_NUM_WORKERS 必须是正整数" >&2
    exit 1
fi
if [[ ! "${lmdb_map_size}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: UMA_FINETUNE_LMDB_MAP_SIZE_BYTES 必须是正整数" >&2
    exit 1
fi
if [[ ! -x "${python_bin}" ]]; then
    echo "ERROR: Python 环境不存在：${python_bin}" >&2
    exit 1
fi
if [[ ! -d "${train_dir}" || ! -d "${val_dir}" ]]; then
    echo "ERROR: train/val 数据目录不存在：${train_dir} / ${val_dir}" >&2
    exit 1
fi

train_dir="$(cd "${train_dir}" && pwd -P)"
val_dir="$(cd "${val_dir}" && pwd -P)"
test_enabled=0
if [[ -d "${test_dir}" ]]; then
    test_dir="$(cd "${test_dir}" && pwd -P)"
    test_enabled=1
elif [[ -n "${UMA_FINETUNE_TEST_DIR:-}" ]]; then
    echo "ERROR: 显式指定的 test 数据目录不存在：${test_dir}" >&2
    exit 1
fi
output_dir="$(realpath -m -- "${output_dir}")"
audit_report="$(realpath -m -- "${audit_report}")"
verify_report="$(realpath -m -- "${verify_report}")"
case "${audit_report}" in
    "${train_dir}"/*|"${val_dir}"/*|"${test_dir}"/*|"${output_dir}"/*)
        echo "ERROR: 审计报告不能写入 train、val、test 或尚未生成的 LMDB 目录" >&2
        exit 1
        ;;
esac
case "${verify_report}" in
    "${train_dir}"/*|"${val_dir}"/*|"${test_dir}"/*|"${output_dir}"/*)
        echo "ERROR: 转换验证报告不能写入 train、val、test 或 LMDB 目录" >&2
        exit 1
        ;;
esac

dataset_script="${UMA_FINETUNE_DATASET_SCRIPT:-}"
if [[ -z "${dataset_script}" ]]; then
    mapfile -t candidates < <(
        "${python_bin}" -c \
            'from importlib.util import find_spec
from pathlib import Path
spec = find_spec("fairchem")
if spec and spec.submodule_search_locations:
    for root in spec.submodule_search_locations:
        candidate = Path(root) / "core/scripts/create_uma_finetune_dataset.py"
        if candidate.is_file():
            print(candidate.resolve())'
    )
    if [[ "${#candidates[@]}" -ne 1 ]]; then
        echo "ERROR: 无法唯一定位 create_uma_finetune_dataset.py" >&2
        exit 1
    fi
    dataset_script="${candidates[0]}"
fi
if [[ ! -f "${dataset_script}" ]]; then
    echo "ERROR: UMA 数据转换脚本不存在：${dataset_script}" >&2
    exit 1
fi

required_templates=(
    "configs/uma/finetune/uma_sm_finetune_template.yaml"
    "configs/uma/finetune/data/uma_conserving_data_task_energy.yaml"
    "configs/uma/finetune/data/uma_conserving_data_task_energy_force.yaml"
    "configs/uma/finetune/data/uma_conserving_data_task_energy_force_stress.yaml"
)
for template in "${required_templates[@]}"; do
    if [[ ! -f "${config_root}/${template}" ]]; then
        echo "ERROR: 缺少 fairchem 2.21.0 配置模板：${config_root}/${template}" >&2
        exit 1
    fi
done

audit_command=(
    "${python_bin}" "${script_dir}/validate_uma_finetune_data.py"
    --train-dir "${train_dir}"
    --val-dir "${val_dir}"
    --regression-tasks "${regression_tasks}"
    --min-distance "${min_distance}"
    --reject-distance "${reject_distance}"
    --report "${audit_report}"
)
if [[ "${test_enabled}" == "1" ]]; then
    audit_command+=(--test-dir "${test_dir}")
fi
prepare_command=(
    "${python_bin}" "${script_dir}/run_uma_finetune_dataset_converter.py"
    --converter "${dataset_script}"
    --train-dir "${train_dir}"
    --val-dir "${val_dir}"
    --output-dir "${output_dir}"
    --uma-task "${uma_task}"
    --regression-tasks "${regression_tasks}"
    --base-model "${base_model}"
    --num-workers "${num_workers}"
)
verify_command=(
    "${python_bin}" "${script_dir}/verify_uma_finetune_dataset.py"
    --output-dir "${output_dir}"
    --uma-task "${uma_task}"
    --regression-tasks "${regression_tasks}"
    --base-model "${base_model}"
    --report "${verify_report}"
)

export VIRTUAL_ENV="${venv_dir}"
export PATH="${venv_dir}/bin:${PATH}"
unset PYTHONHOME || true
export FAIRCHEM_CACHE_DIR="${runtime_dir}/.fairchem_cache"
export MPLCONFIGDIR="${runtime_dir}/.matplotlib_cache"
export HF_HUB_OFFLINE=1
export UMA_FINETUNE_LMDB_MAP_SIZE_BYTES="${lmdb_map_size}"
export ASE_LMDB_MAP_SIZE="${lmdb_map_size}"

echo "UMA fine-tuning dataset preflight"
echo "  runtime          : ${runtime_dir}"
echo "  venv             : ${venv_dir}"
echo "  work_dir         : ${work_dir}"
echo "  train_dir        : ${train_dir}"
echo "  val_dir          : ${val_dir}"
if [[ "${test_enabled}" == "1" ]]; then
    echo "  test_dir         : ${test_dir} (audit only; excluded from conversion)"
else
    echo "  test_dir         : not present; not audited or converted"
fi
echo "  lmdb_output      : ${output_dir}"
echo "  audit_report     : ${audit_report}"
echo "  verify_report    : ${verify_report}"
echo "  task             : ${uma_task}"
echo "  regression_tasks : ${regression_tasks}"
echo "  base_model       : ${base_model}"
echo "  workers          : ${num_workers}"
echo "  min_distance     : ${min_distance} A warning threshold"
echo "  reject_distance  : ${reject_distance} A hard threshold"
echo "  lmdb_map_size    : ${lmdb_map_size} bytes per shard"
echo "  config_root      : ${config_root}"
printf '  audit_command    :'
printf ' %q' "${audit_command[@]}"
printf '\n'
printf '  prepare_command  :'
printf ' %q' "${prepare_command[@]}"
printf '\n'
printf '  verify_command   :'
printf ' %q' "${verify_command[@]}"
printf '\n'

if [[ "${UMA_FINETUNE_DRY_RUN:-0}" == "1" ]]; then
    echo "DRY RUN PASS: 未审计或转换数据，也未启动训练"
    exit 0
fi
if [[ -e "${output_dir}" ]]; then
    echo "ERROR: LMDB 输出路径已经存在，官方转换器要求使用新目录：${output_dir}" >&2
    exit 1
fi

mkdir -p "$(dirname "${audit_report}")"
"${audit_command[@]}"

# fairchem-core 2.21.0's converter resolves configs/uma/finetune relative to CWD.
cd "${config_root}"
"${prepare_command[@]}"
"${verify_command[@]}"
