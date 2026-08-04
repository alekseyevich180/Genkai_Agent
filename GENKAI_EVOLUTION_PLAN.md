# Genkai Library-First Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Genkai_Agent 演进为以稳定 Python 库为核心、以 Agent skill
为决策和实验扩展层的科研工作流平台，使论文读取、结构建模、第一性原理任务、
数据集生成、DeepMD 训练和 UMA 微调能够通过可验证的产物契约协同。

**Architecture:** 新建 `src/genkai/` 作为稳定业务内核，统一定义 artifact、
provenance、workflow 和外部运行环境 adapter；保留
`agents/Agent/skills/`，但稳定 skill 逐步变为调用库接口的薄入口。
`.workspace/skills/` 和尚未成熟的内置 skill 脚本继续作为 Skill-first
实验孵化层，验证成熟后再提升到核心库。

**Tech Stack:** Python 3.12、Pydantic v2、ASE、pymatgen、Google ADK、
Click、pytest、JSON/JSONL、EXTXYZ、ASE-LMDB、VASP、DeepMD-kit、
FAIRChem/UMA、MACE。

## Global Constraints

- 不进行一次性大规模搬迁；每个阶段完成后，现有 CLI 和已验证 skill
  入口仍应可运行。
- `python -m paperread.surface` 在迁移期保持兼容。
- `agent web`、`agent api-server` 和 `agent run` 的现有入口保持兼容。
- 稳定业务逻辑不得依赖 `agents/Agent/skills/` 中的文件。
- skill 可以依赖 `src/genkai/`，但一个 skill 不得直接导入另一个 skill
  的 `scripts/`。
- 所有科研输出保留在调用者明确指定的项目或 run 目录；外部共享环境只提供
  executable、checkpoint 和 runtime，不隐式 `cd`，不复制环境。
- dry-run、模拟计算、真实 DFT、模型训练和科学验收必须使用不同状态，不得用
  dry-run 结果代替真实计算证据。
- 模拟标签必须记录为 `evidence_level=mock`，生产模式下不得进入 DeepMD
  训练或 UMA 微调。
- MACE、DeepMD、UMA 保持三个独立职责：MACE 用于预训练模型推理与弛豫，
  DeepMD 用于训练，UMA 用于微调与微调模型验收。
- 所有跨阶段 JSON 必须包含 `schema_version`；不兼容变更提升主版本。
- 所有迁移任务遵循测试先行：先写失败测试，再实现最小功能。
- 不删除旧入口，直到兼容测试通过且至少完成一个发布周期的弃用提示。

---

## 1. 当前结构判断

当前仓库已经具有三类基础，但它们的职责尚未完全分离：

1. `paperread/surface/` 是目前最接近领域库的部分，已经按
   `core/`、`extraction/`、`experience/`、`modeling/` 和 `pipeline/`
   分类，并具有稳定 CLI。
2. `agents/Agent/` 负责 Agent、DAG 规划、skill 加载、工作空间和执行。
3. `agents/Agent/skills/*/scripts/` 同时承载稳定实现、外部环境启动器和
   探索性脚本。

当前跨目录协同主要依赖：

```text
*_surface_relations.jsonl
-> *_ptomodel.json
-> modeling/plan.json + modeling/checklist.json
-> structure files + modeling_manifest.json
-> VASP inputs/results
-> EXTXYZ
-> DeepMD data or ASE-LMDB
-> trained/fine-tuned model
```

这些文件已经形成事实上的 artifact 链，但文件类型、生产者、父产物、标签来源、
验证状态和适用模型还没有统一契约。Agent DAG 也只知道节点与 skill 名称，
不知道节点实际消费或产生了什么科研产物。

## 2. 目标目录

```text
Genkai_Agent/
├── src/
│   ├── agent/                         # 保留：Agent CLI 与启动入口
│   └── genkai/                        # 新增：稳定科研工作流内核
│       ├── contracts/
│       │   ├── artifacts.py           # ArtifactRef 与各类科研产物
│       │   ├── provenance.py          # 来源、软件、参数和证据等级
│       │   ├── validation.py          # error/warning/check 报告
│       │   └── run.py                 # RunManifest 与 StageRecord
│       ├── workflow/
│       │   ├── stage.py               # StageSpec、StageResult、StageAdapter
│       │   ├── graph.py               # artifact-aware DAG 校验
│       │   └── store.py               # manifest 原子写入与读取
│       ├── literature/
│       │   └── surface.py             # paperread/surface 稳定 facade
│       ├── modeling/
│       │   ├── ptomodel.py            # PToModel facade
│       │   └── surface.py             # 表面结构生成 facade
│       ├── compute/
│       │   └── vasp.py                # VASP prepare/collect adapter
│       ├── datasets/
│       │   ├── ase.py                 # ASE/EXTXYZ 数据读写与标签审计
│       │   └── splits.py              # train/val/test 分组与泄漏检查
│       ├── mlip/
│       │   ├── protocol.py            # MLIP 能力和输入输出协议
│       │   ├── mace.py                # MACE 推理 adapter
│       │   ├── deepmd.py              # DeepMD 训练 adapter
│       │   └── uma.py                 # UMA 微调 adapter
│       ├── workflows/
│       │   └── paper_to_mlip.py        # 论文到 MLIP 的参考工作流
│       └── cli.py                      # genkai-workflow CLI
├── agents/Agent/
│   ├── agents/                        # Agent 规划与执行
│   └── skills/                        # 稳定 skill：薄入口和领域决策
│       ├── paperread/
│       ├── ptomodel/
│       ├── surface-modeling/
│       ├── vasp/
│       ├── mace/
│       ├── deepmd/
│       └── uma/
├── paperread/                          # 兼容层，迁移期保留原入口
├── tests/
│   ├── contracts/
│   ├── workflow/
│   ├── integrations/
│   ├── skills/
│   └── fixtures/
├── plan.md                             # 当前研究任务计划
└── GENKAI_EVOLUTION_PLAN.md            # 本架构演进计划
```

## 3. 文件夹协同规则

### 3.1 单向依赖

```text
agents/Agent/skills
        |
        v
src/genkai/workflows
        |
        v
src/genkai/{literature,modeling,compute,datasets,mlip}
        |
        v
src/genkai/contracts
```

禁止的反向依赖：

- `src/genkai/` 不导入 `agents/Agent/`。
- `src/genkai/` 不读取某个 skill 的私有脚本路径。
- `paperread/surface/` 不直接调用 UMA、DeepMD 或 Agent。
- UMA skill 不直接调用 VASP skill；二者通过
  `CalculationResultArtifact` 和 `DatasetArtifact` 交接。
- Agent planner 不猜测文件内容；它读取 manifest 和 validation report。

### 3.2 Run 目录

