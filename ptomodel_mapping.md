# Ptomodel 对应关系

本文档整理 `genkai.modeling.mapping` 当前已经收集到的已知参数，与后续建模参数之间的对应关系。稳定公共入口为 `genkai.modeling.ptomodel`。

## 1. 总体分层

`ptomodel` 里目前是三层结构：

1. `selected_information`  
   论文中抽到的原始关键信息。
2. `normalized_mapping`  
   把论文语义归并成可复用的建模上下文。
3. `task_argument_template`  
   把上面的上下文映射到具体建模任务参数。

## 2. 参数种类左右对照

下面先把两侧参数分开列出。左侧是当前三个已启用建模脚本实际需要的参数种类；右侧是材料论文中当前抽取链路可以收集到的参数种类。

| 建模用途 | 建模脚本 / task | 建模部分需要的参数种类 | 材料论文中能够收集到的参数种类 |
|---|---|---|---|
| 表面 O 空位 | `vacancy_landscape` | `input`：结构文件 / slab 文件 | `materials` / `Material`：材料名称 |
| 表面 O 空位 | `vacancy_landscape` | `vacancy_counts`：空位数量 | `defects` / `Defect`：oxygen vacancy、Vo、缺陷丰富描述 |
| 表面 O 空位 | `vacancy_landscape` | `z_frac_min` / `z_frac_max`：可选氧原子的 z 分数范围 | `surface_terminations` / `Surface Termination`：表面、subsurface、reduced surface 等空间提示 |
| 表面 O 空位 | `vacancy_landscape` | `mu_o`：氧化学势 | `reaction_parameters`：气氛、氧分压、温度等可作为人工判断依据 |
| 表面 O 空位 | `vacancy_landscape` | `samples_per_count`、`seed` | 论文通常不直接给出；属于建模采样策略 |
| 表面 O 空位 | `vacancy_landscape` | `calculator`、`uma_model`、`device`、`task_name`、`include_d3` | 论文通常不直接给出；属于计算执行配置 |
| 表面 O 空位 | `vacancy_landscape` | `fmax`、`max_steps` | 论文中的 `reaction_parameters` 或 methods 中可能有 DFT 收敛信息，但当前抽取链路不稳定收集 |
| 表面 O 空位 | `vacancy_landscape` | `output_dir`、`structure_prefix`、`write_all_structures`、`smoke_test` | 论文不提供；属于工作流输出配置 |
| SAMs / 分子修饰 / 吸附覆盖 | `adsorbate_landscape` | `surface`：表面结构文件 | `surfaces` / `Surface/Support`、`slab_models`、`facets` / `Facet` |
| SAMs / 分子修饰 / 吸附覆盖 | `adsorbate_landscape` | `molecule`：吸附分子结构文件 | `adsorbates` / `Adsorbate/Reactant`、`intermediates`、SAMs 或 modifier 分子名 |
| SAMs / 分子修饰 / 吸附覆盖 | `adsorbate_landscape` | `site_symbols`：候选吸附位元素 | `active_sites` / `Active Site`：Pt site、Ce site、metal site 等 |
| SAMs / 分子修饰 / 吸附覆盖 | `adsorbate_landscape` | `site_group_size`、`site_radius`、`site_z_tolerance`、`max_sites` | `adsorption_sites` / `Adsorption Site`：top、bridge、hollow、monodentate、bidentate 等 |
| SAMs / 分子修饰 / 吸附覆盖 | `adsorbate_landscape` | `coverage_counts` | `coverage` / `Coverage`：ML、coverage、coadsorption、saturation coverage |
| SAMs / 分子修饰 / 吸附覆盖 | `adsorbate_landscape` | `patterns`、`random_repeats`、`n_trials_single`、`seed` | 论文通常不直接给出；属于构型搜索策略 |
| SAMs / 分子修饰 / 吸附覆盖 | `adsorbate_landscape` | `z_gap_min` / `z_gap_max` | 论文通常不直接给出；可由吸附构型经验人工设定 |
| SAMs / 分子修饰 / 吸附覆盖 | `adsorbate_landscape` | `calculator`、`uma_model`、`device`、`task_name`、`include_d3`、`fmax`、`max_steps` | 论文 methods 中可能有计算设置，但当前主要作为执行配置保留 |
| SAMs / 分子修饰 / 吸附覆盖 | `adsorbate_landscape` | `output_dir`、`structure_prefix`、`smoke_test` | 论文不提供；属于工作流输出配置 |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `surface`：可选表面结构文件 | `surfaces` / `Surface/Support`、`slab_models`、`facets` / `Facet` |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `cluster_element`：团簇元素 | `clusters` / `Cluster/Single Atom`：Pt cluster、Au nanoparticle 等 |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `cluster_atoms`：目标原子数 | `clusters` 中的显式尺寸：`Pt13`、13-atom cluster 等 |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `cluster_structures`：`fcc` / `hcp` / `bcc` | `clusters`、`material_parameters`、`Phase` 中的 fcc/hcp/bcc 或 crystal-structure 描述 |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `cluster_bulk_file` | 论文通常只给材料名；真实 bulk 文件需要上游结构库或人工选择 |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `cluster_layers`、`cluster_radius` | `Morphology/Size`、`clusters` 中的粒径、层数、nanoparticle size |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `cluster_a` / `cluster_c` | `material_parameters`、`Phase` 中可能有晶格常数；当前抽取链路不稳定收集 |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `fcc_rows`、`fcc_row_profile`、`fcc_max_row_atoms`、`fcc_row_count`、`fcc_stacking_mode`、`fcc_layers` | 论文通常不直接给出；属于团簇构型构造策略 |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `hcp_rows`、`hcp_layers`、`bcc_rows`、`bcc_max_row_atoms`、`stack_layers` | 论文通常不直接给出；属于团簇构型构造策略 |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `x_frac`、`y_frac`、`z_height`、`phi`、`theta`、`psi` | `active_sites`、`adsorption_sites`、`links` 可提供放置位置语义，但具体数值需人工决定 |
| 表面负载 / 金属团簇 | `surface_cluster_builder` | `output_dir` | 论文不提供；属于工作流输出配置 |

