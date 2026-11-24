# SAGE 分支工作指南

## 分支定位

`SAGE` 分支由 `main`（提交 `4c7b0bc`）精简而来，只保留表面建模和 MLIP 筛选层，用于在服务器上
加入和运行 MLIP 测试。2026-11-16 创建。

- 保留：7 种结构生成方法、`genkai-surface` 任务文件入口、MLIP 筛选层（calculators、sam_search、
  amorphous_screen、cluster_search）、PToModel 建模计划、artifact 与运行清单契约、surface-modeling Skill 的
  薄入口与示例结构、建模冒烟测试、相关测试和测试结构。
- 删除：Agent 运行时（`agents/Agent/*.py`、`src/agent/`）、Web 界面、论文 PDF 抽取与 LLM、`genkai.cli`
  与 `genkai.workflows`（`genkai-workflow` 命令）、`genkai.mlip`/`compute`/`datasets`（训练与 VASP 适配器）、
  其他 Skill、知识图谱、`legacy/`、main 的 Harness 脚本和发布流程。
- 建模代码此后在 SAGE 上继续开发（MLIP 配置、OOM 回退、周期 GP 采样器等），2026-11-24 起
  `src/genkai/modeling/surface/` 又按职责拆成子包（见“目录结构”），与 `main` 的平铺布局不再一致。
  `literature/surface/__init__.py` 和 `core/catalog.py` 里仍以字符串形式提到已删除的模块，只有调用这些
  延迟导出时才会报错，建模代码不调用它们。

### 与 main 同步

- **不要再用 `git checkout main -- src/genkai/modeling`**：main 的平铺文件会覆盖 `surface/` 顶层的转发模块，
  形成两份实现（`tests/architecture/test_surface_layout.py` 会失败）。`src/genkai/contracts` 等未改布局的目录
  仍可按路径检出。不要直接 `git merge main`：会把已删除的部分带回来。
- 从 main 取某个建模文件：按下表放到新位置，再改相对导入（子包内同组模块仍用 `.x`；`structure_io` 用
  `..structure_io`；跨组用 `..mlip.x`、`..builders.x`），然后在 SAGE 上运行验证。例如
  `git show main:src/genkai/modeling/surface/sam.py > src/genkai/modeling/surface/builders/sam.py`。
  SAGE 上的版本多已改过，先对比差异再合并，不要整文件覆盖。

  | main 路径（`src/genkai/modeling/surface/`） | SAGE 路径 |
  | --- | --- |
  | `calculators.py`、`search_sampler.py`*、`mlip_config.py`* | `mlip/` |
  | `slab.py`、`materials_project_slab.py`、`substrate.py`、`sites.py`、`vacancy.py`、`adsorbate.py`、`sam.py`、`amorphous_overlayer.py`、`amorphous_slab.py`、`metal_cluster/` | `builders/` |
  | `sam_search.py`、`amorphous_screen.py`、`cluster_search.py` | `screening/` |
  | `jobs.py`、`setup.py`* | `app/` |
  | `structure_io.py`、`executor.py`、`facade.py`、`__init__.py` | 原位置 |

  \* 只在 SAGE 上存在。
- 把 SAGE 上的改进带回 main：在 main 上按上表反向放回平铺位置并改回相对导入；`git cherry-pick` 只适合
  不涉及 `surface/` 文件移动的提交。**不要把 SAGE 合并进 main**：精简提交会删除 main 的大部分内容。
- 两个分支都改过的文件（如本文件、README、pyproject.toml、冒烟脚本、`schema/task_parameter_schema.json`）
  按分支各自维护。

## 目录结构

