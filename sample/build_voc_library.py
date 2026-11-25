#!/usr/bin/env python3
"""Generate neutral, explicit-H VOC conformers; verify identities against PubChem."""
import concurrent.futures
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time
from urllib.parse import quote

import numpy as np
import requests
from ase import Atoms
from ase.io import read, write
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors

ROOT = Path(__file__).resolve().parent
# English name, Chinese name, chemical class, unambiguous connectivity SMILES.
VOCS = [
    ('methanol', '甲醇', 'alcohol', 'CO'),
    ('ethanol', '乙醇', 'alcohol', 'CCO'),
    ('1-propanol', '正丙醇', 'alcohol', 'CCCO'),
    ('2-propanol', '异丙醇', 'alcohol', 'CC(O)C'),
    ('1-butanol', '正丁醇', 'alcohol', 'CCCCO'),
    ('formaldehyde', '甲醛', 'aldehyde', 'C=O'),
    ('acetaldehyde', '乙醛', 'aldehyde', 'CC=O'),
    ('propanal', '丙醛', 'aldehyde', 'CCC=O'),
    ('acetone', '丙酮', 'ketone', 'CC(=O)C'),
    ('2-butanone', '丁酮', 'ketone', 'CCC(=O)C'),
    ('ethyl acetate', '乙酸乙酯', 'ester', 'CCOC(C)=O'),
    ('furfural', '糠醛', 'heteroaromatic_aldehyde', 'O=Cc1ccco1'),
    ('diethyl ether', '乙醚', 'ether', 'CCOCC'),
    ('tetrahydrofuran', '四氢呋喃', 'cyclic_ether', 'C1CCOC1'),
    ('n-hexane', '正己烷', 'alkane', 'CCCCCC'),
    ('cyclohexane', '环己烷', 'cycloalkane', 'C1CCCCC1'),
    ('benzene', '苯', 'aromatic', 'c1ccccc1'),
    ('toluene', '甲苯', 'aromatic', 'Cc1ccccc1'),
    ('ethylbenzene', '乙苯', 'aromatic', 'CCc1ccccc1'),
    ('o-xylene', '邻二甲苯', 'aromatic', 'Cc1ccccc1C'),
    ('m-xylene', '间二甲苯', 'aromatic', 'Cc1cccc(C)c1'),
    ('p-xylene', '对二甲苯', 'aromatic', 'Cc1ccc(C)cc1'),
    ('styrene', '苯乙烯', 'aromatic_alkene', 'C=Cc1ccccc1'),
    ('acetonitrile', '乙腈', 'nitrile', 'CC#N'),
    ('trimethylamine', '三甲胺', 'amine', 'CN(C)C'),
    ('dichloromethane', '二氯甲烷', 'halogenated', 'ClCCl'),
    ('chloroform', '三氯甲烷', 'halogenated', 'ClC(Cl)Cl'),
    ('dimethyl sulfide', '二甲硫醚', 'sulfide', 'CSC'),
    ('ethanethiol', '乙硫醇', 'thiol', 'CCS'),
    ('acetic acid', '乙酸', 'carboxylic_acid', 'CC(=O)O'),
]


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def identity(item):
    name, chinese, category, smiles = item
    slug = name.replace(' ', '_')
    path = ROOT / 'provenance' / 'pubchem' / f'{slug}.json'
    if path.exists():
        data = json.loads(path.read_text())
    else:
        url = ('https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/'
               f'{quote(name, safe="")}/property/MolecularFormula,ConnectivitySMILES,InChIKey,IUPACName/JSON')
        for attempt in range(3):
            try:
                response = requests.get(url, timeout=35)
                response.raise_for_status()
                data = {'source_url': url, 'retrieved_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        'response': response.json()}
                dump(path, data)
                break
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        time.sleep(0.4)
    properties = data['response']['PropertyTable']['Properties'][0]
    expected = Chem.MolFromSmiles(smiles)
    actual = Chem.MolFromSmiles(properties['ConnectivitySMILES'])
    assert expected is not None and actual is not None, name
    assert Chem.MolToSmiles(expected) == Chem.MolToSmiles(actual), (name, properties)
    assert Chem.MolToInchiKey(expected) == properties['InChIKey'], name
    assert rdMolDescriptors.CalcMolFormula(expected) == properties['MolecularFormula'], name
    return item, properties, data['source_url']


def main():
    dest = ROOT / 'molecules'
    for sub in ['xyz', 'sdf', 'extxyz', 'vasp_vacuum']:
        (dest / sub).mkdir(parents=True, exist_ok=True)
    (ROOT / 'provenance' / 'pubchem').mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        identities = list(pool.map(identity, VOCS))
    catalog, combined_atoms, combined_mols = [], [], []
    for index, (item, properties, source_url) in enumerate(identities, 1):
        name, chinese, category, smiles = item
        label = f'{index:02d}_{name.replace(" ", "_")}'
        mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
        assert Chem.GetFormalCharge(mol) == 0
        assert sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms()) == 0
        assert AllChem.MMFFHasAllMoleculeParams(mol), name
        settings = AllChem.ETKDGv3()
        settings.randomSeed = 20261119 + index
        settings.numThreads = 2
        settings.pruneRmsThresh = 0.1
        ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=32, params=settings))
        assert ids, name
        energies = AllChem.MMFFOptimizeMoleculeConfs(mol, numThreads=2, maxIters=3000,
                                                   mmffVariant='MMFF94s')
        good = [(float(energy), cid) for cid, (status, energy) in zip(ids, energies)
                if status == 0 and np.isfinite(energy)]
        assert good, f'No converged conformer for {name}'
        energy, cid = min(good)
        selected = Chem.Mol(mol)
        selected.RemoveAllConformers()
        selected.AddConformer(Chem.Conformer(mol.GetConformer(cid)), assignId=True)
        conf = selected.GetConformer()
        coords = np.asarray(conf.GetPositions())
        coords -= coords.mean(axis=0)
        for i, point in enumerate(coords):
            conf.SetAtomPosition(i, point)
        assert np.isfinite(coords).all()
        assert len(Chem.GetMolFrags(selected)) == 1
        table = Chem.GetPeriodicTable()
        radii = np.array([table.GetRcovalent(a.GetAtomicNum()) for a in selected.GetAtoms()])
        distances = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=-1)
        pairs = np.triu_indices(len(coords), 1)
        minimum_ratio = float(np.min(distances[pairs] / (radii[:, None] + radii[None, :])[pairs]))
        assert minimum_ratio > 0.65, (name, minimum_ratio)
        selected.SetProp('_Name', label)
        record = dict(id=label, name=name, name_zh=chinese, category=category,
                      formula=properties['MolecularFormula'], canonical_smiles=Chem.MolToSmiles(Chem.RemoveHs(selected)),
                      inchi_key=properties['InChIKey'], pubchem_cid=properties['CID'],
                      pubchem_url=f'https://pubchem.ncbi.nlm.nih.gov/compound/{properties["CID"]}',
                      identity_source_url=source_url, atoms=selected.GetNumAtoms(), charge=0, multiplicity=1,
                      generation='RDKit ETKDGv3 + MMFF94s; minimum among converged sampled conformers',
                      seed=20261119 + index, requested_conformers=32, embedded_conformers=len(ids),
                      converged_conformers=len(good), selected_mmff_energy_kcal_mol=energy,
                      min_distance_over_covalent_radii=minimum_ratio,
                      xyz=f'molecules/xyz/{label}.xyz', sdf=f'molecules/sdf/{label}.sdf',
                      extxyz=f'molecules/extxyz/{label}.extxyz', vasp=f'molecules/vasp_vacuum/{label}.vasp')
        for key in ['formula', 'inchi_key', 'pubchem_cid', 'canonical_smiles', 'charge', 'multiplicity']:
            selected.SetProp(key, str(record[key]))
        selected.SetProp('MMFF94s_energy_kcal_mol', str(energy))
        with Chem.SDWriter(str(ROOT / record['sdf'])) as writer:
            writer.write(selected)
        atoms = Atoms([a.GetSymbol() for a in selected.GetAtoms()], positions=coords, pbc=False)
        atoms.info.update(name=name, id=label, pubchem_cid=properties['CID'],
                          smiles=record['canonical_smiles'], charge=0, multiplicity=1)
        write(ROOT / record['xyz'], atoms, format='xyz',
              comment=f'{label}; CID={properties["CID"]}; charge=0; multiplicity=1; ETKDGv3+MMFF94s')
        write(ROOT / record['extxyz'], atoms, format='extxyz')
        vacuum_atoms = atoms.copy()
        vacuum_atoms.set_cell(np.maximum(np.ptp(coords, axis=0) + 20.0, 25.0))
        vacuum_atoms.center()
        vacuum_atoms.pbc = True
        write(ROOT / record['vasp'], vacuum_atoms, format='vasp', direct=True, sort=True)
        roundtrip = Chem.SDMolSupplier(str(ROOT / record['sdf']), removeHs=False)[0]
        assert roundtrip is not None and roundtrip.GetNumAtoms() == len(atoms)
        assert rdMolDescriptors.CalcMolFormula(roundtrip) == record['formula']
        assert Chem.MolToInchiKey(Chem.RemoveHs(roundtrip)) == record['inchi_key']
        for fmt in ['xyz', 'extxyz', 'vasp']:
            parsed = read(ROOT / record[fmt])
            assert len(parsed) == record['atoms'] and np.isfinite(parsed.positions).all()
        record['sha256'] = {fmt: hashlib.sha256((ROOT / record[fmt]).read_bytes()).hexdigest()
                            for fmt in ['xyz', 'sdf', 'extxyz', 'vasp']}
        catalog.append(record)
        combined_atoms.append(atoms)
        combined_mols.append(selected)
        print(f'{label}: {record["formula"]}, CID {record["pubchem_cid"]}, '
              f'{len(good)}/{len(ids)} conformers converged', flush=True)
    assert len(catalog) == 30 and len({r['inchi_key'] for r in catalog}) == 30
    dump(dest / 'catalog.json', {'count': len(catalog), 'molecules': catalog})
    fields = ['id', 'name_zh', 'name', 'category', 'formula', 'canonical_smiles', 'pubchem_cid',
              'inchi_key', 'atoms', 'charge', 'multiplicity', 'xyz', 'sdf', 'extxyz', 'vasp', 'pubchem_url']
    with (dest / 'catalog.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(catalog)
    write(dest / 'all_voc.extxyz', combined_atoms, format='extxyz')
    write(dest / 'all_voc.xyz', combined_atoms, format='xyz')
    with Chem.SDWriter(str(dest / 'all_voc.sdf')) as writer:
        for molecule in combined_mols:
            writer.write(molecule)
    (dest / 'all_voc.smi').write_text(''.join(f'{r["canonical_smiles"]}\t{r["id"]}\n' for r in catalog))
    dump(dest / 'generation_versions.json', {p: importlib.metadata.version(p)
                                            for p in ['rdkit', 'numpy', 'ase', 'requests']})
    print('VOC library: 30/30 generated and identity/round-trip checked.', flush=True)


if __name__ == '__main__':
    main()
