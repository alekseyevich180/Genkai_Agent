# Genkai Harness Engineering 使用指南

## 1. 这套 Harness 解决什么问题

Genkai 同时包含 Agent、Skills、科学工作流、表面建模、MLIP 接口、历史研究资产和
Web 前端。它的主要工程风险不是“找不到代码”，而是：

- 稳定逻辑在 `src/genkai/` 与 Skill 脚本中重复，形成两个事实来源；
- mock、dry-run、prepare 和真实计算结果被混为一谈；
- 局部测试通过，但旧入口、旧导入或 wheel 仍指向已经迁移的代码；
- 网络、密钥、GPU、PJM 或科学计算在未明确授权时被意外启动；
- 新会话只看到任务描述，不知道历史所有权和验证边界。

本项目的 Harness 由四层组成：

1. `AGENTS.md`：Codex 必须遵守的项目地图、边界和完成标准；
2. `docs/`：架构、迁移、artifact、Skill 和任务工作法；
3. `tests/` 与 `scripts/check_harness.py`：能自动失败的机械约束；
4. `.github/workflows/test.yml`：每次 push 和 pull request 的最低门禁。

Harness 的目标不是增加文件数量，而是让 Codex 能从仓库本身回答：在哪里修改、不能
改什么、怎样验证、失败后怎样恢复、哪些结果可以被称为科学证据。

## 2. 当前项目地图

| 区域 | 当前职责 | Harness 关注点 |
| --- | --- | --- |
| `src/genkai/contracts/` | artifact 和 run manifest | schema、路径安全、原子写入和 provenance |
| `src/genkai/workflows/`、`workflow/` | 科学工作流与 DAG | 阶段依赖、状态传播、dry-run 边界 |
| `src/genkai/literature/` | 论文和表面科学抽取 | 离线输入、LLM 配置、经验存储 |
| `src/genkai/modeling/` | PToModel、schema、表面算法 | 唯一稳定所有者、程序化 API、参数验证 |
| `src/genkai/compute/` | 外部计算准备和结果边界 | prepare 与 execute 分离 |
| `src/genkai/datasets/` | ASE 数据集与审核 | 数据标签、split、泄漏和 provenance |
| `src/genkai/mlip/` | MACE、DeepMD、UMA 合约 | launcher 与训练/推理证据分离 |
| `agents/Agent/skills/` | Agent 决策与薄运行入口 | 不复制稳定算法、schema 或数据 gate |
| `tests/` | 分层验证 | external 默认排除，局部通过不得冒充全量通过 |
| `legacy/paperread/` | 历史研究资产 | 不进入活动导入、入口或 wheel |
| `web/vite-frontend/` | Vite 用户界面 | 前端依赖和构建独立验证 |

当前依赖方向是：

```text
Skills
  -> Genkai workflows
  -> literature / modeling / compute / datasets / mlip
  -> contracts
```

详细迁移关系见 `docs/migration.md`，artifact 语义见
`docs/artifact-contracts.md`，Skill 边界见 `docs/skill-development.md`。

## 3. 第一次使用

### 3.1 建立独立环境

从仓库根目录执行：

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e .
uv pip install pytest
```

不要复用未知状态的父目录或其他 worktree 虚拟环境。激活后确认：

```bash
python --version
python -m pytest --version
```

Python 必须为 3.12 或更高版本。

### 3.2 运行最小健康检查

```bash
python scripts/check_harness.py doctor
python scripts/check_harness.py quick
```

`doctor` 不运行第三方测试，检查 Python 版本、项目必需路径、`pyproject.toml`、活动所有者、
文档占位符和 CI 接入。`quick` 进一步运行测试分层与架构门禁。

### 3.3 阅读入口

开始开发前至少阅读：

1. 根目录 `AGENTS.md`；
2. `docs/migration.md`；
3. 与任务相关的实现和测试；
4. 涉及 artifact 时阅读 `docs/artifact-contracts.md`；
5. 涉及 Skill 时阅读 `docs/skill-development.md`。

## 4. 给 Codex 下任务的方法

任务说明应包含目标、边界、验收标准和允许的验证范围。Genkai 特别需要明确真实环境
权限，因为“运行工作流”和“启动科学计算”不是同一件事。

推荐格式：

```text
【目标】
要解决的问题或新增的行为。

【验收标准】
1. 可观察的行为一
2. 可观察的行为二
3. 必须添加或更新的测试

【保持不变】
- 外部接口、artifact 格式或兼容入口
- 与本任务无关的模块

【允许修改】
- 明确的目录或文件

【执行权限】
- 是否允许网络、在线 LLM、Materials Project
- 是否允许 VASP、GPU/PJM、MACE/UMA/DeepMD、训练或 MD
- 是否允许 commit、push、发布

