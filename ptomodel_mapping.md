# Ptomodel 对应关系

本文档整理 `paperread.surface.ptomodel` 当前已经收集到的已知参数，与后续建模参数之间的对应关系。

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

## 3. 字段对应关系

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

其余参数大多保留为：

- `needs_manual_decision`
- `needs_upstream_artifact`
- `optional_unset`
- `unresolved_required`

这是为了避免把论文中的语义硬塞成错误的数值参数。

## 7. 备注

这份映射是当前版本的 `ptomodel` 规则总结，不是最终不可变标准。
当后续补充新的 surface modeling 脚本参数时，这里应同步更新：

- `paperread/surface/ptomodel.py`
- `agents/Agent/skills/surface-modeling/schema/task_parameter_schema.json`
- `paperread/surface/parameter_registry.py`
