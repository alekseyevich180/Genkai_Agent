# Paperread Surface Modeling Plan

更新时间：2026-07-01

## 目标

将 `paperread/surface` 从“论文信息抽取工具”扩展为“表面研究建模入口”：

```text
论文 PDF/文本
-> paperread/surface 抽取关键词、参数、关系
-> ptomodel 将论文信息转成 Agent-ready bridge JSON
-> Agent surface-modeling skill 执行结构生成或计算准备
-> 经验抽取机制记录陌生术语和失败/有效经验
-> 反向更新 prompt、schema、ptomodel 和 skill
```

核心原则：

- `paperread` 负责抽取，不直接运行建模。
- `ptomodel` 负责把论文关键词、材料语义和任务意图转成结构化桥接 JSON。
- `surface-modeling` 负责真正的结构生成和后续计算准备。
- `paperread/surface/collect_experience.py` 负责在 paperread 侧沉淀已知有用信息和未知信息。
- `paperread-surface-learning` 负责在 Agent skill 侧沉淀需要进入 skill/ptomodel 的陌生经验。

## 已有基础

当前 `paperread/surface` 已支持：

- PDF 文本抽取与章节分流
- 条件表抽取
- 时间标准化
- 表面材料关系抽取
- 人工可读摘要生成
- `*_ptomodel.json` 桥接输出
- 本地经验收集：`collect_experience.py`

当前 `agents/Agent/skills/surface-modeling` 已支持：

- 氧空位 landscape：`vacancy_landscape.py`
- 吸附物 coverage landscape：`adsorbate_landscape.py`
- 金属团簇/表面结构：`surface_cluster_builder.py`
- 表面团簇 MLIP 搜索：`ads_nanocluster.py`

当前新增的经验沉淀 skill：

```text
agents/Agent/skills/paperread-surface-learning/
  SKILL.md
  scripts/export_surface_experience.py
  experience/
```

paperread 本地经验输出：

```text
paperread/surface/experience/
material_classes/
  carbon_materials.json
  single_atom_catalysts.json
  ...
```

Per-run JSON and Markdown review reports are optional and should be generated only when a human
needs to inspect one extraction run:

```bash
python -m paperread.surface.collect_experience ... --write-run-file --write-markdown
```

## Paperread 抽取字段

### 条件表字段

`paperread/surface/extract_surface_conditions.py` 需要持续覆盖两类字段。

反应与实验参数：

- `Reaction Type`
- `Feed/Concentration`
- `Atmosphere`
- `Pressure`
- `Gas Flow`
- `Solvent`
- `pH`
- `Temperature`
- `Time`
- `Potential/Bias`
- `Current Density`
- `Product`
- `Conversion`
- `Selectivity`
- `Yield`
- `Rate/Activity`
- `Stability/Cycles`

材料与建模参数：

- `Material`
- `Composition`
- `Phase`
- `Morphology/Size`
- `Surface Area`
- `Surface/Support`
- `Facet`
- `Surface Termination`
- `Active Site`
- `Defect`
- `Dopant/Modifier`
- `Adsorbate/Reactant`
- `Adsorption Site`
- `Coverage`
- `Cluster/Single Atom`
- `Loading`
- `Modeling Keywords`

### 关系抽取字段

`paperread/surface/extract_surface_relations.py` 的 schema 应持续覆盖：

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
- `intermediates`
- `products`
- `clusters`
- `single_atoms`
- `modifiers`
- `properties`
- `reaction_parameters`
- `modeling_keywords`
- `recommended_modeling_tasks`
- `applications`
- `links`

## 关键词体系

### 表面与 slab

- `surface`
- `slab`
- `support`
- `interface`
- `facet`
- `(111)`、`(110)` 等晶面
- `surface termination`
- `O-terminated`
- `metal-terminated`
- `hydroxylated`
- `sulfurized`
- `reduced surface`
- `oxidized surface`
- `reconstructed surface`

### 缺陷与空位

- `oxygen vacancy`
- `Vo`
- `vacancy-rich`
- `anion vacancy`
- `cation vacancy`
- `defect-rich`
- `surface vacancy`
- `subsurface oxygen`

### 吸附与覆盖度