每次可复现工作流使用一个明确 run 根目录：

```text
runs/<run_id>/
├── manifest.json
├── inputs/
├── stages/
│   ├── 01_paperread/
│   ├── 02_ptomodel/
│   ├── 03_surface_modeling/
│   ├── 04_dft/
│   ├── 05_dataset/
│   └── 06_mlip/
├── artifacts/
├── reports/
└── logs/
```

`manifest.json` 只保存路径、hash、状态和 provenance，不嵌入大型结构轨迹或
模型 checkpoint。所有路径相对于 run 根目录保存，移动完整 run 目录后仍可解析。
共享环境中的只读 checkpoint、executable 和数据库使用
`ExternalResourceRef` 记录 URI、版本、hash（可获得时）和运行环境，不复制进
run 目录，也不作为 run 生成的 artifact 冒充登记。

### 3.3 状态必须分为两个维度

执行状态：

```text
planned -> prepared -> running -> succeeded
                              \-> failed
          \-> blocked
```

证据等级：

```text
paper_extracted
heuristic
mock
mlip_predicted
dft_calculated
experiment_reported
```

例如“VASP 输入已经生成但没有真实计算”的结构必须表示为：

```json
{
  "execution_state": "prepared",
  "evidence_level": "heuristic"
}
```

不能表示为 `dft_calculated`。

## 4. 核心 Artifact 契约

第一阶段只定义以下稳定 artifact：

| Artifact | 生产阶段 | 下游消费者 |
|---|---|---|
| `PaperArtifact` | paperread ingest | extraction |
| `ExtractionArtifact` | paperread extraction | PToModel、experience |
| `ModelingPlanArtifact` | PToModel | surface modeling、人工审查 |
| `StructureSetArtifact` | surface modeling | VASP、MACE |
| `CalculationInputArtifact` | VASP prepare | 外部调度器 |
| `CalculationResultArtifact` | VASP collect | dataset |
| `DatasetArtifact` | dataset builder | DeepMD、UMA |
| `ModelArtifact` | DeepMD/UMA | evaluation、推理 |
| `EvaluationArtifact` | model evaluation | 验收报告 |

所有 artifact 共有字段：

```python
artifact_id: str
artifact_type: str
schema_version: str
path: str
sha256: str
producer: str
parent_ids: list[str]
execution_state: str
evidence_level: str
validation_status: str
metadata: dict[str, object]
```

`path` 只适用于 run 内产物。外部只读资源使用：

```python
uri: str
resource_type: str
version: str | None
sha256: str | None
read_only: bool
```

`DatasetArtifact.metadata` 还必须包含：

```text
label_source
energy_unit
force_unit
stress_unit
electronic_structure_method
functional
pseudopotential_family
split_strategy
train_count
validation_count
test_count
```

如果这些信息缺失，artifact 可以保存，但状态只能是
`validation_status=needs_review`，不能进入生产训练。

## 5. Skill-first 保留方案

### 5.1 三层成熟度

| 层级 | 位置 | 用途 | 可否承载业务实现 |
|---|---|---|---|
| Experimental | `.workspace/skills/` | 用户或 Agent 临时实验 | 可以 |
| Candidate | `agents/Agent/skills/*/scripts/` | 已进入仓库但仍在验证 | 可以，必须有隔离测试 |
| Stable | `src/genkai/` + 薄 skill | 被多个 workflow 复用 | 实现必须进入库 |

晋升条件：

1. 至少有三个 skill evaluation：正向触发、负向不触发、相邻 skill
   边界判断。
2. 至少有一个成功路径测试和一个失败门禁测试。
3. 输入、输出已经映射为正式 artifact。
4. 不依赖隐式当前目录或开发者个人路径。
5. dry-run 和真实执行边界已经写入 validation report。
6. 业务实现被两个以上入口复用，或已成为关键主工作流的一部分。

### 5.2 稳定 skill 标准结构

```text
agents/Agent/skills/<skill-name>/
├── SKILL.md
├── agents/openai.yaml
├── references/
│   └── runtime.md
├── scripts/
│   └── run_<skill_name>.py
└── evaluations/
    └── cases.yaml
```

稳定 skill 的 `scripts/` 只能做：

- 参数解析；
- 调用 `src/genkai/`；
- 将库返回的 report 转成人类可读输出；
- 启动经过 preflight 的外部命令。

稳定 skill 的 `scripts/` 不再维护第二份领域规则、schema 或数据清洗逻辑。

### 5.3 SKILL.md frontmatter 标准

```yaml
---
name: uma
description: Use when a validated labeled dataset must fine-tune or evaluate a UMA model; do not use for DeepMD training or MACE inference.
metadata:
  maturity: stable
  domain: mlip
  tools:
    - run_skill_script
  dependent_skills: []
  consumes:
    - dataset@1
  produces:
    - model@1
    - evaluation@1
  entrypoints:
    - scripts/run_uma.py
---
```

description 只负责说明触发条件和边界；详细操作步骤写在正文或
`references/`。一个 reference 不再继续引用更深层 reference。

## 6. MLIP 协同边界

三个 MLIP 模块共享 artifact，不共享职责：

```text
StructureSetArtifact
        |
        +--------------------> MACE
        |                      produces CalculationResultArtifact
        |
CalculationResultArtifact
        |
        v
DatasetArtifact
        |
        +--------------------> DeepMD
        |                      produces ModelArtifact(role=trained)
        |
        +--------------------> UMA
                               consumes base ModelArtifact
                               produces ModelArtifact(role=fine_tuned)
```

强制路由规则：

- “使用预训练势计算能量、力或弛豫”选择 MACE。
- “从数据训练新势或继续 DeepMD checkpoint”选择 DeepMD。
- “基于 UMA checkpoint 做单任务微调、恢复或验收”选择 UMA。
- `DatasetArtifact.evidence_level=mock` 时，DeepMD 和 UMA 的生产执行
  preflight 必须失败；dry-run 可以继续。
- UMA 只接受有独立 test split、无跨 split 泄漏并通过 LMDB 回读的训练输入。
- DeepMD 和 UMA 可以共享结构分组、单位和 provenance 审计，但使用各自的
  数据转换和运行 adapter。

---

## 7. 分阶段实施任务

### Task 1: 建立 `genkai` 包和 artifact 契约

**Files:**

- Create: `src/genkai/__init__.py`
- Create: `src/genkai/contracts/__init__.py`
- Create: `src/genkai/contracts/artifacts.py`
- Create: `src/genkai/contracts/provenance.py`
- Create: `src/genkai/contracts/validation.py`
- Test: `tests/contracts/test_artifacts.py`
- Modify: `pyproject.toml`

**Interfaces:**