- `src/genkai/modeling/surface/`（2026-11-24 按职责拆分；依赖方向
  `structure_io` ← `mlip` ← `builders` ← `screening` ← `app`）：
  - `structure_io.py`：结构文件约定和结构检查，所有子包共用。
  - `mlip/`：`calculators.py`（none/emt/MACE/UMA、任务头检查、证据等级）、`search_sampler.py`
    （Optuna TPE 与共享周期 GP）、`mlip_config.py`（`genkai.yaml`、MLIP 运行环境选择、无模型环境检查、OOM 回退配置）。
  - `builders/`：切面 `slab.py`、Materials Project 读取 `materials_project_slab.py`（需要联网，可选依赖
    `mp-api`）、`substrate.py`、`sites.py`、空位 `vacancy.py`、吸附 `adsorbate.py`、SAM `sam.py`、
    ALD `amorphous_overlayer.py`、纯非晶表面 `amorphous_slab.py`、团簇 `metal_cluster/`，以及
    非晶块体 `amorphous_bulk.py`（2026-11-24：晶体 → 扩胞/密度缩放 → Langevin 熔融-淬火-退火 → 弛豫，
    输出可作为 `amorphous_slab`/ALD/`amorphous_screen` 的 `--amorphous`；需要有力的计算器，`none` 被拒绝，
    `--dry-run` 只准备超胞）。
  - `screening/`：SAM 锚定搜索 `sam_search.py`、非晶表面/界面筛选 `amorphous_screen.py`、团簇与岛放置搜索
    `cluster_search.py`、多帧结构的弛豫/单点 `relax.py`（流水线按能量挑选和中间弛豫用）。
  - `app/`：任务文件入口 `jobs.py`（console script `genkai-surface`，按模块名在子进程里启动各方法）、
    流水线 `pipeline.py`（2026-11-24：`pipeline:` 文件自动串联各步骤，`check`/`run` 自动识别）、
    安装向导 `setup.py`（`install.sh` 调用）。面向使用者统一走 `./genkai` / `genkai-surface`。
  - `executor.py`、`facade.py`：论文建模计划的 structure-only 执行。
  - 顶层的 `slab.py`、`jobs.py`、`metal_cluster/` 等旧路径是**转发模块**，只为服务器上已有脚本（hooks、
    `test_interface_kernels.py`、旧 `./genkai` 启动器、`python -m genkai.modeling.surface.<旧名>`）保留，
    不含代码；仓库内的代码和文档只用新路径。
- `src/genkai/modeling/`：PToModel（`mapping.py`、`ptomodel.py`、`checklist.py`、`schema/`）。
- `src/genkai/contracts/`、`src/genkai/workflow/`：artifact、`RunManifest`、阶段图和清单存储。
- `src/genkai/literature/surface/`：只保留 `artifacts.py`（读取已保存的抽取结果）和 `core/` 词表。
- `agents/Agent/skills/surface-modeling/`：各方法的薄入口脚本、`SKILL.md`、示例结构。
- `examples/surface_jobs/`：`genkai-surface` 示例任务文件；运行结果写到 `runs/`，已忽略。
- `scripts/run_modeling_smoke.py`：建模冒烟测试。
- `tests/`：`modeling/`、`contracts/`、`architecture/`、`workflow/`、`integrations/`；测试结构在
  `tests/amorphous/`、`tests/se4c02105_surface_fullrun/automatic_modeling/`、`tests/fixtures/`。
- `docs/surface-modeling-user-guide.md`：给使用者的手册；`docs/artifact-contracts.md`：artifact 契约。
- `install.sh`：安装脚本；`.github/workflows/test.yml`：SAGE 分支的 CI。
- `work_logs/`：工作日志（含 main 的历史日志）；`work_log.md` 只作索引。

## 架构规则

- 稳定实现放在 `src/genkai/`，使用 `genkai.*` 导入；Skill 脚本只做 `from genkai... import *` 加 `main` 转发。
- 依赖方向：`skills` → `modeling` → `contracts`；`tests/architecture/` 检查导入边界和薄入口。
- `modeling/surface/` 内部：`mlip/` 不导入 builders/screening/app，`builders/` 不导入 screening/app，
  `screening/` 不导入 app；新模块放进对应子包，不再放在 `surface/` 顶层。仓库内任何代码不得经由旧路径
  转发模块导入。`tests/architecture/test_surface_layout.py` 检查分层、转发模块不含代码、新旧路径是同一个模块对象，
  以及旧路径 `python -m` 仍可运行。
- 公共 artifact 通过 `genkai.contracts` 和 `RunManifest` 传递。
- 修改某个方法的命令行参数时，同步 `jobs.py` 的参数表；`tests/modeling/test_surface_jobs.py` 会检查。
- 串联顺序（`app/pipeline.py` 的 `STEP_KINDS`）：体相 → 表面 → 空位 → ALD → 团簇 → SAM → 吸附；倒序需 `allow_order: true`。
  新的结构生成方法要进入流水线时，在 `STEP_KINDS` 登记层级、输入参数、候选文件和新原子的 `component`，
  并让方法写出保留固定原子和标签的 extxyz 候选文件。能量筛选方法还未接入流水线。
