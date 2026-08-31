# Genkai 项目工作指南

## 项目目标

Genkai 是面向材料、化学和计算模拟任务的多智能体平台。当前架构以
`src/genkai/` 中的稳定科学工作流库为核心，以 `agents/Agent/skills/` 作为决策、
外部运行入口和实验性能力的载体。

本仓库当前最重要的质量要求是：

- 科学产物必须具有可追踪的契约、来源和运行清单；
- prepare、dry-run、CPU 推理、外部计算和真实科学证据必须明确区分；
- 稳定逻辑只有一个所有者，不能在库、Skill 和历史目录中重复实现；
- 架构迁移必须检查真实导入、入口和 wheel 内容，不能只依赖 facade 或局部测试；
- 修改必须带有与风险相称的实际验证证据。

## 指令范围

- 本文件适用于整个仓库。
- 如果子目录以后出现更具体的 `AGENTS.md`，以距离目标文件最近的规则为准。
- 用户的明确要求优先于本文件；如果用户要求会扩大到网络、GPU、调度器或外部系统，
  必须先确认授权边界。
- 本工作区是结构演进的隔离工作树。只能在当前工作区写入，不修改旁边的主工作区。

## 项目结构

- `src/genkai/`：稳定、可复用的工作流与科学领域实现。
  - `contracts/`：artifact 与 run manifest 契约。
  - `workflows/` 和 `workflow/`：工作流编排与图验证。
  - `literature/`：论文读取和表面科学信息抽取。
  - `modeling/`：PToModel、checklist、schema 与表面建模算法。
  - `compute/`、`datasets/`、`mlip/`：计算、数据集和 MLIP 边界。
- `agents/Agent/`：Agent 运行时、内置 agents 和 skills。
- `agents/Agent/skills/`：薄入口、运行说明、决策逻辑和实验性能力。
- `tests/`：按 contract、architecture、unit、integration、compatibility、external 分层。
- `docs/`：架构迁移、artifact 契约、Skill 开发和 Harness 指南。
- `scripts/`：可重复执行的仓库检查。
- `legacy/paperread/`：只读历史研究资产，不是活动包或工作流所有者。
- `web/vite-frontend/`：Vite 前端。
- `work_logs/`：按日期记录实际工作与验证边界；`work_log.md` 仅作索引。

详细所有权和弃用边界见 `docs/migration.md`。Harness 的任务用法见
`docs/harness-engineering.md`；从 8 月 5 日计划恢复简单日常任务时，使用
`docs/daily-agent-work-guide.md`。

## 架构规则

依赖方向应保持为：

```text
agents/Agent/skills
  -> src/genkai/workflows
  -> src/genkai/{literature,modeling,compute,datasets,mlip}
  -> src/genkai/contracts
```

必须遵守：

- 新的稳定实现放在 `src/genkai/`，新代码使用 `genkai.*` 导入。
- Skill 脚本只负责参数解析、调用稳定库、报告结果或启动经过 preflight 的外部命令。
- Skill 中不得保留第二份 schema、数据清洗、artifact gate 或领域算法。
- 不得恢复 `paperread.surface` 作为活动所有者。
- `legacy/paperread/` 可以保存历史资料，但不得进入活动导入链或 wheel。
- 公共 artifact 必须通过 `src/genkai/contracts/` 中的契约和 `RunManifest` 传递。
- package data 或入口发生变化时，必须检查新构建的 wheel，不能读取旧 `build/` 或
  `*.egg-info/` 得出结论。

这些规则已有机械门禁：

- `tests/architecture/` 检查导入方向、物理目录、Skill 边界和所有权；
- `tests/packaging/test_wheel_contents.py` 检查干净 wheel 的代码、Skill 与资源内容；
- `tests/contracts/` 检查 artifact 和 manifest 行为；
- `scripts/check_harness.py` 检查项目地图、pyproject、CI 和分级验证入口。

## 开始任务前

1. 阅读本文件和目标目录下更具体的规则。
2. 运行 `git status --short --branch`，记录并保留用户已有修改和未跟踪文件。
3. 阅读与任务直接相关的代码、测试、`docs/migration.md` 和 artifact 文档。
4. 查找真实调用者、入口、schema 和 package data，不根据文件名推测所有权。
5. 写清目标、不应改变的行为、验收标准和验证层级。
6. 优先修改现有实现，避免创建平行实现。
7. 对含糊的“全部执行”保持范围边界；不得自动扩展到在线 LLM、Materials Project、
   VASP、DFT、MACE、UMA、DeepMD、训练、MD、GPU、PJM、远程推送或发布。

## 环境和安装