- Produces: `ArtifactRef`, `ExternalResourceRef`, `Provenance`, `ValidationIssue`,
  `ValidationReport`, `EvidenceLevel`, `ExecutionState`,
  `ValidationStatus`.
- All later tasks consume these exact types.

- [x] **Step 1: 写 artifact round-trip 失败测试**

测试构造一个 `StructureSetArtifact`，写出 JSON，再读回并断言
`artifact_id`、`parent_ids`、`evidence_level` 和相对路径不变；同时断言绝对
artifact 路径被拒绝。

Run:

```bash
pytest tests/contracts/test_artifacts.py -v
```

Expected: FAIL because `genkai.contracts` does not exist.

- [x] **Step 2: 实现枚举、provenance 和基础 artifact**

使用 Pydantic discriminated union 定义第 4 节列出的九种 artifact。
`path` 使用 POSIX 相对路径并拒绝 `..`；`sha256` 必须是 64 位小写十六进制。

- [x] **Step 3: 实现 validation report**

`ValidationReport` 提供
`errors: list[ValidationIssue]`、`warnings: list[ValidationIssue]`、
`checks: list[ValidationIssue]` 和只读属性 `passed`；存在 error 时
`passed` 必须为 `False`。

- [x] **Step 4: 声明 Pydantic 直接依赖并运行测试**

在 `pyproject.toml` 中加入与当前 Python 3.12 环境兼容的
`pydantic>=2.12.0`。

Run:

```bash
pytest tests/contracts/test_artifacts.py -v
```

Expected: PASS.

- [x] **Step 5: 提交独立变更**

```bash
git add pyproject.toml src/genkai tests/contracts
git commit -m "feat: add versioned scientific artifact contracts"
```

### Task 2: 建立 RunManifest 和原子化 manifest store

**Files:**

- Create: `src/genkai/contracts/run.py`
- Create: `src/genkai/workflow/__init__.py`
- Create: `src/genkai/workflow/store.py`
- Test: `tests/contracts/test_run_manifest.py`

**Interfaces:**

- Consumes: `ArtifactRef`, `ValidationReport`.
- Produces: `RunManifest`, `StageRecord`,
  `load_manifest(run_root: Path) -> RunManifest` 和
  `save_manifest(run_root: Path, manifest: RunManifest) -> Path`.

- [x] **Step 1: 写 manifest 生命周期失败测试**

测试创建 run、追加 stage、注册 artifact、保存、读回，并验证父 artifact
必须已存在。另一个测试模拟写入中断，断言原 manifest 不被破坏。

- [x] **Step 2: 运行测试并确认预期失败**

```bash
pytest tests/contracts/test_run_manifest.py -v
```

Expected: FAIL because `RunManifest` and store functions are absent.

- [x] **Step 3: 实现 manifest 模型和原子写入**

`save_manifest` 先写同目录临时文件，执行 `flush` 和 `os.fsync` 后用
`Path.replace` 替换 `manifest.json`。禁止在 manifest 中登记 run 根目录之外
的 artifact。

- [x] **Step 4: 运行契约测试**

```bash
pytest tests/contracts/test_run_manifest.py tests/contracts/test_artifacts.py -v
```

Expected: PASS.

- [x] **Step 5: 提交独立变更**

```bash
git add src/genkai/contracts/run.py src/genkai/workflow tests/contracts
git commit -m "feat: add reproducible run manifests"
```

### Task 3: 建立 artifact-aware workflow DAG

**Files:**

- Create: `src/genkai/workflow/stage.py`
- Create: `src/genkai/workflow/graph.py`
- Test: `tests/workflow/test_stage_graph.py`

**Interfaces:**

- Consumes: artifact 类型名与 schema major version。
- Produces: `ArtifactRequirement`, `StageSpec`, `WorkflowGraph`,
  `validate_workflow(graph: WorkflowGraph) -> ValidationReport`.

- [x] **Step 1: 写 DAG 契约失败测试**

覆盖四种情况：

1. paperread 产生 extraction，PToModel 正确消费；
2. 下游要求 `dataset@1` 但上游只产生 `structure-set@1`；
3. schema 主版本不兼容；
4. DAG 存在循环。

- [x] **Step 2: 运行测试并确认四类失败可区分**

```bash
pytest tests/workflow/test_stage_graph.py -v
```

Expected: FAIL because workflow graph validation is absent.

- [x] **Step 3: 实现 StageSpec 和静态 DAG 校验**

每个 stage 明确声明 `consumes`、`produces`、`adapter` 和
`allows_mock_inputs`。校验器在执行前报告缺失生产者、类型不匹配、版本不兼容
和循环。

- [x] **Step 4: 运行 workflow 与 contract 测试**

```bash
pytest tests/contracts tests/workflow -v
```

Expected: PASS.

- [x] **Step 5: 提交独立变更**

```bash
git add src/genkai/workflow tests/workflow
git commit -m "feat: validate workflow artifact dependencies"
```

### Task 4: 为 paperread、PToModel 和 surface modeling 建立稳定 facade

**Files:**

- Create: `src/genkai/literature/__init__.py`
- Create: `src/genkai/literature/surface.py`
- Create: `src/genkai/modeling/__init__.py`
- Create: `src/genkai/modeling/ptomodel.py`
- Create: `src/genkai/modeling/surface.py`
- Test: `tests/integrations/test_surface_facades.py`
- Modify: `paperread/surface/pipeline/runner.py`
- Modify: `paperread/surface/modeling/job_bundle.py`

**Interfaces:**

- Produces:
  `run_surface_extraction(request, run_root) -> ExtractionArtifact`,
  `build_modeling_plan(extraction, run_root) -> ModelingPlanArtifact`，
  `build_surface_candidates(plan, run_root, mode) -> StructureSetArtifact`.
- Existing `paperread.surface` CLI remains a compatibility caller.

- [x] **Step 1: 用最小 JSON fixture 写 facade 失败测试**

fixture 必须覆盖一个明确 `CeO2(111)`、一个 `*OH` 和一个
`needs_manual_decision` 参数。测试不访问网络、不运行真实计算。

- [x] **Step 2: 运行测试并记录旧输出基线**

```bash
pytest tests/integrations/test_surface_facades.py tests/test_paperread_surface.py -v
```

Expected: new facade tests FAIL; existing paperread tests PASS.

- [x] **Step 3: 实现 facade，不搬迁原算法**

第一轮 facade 调用现有 `paperread.surface` 函数，将输出包装为 artifact，
计算 hash，并登记到 manifest。不得复制 PToModel 映射规则。

- [x] **Step 4: 让 job bundle 写 artifact 引用**

保留 `article.json`、`modeling/plan.json` 和 `modeling/checklist.json`，
并在 manifest 中登记它们；旧字段继续保留，新增字段使用 schema version
控制。

