# 项目计划

更新时间：2026-07-30

## 架构演进状态

`GENKAI_EVOLUTION_PLAN.md` 的 Task 1–9 已在 `feat/genkai-evolution` 分支
实现。原 paperread/PToModel 研究闭环现在映射为正式 artifact stages：

```text
PaperArtifact
-> ExtractionArtifact
-> ModelingPlanArtifact
-> StructureSetArtifact
-> CalculationInputArtifact / CalculationResultArtifact
-> DatasetArtifact
-> ModelArtifact / EvaluationArtifact
```

旧 `paperread.surface` 和 Agent graph payload 保持兼容。新的
`genkai-workflow` 只提供 init、inspect、preflight 和 dry-run；真实 VASP、
GPU、PJM、DeepMD 训练和 UMA 微调仍需单独授权与科学验收。下文的经验库、
unknown-term 与 PToModel 映射工作继续作为领域质量改进计划。

## 当前目标

把 `paperread/surface`、`ptomodel` 和 `surface-modeling` 连接成可复用的
论文到建模闭环：

```text
paperread relations/table
-> material class experience
-> surface parameter registry
-> ptomodel 映射实验关键词到建模任务和参数模板
-> surface-modeling 执行或明确标记缺失项
-> 成功、缺口和 unknown-term 再写回经验库
```

当前重点不是继续扩大功能面，而是让已有论文抽取结果能够稳定沉淀为经验，
并让 `ptomodel` 能智能利用这些经验生成建模输入。

## 当前重点工作

### 1. 经验库合并与 registry 重建

每批正式 `relations/table` 结果完成后，优先合并经验库。

输入来源：

- `*_surface_relations.jsonl`
- `*_table.csv`

写入目标：

- `paperread/surface/experience/material_classes/*.json`

每轮合并后必须重建：

- `agents/Agent/skills/paperread/experience/surface_parameter_registry.json`
- `agents/Agent/skills/paperread/experience/surface_parameter_registry.md`

经验库重点字段：

- 材料类别
- 元素和组成
- 表面和支撑
- 晶面
- 缺陷和空位
- 掺杂和修饰
- 活性位点
- 吸附物和反应中间体
- 覆盖状态
- 团簇和单原子
- 反应类型
- 建模任务 cue

目标：

- `material_classes/*.json` 保存可统计、可复用的论文经验。
- `surface_parameter_registry` 不只做词频展示，还要逐步成为
  `ptomodel` 可读取的建模参数词表。
- 后续 extraction、unknown-term 清洗和建模映射都优先复用 registry，
  而不是每次从单篇论文重新判断。

### 2. unknown-term 清洗

unknown-term store 应只保留真正值得后续学习、建模或规则更新的词。

导出原则：

- 只从正式 `*_surface_relations.jsonl` 和 `*_table.csv` 导出 unknown。
- 不把 fallback 启发式文本扫描结果直接写入 skill 侧 unknown store。
- 每轮清洗后重新生成 unknown-term 统计文件。

需要继续剔除的噪声：

- `Full`
- `electronic structure`
- 通用 DFT 和表征方法词
- links/source/cites/DOI 等来源字段残留
- 已知元素符号和元素英文名
- 已知材料类别标签
- 常见分子、公式、反应名和应用词

需要保留的高价值 learnable terms：

- 材料加晶面：`Pt(111)`、`Au(100)`、`TiO2(110)`、`CeO2(111)`
- 吸附中间体：`*OOH`、`*OH`、`CO*`、`H*`
- 配位环境：`Fe-N4`、`Co-O4`、`Ni-S`
- 单原子和团簇：`single-atom Au`、`AgSA`、`Pt13 cluster`
- 缺陷、修饰和覆盖：`oxygen vacancy`、`carbon doping`、mixed OH/O coverage

输出目标：

- `agents/Agent/skills/paperread/experience/unrecognized_surface_terms.jsonl`
- `agents/Agent/skills/paperread/experience/unknown_term_statistics_*.json`
- `agents/Agent/skills/paperread/experience/unknown_term_statistics_*.md`

### 3. PToModel 映射增强

这是当前最重要的开发方向。`ptomodel` 需要从“判断可能的建模任务”升级为
“把实验关键词映射成建模任务、参数模板和缺失项说明”。

PToModel 应读取并利用：

- `paperread/surface/experience/material_classes/*.json`
- `agents/Agent/skills/paperread/experience/surface_parameter_registry.json`
- `agents/Agent/skills/surface-modeling/schema/task_parameter_schema.json`
- `paperread/surface/core/surface_ontology.py`

