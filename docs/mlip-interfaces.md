# 用参数文件接入 MACE / UMA

使用者自行安装 MLIP、PyTorch 和所需模型。Genkai 安装脚本负责连接这些已有环境、安装项目基础依赖、
生成配置与任务文件；不安装 MLIP、PyTorch、CUDA，不下载模型，也不执行真实计算。

## 1. 一次安装

```bash
./install.sh
```

脚本自动检测常见的 Conda / venv 位置，并在终端中提示确认 Python 和模型路径。
也可以显式指定，适合环境放在自定义目录的服务器：

```bash
./install.sh --mace-python /path/to/mace/bin/python --mace-model /path/to/model.model
./install.sh --uma-python /path/to/uma/bin/python --default-mlip uma
```

两个后端的选项可以写在同一次命令中。无人值守时加 `--non-interactive`。
未找到 MLIP 时仍可安装并生成结构；配置文件中会留下可填写的示例。

安装后得到：

- `genkai.yaml`：本机的 MLIP 环境、模型与默认参数；
- `tasks/*.yaml`：11 种方法的参数文件，已填入仓库示例输入，可替换为自己的结构；
- `./genkai`：统一命令，无需激活 Python 环境。

```bash
./genkai doctor                         # 检查配置、依赖和模型路径，不加载模型
./genkai methods                        # 查看方法
./genkai check tasks/sam_search.yaml     # 只检查参数和输入文件
./genkai run tasks/sam_search.yaml       # 实际运行
```

已有配置和任务文件不会被自动覆盖。更换 MLIP 的 Python 路径后运行
`./install.sh --configure-only`，脚本会为新环境准备项目依赖。
仅修改模型、设备、默认后端或任务参数，无需重新安装。

项目运行环境位于 `.genkai/runtimes/`，与原 MLIP 环境分开。
它读取原环境中的后端及可编辑安装，只在自己的环境中安装 Genkai 基础依赖，并约束为原环境已有的依赖版本。
如果原环境版本与 Genkai 要求冲突，安装器会报告冲突，不会改装原有 MLIP 或静默升级它的依赖。
使用者无需管理这些目录。安装脚本的旧 `--mlip` 参数现在只表示连接已有环境；
`--torch-index-url` 已停用。

## 2. 只在 genkai.yaml 登记环境

完整格式见 [genkai.example.yaml](../genkai.example.yaml)。最小示例：

```yaml
version: 1
default: mace
profiles:
  mace:
    backend: mace
    python: /path/to/mace/env/bin/python
    model: /path/to/trusted/model.model
    device: cuda
    dtype: float32
    env:
      TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD: '1'
  uma:
    backend: uma
    python: /path/to/uma/env/bin/python
    model: uma-s-1p2
    task: omat
    device: cuda
```

配置名称可自行命名，例如 `mace_small`、`mace_large`、`uma_cpu`；
`backend` 指定实际后端。所有工作流共用这些配置，不需要修改各个脚本。

| 配置项 | 含义 |
| --- | --- |
| `python` | 已安装相应 MLIP 的 Python，不是 Genkai 主环境的 Python |
| `model` | MACE 本地模型；UMA 模型名称或本地检查点 |
| `device` | `cpu` 或 `cuda` |
| `dtype` | MACE 的 `float32` 或 `float64` |
| `task` | UMA 任务头；默认 `omat`，需按具体体系验证 |
| `launcher` | 可选，例如 `[/path/to/start.sh]`，先激活环境再执行传入命令 |
| `settings` | 可选的公共弛豫默认值：`fmax`、`max_steps`、`screen_steps`、`relax_steps` |
| `oom_fallback` | 可选，CUDA UMA 显存不足时使用的同文件配置名称 |

在 CUDA UMA 配置中写 `oom_fallback: uma_small` 可以启用显存回退。
把 `uma_small` 登记为同一个任务头的 CUDA UMA 配置，并选择较小的模型，例如 `uma-s-1p1`。
`genkai-surface run` 捕获计算子进程的 CUDA OOM 后会保存首次输出到相邻目录，
然后使用小模型从输入重新运行该步骤一次。新输出中的 `job_resolved.yaml` 和 `manifest.json`
记录实际使用的配置，清单的 `oom_fallback` 字段记录原模型和首次日志位置。
离线运行时，两个配置都需要对应的本地模型缓存。

MACE 模型是 Python 检查点对象，示例中的加载选项用于自己信任的本地模型。
MACE 模型不自动下载；UMA 预训练模型在首次真实运行时可能联网下载，并需要已接受许可及已有凭据。
访问令牌使用环境变量或已有 Hugging Face 凭据，不写入配置。

