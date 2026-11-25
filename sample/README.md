# 晶体与 VOC 分子结构测试库

生成日期：2026-11-19。位置：`/home/wu/start/sample`。

**30 个 MP 凸包稳定晶体 + 2 个单独标记的 AB₂O₃ 实验参考晶体 + 30 个不同 VOC 分子。**

## 晶体的选择与稳定性

晶体直接来自 Materials Project 官方开放数据的 **2026-09-28** 版本；下载的是 MP 的 DFT 弛豫结构，没有用理想原型或其他数据库结构替代。原始摘要与坐标保存在 `provenance/mp_selected_summaries.json`，逐项完整记录保存在各晶体的 `metadata/` 中。

主库 30 项全部满足：`is_stable=true`、`energy_above_hull=0 eV/atom`、`theoretical=false`、`deprecated=false`，并具有非空 ICSD 实验数据库交叉引用。先人工选择常见材料和晶相，再核对稳定性及实验记录。

本库中的“稳定”指该版本 MP 近似 0 K 计算的成分凸包稳定性；未另做声子计算。这与室温晶相、空气中化学稳定性、以及经任意势函数优化后的稳定性不同。例如本库选取 MP 凸包上的锐钛矿 TiO₂、3R-MoS₂、白铁矿 FeS₂、正交 BaTiO₃、菱方 KNbO₃/NaNbO₃，文件名与清单均明确给出晶相，不能按化学式误认为其他多晶型。

AB₂O₃ 按字面化学计量处理；同时也保留 Al₂O₃、Fe₂O₃、Cr₂O₃、In₂O₃ 等常见 A₂O₃。CaCu₂O₃ 与 SrCu₂O₃ 是有实验记录的铜氧化物参考相，但 **MP 的 `is_stable=false`**；它们与凸包稳定主库分开放置，不计入 30 个稳定晶体。

| 主库类别 | 数量 |
|---|---:|
| 普通氧化物 | 7 |
| A₂O₃ 氧化物 | 4 |
| 硫化物 | 6 |
| 钙钛矿 ABO₃ | 6 |
| 尖晶石 AB₂O₄ | 7 |

## 目录与格式

```text
crystals/
  stable/               # 30 个凸包稳定晶体
    cif/                # 原 MP 晶胞，全部原子显式写出（P1），不做对称化
    vasp/               # 同一原始晶胞，VASP POSCAR 格式（.vasp）
    extxyz/             # 原晶胞，pbc=True
    conventional_cif/   # 另附标准常规胞，用于常规 Miller 指数
    metadata/           # 每项完整 MP 摘要、来源、稳定性和文件校验码
  ab2o3_reference/      # 2 个非凸包稳定参考，相同格式子目录
  catalog.csv / catalog.json
molecules/
  xyz/                  # 含完整 H 的非周期分子，单位 Å
  sdf/                  # 含键级、PubChem CID、SMILES、InChIKey
  extxyz/               # 非周期分子，pbc=False
  vasp_vacuum/          # 分子真空超胞，边长至少 25 Å，分子外总空隙至少 20 Å
  all_voc.xyz / all_voc.extxyz / all_voc.sdf / all_voc.smi
  catalog.csv / catalog.json
provenance/             # MP 原始记录、筛选候选摘要、PubChem API 原始响应、来源链接
validation_report.json  # 数据完整性与格式回读检查结果
SHA256SUMS              # 交付文件校验码（不含 Python 环境与本文件自身）
```

晶体 `conventional_cif` 是用 pymatgen（`symprec=0.1 Å`）派生的常规晶胞，可能对称化坐标；需完全保留 MP 原胞与原始弛豫坐标时使用 `cif/`、`vasp/` 或 `extxyz/`。CIF 的 P1 导出设置不表示原晶体只有 P1 对称性；实际 MP 空间群见清单。尖晶石文件为 MP 的有序计算模型；完整结构/磁性属性以原始 JSON 为准。

2026 年 MP 引入字母形式的 AlphaID。清单同时给出原始 AlphaID 与按官方 base-26 规则转换的数字别名；文件名使用便于识别的数字 MP 编号。

## 30 个稳定晶体