### 关键词对应关系（待细察）

本表仅标注论文关键词、抽取字段和候选建模参数之间的对应关系，不在脚本中固化任务
顺序或结构传递规则。带有歧义的对应关系需要结合原文语境进一步确认。

| 论文关键词或常见表达 | 优先对应的抽取字段 | 候选建模任务 | 候选参数或作用 | 后续细察重点 |
|---|---|---|---|---|
| oxygen vacancy、O vacancy、`V_O`、Vo、oxygen-deficient、reduced surface | `defects`、`vacancy_models`、`surface_terminations` | `vacancy_landscape` | `vacancy_counts`、`z_frac_min`、`z_frac_max` | 区分表面/次表面空位，并确认空位数量是否明确。 |
| oxygen-rich、oxygen-poor、O chemical potential、oxygen partial pressure | `reaction_parameters`、`surface_terminations` | `vacancy_landscape` | `mu_o` | 论文条件不能直接等同于数值化学势，通常需要人工换算。 |
| adsorbate、adsorbed、chemisorption、physisorption、intermediate | `adsorbates`、`intermediates` | `adsorbate_landscape` | `molecule` | 确认是稳定吸附物、反应中间体还是气相参照物。 |
| adsorption site、active site、top、bridge、hollow、atop | `adsorption_sites`、`active_sites` | `adsorbate_landscape` | `site_symbols`、`site_group_size`、`site_radius` | 位点名称需要与具体表面元素和晶面一起判断。 |
| coverage、monolayer、ML、saturation coverage、coadsorption | `coverage`、`adsorbates` | `adsorbate_landscape` | `coverage_counts` | ML 或百分比覆盖度需要结合表面位点数转换。 |
| SAM、self-assembled monolayer、surface modifier、functionalization | `modifiers`、`adsorbates`、`modeling_keywords` | `adsorbate_landscape` 或 `surface_functionalization` | `molecule`、`coverage_counts` | 区分吸附覆盖搜索与固定表面功能化模型。 |
| cluster、nanocluster、nanoparticle、supported particle、loaded metal | `clusters`、`loaded_nanoparticles_or_clusters` | `surface_cluster_builder` | `cluster_element`、`cluster_atoms`、`cluster_radius` | 确认负载物是团簇、纳米颗粒还是单原子。 |
| `Pt13`、13-atom cluster、subnanometer cluster | `clusters`、`Morphology/Size` | `surface_cluster_builder` | `cluster_atoms`、`cluster_radius` | 优先保留原文明示的原子数；尺寸只作为辅助约束。 |
| fcc、hcp、bcc、crystal structure、phase | `clusters`、`material_parameters`、`Phase` | `surface_cluster_builder` | `cluster_structures`、`cluster_a`、`cluster_c` | 判断结构描述属于团簇、块体前驱体还是载体材料。 |
| supported on、deposited on、loaded on、anchored at | `links`、`surfaces`、`active_sites` | `surface_cluster_builder` | `surface`、`x_frac`、`y_frac`、`z_height` | 只有原文明示时才建立负载物—载体—位点关系。 |
| single atom、isolated atom、SAC、single-atom catalyst | `single_atoms`、`active_sites` | `single_atom_site` | 单原子物种和锚定位点 | 不应仅因出现 metal atom 就判定为单原子催化剂。 |
| facet、surface plane、Miller index、(111)、(110)、(100) | `facets`、`slab_models`、`surfaces` | `slab_generation` 及各表面任务 | `surface`、`input` | 必须把晶面与对应材料、相和终止面关联起来。 |
| termination、terminated surface、metal-terminated、oxygen-terminated | `surface_terminations` | `slab_generation`、`surface_functionalization` | 表面终止选择 | 区分化学终止、吸附修饰与缺陷造成的还原表面。 |