- 流水线按能量挑选（第三期，2026-11-24）：`pick: lowest_energy`（`pick_count`）先用顶层 `mlip` 配置调用
  `screening/relax.py` 弛豫全部候选，再按化学组成分组取最低；`method: relax` 是可放在任意位置的中间弛豫步。
  能量只在同一步、同一分支、同一组成内比较，`relax` 拒绝 `calculator=none`。本机只用 EMT 测试这条路径。

### 结构文件约定

实现位于 `genkai.modeling.surface.structure_io`。

- 用户输入默认 CIF，也接受 ASE 可读的其他格式；输入只在入口读取一次。
- 同一进程内传递 `ase.Atoms`；阶段之间和 artifact 的结构文件使用 extxyz（保留 `FixAtoms`、tags、
  逐原子数组和多帧）；元数据写进 JSON manifest，不放在 extxyz 的 info 里。
- 逐原子数组 `component`（substrate、overlayer、cluster、sam、adsorbate）记录每个原子由哪一步加入，
  辅助函数在 `structure_io`（`label_components`、`solid_mask`、`free_lateral_positions`、`local_solid_top`）。
  加原子的构建器必须给新原子打标签；没有该数组的结构视为全部基底，所以单独使用时行为不变。
  表面区域、SAM 位点、空位候选、吸附位点、团簇和 ALD 岛的位置都按“基底+覆盖层”为表面、避开其他部分。
- CIF 只用于导出（会丢失固定原子等信息）。导出 POSCAR 时不排序；`slab.py` 的 `slab.vasp` 是排过序的，
  不能与 `slab.extxyz` 混用原子索引。

## 安装与验证

```bash
./install.sh                 # 安装项目，连接使用者已安装的 MLIP，生成配置/任务；不安装 MLIP 或 PyTorch
./install.sh --configure-only # 修改环境路径后重新准备项目依赖，保留配置和任务文件
./genkai doctor              # 无模型环境检查
source .venv/bin/activate
python -m pytest -q
python scripts/run_modeling_smoke.py
python -m genkai.modeling.surface.app.jobs check examples/surface_jobs/*.yaml
```

用 `python -m pytest`（不是 `pytest`）运行测试：`tests/architecture` 需要仓库根目录在 `sys.path` 里。

历史基线（2026-11-16，本机 Windows + Python 3.11，所装 genkai 为 `2.2.0+sage`）：

- `python -m pytest -q`：114 passed。
- 冒烟：29 个用例，PASS 27 / WARN 1 / FAIL 0 / SKIP 1。WARN 是旧吸附脚本放置多个分子时不检查分子间重叠
  （`adsorbate_sno2_101_ketone`，0.51 Å 的 C…H 接触），SKIP 是需要联网的 Materials Project 用例。
- `examples/surface_jobs/` 的 10 个任务全部 PASS。
- 本机无法联网，`install.sh` 的完整安装由 CI（Ubuntu + Python 3.12，pip 路径）验证。

当前基线（2026-11-24，`surface/` 拆分子包之后，本机 Windows + Python 3.11，绝对路径 `PYTHONPATH=<仓库>/src`）：

- `python -m pytest -q`：201 passed / 2 deselected（external）；其中 `tests/architecture` 32 passed。
- 冒烟：29 个用例，PASS 28 / WARN 0 / FAIL 0 / SKIP 1（Materials Project 联网项），与拆分前服务器基线一致。
- `examples/surface_jobs/` 10 个任务配置检查通过；新旧模块路径的 `python -m ... --help` 均返回 0。
- 本机没有 `wheel`，新子包的打包只用 setuptools 包发现核对；实际 wheel 由 CI 安装验证。
- 同日加入 `amorphous_bulk` 后：`python -m pytest -q` 214 passed / 2 deselected；冒烟 31 个用例，
  PASS 29 / WARN 0 / FAIL 0 / SKIP 2（Materials Project 联网项；熔融-淬火用例需要 `--profile server`）。
- 同日加入流水线与原子来源标签后：`python -m pytest -q` 227 passed / 2 deselected；冒烟 33 个用例，
  PASS 31 / WARN 0 / FAIL 0 / SKIP 2，其中原有 31 个用例的状态、最小接触比和结构数与加入前逐项相同；
  `examples/surface_jobs/` 10 个任务和 2 个流水线检查通过。