项目要求 Python 3.12 或更高版本。不要假定父目录或其他工作区的虚拟环境可用；
在当前仓库创建并激活自己的 `.venv`：

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e .
uv pip install pytest
```

安装前端依赖：

```bash
cd web/vite-frontend
npm install
cd ../..
```

## 常用验证命令

以下命令均从仓库根目录、在已激活的项目环境中运行。

静态 Harness 健康检查：

```bash
python scripts/check_harness.py doctor
```

快速架构检查：

```bash
python scripts/check_harness.py quick
```

与 CI 相同的检查，包括 Agent 导入和公共 CLI 帮助：

```bash
python scripts/check_harness.py ci
```

目标测试：

```bash
python -m pytest path/to/test_file.py -q --tb=short
```

wheel 与打包内容检查：

```bash
python scripts/check_harness.py package
```

完整默认测试：

```bash
python scripts/check_harness.py full
```

当前完整测试有一个已知收集阻塞：`tests/test_structure_builder.py` 导入已经不存在的
`agent.tools.structure_builder`。在该测试被迁移、恢复或删除前，不能把局部通过报告成
“完整测试通过”。

前端开发与构建：

```bash
cd web/vite-frontend
npm run dev
npm run build
```

差异基本检查：

```bash
git diff --check
git status --short
git diff --stat
```

仓库目前没有配置 Python formatter、lint 或静态类型检查命令。不得编造 `ruff`、
`black`、`mypy` 或 `pyright` 已经可用；如需引入，必须单独说明依赖、范围和 CI 成本。

## 测试分层

- `unit`：隔离、确定性的领域逻辑测试。
- `contract`：artifact、API、架构和物理所有权契约。
- `integration`：离线多组件工作流和 packaging 测试。
- `compatibility`：仍被明确支持的旧入口特征测试。
- `external`：需要网络、密钥、GPU、调度器或外部运行时；默认不执行。

默认 pytest 配置排除 `external`。需要外部测试时，必须由用户明确授权，并使用：

```bash
python -m pytest -m external path/to/test.py -v
```

不得把 mock、fixture、dry-run 或 `calculator=none` 的结果描述为真实能量、力、吸附能、
结构弛豫或训练证据。

## 修改规则

- 保持改动与用户任务一致，不顺便重构无关模块。
- 不删除、覆盖或格式化用户的无关修改。
- Bug 修复先添加能捕获问题的回归测试，再实施最小修复。
- 新行为必须添加或更新对应测试；纯文档修改至少运行 Harness doctor 和差异检查。
- 公共接口变化必须验证所有入口的 `--help`，并搜索旧导入和旧路径。
- 架构迁移必须证明物理所有者、导入方向和 wheel 内容都已收敛。
- 引入新依赖前说明必要性、替代方案、运行环境和维护成本。
- 删除文件前确认它是生成物、缓存或已迁移所有者；历史资料优先移入 `legacy/`。
- 工作日志只记录实际修改、实际命令、实际结果和未验证边界。

## 验证层级

### Level 1：局部

文档、小函数或单个 Skill 修改：

- `python scripts/check_harness.py doctor`
- 目标测试
- `git diff --check`

### Level 2：模块

功能、artifact 或工作流修改：

- 相关目录测试和集成测试
- `python scripts/check_harness.py quick`
- 相关 CLI `--help` 或离线 dry-run

### Level 3：项目

公共接口、架构、package data 或依赖修改：

- `python scripts/check_harness.py ci`
- `python scripts/check_harness.py package`
- 尝试 `python scripts/check_harness.py full`，并单独报告已知或新增阻塞
- 前端改动另运行 `npm run build`

### Level 4：真实环境

网络、LLM、Materials Project、VASP、GPU/PJM、MLIP 训练或生产推理：

- 必须先获得明确授权；
- 先运行本地 contract、preflight 或 dry-run；
- 密钥只从环境读取，不进入命令输出、artifact、日志或提交；
- 报告调度器状态、运行位置、产物路径和科学证据限制。

## 失败处理

1. 保存完整错误和实际命令。
2. 判断失败发生在环境、收集、导入、契约、算法、打包还是外部运行时。
3. 先运行更小的确定性复现，不通过扩大修改范围来绕过问题。
4. 区分任务引入的失败与仓库已有基线，例如当前 structure builder 收集阻塞。
5. 修复后重跑最小复现，再按风险升级验证。
6. 无法继续时记录恢复入口、已经排除的原因和仍需的外部条件。

## 工作日志

- 每日详情写入 `work_logs/YYYY-MM-DD.md`。
- `work_log.md` 只增加该日期的索引，不复制详细内容。
- 日志必须包含修改文件、实际命令、结果、未运行项和残余风险。
- 不得记录密钥或把计划中的验证写成已经通过。

## 完成标准

只有以下条件满足时才能报告完成：

- 用户要求的行为和文档已经实现；
- 验收标准逐项核对；
- 与风险匹配的测试、入口或构建实际运行；
- 架构和 artifact 边界没有被破坏；
- `git diff --check` 通过且无无关文件被修改；
- 文档、CI 和实际命令一致；
- 完成报告列出通过、失败、未运行和残余风险，不使用“应该可以”等无证据表述。