## 3. 字段对应关系

### 元素、矿物名与通俗名称标准化

`ptomodel` 使用 `genkai.literature.surface.core.chemical_vocabulary` 统一识别：

- 原子序数 1–86（H–Rn）的元素符号和标准英文名。
- 论文中仍常见的拼写与旧称，例如 `aluminum/aluminium`、`sulfur/sulphur`、
  `cesium/caesium`、`tungsten/wolfram`、`mercury/quicksilver`。
- 元素材料俗名与同素异形体，例如 `graphite`、`graphene`、`diamond`、
  `black phosphorus`。
- 有唯一常用组成的矿物名和材料俗名，例如 `hematite -> Fe2O3`、
  `magnetite -> Fe3O4`、`ceria -> CeO2`、`alumina/corundum -> Al2O3`、
  `molybdenite -> MoS2`。

原文不会被覆盖。标准化结果写入 `recognized_material_names`，并给出
`normalized_formula`、`kind` 和 `elements`；汇总后的元素写入 `element_set`。
存在组成歧义的结构类型名称不强制转换成单一化学式。

`rutile` 不直接映射到单一化学式，而是作为独立结构类型保存。其代表组成
包括 `TiO2`、`SnO2`、`RuO2`、`IrO2` 和 `MnO2`。当前 surface 阶段只做
文章信息抽取和分类，不根据结构类型推断材料或稳定晶面：

- `crystal_structure_types`：文章明确给出的 `rutile` 等结构类型。
- `oxide_compositions`：文章明确给出的 `TiO2`、`SnO2`、`RuO2` 等组成。
- `facets`：文章明确给出的面指数。
- `surface_stability_descriptors`：文章明确给出的 stable、most stable、
  lowest-energy、metastable 等稳定性描述。
- `links`：只有文章明确建立关系时，才记录 composition—structure 和
  composition—facet—stability 的对应关系。

例如，只出现 `rutile` 时仅保存结构类型；出现“rutile RuO2(110) is the most
stable surface”时，分别保存 `rutile`、`RuO2`、`(110)` 和 `most stable
surface`，并用原文支持的 links 连接，不额外补充其他晶面。