- 同日加入第三期（`relax`、`pick: lowest_energy`）后：`python -m pytest -q` 233 passed / 2 deselected；
  冒烟 33 个用例 PASS 31 / WARN 0 / FAIL 0 / SKIP 2，与第三期之前逐项相同。

## MLIP 测试规则

- MACE / UMA 公共接口与本机独立环境的调用方法见 `docs/mlip-interfaces.md`；
  `genkai.yaml` 集中配置环境与模型；任务 YAML 用 `mlip` 选择配置。
  旧任务默认 structure-only；slab/vacancy/adsorbate 可显式启用 MLIP，
  sam_search/amorphous_surfaces/amorphous_interface/cluster_search/amorphous_bulk 已开放 YAML 入口。
  `amorphous_bulk` 是真实分子动力学（默认约 7.4 万步），与其他 MLIP 计算一样只在获准的服务器上运行；
  本机测试只用 EMT 小胞（32 个 Cu、约 360 步）检查流程，不代表非晶结构质量。
  完整晶体在 MD 中会明显过热（本机 EMT 实测：108 原子 Cu 在 3000 K 下 1 ps 仍未熔化），
  所以 manifest 记录熔融阶段各元素的均方根位移，低于 1.5 Å 时给出警告。
  安装脚本不得安装 MLIP、PyTorch、CUDA 或下载模型；只为已有后端准备独立项目依赖环境，
  使用源环境版本约束，并保留使用者配置与任务文件。
  `scripts/mlip-python.sh` 也读取同一个配置，不得重新加入本机专属环境路径。
- 2026-11-17 服务器验证：MACE 环境离线测试 131 passed / 1 skipped，UMA 环境 132 passed，
  两者各有 2 个 external 用例默认不运行。模拟冒烟 PASS 27 / WARN 1 / FAIL 0 / SKIP 1；
  WARN 为已有吸附示例重叠，SKIP 为 Materials Project 联网项。
  获准通过 Slurm 在 RTX 3080 上运行两个 Cu 原胞单点接口测试，MACE 和 UMA 各 1 passed。
  详见 `work_logs/2026-11-17.md`；未执行真实表面搜索和 DFT 精度验证。
- 同日配置化用户入口的最终基线：普通安装环境 166 passed / 1 skipped / 2 external deselected；
  安装脚本实际自动发现两个后端，11 个生成任务和 4 个筛选示例检查通过，重复配置保留文件校验值；
  模拟冒烟仍为 PASS 27 / WARN 1 / FAIL 0 / SKIP 1。真实单点在安装步骤之外独立验证。

- UMA、DFT、MD、GPU 和调度器作业只在获准做真实计算的环境里运行；不要在没有授权时自动扩展。
- 先确定 UMA 任务头（用少量 DFT 单点对比），并确认所装 fairchem 支持它；`calculators.validate_uma_task`
  会在加载模型前检查。本机 fairchem 2.7.1 有 omol、omat、odac、oc20、oc25、omc，没有 oc22。
- Hugging Face 令牌只从环境变量读取，不写入命令输出、artifact、日志或提交。
- 不得把 `calculator=none`、mock、dry-run 的结果描述为真实能量、力、吸附能或弛豫结果。
  `evidence_for` 会把模拟、经验势和 MLIP 结果分别标为 mock、empirical_potential、mlip_predicted。
- 新的 MLIP 测试默认不在 CI 中运行；需要 GPU 或网络的测试标记为 `external`，用
  `python -m pytest -m external <文件>` 显式运行。

## 修改规则

- 改动与任务一致，不顺便重构无关模块；Bug 修复先加能捕获问题的回归测试。
- 修改 `src/genkai/modeling/surface/` 或其入口时，运行冒烟测试并报告 PASS/WARN/FAIL/SKIP 数量。
- 引入新依赖前说明必要性和运行环境；基础依赖写在 `pyproject.toml` 的 `dependencies`，
  MLIP 相关写在 `mlip` 可选项。
- 不要提交 `.venv/`、冒烟输出或 `examples/surface_jobs/runs/`。

## 工作日志

- 每日详情写入 `work_logs/YYYY-MM-DD.md`，`work_log.md` 只加索引。
- 记录修改文件、实际命令、结果、未运行项和残余风险；不得记录密钥，不得把计划中的验证写成已通过。

## 完成标准

只有当要求的行为已实现、相应测试和冒烟实际运行、文档与命令一致、`git diff --check` 通过时，才报告完成。
完成报告列出通过、失败、未运行和残余风险。