- `adsorbate`
- `adsorption site`
- `coverage`
- `monolayer`
- `coadsorption`
- `top site`
- `bridge site`
- `hollow site`
- `monodentate`
- `bidentate`
- `*OH`
- `*CO`
- `*OOH`
- `*CHO`
- `*COOH`

### 团簇、单原子和修饰

- `metal cluster`
- `nanocluster`
- `nanoparticle`
- `Pt13`
- `single atom`
- `isolated metal site`
- `modifier`
- `promoter`
- `dopant`
- `anchoring`
- `metal-support interaction`
- `exsolved nanoparticle`

## 推荐建模任务

`recommended_modeling_tasks` 当前允许使用：

- `vacancy_landscape`
- `adsorbate_landscape`
- `surface_cluster_builder`
- `single_atom_site`
- `doped_surface`
- `surface_functionalization`
- `slab_generation`

第一阶段只自动转化前三个稳定任务：

- `vacancy_landscape`
- `adsorbate_landscape`
- `surface_cluster_builder`

其余任务先进入 planner 输出和经验记录，不直接执行。

## PToModel 桥接层

当前桥接模块：

```text
paperread/surface/ptomodel.py
```

输入：

```text
*_surface_relations.jsonl
*_summary.txt
*_table.csv
*_time.csv
```

输出：

```text
*_ptomodel.json
```

### 桥接文件格式

```json
{
  "schema_version": "1.0",
  "sources": {
    "relations_jsonl": "paperread output path",
    "table_csv": "paperread output path",
    "summary_txt": "paperread output path"
  },
  "documents": [
    {
      "id": "doc1",
      "selected_information": {
        "materials": ["CeO2", "Pt/CeO2"],
        "surface_facets": [{"raw": "(1 1 1)", "normalized": "(111)"}],
        "loaded_nanoparticles_or_clusters": [{"raw": "Pt13 cluster", "normalized_species": "Pt"}],
        "reaction_types": [{"raw": "CO oxidation", "normalized": "CO oxidation"}]
      },
      "normalized_mapping": {
        "primary_material": "Pt/CeO2",
        "primary_surface_or_support": "CeO2",
        "facet_set": ["(111)"],
        "loaded_species": ["Pt"],
        "reaction_family": ["CO oxidation"]
      },
      "recommended_modeling_tasks": [
        "vacancy_landscape",
        "adsorbate_landscape",
        "surface_cluster_builder"
      ],
      "executable_tasks": [
        "vacancy_landscape",
        "adsorbate_landscape",
        "surface_cluster_builder"
      ],
      "deferred_tasks": [
        "single_atom_site"
      ],
      "task_inputs": {
        "adsorbate_landscape": {
          "material": "Pt/CeO2",
          "surfaces": ["CeO2"],
          "facets": ["(111)"],
          "adsorbates": ["CO", "O2"]
        }
      }
    }
  ]
}
```

### PToModel 规则

- 出现 `oxygen vacancy`、`Vo`、`vacancy-rich`：
  - 推荐 `vacancy_landscape`
- 出现 `adsorbate`、`adsorption`、`coverage`、`*OH`、`*CO` 等：
  - 推荐 `adsorbate_landscape`
- 出现 `Pt13`、`metal cluster`、`nanocluster`、`nanoparticle`：
  - 推荐 `surface_cluster_builder`
- 出现 `single atom`、`isolated metal site`：
  - 记录为 `single_atom_site`，第一阶段不自动执行
- 出现 `doped`、`dopant`：
  - 记录为 `doped_surface`，第一阶段不自动执行
- 出现 `hydroxylated`、`sulfurized`、`nitrided`：
  - 记录为 `surface_functionalization`，第一阶段不自动执行
- 缺少 CIF/POSCAR/XYZ 等结构文件：
  - 保留在 `deferred_tasks` 或等待后续 `surface-modeling` 提供结构模板
  - 不强行建模

### 当前关键不足

`ptomodel` 已能完成：

- facet / cluster species / reaction type 的基础归一化
- `recommended_modeling_tasks` 到 `executable_tasks` / `deferred_tasks` 的拆分
- `task_inputs` 的基础组织

但对复杂材料体系仍然不够，尤其是：

