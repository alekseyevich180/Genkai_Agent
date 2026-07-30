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

- [ ] **Step 1: 写 artifact round-trip 失败测试**

测试构造一个 `StructureSetArtifact`，写出 JSON，再读回并断言
`artifact_id`、`parent_ids`、`evidence_level` 和相对路径不变；同时断言绝对
artifact 路径被拒绝。

Run:

```bash
pytest tests/contracts/test_artifacts.py -v
```

Expected: FAIL because `genkai.contracts` does not exist.

- [ ] **Step 2: 实现枚举、provenance 和基础 artifact**

使用 Pydantic discriminated union 定义第 4 节列出的九种 artifact。
`path` 使用 POSIX 相对路径并拒绝 `..`；`sha256` 必须是 64 位小写十六进制。

- [ ] **Step 3: 实现 validation report**

`ValidationReport` 提供
`errors: list[ValidationIssue]`、`warnings: list[ValidationIssue]`、
`checks: list[ValidationIssue]` 和只读属性 `passed`；存在 error 时
`passed` 必须为 `False`。

- [ ] **Step 4: 声明 Pydantic 直接依赖并运行测试**

在 `pyproject.toml` 中加入与当前 Python 3.12 环境兼容的
`pydantic>=2.12.0`。

Run:

```bash
pytest tests/contracts/test_artifacts.py -v
```

Expected: PASS.

- [ ] **Step 5: 提交独立变更**

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

- [ ] **Step 1: 写 manifest 生命周期失败测试**

测试创建 run、追加 stage、注册 artifact、保存、读回，并验证父 artifact
必须已存在。另一个测试模拟写入中断，断言原 manifest 不被破坏。

- [ ] **Step 2: 运行测试并确认预期失败**

```bash
pytest tests/contracts/test_run_manifest.py -v
```

Expected: FAIL because `RunManifest` and store functions are absent.

- [ ] **Step 3: 实现 manifest 模型和原子写入**

`save_manifest` 先写同目录临时文件，执行 `flush` 和 `os.fsync` 后用
`Path.replace` 替换 `manifest.json`。禁止在 manifest 中登记 run 根目录之外
的 artifact。

- [ ] **Step 4: 运行契约测试**

```bash
pytest tests/contracts/test_run_manifest.py tests/contracts/test_artifacts.py -v
```

Expected: PASS.

- [ ] **Step 5: 提交独立变更**

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

- [ ] **Step 1: 写 DAG 契约失败测试**

覆盖四种情况：

1. paperread 产生 extraction，PToModel 正确消费；
2. 下游要求 `dataset@1` 但上游只产生 `structure-set@1`；
3. schema 主版本不兼容；
4. DAG 存在循环。

- [ ] **Step 2: 运行测试并确认四类失败可区分**

```bash
pytest tests/workflow/test_stage_graph.py -v
```

Expected: FAIL because workflow graph validation is absent.

- [ ] **Step 3: 实现 StageSpec 和静态 DAG 校验**

每个 stage 明确声明 `consumes`、`produces`、`adapter` 和
`allows_mock_inputs`。校验器在执行前报告缺失生产者、类型不匹配、版本不兼容
和循环。

- [ ] **Step 4: 运行 workflow 与 contract 测试**

```bash
pytest tests/contracts tests/workflow -v
```

Expected: PASS.

- [ ] **Step 5: 提交独立变更**

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

- [ ] **Step 1: 用最小 JSON fixture 写 facade 失败测试**

fixture 必须覆盖一个明确 `CeO2(111)`、一个 `*OH` 和一个
`needs_manual_decision` 参数。测试不访问网络、不运行真实计算。

- [ ] **Step 2: 运行测试并记录旧输出基线**

```bash
pytest tests/integrations/test_surface_facades.py tests/test_paperread_surface.py -v
```

Expected: new facade tests FAIL; existing paperread tests PASS.

- [ ] **Step 3: 实现 facade，不搬迁原算法**

第一轮 facade 调用现有 `paperread.surface` 函数，将输出包装为 artifact，
计算 hash，并登记到 manifest。不得复制 PToModel 映射规则。

- [ ] **Step 4: 让 job bundle 写 artifact 引用**

保留 `article.json`、`modeling/plan.json` 和 `modeling/checklist.json`，
并在 manifest 中登记它们；旧字段继续保留，新增字段使用 schema version
控制。

- [ ] **Step 5: 跑兼容与新契约测试**

```bash
pytest tests/test_paperread_surface.py tests/integrations/test_surface_facades.py -v
python -m paperread.surface --help
python -m paperread.surface list-tools
```

Expected: all tests PASS and both CLI commands exit 0.

- [ ] **Step 6: 提交独立变更**

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

- [ ] **Step 1: 写角色边界和证据门禁失败测试**

测试必须证明：

- MACE 接受 structure set；
- DeepMD 接受真实 labeled dataset；
- UMA 接受真实 labeled dataset 和 base model；
- DeepMD/UMA 生产模式拒绝 mock dataset；
- UMA 拒绝缺失 test split 或存在 split leakage 的数据。

- [ ] **Step 2: 写 VASP 可选依赖失败测试**

在没有 `dpdata` 的环境导入 VASP prepare 模块并调用 `--help` 应成功；只有
需要 `dpdata` 的 collect 子命令才返回明确依赖错误。

- [ ] **Step 3: 运行测试并确认失败原因**

```bash
pytest tests/integrations/test_compute_dataset_mlip_contracts.py -v
```

Expected: FAIL because adapters do not exist and VASP imports `dpdata` eagerly.

- [ ] **Step 4: 实现 adapter preflight 和 lazy import**