请先调查真实入口、调用链和现有测试，实施最小方案，最后逐项给出验证证据。
```

如果执行权限没有写明，默认只允许离线调查、代码修改、测试、mock、prepare、preflight
和 dry-run；不允许外部科学运行、远程写入或发布。

## 5. 标准工作循环

### 5.1 定义目标和证据

先把“完成”改写成可以观察的结果。例如，不写“优化表面建模架构”，而写：

- 稳定算法的唯一物理所有者位于 `src/genkai/modeling/surface/`；
- Skill 入口只调用库 API；
- `tests/architecture/` 不出现反向依赖；
- 新 wheel 中没有旧 `paperread/` 包；
- 相关 CLI 的 `--help` 在无 API key 时可运行。

### 5.2 调查当前状态

让 Codex 在修改前完成：

```text
1. 运行 git status，保护已有修改
2. 定位入口、调用者、测试、schema 和 package data
3. 说明当前失败路径或实现路径
4. 找到最小修改位置
5. 指定验证层级
6. 列出不会执行的外部动作
```

架构任务还要搜索：

```bash
rg -n "旧模块名|旧入口名|旧目录名" src agents tests pyproject.toml
```

不能只根据测试文件或 facade 判断迁移完成。

### 5.3 实施最小改动

- Bug：先写回归测试，再修复根因。
- 新功能：优先扩展现有公共 API，不创建同名第二实现。
- Skill：稳定逻辑下沉 `src/genkai/`，Skill 保持薄入口。
- artifact：先定义或复用契约，再连接工作流。
- 外部运行：先有 prepare/preflight/dry-run，再考虑真实执行。
- 迁移：先移动所有者，再修导入、入口、package data 和文档。

### 5.4 分级验证

先运行最小检查，再根据风险扩大。任何失败都要保留原始命令和错误，而不是换一个更窄
的测试后宣称全部通过。

### 5.5 检查最终差异

```bash
git diff --check
git status --short
git diff --stat
git diff -- AGENTS.md docs scripts tests .github README.md
```

确认没有修改用户的无关文件、没有把生成物加入提交、没有在日志或 artifact 中写入密钥。

### 5.6 记录可恢复状态

当天的详细结果写入 `work_logs/YYYY-MM-DD.md`，`work_log.md` 只增加索引。日志应包含：

- 实际修改；
- 实际命令和结果；
- 明确未运行的项目；
- 残余风险或下次恢复入口。

## 6. 验证层级和命令

### Level 0：静态 Harness 合约

适用于文档和规则修改：

```bash
python scripts/check_harness.py doctor
git diff --check
```

### Level 1：快速架构门禁

适用于小型 Python、Skill wrapper 或所有权相关修改：

```bash
python scripts/check_harness.py quick
```

它运行：

```bash
python -m pytest tests/test_test_tiers.py tests/architecture -q --tb=short
```

### Level 2：CI 门禁

适用于 Agent 导入、公共入口或跨模块修改：

```bash
python scripts/check_harness.py ci
```

该配置运行快速架构测试、`tests/test_agent.py`，并检查：

```bash
python -m genkai.cli --help
python -m genkai.cli surface --help
python -m agent.init.start_agent --help
```

GitHub Actions 使用这一层。

### Level 3：打包与项目检查

package data、入口、所有者迁移或发布相关修改必须运行：

```bash
python scripts/check_harness.py package
```

该测试会构建无依赖解析的 wheel、检查 Skill 和 schema 资源、确认 wheel 中没有
`paperread/`，并从解压 wheel 验证导入与入口。

完整默认测试为：

```bash
python scripts/check_harness.py full
```

当前已知 `tests/test_structure_builder.py` 仍导入不存在的
`agent.tools.structure_builder`，因此全量收集会失败。报告时必须同时写出：

- 哪些目标或分层测试通过；
- 全量测试是否尝试；
- 已知阻塞是否仍相同；
- 是否出现任务引入的新失败。

### Level 4：前端或真实环境

前端修改：

```bash
cd web/vite-frontend
npm run build
```

真实 LLM、Materials Project、VASP、GPU/PJM、MLIP 训练/推理和 MD 不属于默认测试。
获得用户授权后仍应先运行相应 contract 与 preflight，并把真实运行位置和产物单独记录。

## 7. 任务类型示例

### 7.1 Bug 修复

```text
请修复 RunManifest 在中断写入后留下不完整 JSON 的问题。

验收标准：
1. 中断写入不破坏上一个有效 manifest
2. 异常信息保留失败阶段
3. 添加回归测试
4. artifact schema 保持兼容

只允许离线测试，不启动任何外部计算。先复现，再实施最小修复。
```

建议验证：目标 contract 测试、`quick`，必要时相关 workflow 集成测试。

### 7.2 Skill 修改

```text
为 UMA Skill 增加一个 prepare-only 参数。

要求：稳定校验逻辑放在 src/genkai/mlip，Skill 只解析参数和调用库；不启动训练、GPU
或 PJM；保留现有 CLI；添加 contract 和 Skill 边界测试。
```

建议验证：目标 MLIP/Skill 测试、`quick`、入口 `--help`；package data 变化时运行
`package`。

### 7.3 架构迁移

```text
把某稳定实现从 Skill 迁移到 src/genkai。

验收标准：
1. src/genkai 成为唯一实现所有者
2. Skill 只保留兼容 wrapper
3. 无反向导入和重复 schema
4. 所有入口 --help 可运行
5. 干净 wheel 不包含旧所有者
```

建议验证：目标测试、`quick`、`ci`、`package`，并扫描所有旧路径和入口。

### 7.4 科学工作流

```text
从已保存的 extraction artifact 生成结构候选。

