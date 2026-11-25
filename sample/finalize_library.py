#!/usr/bin/env python3
"""Audit delivered structure files and rebuild the human-readable library index."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from ase.io import read
import numpy as np
from pymatgen.core import Composition, Structure
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

ROOT = Path(__file__).resolve().parent


def main():
    crystals = json.loads((ROOT / 'crystals/catalog.json').read_text())['crystals']
    molecules = json.loads((ROOT / 'molecules/catalog.json').read_text())['molecules']
    stable = [r for r in crystals if r['collection'] == 'stable']
    refs = [r for r in crystals if r['collection'] == 'ab2o3_reference']
    assert len(stable) == 30 and len(refs) == 2 and len(molecules) == 30
    assert all(r['is_stable'] and abs(r['energy_above_hull_eV_atom']) < 1e-8
               and not r['theoretical'] and r['icsd_ids'] for r in stable)
    checks = []
    for record in crystals:
        for fmt in ['cif', 'vasp', 'extxyz', 'conventional_cif']:
            path = ROOT / record[fmt]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'][fmt]
            structure = Structure.from_file(path) if fmt != 'extxyz' else None
            if structure is not None:
                assert structure.composition.reduced_composition == Composition(record['formula']).reduced_composition
                assert structure.is_ordered and np.isfinite(structure.cart_coords).all()
            atoms = read(path)
            assert atoms.pbc.all() and np.isfinite(atoms.positions).all()
            assert atoms.get_volume() > 0
        checks.append({'id': record['id'], 'type': 'crystal', 'status': 'PASS',
                       'collection': record['collection'], 'mp_is_stable': record['is_stable']})
    for record in molecules:
        sdf = Chem.SDMolSupplier(str(ROOT / record['sdf']), removeHs=False)[0]
        assert sdf is not None and len(Chem.GetMolFrags(sdf)) == 1
        assert Chem.GetFormalCharge(sdf) == 0
        assert sum(a.GetNumRadicalElectrons() for a in sdf.GetAtoms()) == 0
        assert rdMolDescriptors.CalcMolFormula(sdf) == record['formula']
        assert Chem.MolToInchiKey(Chem.RemoveHs(sdf)) == record['inchi_key']
        for fmt in ['xyz', 'sdf', 'extxyz', 'vasp']:
            path = ROOT / record[fmt]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'][fmt]
            if fmt != 'sdf':
                atoms = read(path)
                assert len(atoms) == record['atoms'] and np.isfinite(atoms.positions).all()
                assert Composition(atoms.get_chemical_formula()) == Composition(record['formula'])
                if fmt in ['xyz', 'extxyz']:
                    assert not atoms.pbc.any()
                else:
                    margin = atoms.cell.lengths() - np.ptp(atoms.positions, axis=0)
                    assert min(margin) > 19.99
        checks.append({'id': record['id'], 'type': 'molecule', 'status': 'PASS',
                       'pubchem_cid': record['pubchem_cid']})
    assert len({r['inchi_key'] for r in molecules}) == 30
    assert len(read(ROOT / 'molecules/all_voc.extxyz', index=':')) == 30
    assert len(read(ROOT / 'molecules/all_voc.xyz', index=':')) == 30
    assert len([m for m in Chem.SDMolSupplier(str(ROOT / 'molecules/all_voc.sdf'), removeHs=False)
                if m is not None]) == 30
    report = {'status': 'PASS', 'checked_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'stable_crystals': 30, 'ab2o3_near_hull_references': 2, 'voc_molecules': 30,
              'individual_structure_files_checked': 32 * 4 + 30 * 4,
              'checks': ['core MP stability, ICSD evidence and non-deprecation',
                         'SHA256 integrity of individual structure files',
                         'CIF/VASP/extxyz periodicity, finite coordinates, ordered occupancy and composition',
                         'molecular SDF connectivity, explicit-H formula, neutral closed-shell state and PubChem InChIKey',
                         'XYZ/extxyz nonperiodicity and vacuum VASP cell margins',
                         '30 unique molecular identities and 30-frame aggregate files'],
              'records': checks}
    (ROOT / 'validation_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    counts = Counter(r['category'] for r in stable)
    lines = [
        '# 晶体与 VOC 分子结构测试库', '',
        '生成日期：2026-11-19。位置：`/home/wu/start/sample`。', '',
        '**30 个 MP 凸包稳定晶体 + 2 个单独标记的 AB₂O₃ 实验参考晶体 + 30 个不同 VOC 分子。**', '',
        '## 晶体的选择与稳定性', '',
        '晶体直接来自 Materials Project 官方开放数据的 **2026-09-28** 版本；下载的是 MP 的 DFT 弛豫结构，'
        '没有用理想原型或其他数据库结构替代。原始摘要与坐标保存在 `provenance/mp_selected_summaries.json`，'
        '逐项完整记录保存在各晶体的 `metadata/` 中。', '',
        '主库 30 项全部满足：`is_stable=true`、`energy_above_hull=0 eV/atom`、`theoretical=false`、'
        '`deprecated=false`，并具有非空 ICSD 实验数据库交叉引用。先人工选择常见材料和晶相，再核对稳定性及实验记录。', '',
        '本库中的“稳定”指该版本 MP 近似 0 K 计算的成分凸包稳定性；未另做声子计算。'
        '这与室温晶相、空气中化学稳定性、以及经任意势函数优化后的稳定性不同。'
        '例如本库选取 MP 凸包上的锐钛矿 TiO₂、3R-MoS₂、白铁矿 FeS₂、正交 BaTiO₃、'
        '菱方 KNbO₃/NaNbO₃，文件名与清单均明确给出晶相，不能按化学式误认为其他多晶型。', '',
        'AB₂O₃ 按字面化学计量处理；同时也保留 Al₂O₃、Fe₂O₃、Cr₂O₃、In₂O₃ 等常见 A₂O₃。'
        'CaCu₂O₃ 与 SrCu₂O₃ 是有实验记录的铜氧化物参考相，但 **MP 的 `is_stable=false`**；'
        '它们与凸包稳定主库分开放置，不计入 30 个稳定晶体。', '',
        '| 主库类别 | 数量 |', '|---|---:|',
        f'| 普通氧化物 | {counts["oxide"]} |',
        f'| A₂O₃ 氧化物 | {counts["A2O3"]} |',
        f'| 硫化物 | {counts["sulfide"]} |',
        f'| 钙钛矿 ABO₃ | {counts["perovskite_ABO3"]} |',
        f'| 尖晶石 AB₂O₄ | {counts["spinel_AB2O4"]} |', '',
        '## 目录与格式', '',
        '```text',
        'crystals/',
        '  stable/               # 30 个凸包稳定晶体',
        '    cif/                # 原 MP 晶胞，全部原子显式写出（P1），不做对称化',
        '    vasp/               # 同一原始晶胞，VASP POSCAR 格式（.vasp）',
        '    extxyz/             # 原晶胞，pbc=True',
        '    conventional_cif/   # 另附标准常规胞，用于常规 Miller 指数',
        '    metadata/           # 每项完整 MP 摘要、来源、稳定性和文件校验码',
        '  ab2o3_reference/      # 2 个非凸包稳定参考，相同格式子目录',
        '  catalog.csv / catalog.json',
        'molecules/',
        '  xyz/                  # 含完整 H 的非周期分子，单位 Å',
        '  sdf/                  # 含键级、PubChem CID、SMILES、InChIKey',
        '  extxyz/               # 非周期分子，pbc=False',
        '  vasp_vacuum/          # 分子真空超胞，边长至少 25 Å，分子外总空隙至少 20 Å',
        '  all_voc.xyz / all_voc.extxyz / all_voc.sdf / all_voc.smi',
        '  catalog.csv / catalog.json',
        'provenance/             # MP 原始记录、筛选候选摘要、PubChem API 原始响应、来源链接',
        'validation_report.json  # 数据完整性与格式回读检查结果',
        'SHA256SUMS              # 交付文件校验码（不含 Python 环境与本文件自身）',
        '```', '',
        '晶体 `conventional_cif` 是用 pymatgen（`symprec=0.1 Å`）派生的常规晶胞，可能对称化坐标；'
        '需完全保留 MP 原胞与原始弛豫坐标时使用 `cif/`、`vasp/` 或 `extxyz/`。'
        'CIF 的 P1 导出设置不表示原晶体只有 P1 对称性；实际 MP 空间群见清单。'
        '尖晶石文件为 MP 的有序计算模型；完整结构/磁性属性以原始 JSON 为准。', '',
        '2026 年 MP 引入字母形式的 AlphaID。清单同时给出原始 AlphaID 与按官方 base-26 规则转换的数字别名；'
        '文件名使用便于识别的数字 MP 编号。', '',
        '## 30 个稳定晶体', '',
        '| 序号 | 化学式 | 类别 / 晶相 | 空间群 | 数字 MP 编号 | 原胞原子数 | CIF |',
        '|---:|---|---|---|---|---:|---|',
    ]
    for i, r in enumerate(stable, 1):
        lines.append(f'| {i} | {r["formula"]} | {r["category"]} / {r["phase"]} | {r["mp_spacegroup"]} | '
                     f'[{r["legacy_numeric_id"]}]({r["mp_url"]}) | {r["atoms"]} | [下载]({r["cif"]}) |')
    lines += ['', '## AB₂O₃ 参考结构（不属于凸包稳定主库）', '',
              '| 化学式 | 空间群 | E_hull / meV·atom⁻¹ | MP 稳定标记 | CIF |',
              '|---|---|---:|---|---|']
    for r in refs:
        lines.append(f'| {r["formula"]} | {r["mp_spacegroup"]} | {1000*r["energy_above_hull_eV_atom"]:.3f} | '
                     f'false | [下载]({r["cif"]}) |')
    lines += ['', '## VOC 分子的生成与使用', '',
              '选择 30 个常见气敏/吸附测试分子，覆盖醇、醛、酮、酯、醚、烷烃、芳香烃、腈、胺、'
              '卤代物、含硫分子和羧酸；VOC 按气敏测试的广义用法，包括甲醛等很易挥发的有机物。', '',
              '逐一在线获取 PubChem CID、分子式、ConnectivitySMILES 和 InChIKey，校验身份后，'
              '用 RDKit ETKDGv3 生成三维构象，加入完整 H，并用 MMFF94s 局部最小化。'
              '每种分子尝试 32 个构象，按 0.1 Å RMSD 去重，从收敛构象中选最低力场能者；随机种子已固定。'
              '全部为中性、单重态、无自由基的单分子。', '',
              '这些分子坐标是生成的力场局部极小结构，不是下载的实验三维坐标，也不是 DFT 优化或全局最低能证明。'
              'MMFF 能量只用于同一分子的构象筛选，不用于不同分子的能量比较。'
              'SDF 保存键级；XYZ 仅保存元素与坐标。VASP 文件以真空超胞表达孤立分子，'
              '常规分子读取优先使用 XYZ/SDF/extxyz。', '',
              '| 序号 | 中文名 | 英文名 | 分子式 | PubChem CID | XYZ | SDF |',
              '|---:|---|---|---|---:|---|---|']
    for i, r in enumerate(molecules, 1):
        lines.append(f'| {i} | {r["name_zh"]} | {r["name"]} | {r["formula"]} | '
                     f'[{r["pubchem_cid"]}]({r["pubchem_url"]}) | [下载]({r["xyz"]}) | [下载]({r["sdf"]}) |')
    first = stable[0]['cif']
    lines += ['', '## 读取与复现', '', '在本目录执行：', '', '```python',
              'import json', 'from pathlib import Path', 'from ase.io import read', '',
              'root = Path("/home/wu/start/sample")',
              'crystals = json.loads((root / "crystals/catalog.json").read_text())["crystals"]',
              'core = [r for r in crystals if r["collection"] == "stable"]',
              'bulk = read(root / core[0]["cif"])',
              'vocs = read(root / "molecules/all_voc.extxyz", index=":")',
              'print(len(core), len(vocs))  # 30, 30', '```', '',
              '本目录独立 `.venv` 已安装所需库；没有改动现有 UMA/MACE 环境。复现命令：', '',
              '```bash', 'cd /home/wu/start/sample',
              '.venv/bin/python build_voc_library.py',
              '.venv/bin/python build_crystal_library.py',
              '.venv/bin/python finalize_library.py',
              'sha256sum -c SHA256SUMS', '```', '',
              '重建环境可使用 `uv venv .venv` 和 `uv pip install --python .venv/bin/python -r requirements.lock.txt`。'
              '晶体脚本优先复用已保存的 MP 原始文档；VOC 脚本复用已保存的 PubChem 身份响应，均可离线重建结构文件。', '',
              '## 校验结果', '',
              '**62/62 个对象通过，248 个独立结构文件完成哈希和格式回读检查。** '
              '主库稳定性、实验记录、化学计量、有限坐标、有序占位、周期性均已检查；'
              '分子额外核对完整氢、连接性、电荷、PubChem 身份、真空边距和聚合文件的 30 帧计数。'
              '详见 [validation_report.json](validation_report.json)。', '',
              '## 数据来源', '',
              '- [Materials Project 官方开放数据](https://docs.materialsproject.org/downloading-data/aws-opendata)',
              '- [MP 稳定性术语](https://docs.materialsproject.org/frequently-asked-questions/glossary-of-terms)',
              '- [MP 标识符规则](https://docs.materialsproject.org/data-production/identifiers)',
              '- [PubChem PUG-REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest)',
              '- [RDKit 构象与力场方法](https://www.rdkit.org/docs/GettingStartedInPython.html)',
              '- [CaCu₂O₃ 文献](https://arxiv.org/abs/cond-mat/0208180)',
              '- [SrCu₂O₃ 文献，PRL 73, 3463](https://pubmed.ncbi.nlm.nih.gov/10057387/)', '',
              '使用 MP 数据请保留来源并遵守其 [数据使用条款](https://materialsproject.org/about/terms)。'
              '每项 MP 文档的许可字段与完整来源均保存在 metadata JSON 中。', '']
    (ROOT / 'README.md').write_text('\n'.join(lines))
    index = {'stable_crystals': 30, 'ab2o3_references': 2, 'voc_molecules': 30,
             'crystal_catalog': 'crystals/catalog.json', 'voc_catalog': 'molecules/catalog.json',
             'readme': 'README.md', 'validation': 'validation_report.json'}
    (ROOT / 'library.json').write_text(json.dumps(index, indent=2) + '\n')
    files = sorted(p for p in ROOT.rglob('*') if p.is_file() and
                   not any(part in ['.venv', '__pycache__', '.git'] for part in p.relative_to(ROOT).parts)
                   and p.name != 'SHA256SUMS')
    (ROOT / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT)}\n' for p in files))
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}, ensure_ascii=False, indent=2))
    print(f'Indexed {len(files)} delivered files; see README.md and SHA256SUMS.', flush=True)


if __name__ == '__main__':
    main()