- [x] **Step 5: 跑兼容与新契约测试**

```bash
pytest tests/test_paperread_surface.py tests/integrations/test_surface_facades.py -v
python -m paperread.surface --help
python -m paperread.surface list-tools
```

Expected: all tests PASS and both CLI commands exit 0.

- [x] **Step 6: 提交独立变更**

```bash
git add src/genkai/literature src/genkai/modeling paperread/surface tests/integrations
git commit -m "feat: expose surface workflow through stable facades"
```

### Task 5: 建立 VASP、dataset 和 MLIP adapter 边界

**Files:**

- Create: `src/genkai/compute/__init__.py`
- Create: `src/genkai/compute/vasp.py`
- Create: `src/genkai/datasets/__init__.py`
- Create: `src/genkai/datasets/ase.py`
- Create: `src/genkai/datasets/splits.py`
- Create: `src/genkai/mlip/__init__.py`
- Create: `src/genkai/mlip/protocol.py`
- Create: `src/genkai/mlip/mace.py`
- Create: `src/genkai/mlip/deepmd.py`
- Create: `src/genkai/mlip/uma.py`
- Modify: `agents/Agent/skills/vasp/scripts/vasp_tools.py`
- Test: `tests/integrations/test_compute_dataset_mlip_contracts.py`

**Interfaces:**

- `prepare_vasp_inputs(structures, run_root) -> CalculationInputArtifact`
- `collect_vasp_results(input_artifact, run_root) -> CalculationResultArtifact`
- `build_dataset(results, split_policy, run_root) -> DatasetArtifact`
- `MaceAdapter.prepare_inference(structures: StructureSetArtifact, run_root: Path, mode: RunMode) -> StageResult`
- `DeepMDAdapter.prepare_training(dataset: DatasetArtifact, run_root: Path, mode: RunMode) -> StageResult`
- `UmaAdapter.prepare_finetuning(dataset: DatasetArtifact, base_model: ModelArtifact | ExternalResourceRef, run_root: Path, mode: RunMode) -> StageResult`

- [x] **Step 1: 写角色边界和证据门禁失败测试**

测试必须证明：

- MACE 接受 structure set；
- DeepMD 接受真实 labeled dataset；
- UMA 接受真实 labeled dataset 和 base model；
- DeepMD/UMA 生产模式拒绝 mock dataset；
- UMA 拒绝缺失 test split 或存在 split leakage 的数据。

- [x] **Step 2: 写 VASP 可选依赖失败测试**

在没有 `dpdata` 的环境导入 VASP prepare 模块并调用 `--help` 应成功；只有
需要 `dpdata` 的 collect 子命令才返回明确依赖错误。

- [x] **Step 3: 运行测试并确认失败原因**

```bash
pytest tests/integrations/test_compute_dataset_mlip_contracts.py -v
```

Expected: FAIL because adapters do not exist and VASP imports `dpdata` eagerly.

- [x] **Step 4: 实现 adapter preflight 和 lazy import**

adapter 只生成经过验证的 command specification，不自行提交 PJM 作业。
VASP 中将 `dpdata` 移到实际需要它的函数内，并返回安装建议。

- [x] **Step 5: 复用现有 UMA 审计，不复制规则**

将稳定的距离、标签、split leakage 和 LMDB readback 逻辑提升到
`src/genkai/datasets/`；旧 UMA 脚本改为调用这些函数，并保持原命令行参数。

- [x] **Step 6: 运行门禁和脚本静态检查**

```bash
pytest tests/integrations/test_compute_dataset_mlip_contracts.py -v
python agents/Agent/skills/vasp/scripts/vasp_tools.py --help
bash -n agents/Agent/skills/mace/scripts/submit_mace_calculation.sh
bash -n agents/Agent/skills/deepmd/scripts/submit_deepmd_training.sh
bash -n agents/Agent/skills/uma/scripts/prepare_uma_finetune_dataset.sh
bash -n agents/Agent/skills/uma/scripts/submit_uma_finetuning.sh
```

Expected: all commands exit 0; no real calculation or training starts.

- [x] **Step 7: 提交独立变更**

```bash
git add src/genkai/compute src/genkai/datasets src/genkai/mlip agents/Agent/skills/vasp agents/Agent/skills/uma tests/integrations
git commit -m "feat: add validated compute dataset and MLIP adapters"
```

### Task 6: 建立论文到 MLIP 的参考工作流和 CLI

**Files:**

- Create: `src/genkai/workflows/__init__.py`
- Create: `src/genkai/workflows/paper_to_mlip.py`
- Create: `src/genkai/cli.py`
- Create: `tests/workflow/test_paper_to_mlip.py`
- Create: `tests/fixtures/paper_to_mlip/minimal_surface_relations.jsonl`
- Create: `tests/fixtures/paper_to_mlip/mock_labels.extxyz`
- Modify: `pyproject.toml`

**Interfaces:**

- `build_paper_to_mlip_graph(target: Literal["mace", "deepmd", "uma"])`
- `preflight_paper_to_mlip(run_root, target, mode) -> ValidationReport`
- CLI entrypoint: `genkai-workflow`.

- [x] **Step 1: 写三种目标路由失败测试**

断言 MACE 路径在 structure set 后结束；DeepMD 路径需要真实 dataset；UMA
路径同时需要真实 dataset、base model 和 test split。

- [x] **Step 2: 写 mock 标签隔离测试**

`genkai-workflow preflight --target uma --mode production` 对 mock fixture
必须退出非零；`--mode dry-run` 可以生成计划，但 report 必须包含
`mock_labels_not_trainable`。

- [x] **Step 3: 实现工作流构建和 preflight CLI**

CLI 只执行 `init`、`inspect`、`preflight` 和 `run --mode dry-run`。
真实 DFT、训练或 scheduler submission 仍需通过对应 adapter 和用户明确授权。

- [x] **Step 4: 声明 CLI 并运行测试**

在 `pyproject.toml` 增加：

```toml
genkai-workflow = "genkai.cli:main"
```

Run:

```bash
pytest tests/workflow/test_paper_to_mlip.py -v
genkai-workflow --help
```

Expected: PASS and help exits 0.

- [x] **Step 5: 提交独立变更**

```bash
git add pyproject.toml src/genkai/workflows src/genkai/cli.py tests/workflow tests/fixtures/paper_to_mlip
git commit -m "feat: add artifact-aware paper to MLIP workflow"
```

### Task 7: 建立统一 skill contract 和孵化晋升机制

**Files:**