- 单原子催化剂
- 碳载体单原子位点
- M-Nx / M-Ox / M-Sx 配位环境
- 缺陷锚定位点和局部活性位构型

例如真实论文中的 `Ni-O-G SACs` 不能只被压缩成 `primary_material = nickel`。对下游建模更有意义的表达应接近：

- `active_metal_species = Ni`
- `site_type = single_atom_site`
- `host_or_support = graphene-like carbon`
- `coordination_environment = O-coordinated`
- `anchor_or_local_motif = Ni-O_x on carbon support`

后续计划需要围绕这类“材料种类 + 位点/配位环境”的表达能力持续扩充。

## 经验抽取机制

经验处理分为三类。

### 固定经验：Skill

稳定、可复用的计算模拟经验放入 `agents/Agent/skills/`：

- 建模流程说明
- 脚本路径
- 输入输出格式
- 常用命令
- 注意事项
- 依赖关系

这类经验由 Agent 在规划和执行时通过 `search_skills`、`load_skill` 和 `run_skill_script` 使用。

### 运行经验：Knowledge Graph

Agent 执行计算模拟任务后，会将轨迹中的结果、失败、产物和总结抽取到知识图谱。

流程：

```text
thinking_agent 规划
-> execution_agent 执行 DAG
-> step_executor 加载 skill 并运行命令
-> 每步提交 key_results / artifacts / concise_summary
-> trajectory 记录执行结果
-> knowledge.extractor 抽取经验
-> MemGraph/Know-Do Graph 保存经验
-> knowledge.synthesizer 将重复成功经验提升为稳定知识
```

这类经验适合沉淀：

- 某个 workflow 的有效参数
- 某个脚本的失败原因
- 某类结构输入格式的限制
- 某个计算环境中的依赖问题
- 某类材料体系的建模注意事项

### 陌生经验：paperread-surface-learning

paperread 侧先通过 `collect_experience.py` 收集经验：

```bash
python -m paperread.surface.collect_experience \
  --relations tests/test2_api_surface_relations.jsonl \
  --table tests/test2_api_table.csv \
  --output-dir paperread/surface/experience
```

或者在 pipeline 中直接启用：

```bash
python -m paperread.surface.run_surface_pipeline paper.pdf \
  --output-dir paperread/surface/output \
  --collect-experience
```

paperread 本地经验分类：

- `surface_materials`
- `surface_structure`
- `defects_active_sites`
- `adsorption_reaction`
- `clusters_single_atoms`
- `modeling_tasks`
- `unknown_information`

每个类别内部按规范化术语聚合，记录出现次数、来源文件、来源字段、上下文和建议动作。这样经验库保存的是“研究类别下的去重知识”，不是逐项证据流水账。

经验收集必须参考 NERRE 和 ReactionSeek 的处理方式：先定义目标 schema，再只从目标字段中收集信息。不要把文本中所有材料名、性能指标、反应条件、应用描述都作为经验保存。经验库只保留会影响后续表面模型构建、`ptomodel` 映射、prompt/schema 修正的内容。

经验库需要以 `material_classes` 作为主索引，使经验能按无机材料种类累积，而不是按论文保存。比如两个 PDF 都属于 `carbon_materials` 和 `single_atom_catalysts`，其经验应合并进：

```text
paperread/surface/experience/material_classes/carbon_materials.json
paperread/surface/experience/material_classes/single_atom_catalysts.json
```

当前无机材料种类包括：

- `single_atom_catalysts`
- `supported_catalysts`
- `metals_alloys`
- `oxides`
- `hydroxides_oxyhydroxides`
- `sulfides`
- `selenides_tellurides`
- `nitrides`
- `carbides_mxenes`
- `phosphides_phosphates`
- `halides`
- `carbon_materials`
- `perovskites_spinels`
- `zeolites_silicates`
- `mofs_coordination_polymers`
- `borides`
- `defect_engineered_materials`
- `surface_functionalized_materials`
- `battery_electrode_materials`
- `other_inorganic_materials`

所有材料种类文件应预先初始化，保证后续抽取可以直接合并写入：

```bash
python -m paperread.surface.collect_experience \
  --init-material-classes \
  --output-dir paperread/surface/experience
```

