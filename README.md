# SAGE：气体传感研究的自动化原子级表面建模

SAGE（An AI agent for automated atomistic surface modeling in gas sensor research）分支只保留了
Genkai 中的表面建模部分：

- 切面、氧空位、分子吸附、金属团簇、SAM、ALD 非晶覆盖层、纯非晶表面，共 7 种结构生成方法；
- MLIP 筛选层：切面、空位、吸附、SAM、非晶表面与界面、团簇或岛的筛选，支持 MACE 和 UMA。

Agent 运行时、Web 界面、论文抽取（LLM）、MLIP 训练适配器和其他 Skill 不在这个分支上，需要时请到 `main` 分支。
这个分支用来在服务器上加入和运行 MLIP 测试。

## 安装

需要 Python 3.11 或更高版本（推荐 3.12）。

```bash
git clone -b SAGE --single-branch https://github.com/alekseyevich180/Genkai_Agent.git SAGE
cd SAGE

./install.sh                 # 安装 Genkai，自动检测/引导连接已有 MLIP，生成配置和任务文件
./install.sh --help          # 全部选项
```

脚本在仓库内创建 `.venv`，以可编辑方式安装当前检出的代码，所以 `git pull` 后不用重新安装；
依赖有变化时再运行一次即可。**MLIP、PyTorch、CUDA 和模型由使用者自行安装，安装脚本不安装这些内容。**
脚本会检测已有的 MACE / UMA 环境，也可手动输入 Python 与模型路径；为每个后端准备独立的
项目运行环境，并生成 `genkai.yaml`、`tasks/*.yaml` 和 `./genkai` 命令。安装时不运行真实计算。

没有自动找到环境时，也可一步指定：

```bash
./install.sh --mace-python /path/to/mace/bin/python --mace-model /path/to/model.model
# 或：./install.sh --uma-python /path/to/uma/bin/python --default-mlip uma
# 无人值守：加 --non-interactive；已有配置会保留。
```

## 使用

安装后统一使用项目根目录的 `./genkai`。`genkai.yaml` 登记 MLIP，
`tasks/*.yaml` 决定要构建什么结构；安装生成的任务默认填入仓库示例，使用自己的体系时要替换输入。
目前通过编辑带中文注释的 YAML 选择材料、晶面和参数，没有交互式材料/晶面选择向导。

第一次使用可以先构建自己的表面：

1. 在项目根目录创建 `inputs/`，放入自己的三维块体结构，命名为 `my_bulk.cif`。
   材料、晶相和晶格由文件内容决定。
2. 执行 `cp tasks/slab.yaml tasks/my_surface.yaml`，将新文件改为：

```yaml
method: slab
mlip: none                    # 先生成几何，不需要 MLIP，也不运行 GPU
bulk: ../inputs/my_bulk.cif    # 相对于 tasks/my_surface.yaml
facet: "110"                  # 目标晶面；例如改为 "111"、"100"、"101"
miller_basis: conventional    # 明确按常规标准晶胞解释晶面指数
min_slab_size: 12              # slab 最小厚度，Å
min_vacuum_size: 18            # 最小真空厚度，Å
repeat_xy: [2, 2]              # 面内扩胞
fixed_fraction: 0.5            # 固定底部一半厚度范围内的原子
output: ../runs/my_surface     # 项目根目录的 runs/my_surface
```

3. 在项目根目录执行：

```bash
./genkai check tasks/my_surface.yaml
./genkai run tasks/my_surface.yaml
```

主结构为 `runs/my_surface/slab.extxyz`，另有 `slab.vasp`；生成的是未弛豫几何。
想在它上面加分子，就修改 `tasks/adsorbate.yaml` 的 `surface`、`molecule` 和 `site_symbols`；
想做氧空位、团簇、SAM 或非晶覆盖层，就选相应任务文件。
用 `./genkai methods` 看方法，`./genkai methods slab` 看某个方法的全部参数，
`./genkai template slab -o tasks/another_surface.yaml` 生成新的中文注释模板。

MLIP 计算只需在任务里选择已配置的 `mlip: uma`、`mace` 或 `default`；
GPU 服务器上须把运行命令放入所在集群的 Slurm 脚本，由 `sbatch`/`srun` 启动。
安装脚本生成配置和任务，不会自动提交真实计算或生成特定集群的 Slurm 资源设置。

其他检查与能量筛选示例：

```bash
./genkai doctor                             # 检查 MLIP 配置，不加载模型
./genkai methods                            # 可用的方法
./genkai check tasks/sam_search.yaml         # 修改参数文件后先检查
./genkai run tasks/sam_search.yaml           # 运行
```