- Create: `src/genkai/skills/__init__.py`
- Create: `src/genkai/skills/contract.py`
- Create: `tests/skills/test_builtin_skill_contracts.py`
- Create: `tests/skills/test_skill_boundaries.py`
- Modify: `agents/Agent/skills/paperread/SKILL.md`
- Modify: `agents/Agent/skills/ptomodel/SKILL.md`
- Modify: `agents/Agent/skills/surface-modeling/SKILL.md`
- Modify: `agents/Agent/skills/vasp/SKILL.md`
- Modify: `agents/Agent/skills/mace/SKILL.md`
- Modify: `agents/Agent/skills/deepmd/SKILL.md`
- Modify: `agents/Agent/skills/uma/SKILL.md`
- Create in each listed skill: `evaluations/cases.yaml`

**Interfaces:**

- `load_skill_contract(skill_dir: Path) -> SkillContract`
- `validate_skill_contract(contract, known_skills) -> ValidationReport`
- Required metadata: `maturity`, `domain`, `tools`, `dependent_skills`,
  `consumes`, `produces`, `entrypoints`.

- [x] **Step 1: 写当前 skill 的 characterization test**

先记录七个核心 skill 能被 ADK 加载、名称唯一，且现有
`dependent_skills` 均指向真实 skill。

- [x] **Step 2: 写新 contract 失败测试**

测试缺少 maturity、未知 dependency、无效 artifact version、缺失 entrypoint
和 description 未以 `Use when` 开头时会给出不同错误码。

- [x] **Step 3: 实现 YAML frontmatter contract loader**

只解析 `SKILL.md` 首个 YAML frontmatter；保留 ADK 原字段，不创建第二份
manifest。`evaluations/cases.yaml` 至少包含 `positive`、`negative` 和
`boundary` 三类。

- [x] **Step 4: 逐个规范七个核心 skill**

不在这一任务搬迁尚未稳定的算法；只统一触发描述、角色边界、artifact 声明、
entrypoint 和 evaluation。MACE、DeepMD、UMA 的排他边界必须进入 boundary
cases。

- [x] **Step 5: 运行静态、加载和边界测试**

```bash
pytest tests/skills/test_builtin_skill_contracts.py tests/skills/test_skill_boundaries.py -v
python -c "from agents.Agent.skill import load_skills; assert len(load_skills()) > 0"
```

Expected: PASS.

- [x] **Step 6: 提交独立变更**

```bash
git add src/genkai/skills agents/Agent/skills tests/skills
git commit -m "feat: standardize stable skill contracts"
```

### Task 8: 让 Agent DAG 感知 artifact，但保持旧计划兼容

**Files:**

- Modify: `agents/Agent/agents/thinking_agent/planning.py`
- Modify: `agents/Agent/agents/execution_agent/step_executor.py`
- Modify: `agents/Agent/agents/execution_agent/step_executor_runner.py`
- Modify: `agents/Agent/skill.py`
- Test: `tests/test_agent_artifact_planning.py`

**Interfaces:**

- `GraphNode` 新增默认空列表：
  `consumes: list[ArtifactRequirement]` 和
  `produces: list[ArtifactRequirement]`.
- `StepExecutorResult` 保留 `artifacts: list[str]`，并新增
  `artifact_ids: list[str]` 和 `manifest_path: str | None`。
- 旧计划不提供新字段时仍可解析。

- [x] **Step 1: 写旧计划兼容失败测试**

使用当前不含 artifact 字段的 graph payload，断言仍可通过
`ExecutionGraph` 校验。

- [x] **Step 2: 写新计划静态拒绝测试**

构造一个 UMA 节点直接消费 structure set 的 DAG，断言规划阶段失败并指出
缺少 dataset 和 base model。

- [x] **Step 3: 实现可选 artifact 字段和 graph 转换**

Agent 现有节点状态机保持不变；仅在提供 artifact 声明时调用
`src/genkai/workflow/graph.py` 做额外校验。

- [x] **Step 4: 执行器登记真实产物**

当 skill 返回 manifest path 时，执行器从 manifest 读取 artifact IDs；
普通文件路径继续放在旧 `artifacts` 字段，避免破坏前端展示。

- [x] **Step 5: 运行 Agent 回归测试**

```bash
pytest tests/test_agent.py tests/test_agent_artifact_planning.py -v
```

Expected: PASS.

- [x] **Step 6: 提交独立变更**

```bash
git add agents/Agent tests/test_agent_artifact_planning.py
git commit -m "feat: make agent plans artifact aware"
```

### Task 9: 完成端到端 dry-run、文档和弃用门禁

**Files:**

- Create: `tests/integrations/test_paper_surface_to_uma_dry_run.py`
- Create: `docs/artifact-contracts.md`
- Create: `docs/skill-development.md`
- Modify: `README.md`
- Modify: `plan.md`
- Modify: `work_log.md`
- Modify: `work_logs/2026-07-30.md`

**Interfaces:**

- End-to-end test consumes repository fixture only。
- Produces a complete run manifest ending at UMA training preflight.
- No network、GPU、PJM、VASP execution or UMA training.

- [x] **Step 1: 写完整 dry-run 测试**

链路固定为：

```text
saved paper extraction
-> PToModel
-> surface candidate
-> VASP input preparation
-> mock calculation result
-> dataset audit
-> UMA production rejection
-> UMA dry-run plan success
```

测试同时断言 mock result 从未变成 `dft_calculated`。

- [x] **Step 2: 运行端到端测试**

```bash
pytest tests/integrations/test_paper_surface_to_uma_dry_run.py -v
```

Expected: PASS without external services.

- [x] **Step 3: 运行完整相关回归**

```bash
pytest tests/contracts tests/workflow tests/integrations tests/skills tests/test_paperread_surface.py tests/test_agent.py -v
python -m paperread.surface --help
agent --help
genkai-workflow --help
```

Expected: all selected tests and commands PASS.

- [x] **Step 4: 更新文档和真实验证边界**

`README.md` 描述新库入口和三个 MLIP 角色；`plan.md` 将原
paperread/PToModel 计划映射到 artifact stages；工作日志记录实际执行过的
命令，并明确没有运行的真实计算、GPU、PJM 和训练。

- [x] **Step 5: 检查弃用条件**

只有同时满足以下条件，才在后续版本删除旧实现：

1. 新 facade 已覆盖旧 CLI 的已维护功能；
2. 兼容测试持续通过；
3. README 已发布替代入口；
4. 至少经过一个带弃用提示的发布周期；
5. 仓库内没有 skill 直接导入被删除脚本。

- [x] **Step 6: 执行仓库一致性检查**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; status only contains本计划范围内的文件。

- [x] **Step 7: 提交独立变更**

```bash
git add README.md plan.md work_log.md work_logs docs tests/integrations
git commit -m "docs: complete library-first workflow migration"
```

---

## 8. 阶段验收门槛

### Milestone A：契约内核可用

- 九种 artifact 可以 JSON round-trip。
- manifest 原子写入、路径隔离和父产物检查通过。
- workflow DAG 能在执行前发现类型、版本和循环错误。