初始化后应存在：

```text
paperread/surface/experience/material_classes/single_atom_catalysts.json
paperread/surface/experience/material_classes/supported_catalysts.json
paperread/surface/experience/material_classes/metals_alloys.json
paperread/surface/experience/material_classes/oxides.json
paperread/surface/experience/material_classes/hydroxides_oxyhydroxides.json
paperread/surface/experience/material_classes/sulfides.json
paperread/surface/experience/material_classes/selenides_tellurides.json
paperread/surface/experience/material_classes/nitrides.json
paperread/surface/experience/material_classes/carbides_mxenes.json
paperread/surface/experience/material_classes/phosphides_phosphates.json
paperread/surface/experience/material_classes/halides.json
paperread/surface/experience/material_classes/carbon_materials.json
paperread/surface/experience/material_classes/perovskites_spinels.json
paperread/surface/experience/material_classes/zeolites_silicates.json
paperread/surface/experience/material_classes/mofs_coordination_polymers.json
paperread/surface/experience/material_classes/borides.json
paperread/surface/experience/material_classes/defect_engineered_materials.json
paperread/surface/experience/material_classes/surface_functionalized_materials.json
paperread/surface/experience/material_classes/battery_electrode_materials.json
paperread/surface/experience/material_classes/other_inorganic_materials.json
```

维护规则：

- 长期经验只写入 `material_classes/<class>.json`。
- 不按 PDF 生成长期经验文件。
- per-run JSON/Markdown 只作为人工审阅临时报告，必须显式使用 `--write-run-file` 或 `--write-markdown`。
- 同一术语重复出现时，应在对应材料类文件中合并 `count`、`sources`、`fields` 和 `contexts`。
- 如果一个材料同时属于多个类别，例如 carbon material 和 single atom catalyst，相关经验应同时写入多个材料类文件。

paperread 经验文件的作用：

```text
paperread/surface extraction
-> collect_experience.py
-> grouped useful information / unknown_information
-> ptomodel 规则更新
-> paperread prompt/schema 更新
-> Agent skill 更新
```

Agent 侧再通过 `paperread-surface-learning` 把需要长期复用或需要进入 skill 的陌生经验沉淀下来。

论文中出现但当前 schema 或 planner 无法识别的术语，进入：

```text
agents/Agent/skills/paperread-surface-learning/
```

导出命令：

```bash
python agents/Agent/skills/paperread-surface-learning/scripts/export_surface_experience.py export \
  --relations tests/test2_api_surface_relations.jsonl \
  --table tests/test2_api_table.csv
```

手动加入术语：

```bash
python agents/Agent/skills/paperread-surface-learning/scripts/export_surface_experience.py add-term \
  --term "exsolved nanoparticle" \
  --category "surface modifier" \
  --context "Appears in a catalyst paper but is not mapped to a workflow yet." \
  --suggested-action "Decide whether this maps to cluster generation or a new exsolution workflow."
```

默认输出：

```text
agents/Agent/skills/paperread-surface-learning/experience/unrecognized_surface_terms.jsonl
agents/Agent/skills/paperread-surface-learning/experience/unrecognized_surface_terms.md
```

这些记录是候选经验，不是立即生效的规则。

审查策略：

- 单次出现：只记录，不改 planner。
- 多篇论文重复出现：加入 `paperread/surface` prompt 或 schema。
- 与已有建模脚本可对应：加入 `ptomodel.py` 映射。
- 与已有脚本无法对应但研究价值高：新增或扩展 `surface-modeling` workflow。

## Agent 工作方式

正常模式：

```text
用户提出目标
-> thinking_agent 理解目标并搜索相关 skill
-> thinking_agent 生成执行图
-> 用户确认
-> execution_agent 调度 DAG 节点
-> step_executor 加载 skill
-> run_python / run_bash / run_skill_script 执行
-> 产物写入 artifacts
-> trajectory 与 knowledge graph 记录经验
```

简单任务或 flash 模式：

```text
用户提出直接任务
-> run_flash_step
-> step_executor 加载 skill 并执行
-> 保存关键发现
```

## 分阶段计划

### 第一阶段：抽取质量验证

