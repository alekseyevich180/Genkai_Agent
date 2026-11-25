# 建模配方：照着改就能用的例子

每个文件是一条完整的建模流程（流水线），对应一种常见的气敏材料体系。用法只有三步：

```bash
cp examples/recipes/03_pt_sno2_co.yaml my_job.yaml   # 1. 复制一个最接近的例子
# 2. 改两三行：晶体文件、气体、吸附位点元素（见下面“常改的地方”）
./genkai run my_job.yaml                              # 3. 运行（先 ./genkai check my_job.yaml 只检查不运行）
```

结果在 `runs/<文件名>/pipeline_structures.extxyz`，每个结构带来源记录（如 `slab#0 > vacancy#0 > cluster#0 > adsorbate#0`）。
前 10 个只生成几何结构（不算能量），普通电脑上几十秒到一两分钟；11、12 需要 MLIP，在服务器上运行。

| 文件 | 体系 | 流程 |
| --- | --- | --- |
| `01_sno2_no2.yaml` | SnO2 检测 NO2（最简单） | 切面 → NO2 |
| `02_sno2_vacancy_no2.yaml` | 还原态 SnO2 检测 NO2 | 切面 → 氧空位 → NO2 |
| `03_pt_sno2_co.yaml` | Pt/SnO2 检测 CO | 切面 → 氧空位 → Pt13 → CO（在 Pt 上） |
| `04_pd_sno2_h2.yaml` | Pd/SnO2 检测 H2 | 切面 → Pd13 → H2（在 Pd 上） |
| `05_zno_vacancy_ethanol.yaml` | ZnO 检测乙醇 | ZnO(10-10) → 氧空位 → 乙醇 |
| `06_sam_sno2_no2.yaml` | 有机分子修饰 SnO2 检测 NO2 | 切面 → 丁酸 SAM → NO2（避开分子） |
| `07_ald_tio2_islands_sno2_h2o.yaml` | ALD TiO2 岛修饰 SnO2，湿度 | 切面 → 非晶 TiO2 岛 → H2O |
| `08_ald_tio2_film_nh3.yaml` | SnO2/TiO2 核壳，检测 NH3 | 切面 → 5 Å 非晶 TiO2 膜 → NH3（在 Ti 上） |
| `09_ceo2_slab_vacancy_pt_co.yaml` | 已有 slab：Pt/CeO2(111) | CeO2(111) slab → 氧空位 → Pt13 → CO |
| `10_amorphous_sno2_acetone.yaml` | 非晶 SnO2 膜检测丙酮 | 非晶块体 → 非晶表面 → 氧空位 → 丙酮 |
| `11_mlip_pt_sno2_co_lowest_energy.yaml` | 例 03 的能量版（MLIP） | 每一步按能量挑最稳定的 |
| `12_mlip_crystal_to_amorphous_acetone.yaml` | 只有晶体时做非晶（MLIP） | 晶体 → 熔融-淬火 → 非晶表面 → 氧空位 → 丙酮 |

## 常改的地方

- **晶体**：`bulk: inputs/SnO2.cif` 换成自己的 CIF；`facet` 写晶面（如 `"110"`、`"101"`、六方的 `"10-10"`）；
  不写 facet 时按内置稳定晶面表选（表里有 SnO2、TiO2、CeO2、RuO2、IrO2 和常见金属）。
  `repeat_xy` 是面内扩胞，放团簇时用大一点（如 `[2, 4]`）。
- **已经有 slab**：第一步换成别的方法并自己给 slab，例如 `- method: vacancy` 加 `input: 我的slab.cif`（见例 09）。
- **气体**：`molecule:` 直接写名字：NO2、NO、CO、CO2、H2、O2、O3、H2O、NH3、H2S、SO2、CH4、CH3OH（甲醇）、
  C2H5OH（乙醇）、HCHO（甲醛）、CH3CHO（乙醛）、CH3COCH3（丙酮）、C6H6（苯）；其他分子写结构文件路径。
- **吸附位点**：`site_symbols: [auto]` 自动选表面裸露的阳离子；也可以写放分子的元素：氧化物的金属（Sn、Zn、Ti、Ce、W、In）、负载金属（Pt、Pd、Au），
  或 O（如 H 溢流）。被团簇、SAM 分子盖住的位点会自动排除。
- **负载金属**：`cluster_element` 换成 Pt、Pd、Au、Ag、Ru、Rh、Ni 等，`cluster_atoms` 是原子数。
- **空位**：`vacancy_counts: [1, 2]` 生成 1 个和 2 个空位；`samples_per_count` 是每种数目的构型数；
  硫化物写 `element: S`。
- **想要随机组合**：`./genkai random -n 10 --seed 7 -o random_jobs` 从 `sample/` 结构库随机生成（见项目 README）。
- **多个分子**：在 adsorbate 里写 `coverage_counts: [1, 2]`（流水线默认只放 1 个）。

## 想比较多个构型时

- `pick: all`：这一步的每个候选都往下做，变成多条分支（例如几个空位构型各自加团簇、加分子）。
- `pick: lowest_energy`：用 MLIP 弛豫这一步的候选，按组成取能量最低的（需要在文件开头写 `mlip: 配置名`，见例 11）。

步骤顺序固定为：体相 → 表面 → 空位 → ALD → 团簇 → SAM → 吸附，`relax`（弛豫）可以插在任意一步之后。
顺序写反会提示；更多规则见 `docs/surface-modeling-user-guide.md` 的 4.4 节。