任务文件写法、输出说明和常见问题见 [表面建模使用手册](docs/surface-modeling-user-guide.md)。
普通使用者只需要改两个位置，不需要改任何 Python 或 shell 脚本：

1. `genkai.yaml`：集中填写已有 MLIP 的 Python、模型路径/名称、设备和默认配置，格式见
   [genkai.example.yaml](genkai.example.yaml)。更换 Python 环境后重跑 `./install.sh --configure-only`。
2. `tasks/<方法>.yaml`：填写输入结构、搜索参数以及 `mlip: default` / `mace` / `uma`。
   更换模型或切换后端，只修改配置或任务中的 `mlip` 名称即可。

```yaml
method: sam_search
mlip: default
surface: /path/to/slab.extxyz
molecule: /path/to/acid.xyz
binding_mode: monodentate
n_trials: 10
coverage_counts: [1, 2]
output: runs/my_sam
```

`sam_search`、`amorphous_surfaces`、`amorphous_interface`、`cluster_search`、`amorphous_bulk` 自动使用所选配置；
`slab`、`vacancy`、`adsorbate` 可加 `mlip: <名称>` 启用能量计算。不启用 MLIP 的旧任务仍只生成结构。
只有晶体、需要非晶表面时，先用 `amorphous_bulk`（MLIP 熔融-淬火）得到非晶块体，再交给 `amorphous_slab`
切表面，两步可写在同一个任务文件里，见
[examples/mlip_jobs/05_crystal_to_amorphous_slab.yaml](examples/mlip_jobs/05_crystal_to_amorphous_slab.yaml)。
可复用的筛选任务见 [examples/mlip_jobs](examples/mlip_jobs)，配置与安装详解见
[MACE / UMA 接口](docs/mlip-interfaces.md)。`genkai-surface` 仍可在激活 `.venv` 后直接使用。

## 测试

```bash
.venv/bin/python -m pytest -q                          # 离线测试，不需要 GPU
.venv/bin/python scripts/run_modeling_smoke.py         # 全部建模方法，模拟计算器
# 真实 UMA 测试在获准计算的节点上运行：
bash scripts/mlip-python.sh uma scripts/run_modeling_smoke.py --profile server --device cuda --uma-task <任务头>
```

运行 UMA 前请注意：

- 只在获准进行真实计算的服务器上运行；
- 先确定 UMA 任务头。可用的任务头取决于所装的 fairchem 版本，例如 fairchem 2.7.1 有 omol、omat、
  odac、oc20、oc25、omc，没有 oc22；
- 第一次运行会从 Hugging Face 下载模型，通常需要先接受模型许可，并设置 `HF_TOKEN`
  （或运行 `hf auth login`，旧版为 `huggingface-cli login`）；
- 模拟计算器（`calculator=none`）给出的能量和排序没有物理意义，只用来确认流程能走通。

## 目录

| 路径 | 内容 |
| --- | --- |
| `src/genkai/modeling/surface/builders/` | 结构生成：切面、空位、吸附、团簇、SAM、ALD、纯非晶表面 |
| `src/genkai/modeling/surface/screening/` | 能量筛选：SAM 锚定搜索、非晶表面/界面筛选、团簇与岛放置搜索 |
| `src/genkai/modeling/surface/mlip/` | 计算器（none/emt/MACE/UMA）、搜索采样器（TPE/周期 GP）、`genkai.yaml` 配置 |
| `src/genkai/modeling/surface/app/` | `genkai-surface`（`jobs.py`）和安装向导（`setup.py`） |
| `src/genkai/modeling/surface/` 顶层 | `structure_io.py`（文件约定与结构检查）、论文计划执行器；旧路径的 `slab.py` 等是转发模块 |
| `src/genkai/modeling/` | PToModel 建模计划（mapping、ptomodel、checklist、schema） |
| `src/genkai/contracts/`、`src/genkai/workflow/` | artifact 与运行清单（`manifest.json`）契约 |
| `src/genkai/literature/surface/` | 只保留建模用到的词表和读取已保存抽取结果的函数 |
| `agents/Agent/skills/surface-modeling/` | 各方法的薄入口脚本、Skill 说明和示例结构 |
| `examples/surface_jobs/` | `genkai-surface` 示例任务文件 |
| `genkai.example.yaml`、`examples/mlip_jobs/` | MLIP 配置格式与能量筛选任务示例 |
| `scripts/run_modeling_smoke.py` | 建模冒烟测试 |
| `tests/` | 测试和测试用结构 |
| `AGENTS.md` | 在这个分支上工作的规则 |