### Milestone B：现有表面工作流进入统一协议

- `paperread.surface` 旧入口继续通过。
- paperread、PToModel、surface modeling 产生正式 artifact。
- unresolved 参数仍停留在 checklist，不被自动伪造。

### Milestone C：计算与 MLIP 边界稳定

- VASP prepare 在缺少 `dpdata` 时仍可使用。
- mock 标签在生产 DeepMD/UMA preflight 被拒绝。
- MACE、DeepMD、UMA 路由测试覆盖正向与排他场景。

### Milestone D：Agent 和 skill 完成迁移

- 七个核心 skill 通过统一 contract 和三类 evaluation。
- Agent DAG 可以声明并检查 artifact 输入输出。
- 旧 plan 和前端 artifact 路径仍兼容。

### Milestone E：允许逐步删除旧实现

- 端到端 dry-run 连通。
- 旧入口至少经历一个弃用周期。
- 删除动作单独规划和审查，不与功能迁移混在同一提交。

## 9. 不纳入第一轮改造的事项

以下能力需要独立科学方案，不应借架构重构顺带宣称完成：

- 自动生成完整表面反应物、中间体、产物和过渡态；
- 自动构建可信 NEB 路径；
- 无定形 LaOx/SiO2 支撑体的通用构建；
- 真实 VASP/PJM 批量提交和收敛判定；
- 真实 UMA 微调、checkpoint 恢复和微调模型精度验收；
- GPU/CUDA 性能和稳定性验证；
- 用模拟标签训练可用于科研结论的模型。

这些任务以后可以作为独立 workflow pack 开发，但仍必须消费和产生本计划定义
的 artifact。

## 10. 推荐实施顺序

```text
Task 1 contracts
-> Task 2 manifest
-> Task 3 workflow DAG
-> Task 4 paper/modeling facade
-> Task 5 compute/dataset/MLIP adapters
-> Task 6 reference workflow
-> Task 7 skill contract
-> Task 8 Agent integration
-> Task 9 end-to-end acceptance
```

Task 1–3 是平台基础；Task 4–6 形成第一条可运行纵向切片；Task 7 保留并规范
Skill-first 扩展能力；Task 8–9 最后接入 Agent，避免在核心契约尚未稳定时同时
修改规划器和领域逻辑。

## 11. 工期与 Token 预算

### 11.1 估算口径

下列估算只包含：

- 代码、测试、兼容层和文档修改；
- 本地静态检查、单元测试、集成 dry-run；
- 已保存论文抽取结果的离线回放；
- MACE、DeepMD、UMA launcher 的非计算 preflight；
- 每个任务一次实现审查和一次修正循环。

下列工作不计入估算：

- 真实 VASP、GPU、PJM 或其他 scheduler 队列等待；
- DeepMD 真实训练；
- UMA 真实微调、resume 或 checkpoint 验收；
- 外部 LLM 批量论文抽取；
- 新的反应路径、过渡态、NEB 或无定形结构科学方法开发；
- 因外部依赖版本变化导致的大规模环境重装。

Token 指 Agent 在阅读代码、生成补丁、分析工具输出、运行测试和修正问题时消耗
的模型上下文与输出 Token，不代表 GPU、CPU 或 API 计算费用。

### 11.2 为什么完整改造需要较长时间

本计划不是单纯新建目录，而是带兼容约束的渐进迁移，主要成本来自：

1. 现有 `paperread.surface`、Agent CLI、skill 和 JSON 输出不能同时中断；
2. artifact、manifest、provenance 和 validation 必须先形成稳定契约；
3. VASP、ASE、DeepMD、UMA、MACE 使用不同格式和运行环境；
4. mock、dry-run、真实 DFT 和训练结果必须有不可混淆的证据边界；
5. 稳定逻辑从 skill 提升到库后，旧脚本仍需作为兼容入口；
6. Agent DAG、skill loader、前端文件路径和旧 session 需要回归检查；
7. 每个任务都包含失败测试、最小实现、回归测试、文档和独立提交。

因此，直接写出一套新目录很快；证明新旧路径协同且不会产生错误科研状态，才是
主要时间成本。

### 11.3 按 Task 的保守估算

| Task | 内容 | Agent 活跃时间 | Token |
|---|---|---:|---:|
| 1 | Artifact contracts | 2.5–4 小时 | 30k–55k |
| 2 | RunManifest 与 store | 2–3.5 小时 | 25k–45k |
| 3 | Artifact-aware DAG | 3–5 小时 | 35k–65k |
| 4 | paperread/modeling facade | 5–8 小时 | 60k–110k |
| 5 | VASP/dataset/MLIP adapters | 7–11 小时 | 90k–160k |
| 6 | paper-to-MLIP workflow CLI | 4–6 小时 | 45k–85k |
| 7 | Skill contract 与 evaluation | 4–7 小时 | 55k–100k |
| 8 | Agent DAG 集成 | 5–9 小时 | 70k–130k |
| 9 | 端到端验收与文档 | 3.5–6 小时 | 45k–80k |
| **合计** | **完整 Task 1–9** | **36–60 小时** | **455k–830k** |

为依赖差异、旧路径耦合和一次额外修正预留缓冲后，完整预算按：

```text
时间：35–60 小时活跃实施，约 5–10 个工作日
Token：500k–900k
```

如果使用多个 Agent 并行，墙钟时间预计缩短到 3–6 个工作日，但因为重复读取
上下文和交叉审查，Token 通常增加 20%–40%。

### 11.4 高不确定性任务

估算波动主要来自：

- Task 5：UMA 审计逻辑从 skill 提升到库后的命令行兼容；
- Task 5：VASP `dpdata` lazy import 对 result collection 的影响；
- Task 8：新增 artifact 字段对 ADK 序列化、旧 session 和前端的影响；
- `tests/test_paperread_surface.py` 暴露的隐藏路径依赖；
- 当前环境中的 ASE、Pydantic、Google ADK 和 FAIRChem 版本差异。

如果其中一项需要重新设计，该任务先停止并形成独立问题记录，不从后续任务预算
中静默借用时间。

## 12. 三种交付级别

### Level A：架构骨架

范围：

- Task 1 完整完成；
- Task 2 完成最小 RunManifest 和原子写入；
- Task 3 完成静态 artifact DAG 校验；
- 不迁移现有领域代码，不修改 Agent DAG。

预算：

```text
时间：4–8 小时
Token：80k–150k
```

交付结果：

- `src/genkai/` 包可导入；
- artifact 和 manifest 可 JSON round-trip；
- workflow 在执行前能发现缺失 artifact 和循环；
- 现有工作流完全不受影响。

### Level B：快速可用 MVP（推荐）

