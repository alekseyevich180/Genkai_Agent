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
- 保留下来的源码文件与 `main` 相同，没有为精简而修改，方便以后同步。
  `literature/surface/__init__.py` 和 `core/catalog.py` 里仍以字符串形式提到已删除的模块，只有调用这些
  延迟导出时才会报错，建模代码不调用它们。

### 与 main 同步

- 从 main 取建模更新：只检出需要的路径，例如
  `git checkout main -- src/genkai/modeling src/genkai/contracts tests/modeling`，再在 SAGE 上运行验证。
  不要直接 `git merge main`：会把已删除的部分带回来。
- 把 SAGE 上的改进带回 main：用 `git cherry-pick` 挑选只改建模代码的提交，或在 main 上按路径检出。
  **不要把 SAGE 合并进 main**：精简提交会删除 main 的大部分内容。
- 两个分支都改过的文件（如本文件、README、pyproject.toml、冒烟脚本）按分支各自维护。

## 目录结构

- `src/genkai/modeling/surface/`：切面 `slab.py`、空位 `vacancy.py`、吸附 `adsorbate.py`、团簇
  `metal_cluster/`、SAM `sam.py`、ALD `amorphous_overlayer.py`、纯非晶表面 `amorphous_slab.py`，共用的
  `substrate.py`、`sites.py`、`structure_io.py`（文件约定和结构检查），structure-only 执行器 `executor.py`
  与 `facade.py`，MLIP 筛选层 `calculators.py`、`sam_search.py`、`amorphous_screen.py`、`cluster_search.py`，
  任务文件入口 `jobs.py`（console script `genkai-surface`），Materials Project 读取 `materials_project_slab.py`
  （需要联网，可选依赖 `mp-api`）。
- `modeling/surface/mlip_config.py`：统一 MLIP 配置、运行环境选择与无模型环境检查；
  `setup.py`：安装向导、独立项目依赖环境、配置和任务生成。面向使用者统一走 `./genkai` / `genkai-surface`。
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
- 公共 artifact 通过 `genkai.contracts` 和 `RunManifest` 传递。
- 修改某个方法的命令行参数时，同步 `jobs.py` 的参数表；`tests/modeling/test_surface_jobs.py` 会检查。

### 结构文件约定

实现位于 `genkai.modeling.surface.structure_io`。

- 用户输入默认 CIF，也接受 ASE 可读的其他格式；输入只在入口读取一次。
- 同一进程内传递 `ase.Atoms`；阶段之间和 artifact 的结构文件使用 extxyz（保留 `FixAtoms`、tags、
  逐原子数组和多帧）；元数据写进 JSON manifest，不放在 extxyz 的 info 里。
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
python -m genkai.modeling.surface.jobs check examples/surface_jobs/*.yaml
```

用 `python -m pytest`（不是 `pytest`）运行测试：`tests/architecture` 需要仓库根目录在 `sys.path` 里。

历史基线（2026-11-16，本机 Windows + Python 3.11，所装 genkai 为 `2.2.0+sage`）：

- `python -m pytest -q`：114 passed。
- 冒烟：29 个用例，PASS 27 / WARN 1 / FAIL 0 / SKIP 1。WARN 是旧吸附脚本放置多个分子时不检查分子间重叠
  （`adsorbate_sno2_101_ketone`，0.51 Å 的 C…H 接触），SKIP 是需要联网的 Materials Project 用例。
- `examples/surface_jobs/` 的 10 个任务全部 PASS。
- 本机无法联网，`install.sh` 的完整安装由 CI（Ubuntu + Python 3.12，pip 路径）验证。

## MLIP 测试规则

- MACE / UMA 公共接口与本机独立环境的调用方法见 `docs/mlip-interfaces.md`；
  `genkai.yaml` 集中配置环境与模型；任务 YAML 用 `mlip` 选择配置。
  旧任务默认 structure-only；slab/vacancy/adsorbate 可显式启用 MLIP，
  sam_search/amorphous_surfaces/amorphous_interface/cluster_search 已开放 YAML 入口。
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