目标：

- 用真实表面研究论文验证新增关键词能否稳定抽出。

任务：

1. 选择 3-5 篇表面催化、吸附、电催化或表面改性论文。
2. 运行：

```bash
python -m paperread.surface.run_surface_pipeline paper.pdf --output-dir paperread/surface/output
```

3. 检查：
   - `*_table.csv`
   - `*_surface_relations.jsonl`
   - `*_summary.txt`
4. 记录漏抽、误抽和陌生术语。
5. 用 `paperread-surface-learning` 导出陌生经验。

验收标准：

- 主要材料、表面、吸附物、缺陷、团簇/单原子能稳定出现在输出中。
- 陌生术语能进入经验记录，而不是丢失。

### 第二阶段：稳固 PToModel 桥接层

目标：

- 将 paperread 输出转成稳定、可消费的 `*_ptomodel.json`。

任务：

1. 持续维护 `paperread/surface/ptomodel.py`。
2. 支持输入：
   - `*_surface_relations.jsonl`
   - `*_table.csv`
   - `*_summary.txt`
3. 输出：
   - `*_ptomodel.json`
4. 第一版只自动转化：
   - `vacancy_landscape`
   - `adsorbate_landscape`
   - `surface_cluster_builder`
5. 其余任务进入 `deferred_tasks`，不强行执行。

验收标准：

- 给定 paperread 输出，可以生成稳定的桥接 JSON。
- 不会在输入不完整时直接运行建模。

### 第三阶段：扩展材料种类与局部结构语义

目标：

- 通过真实论文经验收集，扩展 `paperread` 对材料种类、位点和配位环境的表达能力，使 `ptomodel` 能做更细的一一对应。

任务：

1. 持续收集真实论文中的材料种类经验，重点覆盖：
   - `single_atom_catalysts`
   - `supported_catalysts`
   - `carbon_materials`
   - `oxides`
   - `defect_engineered_materials`
   - `surface_functionalized_materials`
2. 对复杂体系建立更细的表达槽位，例如：
   - `host_or_support`
   - `active_metal_species`
   - `site_type`
   - `coordination_environment`
   - `defect_anchor`
   - `local_motif`
3. 重点解决类似 `Ni` on graphene-like carbon with `O` coordination 的案例，避免桥接层只留下元素名而丢失建模关键约束。
4. 将重复出现的材料表述沉淀回 `paperread` prompt/schema 和 `ptomodel` 归一化规则。

验收标准：

- `ptomodel` 不再只输出粗粒度 `primary_material`，还能稳定表达载体、位点类型和配位环境。
- 同类论文中的近义材料描述能归并到一致的桥接字段。

### 第四阶段：新增调度 Skill

目标：

- 将 `ptomodel` 与 Agent 建模能力连接。

建议新增：

```text
agents/Agent/skills/paperread-surface-modeling/SKILL.md
```

职责：

```text
paperread output
-> ptomodel.json
-> surface-modeling command
```

它不替代 `surface-modeling`，只作为上游调度器。

验收标准：

- Agent 能从 `*_ptomodel.json` 判断应该调用哪个建模脚本。
- Agent 能在缺少结构文件时明确向用户要 CIF/POSCAR/XYZ，或降级到可行的模板任务。

### 第五阶段：经验闭环

目标：

- 让论文阅读、建模执行和经验沉淀形成闭环。

闭环：

```text
paperread keywords
-> ptomodel.json
-> generated structures / energy tables
-> modeling_summary.json
-> knowledge graph
-> prompt/schema/ptomodel/skill 更新
```

验收标准：

- 陌生术语可追踪。
- 重复出现的术语能被提升为规则。
- 成功或失败的建模经验能被后续 Agent 查询和复用。

## 下一步

1. 用真实表面论文重新跑 `run_surface_pipeline.py`。
2. 用 `paperread-surface-learning` 记录陌生术语。
3. 持续扩展 `paperread` 的材料种类、位点和配位环境经验覆盖。
4. 让 `ptomodel` 对复杂体系输出更细的 `host/support + site_type + coordination` 映射。
5. 根据 `ptomodel` 稳定度再新增 `paperread-surface-modeling` skill。