配置中的相对模型/环境路径以配置文件所在目录为准。
任务会自动查找上级目录中的 `genkai.yaml`，也可以用
`./genkai run --config /path/to/genkai.yaml task.yaml` 指定。
任务中的 `config: ../genkai.yaml` 可以固定使用的配置文件；命令行 `--config` 优先。

## 3. 任务只选择配置名称

```yaml
method: sam_search
mlip: default             # 使用 genkai.yaml 的 default；也可填写 mace、uma 或自定义名称
surface: /path/to/slab.extxyz
molecule: /path/to/acid.xyz
binding_mode: monodentate
n_trials: 10
top_k: 2
coverage_counts: [1, 2]
max_steps: 100            # 可选：覆盖公共弛豫默认值
output: runs/my_sam
```

把 `mlip: default` 改成 `mlip: uma` 就会自动选择 UMA 的 Python、模型、设备和任务头。
计算器/模型/设备不用重复写进每个任务，更不用修改 Python 文件。

| 方法 | MLIP 行为 |
| --- | --- |
| `slab` | 填 `mlip: <名称>` 启用晶面/终止面的能量排序，默认不启用 |
| `vacancy` | 填 `mlip: <名称>` 启用空位能量计算和弛豫 |
| `adsorbate` | 填 `mlip: <名称>` 启用吸附与覆盖度能量搜索 |
| `sam_search` | SAM 锚定与覆盖度搜索，默认选择配置中的 default |
| `amorphous_surfaces` | 非晶表面能筛选，默认选择 default |
| `amorphous_interface` | 非晶膜/晶体界面搜索，默认选择 default |
| `cluster_search` | 预制团簇或非晶岛的负载位置搜索，默认选择 default |
| `amorphous_bulk` | 晶体熔融-淬火得到非晶块体（Langevin MD + 最终弛豫），默认选择 default |

`sam`、`ald`、`cluster`、`amorphous_slab` 仍是几何生成方法。
需要能量筛选时选用对应的搜索方法；例如 ALD 生成的岛可作为 `cluster_search` 的 `cluster` 输入。
结构生成与 MLIP 搜索也可放进同一个 `jobs:` 列表，后一个任务引用前一个任务的输出。

`adsorbate`、`sam_search`、`amorphous_interface` 和 `cluster_search` 默认使用 Periodic GP
搜索候选构型。该优化器把周期方位角和晶胞面内分数平移接成闭环，把位点编号作为无序类别。
前 8 次有效试验用于初始采样。超过 96 条有效记录时，每次拟合使用最近 48 条和更早的最优 48 条。
如需沿用原来的 TPE，在对应任务中填写 `sampler: tpe`。用 `python -m` 调用方法时可传 `--sampler tpe`。
`amorphous_surfaces` 按几何规则选取切割窗口并做能量排序，没有 `sampler` 参数。

可复制的真实筛选任务见 [examples/mlip_jobs](../examples/mlip_jobs)。
这些任务可能计算较久，安装脚本只生成它们，不执行。
GPU 计算在分配的 GPU 节点上运行同一条 `./genkai run ...` 命令；
调度器资源按所在集群的规则申请。

## 4. 结果与检查

每次运行记录：

- `job_resolved.yaml`：实际任务及配置文件位置；
- `run.log`：所选 Python 环境执行的输出；
- `manifest.json`：模型、设备、环境版本、证据级别和结构检查；
- 方法本身的能量表、结构和搜索清单。

MLIP 结构标为 `mlip_predicted`；EMT 标为 `empirical_potential`。
结构生成任务的模拟能量仍没有物理意义。失败任务不登记为成功的能量结果。
模型对目标元素/表面/界面的精度需要独立验证；不同模型的绝对能量不能混合相减。

缺环境、缺模型、配置拼写错误或 UMA 任务头不可用时，`check` / `doctor` 会给出修改提示。
`check` 不加载模型、不弛豫、不做 GPU 计算。参数检查通过不代表目标体系已完成物理精度验证。

## 开发者入口

原有各模块 CLI 和公共 ASE 工厂仍可用：

```python
from genkai.modeling.surface.mlip.calculators import build_calculator, relax

calc = build_calculator("mace", mace_model="/path/to/model.model", device="cuda")
energy_eV = relax(atoms, calc, fmax=0.05, steps=200)
```

`scripts/mlip-python.sh <配置名> <Python 参数>` 也读取同一个 `genkai.yaml`；
其中没有本机专属环境或模型路径。默认测试不加载真实 MLIP；
`tests/external/test_mlip_calculators.py` 需要显式选择 `-m external`。