核心映射规则：

- 晶面和表面：
  - `Pt(111)` -> material=`Pt`, facet=`(111)`, task=`slab_generation`
  - `TiO2(110)` -> material=`TiO2`, facet=`(110)`
  - `CeO2(111)` -> material=`CeO2`, facet=`(111)`
- 缺陷：
  - `oxygen vacancy` -> task=`vacancy_landscape`
  - `surface vacancy` -> task=`vacancy_landscape`
  - `defective surface` -> vacancy 或 doped surface 候选
- 吸附物和中间体：
  - `*OH`、`*OOH`、`O*`、`CO*`、`H*` -> task=`adsorbate_landscape`
  - `top site`、`bridge site`、`hollow site` -> adsorption site hint
  - coverage 描述进入 `coverage`，但具体 `coverage_counts` 不自动强填
- 团簇和纳米颗粒：
  - `Pt13 cluster` -> `cluster_element=Pt`, `cluster_atoms=13`
  - `Au nanoparticle` -> `cluster_element=Au`
  - `fcc Pt` -> `cluster_structures=["fcc"]`
- 单原子和配位环境：
  - `Fe-N4` -> center=`Fe`, coordination=`N4`
  - `single-atom Au` -> task=`single_atom_site`
  - 当前不可执行的单原子建模先进入 `deferred_tasks`，但必须保留映射证据
- 掺杂和修饰：
  - `Ni-doped`、`Fe-doped`、`carbon doping` -> task=`doped_surface`
  - `interface`、`heterostructure`、`modifier` -> surface functionalization 或 deferred task

PToModel 参数状态必须明确区分：

- `auto`：论文证据足够明确，可以安全自动填
- `registry_suggested`：经验库强提示，但仍需确认
- `needs_upstream_artifact`：需要真实结构文件
- `needs_manual_decision`：需要人工选择数值或构型
- `deferred`：当前建模 skill 暂不支持

参数来源建议记录：

```json
{
  "value": "Pt",
  "status": "auto",
  "confidence": "high",
  "source_field": "Cluster/Single Atom",
  "source_term": "Pt13 cluster",
  "reason": "normalized cluster species from explicit cluster mention"
}
```

### 4. PToModel 回归样例

不必等待 `tests/papers2` 全部正式抽取完成，可以先用已有输出建立代表样例。

优先覆盖：

- oxide + oxygen vacancy
- metal/alloy + facet
- supported catalyst + nanoparticle
- carbon/single atom + `M-Nx`
- adsorbate/intermediate + coverage/site

每类样例检查：

- 是否选对 `recommended_modeling_tasks`
- 是否正确区分 `executable_tasks` 和 `deferred_tasks`
- 是否提取正确 material、facet、species、adsorbate、active site
- 是否只自动填安全参数
- 是否把结构文件、coverage 数量、vacancy 数量等保留为待补项

## 外围事项

以下事项仍需推进，但暂时不是详细计划重点。

### API 和 papers2 断点续跑

- 修复或确认 `LLM_API_KEY`、`LLM_BASE_URL`、模型名和额度状态。
- `tests/papers2` 后续不重新解析 PDF，直接基于
  `tests/paperread_papers2_experience/*_conditions_input.json` 和
  `*_relations_input.json` 断点续跑。
- 每次小批量处理 2-3 篇，避免继续触发限流。
- 优先补齐 `*_table.csv`、`*_surface_relations.jsonl`、`*_summary.txt` 和
  `*_ptomodel.json`。

### 文档和日志

- 每轮稳定结果写入 `agents/Agent/skills/paperread/experience/`。
- 每轮关键结果写入对应日期的 `work_logs/*.md`。
- 如果 unknown-term 规则、registry 字段或 PToModel 映射规则变化，同步更新
  `README.md`、`paperread/surface/README.md` 和相关 skill 文档。

### 全局检查

- 统计 `tests/papers2` 完成率。
- 检查 known/unknown 比例是否合理。
- 检查 PToModel 映射覆盖率。
- 跑必要 smoke test 或针对性单元测试。

## 长期原则

- `paperread` 负责论文抽取和经验沉淀。
- `surface_parameter_registry` 负责把经验库转成可复用词表。
- `ptomodel` 负责从论文语义到建模任务和参数模板的桥接。
- `surface-modeling` 负责执行具体结构生成和建模脚本。
- 成功映射、缺失参数和 unknown-term 都要回流到经验库。
- 不把单篇论文结果写死进逻辑；重复出现的模式先进入经验库，再沉淀为 ontology、registry、prompt、planner 或 skill 更新。