范围：

- 完成 Level A；
- Task 4 完成 paperread、PToModel 和 surface modeling facade；
- Task 5 先完成 VASP prepare、dataset preflight 和 UMA adapter；
- MACE、DeepMD 在本级只落实协议与角色测试，不迁移其全部内部实现；
- UMA 继续复用当前已验证脚本，不在本级提升全部审计代码；
- Task 6 完成离线 `paper -> surface -> mock DFT -> UMA dry-run`；
- 不执行 Task 7–8，不修改全部 skill，也不修改 Agent DAG。

预算：

```text
时间：12–24 小时
Token：200k–400k
自然时间：约 1–3 个工作日
```

MVP 验收命令：

```bash
pytest tests/contracts tests/workflow/test_stage_graph.py tests/integrations/test_surface_facades.py tests/workflow/test_paper_to_mlip.py -v
python -m paperread.surface --help
genkai-workflow --help
```

MVP 必须证明：

- 新库核心存在且不依赖 `agents/Agent/skills/`；
- 现有 paperread CLI 仍可运行；
- run manifest 可以追踪 paper、plan、structure、mock result 和 dataset；
- UMA production preflight 拒绝 mock 数据；
- UMA dry-run 可以生成计划但不会训练；
- 没有网络、真实 DFT、GPU 或 PJM 作业。

### Level C：完整生产级改造

范围：

- 完成 Task 1–9；
- 将稳定数据审计逻辑提升到库；
- 七个核心 skill 通过 contract 和三类 evaluation；
- Agent DAG 感知 artifact；
- 完成兼容、端到端和弃用门禁。

预算：

```text
时间：35–60 小时活跃实施
Token：500k–900k
自然时间：约 5–10 个工作日
```

Level C 不包含真实科研计算。真实训练与科学验收必须另行估算。

## 13. 推荐分批执行和停止门槛

### Batch 1：契约内核

执行 Task 1–3。

继续条件：

- contract tests 全部通过；
- manifest 不允许路径逃逸；
- DAG 能识别类型、版本和循环错误；
- 现有测试未出现由新包引起的回归。

任一条件失败时，在 Batch 1 内修复，不进入 facade 迁移。

### Batch 2：快速 MVP

执行 Task 4、Task 5 的 MVP 范围和 Task 6。

继续条件：

- paperread 兼容入口通过；
- artifact chain 可以离线重放；
- mock 标签无法进入 UMA production；
- 新 facade 没有复制第二份 PToModel 规则；
- run 输出全部保留在调用者目录。

完成 Batch 2 后先审查一次架构和实际使用体验，再决定是否进入 Agent 集成。

### Batch 3：Skill 与 Agent

执行 Task 5 剩余范围、Task 7–9。

继续条件：

- MACE、DeepMD、UMA 排他路由测试通过；
- 七个核心 skill 的 contract 和 evaluation 通过；
- 旧 Agent graph payload 仍可解析；
- 完整相关回归通过；
- 文档明确 dry-run 与真实科研计算的边界。

## 14. Token 控制策略

如果优先控制 Token，采用以下执行规则：

1. 默认单 Agent 顺序执行，不主动并行。
2. 每个 Batch 使用独立上下文摘要，只加载当前 Task、Global Constraints 和直接
   依赖文件。
3. 开发阶段运行目标测试；完整相关回归只在 Milestone 和 Task 9 运行。
4. 工具输出只保留失败片段、测试汇总和必要 diff，不反复读取大型 fixture。
5. 每个 Task 完成后提交或形成明确 checkpoint，避免后续重新分析已完成范围。
6. 如果同一错误连续出现三次，停止重复尝试，记录根因并重新设计该小节。
7. 不在架构迁移中顺带增加新的科学功能。

推荐 Token 上限：

```text
Level A：150k
Level B：400k
Level C：900k
```

到达某一级预算的 80% 时，先运行该级验收并报告剩余工作，不自动扩大范围。

---

## 15. 2026-07-30 当前实施快照与下一阶段交接

本节用于在后续会话中恢复实际进度。它区分“稳定契约和工作流已经建立”与
“旧代码已经完成物理迁移”两个不同的完成条件。

### 15.1 当前分支与交付位置

- Task 1–9 的当前实现提交为 `f338263`。
- GitHub 分支为 `feat/genkai-evolution`，远端跟踪分支为
  `origin/feat/genkai-evolution`。
- 主项目目录下的 `Genkai_Evolution/` 是该分支的独立 Git worktree，也是继续
  开发和验证新版本的位置。
- 根目录共享 `.venv` 的 `Genkai 2.2.0` editable project 指向
  `Genkai_Evolution/`；旧 `agent 1.0.0` editable 映射已移除。

### 15.2 第一轮已经完成的范围

第一轮已建立并验证：

1. `src/genkai/contracts/` 的 artifact、provenance、validation 和 run
   manifest 契约。
2. `src/genkai/workflow/` 的 stage、artifact-aware DAG 和原子 manifest
   store。
3. paperread、PToModel 和 surface modeling 的稳定 facade。
4. VASP、ASE dataset、MACE、DeepMD 和 UMA 的职责边界与生产门禁。
5. `genkai-workflow` CLI 和 paper-to-MLIP reference workflow。
6. 七个核心 skill 的 contract、evaluation 和边界声明。
7. Agent DAG 的可选 artifact 输入输出以及旧 graph payload 兼容。
8. clean wheel 中的 Agent package、skill 资源和 CLI 入口。

当前相关回归记录为 `100 passed`、`16 subtests passed`。同时通过两个 CLI
help、`paperread.surface list-tools`、launcher `bash -n`、clean-wheel
安装和 skill 加载检查。仓库级 `pytest -q` 仍被既有
`tests/test_structure_builder.py` 的缺失模块
`agent.tools.structure_builder` 阻断；这不是 Task 1–9 回归通过的组成部分。

没有运行真实 VASP、GPU/CUDA、PJM、MACE 科学推理、DeepMD 训练、UMA 微调、
结构弛豫或分子动力学。dry-run 与 mock 结果不得视为真实科研计算证据。

### 15.3 结构审计结论

用户对新旧目录进行对比后指出顶层结构变化不明显。审计确认：

- 新增的主要物理结构是 `src/genkai/` 及按 contracts、workflow、
  integrations、skills 和 packaging 分类的新测试。
- `agents/`、`paperread/`、`start/`、`web/` 和大量旧测试仍保留原位置。
- 本地 `main` 已包含同一轮实现，因此本地比较 `main` 与
  `feat/genkai-evolution` 时只剩专用 worktree 的 `.gitignore` 差异；评估演进
  内容应比较 GitHub `origin/main` 与 `feat/genkai-evolution`。