执行权限：只允许 structure-only，calculator=none，max_steps=0；禁止在线 LLM、VASP、
MLIP、训练、MD、GPU/PJM。无法从证据唯一确定的参数必须阻断并要求用户输入。
```

完成报告必须把“结构文件可被 ASE 读取”与“结构经过物理弛豫或能量验证”分开。

## 8. 已机械化的规则

| 规则 | 自动执行位置 |
| --- | --- |
| `src/genkai` 不反向依赖 Skill 或旧 paperread | `tests/architecture/test_import_boundaries.py` |
| Skill 不复制稳定 gate 或重型算法 | `tests/architecture/` |
| 旧活动所有者不回到源码树 | `tests/architecture/test_physical_layout.py`、Harness doctor |
| artifact 和 manifest 遵守契约 | `tests/contracts/` |
| pytest 分层标记存在 | `tests/test_test_tiers.py`、Harness doctor |
| wheel 包含 Skills、schema 和经验资源 | `tests/packaging/test_wheel_contents.py` |
| wheel 不包含 `paperread/` | packaging test |
| 公共 Agent/Genkai 入口可导入或显示帮助 | Harness `ci` profile |
| CI 没有绕过 Harness 门禁 | Harness doctor |
| 文档没有保留模板占位符 | Harness doctor |

仍然依赖人工判断的事项：

- 论文证据是否足以确定模型参数；
- mock 或 dry-run 是否被错误解释为科学结果；
- 外部计算的成本和授权是否合适；
- 新逻辑应进入稳定库还是继续在 Skill 中孵化；
- 全量测试中的失败是历史基线还是新回归。

## 9. 失败后的恢复方法

### 环境失败

如果 Python 版本、依赖或 editable install 不正确：

1. 运行 `python --version`；
2. 确认当前解释器来自本仓库 `.venv`；
3. 重新执行 `uv pip install -e .` 和 `uv pip install pytest`；
4. 先运行 `doctor`，再运行测试。

不要把环境失败修改成业务代码补丁。

### 测试收集失败

先区分已知的 `agent.tools.structure_builder` 阻塞与新错误。运行目标测试确认任务本身，
但最终报告必须保留全量边界，不能隐藏收集失败。

### 入口迁移失败

同时检查：

- Python 导入；
- console script 或 `python -m` 入口；
- Agent/Skill wrapper；
- package discovery 与 package data；
- 从新 wheel 解压后的导入。

### 外部运行失败

记录 preflight、调度器状态、运行目录和日志路径。不要自动重试高成本计算，不要把凭据
复制进诊断输出。能从保存的中间 artifact 恢复时，不重新执行上游在线步骤。

## 10. 完成报告模板

```markdown
## 完成内容

- 修改了什么
- 为什么这样修改

## 主要文件

- `path/to/file`：职责
- `path/to/test`：覆盖的失败路径

## 验证结果

- `实际命令`：通过，具体计数或关键输出
- `实际命令`：失败，具体原因

## 验收标准

- [x] 已满足的条件
- [ ] 未满足的条件：原因和恢复入口

## 未验证内容

- 未运行的外部、全量或平台检查及原因

## 残余风险

- 当前仍存在的风险；没有则写“未发现新增风险”
```

禁止用“应该可以”“理论上没问题”代替实际结果。

## 11. 定期健康检查

每周或一个架构阶段结束后，让 Codex 先调查而不是直接重构：

```text
请对 Genkai 进行 Harness 健康检查，不直接实施大规模重构。

检查：
1. AGENTS.md 和 docs/harness-engineering.md 是否与仓库一致
2. scripts/check_harness.py 的 profile 是否仍能运行
3. CI 是否执行当前最低门禁
4. 最近失败是否暴露新的可机械化规则
5. src/genkai 与 Skills 是否出现重复实现或反向依赖
6. artifact、schema、入口和 wheel 是否一致
7. external 测试是否仍默认隔离
8. 已知 full-suite 阻塞是否仍存在

输出事实、证据、优先级和最小改造建议，不猜测不存在的命令。
```

建议顺序：

```bash
python scripts/check_harness.py doctor
python scripts/check_harness.py quick
git status --short --branch
git diff --check
```

只有反复发生并能减少真实错误的经验才写回 Harness。一次性任务细节继续留在 dated work
log，不扩张 `AGENTS.md`。

## 12. 当前信息和自动化缺口

以下缺口应如实保留，不能用文档措辞掩盖：

- 仓库尚未配置统一的 Python formatter、lint 和静态类型检查；
- CI 的最低门禁不等于完整默认测试或 wheel 检查；
- 完整默认测试仍有 structure builder 收集阻塞；
- external 层没有统一可在所有环境执行的真实运行测试；
- 前端目前有 build 命令，但没有独立 lint 或测试脚本。

后续只在确实减少失败时逐步增加：先修复全量收集和 CI 覆盖，再评估 formatter、lint、
类型检查、前端测试和更细的科学 provenance 审计。