adapter 只生成经过验证的 command specification，不自行提交 PJM 作业。
VASP 中将 `dpdata` 移到实际需要它的函数内，并返回安装建议。

- [ ] **Step 5: 复用现有 UMA 审计，不复制规则**

将稳定的距离、标签、split leakage 和 LMDB readback 逻辑提升到
`src/genkai/datasets/`；旧 UMA 脚本改为调用这些函数，并保持原命令行参数。

- [ ] **Step 6: 运行门禁和脚本静态检查**

```bash
pytest tests/integrations/test_compute_dataset_mlip_contracts.py -v
python agents/Agent/skills/vasp/scripts/vasp_tools.py --help
bash -n agents/Agent/skills/mace/scripts/submit_mace_calculation.sh
bash -n agents/Agent/skills/deepmd/scripts/submit_deepmd_training.sh
bash -n agents/Agent/skills/uma/scripts/prepare_uma_finetune_dataset.sh
bash -n agents/Agent/skills/uma/scripts/submit_uma_finetuning.sh
```

Expected: all commands exit 0; no real calculation or training starts.

- [ ] **Step 7: 提交独立变更**

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

- [ ] **Step 1: 写三种目标路由失败测试**

断言 MACE 路径在 structure set 后结束；DeepMD 路径需要真实 dataset；UMA
路径同时需要真实 dataset、base model 和 test split。

- [ ] **Step 2: 写 mock 标签隔离测试**

`genkai-workflow preflight --target uma --mode production` 对 mock fixture
必须退出非零；`--mode dry-run` 可以生成计划，但 report 必须包含
`mock_labels_not_trainable`。

- [ ] **Step 3: 实现工作流构建和 preflight CLI**

CLI 只执行 `init`、`inspect`、`preflight` 和 `run --mode dry-run`。
真实 DFT、训练或 scheduler submission 仍需通过对应 adapter 和用户明确授权。

- [ ] **Step 4: 声明 CLI 并运行测试**

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

- [ ] **Step 5: 提交独立变更**

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

- [ ] **Step 1: 写当前 skill 的 characterization test**

先记录七个核心 skill 能被 ADK 加载、名称唯一，且现有
`dependent_skills` 均指向真实 skill。

- [ ] **Step 2: 写新 contract 失败测试**

测试缺少 maturity、未知 dependency、无效 artifact version、缺失 entrypoint
和 description 未以 `Use when` 开头时会给出不同错误码。

- [ ] **Step 3: 实现 YAML frontmatter contract loader**

只解析 `SKILL.md` 首个 YAML frontmatter；保留 ADK 原字段，不创建第二份
manifest。`evaluations/cases.yaml` 至少包含 `positive`、`negative` 和
`boundary` 三类。

- [ ] **Step 4: 逐个规范七个核心 skill**

不在这一任务搬迁尚未稳定的算法；只统一触发描述、角色边界、artifact 声明、
entrypoint 和 evaluation。MACE、DeepMD、UMA 的排他边界必须进入 boundary
cases。

- [ ] **Step 5: 运行静态、加载和边界测试**

```bash
pytest tests/skills/test_builtin_skill_contracts.py tests/skills/test_skill_boundaries.py -v
python -c "from agents.Agent.skill import load_skills; assert len(load_skills()) > 0"
```

Expected: PASS.

- [ ] **Step 6: 提交独立变更**

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

- [ ] **Step 1: 写旧计划兼容失败测试**

使用当前不含 artifact 字段的 graph payload，断言仍可通过
`ExecutionGraph` 校验。

- [ ] **Step 2: 写新计划静态拒绝测试**

构造一个 UMA 节点直接消费 structure set 的 DAG，断言规划阶段失败并指出
缺少 dataset 和 base model。

- [ ] **Step 3: 实现可选 artifact 字段和 graph 转换**

Agent 现有节点状态机保持不变；仅在提供 artifact 声明时调用
`src/genkai/workflow/graph.py` 做额外校验。

- [ ] **Step 4: 执行器登记真实产物**

当 skill 返回 manifest path 时，执行器从 manifest 读取 artifact IDs；
普通文件路径继续放在旧 `artifacts` 字段，避免破坏前端展示。

- [ ] **Step 5: 运行 Agent 回归测试**

```bash
pytest tests/test_agent.py tests/test_agent_artifact_planning.py -v
```

Expected: PASS.

- [ ] **Step 6: 提交独立变更**

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

- [ ] **Step 1: 写完整 dry-run 测试**

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

- [ ] **Step 2: 运行端到端测试**

```bash
pytest tests/integrations/test_paper_surface_to_uma_dry_run.py -v
```

Expected: PASS without external services.

- [ ] **Step 3: 运行完整相关回归**

```bash
pytest tests/contracts tests/workflow tests/integrations tests/skills tests/test_paperread_surface.py tests/test_agent.py -v
python -m paperread.surface --help
agent --help
genkai-workflow --help
```

Expected: all selected tests and commands PASS.

- [ ] **Step 4: 更新文档和真实验证边界**

`README.md` 描述新库入口和三个 MLIP 角色；`plan.md` 将原
paperread/PToModel 计划映射到 artifact stages；工作日志记录实际执行过的
命令，并明确没有运行的真实计算、GPU、PJM 和训练。

- [ ] **Step 5: 检查弃用条件**

只有同时满足以下条件，才在后续版本删除旧实现：

1. 新 facade 已覆盖旧 CLI 的已维护功能；
2. 兼容测试持续通过；
3. README 已发布替代入口；
4. 至少经过一个带弃用提示的发布周期；
5. 仓库内没有 skill 直接导入被删除脚本。

- [ ] **Step 6: 执行仓库一致性检查**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; status only contains本计划范围内的文件。

- [ ] **Step 7: 提交独立变更**

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
