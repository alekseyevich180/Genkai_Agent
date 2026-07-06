# 项目计划

更新时间：2026-07-06

## 目标

把 Genkai Agent 维护成一个稳定的材料科研工作台，核心方向是：

1. `paperread/surface` 负责论文抽取和经验沉淀。
2. `surface-modeling` 负责结构生成和建模入口。
3. `Agent` 负责规划、执行、技能加载和知识图谱管理。

## 当前重点

### 1. Surface 规则统一

- 把材料分类、任务名、关键词桶、反应归一化收敛成单一规则源。
- 让 `collect_experience`、`parameter_registry`、`ptomodel`、经验导出脚本共用同一套定义。
- 保持经验库可复用，而不是按论文堆积。

### 2. 经验闭环

- 从论文里提取材料、表面、缺陷、吸附物、覆盖度、团簇、单原子、修饰和反应关键词。
- 汇总到 `material_classes/*.json`。
- 由 registry 再反哺后续抽取提示。

### 3. 框架整理

- 精简入口脚本数量，保留一个主 CLI。
- 拆分过大的 web 服务文件。
- 减少 import-time 状态冻结。

### 4. Agent 知识闭环处理方法

整体闭环：

```text
会话运行 -> 收集轨迹 -> 抽取知识 -> 写入图谱 -> 检索复用 -> 反复提炼 -> skills/guides 作为框架骨架
```

#### 4.1 知识收集

- 项目里的主要知识收集入口不是手工写文档，而是会话结束后的自动抽取。
- `agents/Agent/agents/orchestrator/agent.py` 在一次执行完成后调用 `run_knowledge_extractor(ctx.session.id)`。
- `agents/Agent/knowledge/extractor.py` 读取 `trajectories/<session>.jsonl` 和 `trajectories/<session>_summary.json`。
- 抽取器让 LLM 生成 JSON 条目，重点是经验、警告、规律和结果，不是保存原始对话。
- 抽出的内容先作为 `EntryType.memory` 写入图谱，后续再判断是否提升为长期知识。

#### 4.2 知识迁移

- 迁移目标是把旧的、分散的存储统一到 `know_do_graph.db`。
- 迁移逻辑由 `agents/Agent/knowledge/kdg_memory.py` 负责。
- 历史来源包括旧的 `skill_graph.db`、`memory_graph.db`、`memory/*.json` 和 `MEMORY.md`。
- `agent knowledge migrate` 触发迁移链，把历史数据转成统一图谱里的 entry 和 edge。
- `agent knowledge seed` 把当前仓库里的 skills 和 guides 重新写入图谱，作为可检索的 durable knowledge。

#### 4.3 知识检索

- 检索统一走知识图谱，主要入口在 `agents/Agent/knowledge/query.py`。
- `query_knowledge_graph()` 查询 durable knowledge 和 working memory。
- `search_skills()` 只查技能、流程、工作流和工具这类 durable capability。
- `get_related_skills()` 沿图谱关系边查找相关技能，不只是简单文本搜索。
- `search_skills()` 只返回带 `agent-skill` 标签的节点，并过滤配置中禁用的技能。
- 检索的对象不是单个文件，而是图谱里的节点和边。

#### 4.4 知识提炼

- 提炼逻辑在 `agents/Agent/knowledge/synthesizer.py`。
- 它先取未 promoted 的 memory，再按内容相似度聚类。
- 聚类至少要达到 `min_insights_for_workflow`，手动命令可用 `agent knowledge distill --min-evidence 3`。
- 除了数量阈值，还需要足够的成功证据，通常要求多个 session 或多个成功样本。
- 满足条件后，把 canonical memory promote 成 durable entry。
- 提炼时建立 `related_memory`、`heuristic_for`、`refinement_of` 等关系边。
- 提炼过程也会清理长期没有成功证据、未被提炼的 stale memory。
- 核心原则是把多次重复出现的工作记忆升级成可长期复用的规则或经验。

#### 4.5 知识利用

- 自动线：orchestrator 在每次执行后自动运行 extractor，累计到一定程度后再运行 synthesizer。
- 手动线：使用 `agent knowledge stats` 查看图谱状态。
- 手动线：使用 `agent knowledge distill` 强制触发提炼。
- 手动线：使用 `agent knowledge seed` 把当前 skills 和 guides 重新入图。
- 对后续任务来说，运行过的任务会留下可检索经验，重复出现的规律会变成长期知识。
- 后续任务应优先检索和复用这些知识，而不是重新从零推理。

#### 4.6 Skills 构建知识框架