| 序号 | 化学式 | 类别 / 晶相 | 空间群 | 数字 MP 编号 | 原胞原子数 | CIF |
|---:|---|---|---|---|---:|---|
| 1 | MgO | oxide / rocksalt | Fm-3m | [mp-1265](https://materialsproject.org/materials/mp-aaaaabwr) | 2 | [下载](crystals/stable/cif/01_MgO_rocksalt_mp-1265.cif) |
| 2 | ZnO | oxide / wurtzite | P6_3mc | [mp-2133](https://materialsproject.org/materials/mp-aaaaadeb) | 4 | [下载](crystals/stable/cif/02_ZnO_wurtzite_mp-2133.cif) |
| 3 | TiO2 | oxide / anatase | I4_1/amd | [mp-390](https://materialsproject.org/materials/mp-aaaaaapa) | 6 | [下载](crystals/stable/cif/03_TiO2_anatase_mp-390.cif) |
| 4 | SnO2 | oxide / cassiterite_rutile | P4_2/mnm | [mp-856](https://materialsproject.org/materials/mp-aaaaabgy) | 6 | [下载](crystals/stable/cif/04_SnO2_cassiterite_rutile_mp-856.cif) |
| 5 | CeO2 | oxide / fluorite | Fm-3m | [mp-20194](https://materialsproject.org/materials/mp-aaaabdws) | 3 | [下载](crystals/stable/cif/05_CeO2_fluorite_mp-20194.cif) |
| 6 | NiO | oxide / rocksalt | Fm-3m | [mp-19009](https://materialsproject.org/materials/mp-aaaabcdd) | 2 | [下载](crystals/stable/cif/06_NiO_rocksalt_mp-19009.cif) |
| 7 | Al2O3 | A2O3 / alpha_corundum | R-3c | [mp-1143](https://materialsproject.org/materials/mp-aaaaabrz) | 10 | [下载](crystals/stable/cif/07_Al2O3_alpha_corundum_mp-1143.cif) |
| 8 | Fe2O3 | A2O3 / alpha_hematite | R-3c | [mp-19770](https://materialsproject.org/materials/mp-aaaabdgk) | 10 | [下载](crystals/stable/cif/08_Fe2O3_alpha_hematite_mp-19770.cif) |
| 9 | Cr2O3 | A2O3 / corundum | R-3c | [mp-19399](https://materialsproject.org/materials/mp-aaaabcsd) | 10 | [下载](crystals/stable/cif/09_Cr2O3_corundum_mp-19399.cif) |
| 10 | SiO2 | oxide / alpha_quartz | P3_121 | [mp-7000](https://materialsproject.org/materials/mp-aaaaakjg) | 9 | [下载](crystals/stable/cif/10_SiO2_alpha_quartz_mp-7000.cif) |
| 11 | In2O3 | A2O3 / bixbyite | Ia-3 | [mp-22598](https://materialsproject.org/materials/mp-aaaabhle) | 40 | [下载](crystals/stable/cif/11_In2O3_bixbyite_mp-22598.cif) |
| 12 | CdS | sulfide / wurtzite | P6_3mc | [mp-672](https://materialsproject.org/materials/mp-aaaaaazw) | 4 | [下载](crystals/stable/cif/12_CdS_wurtzite_mp-672.cif) |
| 13 | MoS2 | sulfide / 3R | R3m | [mp-1434](https://materialsproject.org/materials/mp-aaaaacde) | 3 | [下载](crystals/stable/cif/13_MoS2_3R_mp-1434.cif) |
| 14 | WS2 | sulfide / 2H | P6_3/mmc | [mp-224](https://materialsproject.org/materials/mp-aaaaaaiq) | 6 | [下载](crystals/stable/cif/14_WS2_2H_mp-224.cif) |
| 15 | SnS | sulfide / orthorhombic | Pnma | [mp-2231](https://materialsproject.org/materials/mp-aaaaadhv) | 8 | [下载](crystals/stable/cif/15_SnS_orthorhombic_mp-2231.cif) |
| 16 | SnS2 | sulfide / CdI2_type | P-3m1 | [mp-1170](https://materialsproject.org/materials/mp-aaaaabta) | 3 | [下载](crystals/stable/cif/16_SnS2_CdI2_type_mp-1170.cif) |
| 17 | FeS2 | sulfide / marcasite | Pnnm | [mp-1522](https://materialsproject.org/materials/mp-aaaaacgo) | 6 | [下载](crystals/stable/cif/17_FeS2_marcasite_mp-1522.cif) |
| 18 | CaTiO3 | perovskite_ABO3 / orthorhombic | Pnma | [mp-4019](https://materialsproject.org/materials/mp-aaaaafyp) | 20 | [下载](crystals/stable/cif/18_CaTiO3_orthorhombic_mp-4019.cif) |
| 19 | BaTiO3 | perovskite_ABO3 / orthorhombic | Amm2 | [mp-5777](https://materialsproject.org/materials/mp-aaaaaiof) | 5 | [下载](crystals/stable/cif/19_BaTiO3_orthorhombic_mp-5777.cif) |
| 20 | LaCrO3 | perovskite_ABO3 / orthorhombic | Pnma | [mp-19281](https://materialsproject.org/materials/mp-aaaabcnp) | 20 | [下载](crystals/stable/cif/20_LaCrO3_orthorhombic_mp-19281.cif) |
| 21 | SrZrO3 | perovskite_ABO3 / orthorhombic | Pnma | [mp-4387](https://materialsproject.org/materials/mp-aaaaagmt) | 20 | [下载](crystals/stable/cif/21_SrZrO3_orthorhombic_mp-4387.cif) |
| 22 | KNbO3 | perovskite_ABO3 / rhombohedral | R3m | [mp-7375](https://materialsproject.org/materials/mp-aaaaakxr) | 5 | [下载](crystals/stable/cif/22_KNbO3_rhombohedral_mp-7375.cif) |
| 23 | NaNbO3 | perovskite_ABO3 / rhombohedral | R3c | [mp-4514](https://materialsproject.org/materials/mp-aaaaagrq) | 10 | [下载](crystals/stable/cif/23_NaNbO3_rhombohedral_mp-4514.cif) |
| 24 | MgAl2O4 | spinel_AB2O4 / cubic | Fd-3m | [mp-3536](https://materialsproject.org/materials/mp-aaaaafga) | 14 | [下载](crystals/stable/cif/24_MgAl2O4_cubic_mp-3536.cif) |
| 25 | ZnAl2O4 | spinel_AB2O4 / cubic | Fd-3m | [mp-2908](https://materialsproject.org/materials/mp-aaaaaehw) | 14 | [下载](crystals/stable/cif/25_ZnAl2O4_cubic_mp-2908.cif) |
| 26 | MgCr2O4 | spinel_AB2O4 / cubic | Fd-3m | [mp-19202](https://materialsproject.org/materials/mp-aaaabcko) | 14 | [下载](crystals/stable/cif/26_MgCr2O4_cubic_mp-19202.cif) |
| 27 | ZnCr2O4 | spinel_AB2O4 / cubic | Fd-3m | [mp-19410](https://materialsproject.org/materials/mp-aaaabcso) | 14 | [下载](crystals/stable/cif/27_ZnCr2O4_cubic_mp-19410.cif) |
| 28 | FeAl2O4 | spinel_AB2O4 / hercynite | Fd-3m | [mp-30084](https://materialsproject.org/materials/mp-aaaabsnc) | 14 | [下载](crystals/stable/cif/28_FeAl2O4_hercynite_mp-30084.cif) |
| 29 | MgFe2O4 | spinel_AB2O4 / cubic_ordered_MP_model | Fd-3m | [mp-608016](https://materialsproject.org/materials/mp-aaabiplg) | 14 | [下载](crystals/stable/cif/29_MgFe2O4_cubic_ordered_MP_model_mp-608016.cif) |
| 30 | ZnFe2O4 | spinel_AB2O4 / cubic | Fd-3m | [mp-19313](https://materialsproject.org/materials/mp-aaaabcov) | 14 | [下载](crystals/stable/cif/30_ZnFe2O4_cubic_mp-19313.cif) |

## AB₂O₃ 参考结构（不属于凸包稳定主库）

| 化学式 | 空间群 | E_hull / meV·atom⁻¹ | MP 稳定标记 | CIF |
|---|---|---:|---|---|
| CaCu2O3 | Pmmn | 31.315 | false | [下载](crystals/ab2o3_reference/cif/31_CaCu2O3_pseudo_ladder_mp-7466.cif) |
| SrCu2O3 | Cmmm | 16.884 | false | [下载](crystals/ab2o3_reference/cif/32_SrCu2O3_two_leg_ladder_mp-5938.cif) |

## VOC 分子的生成与使用

选择 30 个常见气敏/吸附测试分子，覆盖醇、醛、酮、酯、醚、烷烃、芳香烃、腈、胺、卤代物、含硫分子和羧酸；VOC 按气敏测试的广义用法，包括甲醛等很易挥发的有机物。

逐一在线获取 PubChem CID、分子式、ConnectivitySMILES 和 InChIKey，校验身份后，用 RDKit ETKDGv3 生成三维构象，加入完整 H，并用 MMFF94s 局部最小化。每种分子尝试 32 个构象，按 0.1 Å RMSD 去重，从收敛构象中选最低力场能者；随机种子已固定。全部为中性、单重态、无自由基的单分子。

这些分子坐标是生成的力场局部极小结构，不是下载的实验三维坐标，也不是 DFT 优化或全局最低能证明。MMFF 能量只用于同一分子的构象筛选，不用于不同分子的能量比较。SDF 保存键级；XYZ 仅保存元素与坐标。VASP 文件以真空超胞表达孤立分子，常规分子读取优先使用 XYZ/SDF/extxyz。

| 序号 | 中文名 | 英文名 | 分子式 | PubChem CID | XYZ | SDF |
|---:|---|---|---|---:|---|---|
| 1 | 甲醇 | methanol | CH4O | [887](https://pubchem.ncbi.nlm.nih.gov/compound/887) | [下载](molecules/xyz/01_methanol.xyz) | [下载](molecules/sdf/01_methanol.sdf) |
| 2 | 乙醇 | ethanol | C2H6O | [702](https://pubchem.ncbi.nlm.nih.gov/compound/702) | [下载](molecules/xyz/02_ethanol.xyz) | [下载](molecules/sdf/02_ethanol.sdf) |
| 3 | 正丙醇 | 1-propanol | C3H8O | [1031](https://pubchem.ncbi.nlm.nih.gov/compound/1031) | [下载](molecules/xyz/03_1-propanol.xyz) | [下载](molecules/sdf/03_1-propanol.sdf) |
| 4 | 异丙醇 | 2-propanol | C3H8O | [3776](https://pubchem.ncbi.nlm.nih.gov/compound/3776) | [下载](molecules/xyz/04_2-propanol.xyz) | [下载](molecules/sdf/04_2-propanol.sdf) |
| 5 | 正丁醇 | 1-butanol | C4H10O | [263](https://pubchem.ncbi.nlm.nih.gov/compound/263) | [下载](molecules/xyz/05_1-butanol.xyz) | [下载](molecules/sdf/05_1-butanol.sdf) |
| 6 | 甲醛 | formaldehyde | CH2O | [712](https://pubchem.ncbi.nlm.nih.gov/compound/712) | [下载](molecules/xyz/06_formaldehyde.xyz) | [下载](molecules/sdf/06_formaldehyde.sdf) |
| 7 | 乙醛 | acetaldehyde | C2H4O | [177](https://pubchem.ncbi.nlm.nih.gov/compound/177) | [下载](molecules/xyz/07_acetaldehyde.xyz) | [下载](molecules/sdf/07_acetaldehyde.sdf) |
| 8 | 丙醛 | propanal | C3H6O | [527](https://pubchem.ncbi.nlm.nih.gov/compound/527) | [下载](molecules/xyz/08_propanal.xyz) | [下载](molecules/sdf/08_propanal.sdf) |
| 9 | 丙酮 | acetone | C3H6O | [180](https://pubchem.ncbi.nlm.nih.gov/compound/180) | [下载](molecules/xyz/09_acetone.xyz) | [下载](molecules/sdf/09_acetone.sdf) |
| 10 | 丁酮 | 2-butanone | C4H8O | [6569](https://pubchem.ncbi.nlm.nih.gov/compound/6569) | [下载](molecules/xyz/10_2-butanone.xyz) | [下载](molecules/sdf/10_2-butanone.sdf) |
| 11 | 乙酸乙酯 | ethyl acetate | C4H8O2 | [8857](https://pubchem.ncbi.nlm.nih.gov/compound/8857) | [下载](molecules/xyz/11_ethyl_acetate.xyz) | [下载](molecules/sdf/11_ethyl_acetate.sdf) |
| 12 | 糠醛 | furfural | C5H4O2 | [7362](https://pubchem.ncbi.nlm.nih.gov/compound/7362) | [下载](molecules/xyz/12_furfural.xyz) | [下载](molecules/sdf/12_furfural.sdf) |
| 13 | 乙醚 | diethyl ether | C4H10O | [3283](https://pubchem.ncbi.nlm.nih.gov/compound/3283) | [下载](molecules/xyz/13_diethyl_ether.xyz) | [下载](molecules/sdf/13_diethyl_ether.sdf) |
| 14 | 四氢呋喃 | tetrahydrofuran | C4H8O | [8028](https://pubchem.ncbi.nlm.nih.gov/compound/8028) | [下载](molecules/xyz/14_tetrahydrofuran.xyz) | [下载](molecules/sdf/14_tetrahydrofuran.sdf) |
| 15 | 正己烷 | n-hexane | C6H14 | [8058](https://pubchem.ncbi.nlm.nih.gov/compound/8058) | [下载](molecules/xyz/15_n-hexane.xyz) | [下载](molecules/sdf/15_n-hexane.sdf) |
| 16 | 环己烷 | cyclohexane | C6H12 | [8078](https://pubchem.ncbi.nlm.nih.gov/compound/8078) | [下载](molecules/xyz/16_cyclohexane.xyz) | [下载](molecules/sdf/16_cyclohexane.sdf) |
| 17 | 苯 | benzene | C6H6 | [241](https://pubchem.ncbi.nlm.nih.gov/compound/241) | [下载](molecules/xyz/17_benzene.xyz) | [下载](molecules/sdf/17_benzene.sdf) |
| 18 | 甲苯 | toluene | C7H8 | [1140](https://pubchem.ncbi.nlm.nih.gov/compound/1140) | [下载](molecules/xyz/18_toluene.xyz) | [下载](molecules/sdf/18_toluene.sdf) |
| 19 | 乙苯 | ethylbenzene | C8H10 | [7500](https://pubchem.ncbi.nlm.nih.gov/compound/7500) | [下载](molecules/xyz/19_ethylbenzene.xyz) | [下载](molecules/sdf/19_ethylbenzene.sdf) |
| 20 | 邻二甲苯 | o-xylene | C8H10 | [7237](https://pubchem.ncbi.nlm.nih.gov/compound/7237) | [下载](molecules/xyz/20_o-xylene.xyz) | [下载](molecules/sdf/20_o-xylene.sdf) |
| 21 | 间二甲苯 | m-xylene | C8H10 | [7929](https://pubchem.ncbi.nlm.nih.gov/compound/7929) | [下载](molecules/xyz/21_m-xylene.xyz) | [下载](molecules/sdf/21_m-xylene.sdf) |
| 22 | 对二甲苯 | p-xylene | C8H10 | [7809](https://pubchem.ncbi.nlm.nih.gov/compound/7809) | [下载](molecules/xyz/22_p-xylene.xyz) | [下载](molecules/sdf/22_p-xylene.sdf) |
| 23 | 苯乙烯 | styrene | C8H8 | [7501](https://pubchem.ncbi.nlm.nih.gov/compound/7501) | [下载](molecules/xyz/23_styrene.xyz) | [下载](molecules/sdf/23_styrene.sdf) |
| 24 | 乙腈 | acetonitrile | C2H3N | [6342](https://pubchem.ncbi.nlm.nih.gov/compound/6342) | [下载](molecules/xyz/24_acetonitrile.xyz) | [下载](molecules/sdf/24_acetonitrile.sdf) |
| 25 | 三甲胺 | trimethylamine | C3H9N | [1146](https://pubchem.ncbi.nlm.nih.gov/compound/1146) | [下载](molecules/xyz/25_trimethylamine.xyz) | [下载](molecules/sdf/25_trimethylamine.sdf) |
| 26 | 二氯甲烷 | dichloromethane | CH2Cl2 | [6344](https://pubchem.ncbi.nlm.nih.gov/compound/6344) | [下载](molecules/xyz/26_dichloromethane.xyz) | [下载](molecules/sdf/26_dichloromethane.sdf) |
| 27 | 三氯甲烷 | chloroform | CHCl3 | [6212](https://pubchem.ncbi.nlm.nih.gov/compound/6212) | [下载](molecules/xyz/27_chloroform.xyz) | [下载](molecules/sdf/27_chloroform.sdf) |
| 28 | 二甲硫醚 | dimethyl sulfide | C2H6S | [1068](https://pubchem.ncbi.nlm.nih.gov/compound/1068) | [下载](molecules/xyz/28_dimethyl_sulfide.xyz) | [下载](molecules/sdf/28_dimethyl_sulfide.sdf) |
| 29 | 乙硫醇 | ethanethiol | C2H6S | [6343](https://pubchem.ncbi.nlm.nih.gov/compound/6343) | [下载](molecules/xyz/29_ethanethiol.xyz) | [下载](molecules/sdf/29_ethanethiol.sdf) |
| 30 | 乙酸 | acetic acid | C2H4O2 | [176](https://pubchem.ncbi.nlm.nih.gov/compound/176) | [下载](molecules/xyz/30_acetic_acid.xyz) | [下载](molecules/sdf/30_acetic_acid.sdf) |

## 读取与复现

在本目录执行：

```python
import json
from pathlib import Path
from ase.io import read

root = Path("/home/wu/start/sample")
crystals = json.loads((root / "crystals/catalog.json").read_text())["crystals"]
core = [r for r in crystals if r["collection"] == "stable"]
bulk = read(root / core[0]["cif"])
vocs = read(root / "molecules/all_voc.extxyz", index=":")
print(len(core), len(vocs))  # 30, 30
```

本目录独立 `.venv` 已安装所需库；没有改动现有 UMA/MACE 环境。复现命令：

```bash
cd /home/wu/start/sample
.venv/bin/python build_voc_library.py
.venv/bin/python build_crystal_library.py
.venv/bin/python finalize_library.py
sha256sum -c SHA256SUMS
```

重建环境可使用 `uv venv .venv` 和 `uv pip install --python .venv/bin/python -r requirements.lock.txt`。晶体脚本优先复用已保存的 MP 原始文档；VOC 脚本复用已保存的 PubChem 身份响应，均可离线重建结构文件。

## 校验结果

**62/62 个对象通过，248 个独立结构文件完成哈希和格式回读检查。** 主库稳定性、实验记录、化学计量、有限坐标、有序占位、周期性均已检查；分子额外核对完整氢、连接性、电荷、PubChem 身份、真空边距和聚合文件的 30 帧计数。详见 [validation_report.json](validation_report.json)。

## 数据来源

- [Materials Project 官方开放数据](https://docs.materialsproject.org/downloading-data/aws-opendata)
- [MP 稳定性术语](https://docs.materialsproject.org/frequently-asked-questions/glossary-of-terms)
- [MP 标识符规则](https://docs.materialsproject.org/data-production/identifiers)
- [PubChem PUG-REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest)
- [RDKit 构象与力场方法](https://www.rdkit.org/docs/GettingStartedInPython.html)
- [CaCu₂O₃ 文献](https://arxiv.org/abs/cond-mat/0208180)
- [SrCu₂O₃ 文献，PRL 73, 3463](https://pubmed.ncbi.nlm.nih.gov/10057387/)

使用 MP 数据请保留来源并遵守其 [数据使用条款](https://materialsproject.org/about/terms)。每项 MP 文档的许可字段与完整来源均保存在 metadata JSON 中。