这是原计划约束的直接结果，而不是已经完成了目录迁移：

1. Global Constraints 禁止一次性大规模搬迁。
2. Task 4 明确要求 facade “不搬迁原算法”。
3. Task 7 明确不在该任务迁移尚未稳定的算法。
4. Milestone E 要求旧入口经过兼容测试和弃用周期后才允许删除。

因此，Task 1–9 可以标记为“library-first 契约和纵向工作流完成”，但不能标记
为“仓库物理结构收敛完成”。

### 15.4 下一阶段结构方向决策

继续作业前必须选择一个成功标准：

#### 方案 A：兼容优先的结构收敛（推荐）

- 将已经稳定并被多个入口复用的实现逐步迁入 `src/genkai/`。
- `paperread/` 只保留旧 CLI 和 import compatibility shim。
- 七个稳定 skill 的 scripts 只保留参数解析、库调用、报告展示和经过 preflight
  的外部命令启动。
- 每次只迁移一个领域边界，并使用 characterization test 保证旧入口行为不变。

优点是能形成明显且可持续的新结构，同时控制兼容风险；缺点是需要一个过渡期，
旧目录不会一次性消失。

#### 方案 B：全新顶层布局

- 重新设计为 `packages/`、`skills/`、`apps/`、`tests/` 和 `docs/` 等顶层
  目录。
- 同时修改 packaging、CLI、import path、Docker、Web 和发布流程。

优点是视觉变化最大；缺点是跨系统改动范围和回归风险最高，不适合在缺少完整
发布兼容测试时直接执行。

#### 方案 C：只整理非核心内容

- 整理根目录文档、测试数据、历史脚本和生成物。
- 不迁移 paperread、Agent 或 skill 的核心实现。

优点是风险最低；缺点是只改善可读性，不能解决双重业务实现和依赖边界问题。

当前决策状态：**方案 A 已于 2026-08-03 获批并开始执行**。用户进一步确认
`Genkai_Evolution/` 是专用于新结构的沙盒，不要求保留旧
`paperread.surface.*` import 或 `python -m paperread.surface` CLI；因此 Task
10–11 采用完整纵向迁移，不创建 compatibility shim。

### 15.5 方案 A 实施状态

Task 10–11 的设计和逐文件计划已记录在：

- `docs/superpowers/specs/2026-08-03-genkai-surface-literature-convergence-design.md`
- `docs/superpowers/plans/2026-08-03-genkai-surface-literature-convergence.md`

当前任务状态：

1. **Task 10：建立结构基线和依赖门禁（已完成）**
   - 记录顶层目录、Python import、CLI、wheel 内容和 skill entrypoint 基线。
   - 增加测试，禁止 `src/genkai/` 反向导入 `paperread/` 私有实现或 skill
     scripts。
   - 基线见 `docs/structure-baseline.md`；其中记录的两条 Task 12 技术债已于
     2026-08-04 的 PToModel 收敛切片移除，当前门禁 allowlist 为空：
     - `src/genkai/modeling/ptomodel.py` ->
       `paperread.surface.modeling.job_bundle.build_modeling_checklist`
     - `src/genkai/modeling/ptomodel.py` ->
       `paperread.surface.modeling.ptomodel.build_ptomodel_payload`
2. **Task 11：迁移 surface literature 内核（已完成）**
   - 将稳定 extraction、experience 和 pipeline 业务实现迁入
     `src/genkai/literature/surface/`。
   - 共享 LLM 配置迁入 `src/genkai/llm.py`，组合入口迁入
     `src/genkai/workflows/surface_paper.py`。
   - 旧 surface literature import 和 module CLI 已删除；Agent paperread skill
     脚本改为调用新库。
   - wheel 显式包含全部 20 个 canonical material-class JSON 资源。
3. **Task 12：迁移 PToModel 与 surface modeling 内核（已完成）**
   - PToModel 映射、modeling checklist 和 canonical task schema 已迁入
     `src/genkai/modeling/`；旧 `paperread/surface/modeling/` 已删除。
   - PToModel skill 已改为调用公共库 API 的薄入口，`src/genkai/` 对
     `paperread` 的两条反向 import 已清零。
   - vacancy、adsorbate、Materials Project slab、metal-cluster 与 cluster-search
     算法已迁入 `src/genkai/modeling/surface/`；原 Skill 路径仅保留薄包装器。
   - canonical task schema 已指向 Genkai 模块入口，离线架构、兼容性与 wheel
     门禁均已验证；不包含外部科研运行时验证。
4. **Task 13：收敛 compute、dataset 与 MLIP 入口**
   - 统一 adapter 与 launcher contract 的所有权，完成 `src/genkai/mlip/launchers.py`
     注册表并由 MACE/DeepMD/UMA adapter 共同消费。
   - 稳定数据审计归属 `src/genkai/datasets/`；架构门禁确认 VASP、MACE、DeepMD
     和 UMA Skill 脚本不复制 artifact/training/dataset gate。
   - 已完成离线集成回归、Skill `--help`/shell 语法和 wheel 导入验证；未运行
     外部计算、训练或 scheduler。
5. **Task 14：重组测试和 fixtures**
   - 已通过 pytest marker 与目录约定明确契约、单元、集成、兼容和外部运行时测试层。
   - 兼容性 characterization 测试已迁入 `tests/compatibility/`；外部测试保留在
     `tests/external/` 并默认排除。
   - 大型论文和生成样例已迁入 `tests/fixtures/archives/`，来源、用途和离线策略
     记录在 `tests/fixtures/README.md`。
   - 离线分层回归已验证；未执行外部运行时测试。
6. **Task 15：根目录与弃用清理**
   - 已审查旧 surface owner、兼容 Skill 入口、研究资产和忽略的生成目录；仅
     删除本地 `build/`/`Genkai.egg-info/` 生成状态，保留仍有用途的研究资产。
   - 已新增 `docs/migration.md`，更新 README、wheel 门禁和 work log；干净 wheel
     不再包含 `paperread/surface/`。
   - 兼容测试与分层回归通过后，Task15 完成；未进行远端推送或外部科研运行。

方案 A 的物理布局收敛补充：独立的 NERRE/ReactionSeek 历史资产已归档到
`legacy/paperread/`，活动库和 Skill 不再与其共享顶层 owner；wheel package
discovery 已移除 `paperread*`。

### 15.6 下一次会话恢复顺序

1. 读取本节、`work_logs/2026-08-04.md` 以及 PToModel 收敛设计与实施计划。
2. 审计 `Genkai_Evolution/` 工作树和 `feat/genkai-evolution` 分支状态。
3. 复核 Task 12 的离线回归与 wheel 产物，保留外部科研运行时边界。
4. Task 13–15 按各自设计继续推进；不得将其未开始状态误记为完成。