- skill 不只是脚本目录，而是知识框架的骨架。
- `agents/Agent/skill.py` 扫描 `agents/Agent/skills/**/SKILL.md`。
- skill 系统加载默认技能和 workspace 自定义技能。
- skills 和 guides 会作为 durable entry seed 到知识图谱。
- `dependent_skills` 会变成图谱里的依赖边。
- 规划阶段通过 `search_skills()` 和 `load_skill()` 找到合适技能，并把说明加载给模型。
- `AgentSkillToolset` 暴露 `run_skill_script`，让模型可以直接调用技能脚本。
- skill 的三层作用是可执行工具、规划时可检索的知识节点、知识图谱里的技能依赖结构。

#### 4.7 总结原则

- 这个项目的知识体系是图谱化的。
- 运行中收集 memory，迁移历史数据进统一数据库。
- 检索时查图谱节点和关系边。
- 提炼时把重复 memory 升级为 durable knowledge。
- skills 和 guides 负责把能做什么、怎么做、依赖什么固化成知识框架。
- 当前必须接入这套方法的重点 skill 是 `lobster`、`paperread`、
  `surface-modeling` 和 `ptomodel`。
- 这些 skill 都应遵循运行前检索已有经验、运行中保留结构化证据、
  运行后沉淀 memory、重复证据再提炼为 durable knowledge 的流程。

### 5. Surface 经验处理方法

- 经验收集目标不是保留大量论文来源，而是统计并复用论文中常见的材料描述关键词。
- 经验库重点保留材料本体、组成、状态、修饰、参与反应和建模关键词，不把单篇论文的长来源列表作为核心。
- 抽取时优先统计这些维度：
  - `materials`
  - `material_parameters`
  - `surfaces`
  - `surface_terminations`
  - `slab_models`
  - `facets`
  - `dopants`
  - `defects`
  - `vacancy_models`
  - `active_sites`
  - `adsorbates`
  - `adsorption_sites`
  - `coverage`
  - `clusters`
  - `single_atoms`
  - `modifiers`
  - `modeling_keywords`
  - `recommended_modeling_tasks`
- 材料类型按论文中常见类别聚合，不按单篇论文堆叠：
  - `supported_catalysts`
  - `carbon_materials`
  - `single_atom_catalysts`
  - `metals_alloys`
  - `oxides`
  - `hydroxides_oxyhydroxides`
  - `sulfides`
  - `selenides_tellurides`
  - `nitrides`
  - `carbides_mxenes`
  - `phosphides_phosphates`
  - `halides`
  - `perovskites_spinels`
  - `zeolites_silicates`
  - `mofs_coordination_polymers`
  - `borides`
  - `defect_engineered_materials`
  - `surface_functionalized_materials`
  - `battery_electrode_materials`
  - `other_inorganic_materials`
- 对不同材料类，提炼不同的建模关键词：
  - `supported_catalysts`：组成元素、support、负载组分、含量、暴露表面
  - `carbon_materials`：二维碳材料、掺杂结构、N/O/S 配位、单原子中心
  - `metals_alloys`：合金元素、高熵组成、元素含量、暴露晶面
  - `oxides`：氧化物种类、空间群、表面终止、缺陷和晶面
  - `perovskites_spinels`：A/B 位点、结构类型、空间群、暴露面
- `collect_experience` 的职责是把抽取结果归档成可统计的经验，不是把每篇论文写成长日志。
- `material_classes/*.json` 作为长期经验库，记录词频、分类、上下文和少量示例，而不是完整论文复述。
- `surface_parameter_registry` 从 material class 经验中重建，供后续抽取提示、参数补全和建模映射复用。
- `surface_ontology.py` 作为共享词表和规则源，统一材料类别、关键词桶、任务名、反应归一化规则。
- `ptomodel` 负责把论文语义映射成 Agent 可执行或可延迟处理的建模桥接 JSON。
- `paperread` 同时负责论文抽取和未知词、未映射术语、新关键词的 skill 侧经验沉淀。
- 后续若出现新关键词，先进入 experience / registry，再更新 prompt、schema、planner 或 skill，而不是直接把单篇论文写死进逻辑。

### 6. 这套方法的长期目标

- 让 surface 相关论文的材料描述可以被统一统计、统一归类、统一复用。
- 让同类材料在不同论文中共享同一套参数解释方式。
- 让后续建模脚本可以通过关键词和经验库快速补全材料参数，而不是每次重新手工分析。
- 让 skill、registry、ptomodel 和 surface-modeling 最终形成一个可回收、可扩展、可迭代的闭环。

## 执行优先级

1. 先完成 `paperread/surface` 的公共 ontology 和 registry 收敛。
2. 再整理 `manual.md`、`plan.md` 和根目录说明文件。
3. 最后拆分 web 层和 CLI 封装，减少重复入口。
4. 持续维护知识图谱闭环，让经验沉淀能反哺后续抽取和建模。

## 备注

- `tests/` 目录继续只作为验证和样例输入，不作为主文档源。
- `data/` 目录继续只作为数据输入，不纳入文档整理范围。