| 论文抽取字段 | ptomodel 中间字段 | 建模任务 / 参数 | 说明 |
|---|---|---|---|
| `materials` | `normalized_mapping.primary_material` | `vacancy_landscape.input`，`adsorbate_landscape.surface`，`surface_cluster_builder.surface`，`surface_cluster_mlip_search.surface` | 作为主材料或主表面上下文。 |
| `surfaces` | `normalized_mapping.primary_surface_or_support` | 同上 | 作为支撑体、表面或基底。 |
| `slab_models` | `selected_information.surface_facets`，`normalized_mapping.facet_set` | `slab_generation.surface` | 作为板模型或显式表面信息。 |
| `facets` | `selected_information.surface_facets[].surface_index`，`normalized_mapping.facet_set` | `slab_generation.surface`，`vacancy_landscape.input` | 会进一步做 Miller 指数规范化。 |
| `surface_terminations` | `selected_information.surface_terminations` | `surface_functionalization` | 表面终止态 / 功能化信息。 |
| `active_sites` | `selected_information.active_sites`，`surface_site_contexts` | `adsorbate_landscape.site_symbols`，`surface_cluster_mlip_search.active_symbols`，`single_atom_site` | 金属表面常对应 top / bridge / hollow 语义，氧化物常对应 active-site 语义。 |
| `adsorption_sites` | `selected_information.adsorption_sites`，`surface_site_contexts` | `adsorbate_landscape`，`surface_cluster_mlip_search.active_symbols` | 吸附位点，和表面 / 晶面一起看。 |
| `coverage` | `selected_information.coverage` | `adsorbate_landscape.coverage_counts` | 覆盖度信息。 |
| `clusters` | `selected_information.loaded_nanoparticles_or_clusters`，`normalized_mapping.loaded_species` | `surface_cluster_builder.cluster_element`，`surface_cluster_builder.cluster_structures`，`surface_cluster_builder.cluster_atoms` | 团簇 / 纳米粒子 / 负载物种；`Pt13` 这类显式尺寸可对应 `cluster_atoms`。 |
| `single_atoms` | `selected_information.single_atom_species` | `single_atom_site` | 单原子位点或单原子物种。 |
| `defects` | `selected_information.defects` | `vacancy_landscape` | 缺陷、空位、氧空位。 |
| `vacancy_models` | `selected_information.defects`，`task_inputs.vacancy_landscape.vacancy_models` | `vacancy_landscape` | 空位建模语义。 |
| `dopants` | `selected_information.defects` / `selected_information.modeling_keywords` | `doped_surface` | 掺杂、修饰信息。 |
| `modifiers` | `selected_information.modeling_keywords`，`selected_information.defects` | `doped_surface`，`surface_functionalization` | 修饰剂、表面功能化。 |
| `reaction_type` / `applications` | `normalized_mapping.reaction_family` | 各建模任务的语义上下文 | 主要用于判断这是 OER / HER / ORR 等哪一类问题。 |
| `modeling_keywords` | `selected_information.modeling_keywords` | 作为所有任务的辅助上下文 | 不直接变成参数，但会影响任务选择和提示。 |

## 4. 任务级映射

任务选择按两级顺序执行：

1. 先根据 `material_classes` 确定材料上适用的候选建模脚本。例如氧化物、
   氢氧化物和缺陷材料才进入 `vacancy_landscape` 候选，负载催化剂或金属材料
   才进入 `surface_cluster_builder` 候选。
2. 再使用论文的 `modeling_keywords` 和明确抽取字段触发具体任务。材料类别本身
   不会单独触发任务，`DFT`、`OER` 等通用词也不会被强行解释为空位、吸附或团簇任务。

输出中的 `task_selection` 保存材料候选、研究关键词和每个入选任务的证据，便于检查
为什么选择了某个脚本。

### vacancy_landscape

当前主要由以下信息触发：

- `defects`
- `vacancy_models`
- `surface_terminations` 中带缺陷语义的条目

对应参数：

- `input`
- `vacancy_counts`
- `samples_per_count`
- `mu_o`
- `z_frac_min`
- `z_frac_max`
- `calculator`
- `uma_model`
- `device`

### adsorbate_landscape

当前主要由以下信息触发：

- `adsorbates`
- `adsorption_sites`
- `coverage`
- `active_sites`

自动可映射参数：

- `site_symbols`：由 `active_sites` 中可解析出的元素符号推断

需要人工确认的参数：

- `surface`
- `molecule`
- `coverage_counts`
- `patterns`
- `site_group_size`
- `site_radius`
- `z_gap_min`
- `z_gap_max`

### surface_cluster_builder

当前主要由以下信息触发：

- `clusters`
- `single_atoms`
- `Cluster/Single Atom`

自动可映射参数：

- `cluster_element`
- `cluster_structures`

### surface_cluster_mlip_search

当前主要由以下信息触发：

- `surface`
- `cluster`
- `active_sites`

对应的核心参数是：

- `surface`
- `cluster`
- `placement_mode`
- `active_symbols`
- `site_radius`

### single_atom_site

由以下信息触发：

- `single_atoms`
- `active_sites`
- `Cluster/Single Atom`

说明：

- 目前 `ptomodel` 会把单原子语义保留在 `selected_information` 与 `normalized_mapping` 里；
- 具体的 `single_atom_site` 参数模板仍然需要结合后续的建模脚本再细化。

### doped_surface

由以下信息触发：

- `dopants`
- `modifiers`
- `surface_terminations`

说明：

- 目前更多是语义层映射，不会强行给出单一数值参数。

### surface_functionalization

由以下信息触发：

- `surface_terminations`
- `modifiers`
- `functionalized surface` 相关表达

### slab_generation

由以下信息触发：

- `surfaces`
- `slab_models`
- `facets`

说明：

- 这是将论文中的表面语义转成可建模 slab 的桥接任务；
- 精确晶面会优先来自 `surface_facets[].surface_index`。

## 5. 新增的表面-位点关联层

现在 `ptomodel` 里增加了 `surface_site_contexts`，用于把同一条证据中的：

- `surface_terms`
- `facet_terms`
- `active_site_terms`
- `adsorption_site_terms`
- `site_role_terms`

放到同一个上下文里。

这个字段的意义是：

- 金属表面上更容易解释 `top` / `bridge` / `hollow`
- 氧化物、氢氧化物、单原子体系上更容易解释 `facet + active site`
- 后续做参数模板时，可以据此判断是“表面位点问题”还是“材料主体问题”

## 6. 当前自动填充规则

已实现的自动填充主要是：

- `active_sites` -> `adsorbate_landscape.site_symbols`
- `clusters` -> `surface_cluster_builder.cluster_element`
- `clusters` 中的显式尺寸，如 `Pt13` -> `surface_cluster_builder.cluster_atoms`
- `clusters` -> `surface_cluster_builder.cluster_structures`
- `two oxygen vacancies` 等显式数量 -> `vacancy_landscape.vacancy_counts`
- `monodentate` / `bidentate` / `tridentate` -> `adsorbate_landscape.site_group_size`

每篇文档还会输出 `parameter_correspondence`，将材料/表面、吸附物、覆盖度、团簇和
活性位字段对应到具体脚本参数。只有值可直译且无单位或构型歧义时才标记为 `auto`；
结构文件、覆盖度换算以及采样策略仍保留为上游依赖或人工决策。

其余参数大多保留为：

- `needs_manual_decision`
- `needs_upstream_artifact`
- `optional_unset`
- `unresolved_required`

这是为了避免把论文中的语义硬塞成错误的数值参数。

## 7. 备注

这份映射是当前版本的 `ptomodel` 规则总结，不是最终不可变标准。
当后续补充新的 surface modeling 脚本参数时，这里应同步更新：

- `src/genkai/modeling/mapping.py`
- `src/genkai/modeling/schema/task_parameter_schema.json`
- `src/genkai/literature/surface/experience/parameter_registry.py`
