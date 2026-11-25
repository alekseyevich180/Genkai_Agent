#!/usr/bin/env python3
"""Retrieve selected MP records from official, versioned public Parquet data."""
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

import duckdb
import numpy as np
from ase.io import read, write
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.io.cif import CifWriter
from pymatgen.io.vasp import Poscar
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

ROOT = Path(__file__).resolve().parent
SOURCE = ('https://materialsproject-build.s3.amazonaws.com/collections/summary/'
          'version=2026-09-28/part-00000-2cc5f2cc-2a79-4051-b013-2f9dec6a302e-c000.zstd.parquet')
VERSION = '2026-09-28'
# Formula, class, phase, exact current MP identifier. Core entries require E_hull=0,
# is_stable=True, theoretical=False and at least one ICSD cross-reference.
SELECTION = [
    ('MgO', 'oxide', 'rocksalt', 'mp-aaaaabwr'),
    ('ZnO', 'oxide', 'wurtzite', 'mp-aaaaadeb'),
    ('TiO2', 'oxide', 'anatase', 'mp-aaaaaapa'),
    ('SnO2', 'oxide', 'cassiterite_rutile', 'mp-aaaaabgy'),
    ('CeO2', 'oxide', 'fluorite', 'mp-aaaabdws'),
    ('NiO', 'oxide', 'rocksalt', 'mp-aaaabcdd'),
    ('Al2O3', 'A2O3', 'alpha_corundum', 'mp-aaaaabrz'),
    ('Fe2O3', 'A2O3', 'alpha_hematite', 'mp-aaaabdgk'),
    ('Cr2O3', 'A2O3', 'corundum', 'mp-aaaabcsd'),
    ('SiO2', 'oxide', 'alpha_quartz', 'mp-aaaaakjg'),
    ('In2O3', 'A2O3', 'bixbyite', 'mp-aaaabhle'),
    ('CdS', 'sulfide', 'wurtzite', 'mp-aaaaaazw'),
    ('MoS2', 'sulfide', '3R', 'mp-aaaaacde'),
    ('WS2', 'sulfide', '2H', 'mp-aaaaaaiq'),
    ('SnS', 'sulfide', 'orthorhombic', 'mp-aaaaadhv'),
    ('SnS2', 'sulfide', 'CdI2_type', 'mp-aaaaabta'),
    ('FeS2', 'sulfide', 'marcasite', 'mp-aaaaacgo'),
    ('CaTiO3', 'perovskite_ABO3', 'orthorhombic', 'mp-aaaaafyp'),
    ('BaTiO3', 'perovskite_ABO3', 'orthorhombic', 'mp-aaaaaiof'),
    ('LaCrO3', 'perovskite_ABO3', 'orthorhombic', 'mp-aaaabcnp'),
    ('SrZrO3', 'perovskite_ABO3', 'orthorhombic', 'mp-aaaaagmt'),
    ('KNbO3', 'perovskite_ABO3', 'rhombohedral', 'mp-aaaaakxr'),
    ('NaNbO3', 'perovskite_ABO3', 'rhombohedral', 'mp-aaaaagrq'),
    ('MgAl2O4', 'spinel_AB2O4', 'cubic', 'mp-aaaaafga'),
    ('ZnAl2O4', 'spinel_AB2O4', 'cubic', 'mp-aaaaaehw'),
    ('MgCr2O4', 'spinel_AB2O4', 'cubic', 'mp-aaaabcko'),
    ('ZnCr2O4', 'spinel_AB2O4', 'cubic', 'mp-aaaabcso'),
    ('FeAl2O4', 'spinel_AB2O4', 'hercynite', 'mp-aaaabsnc'),
    ('MgFe2O4', 'spinel_AB2O4', 'cubic_ordered_MP_model', 'mp-aaabiplg'),
    ('ZnFe2O4', 'spinel_AB2O4', 'cubic', 'mp-aaaabcov'),
    ('CaCu2O3', 'AB2O3_reference', 'pseudo_ladder', 'mp-aaaaalbe'),
    ('SrCu2O3', 'AB2O3_reference', 'two_leg_ladder', 'mp-aaaaaiuk'),
]


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def without_null_fields(value):
    # Parquet's shared schema inserts fields absent from the original object,
    # including oxidation_state=null. Pymatgen treats its presence as Species
    # rather than Element, so remove schema-only null fields before decoding.
    if isinstance(value, dict):
        return {key: without_null_fields(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [without_null_fields(item) for item in value]
    return value


def numeric_alias(mpid):
    token = mpid.removeprefix('mp-')
    if token.isdigit():
        return mpid
    value = 0
    for char in token:
        value = value * 26 + ord(char) - ord('a')
    return f'mp-{value}'


def fetch_records():
    provenance = ROOT / 'provenance'
    provenance.mkdir(exist_ok=True)
    cache = provenance / 'mp_selected_summaries.json'
    if cache.exists():
        payload = json.loads(cache.read_text())
        assert payload['source_url'] == SOURCE
        return payload['records']
    conn = duckdb.connect()
    conn.execute('SET threads=2')
    conn.execute("SET memory_limit='1GB'")
    print('Retrieving 32 selected MP summary documents, including original structures...', flush=True)
    # DuckDB issues HTTP range requests and applies the identifier filter.
    records = [json.loads(row[0]) for row in conn.execute(
        'SELECT to_json(t) FROM read_parquet(?) AS t WHERE material_id IN (SELECT unnest(?))',
        [SOURCE, [r[3] for r in SELECTION]]).fetchall()]
    assert len(records) == len(SELECTION), (len(records), len(SELECTION))
    dump(cache, {'source_url': SOURCE, 'database_version': VERSION,
                 'retrieved_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                 'records': records})
    return records


def main():
    records = {r['material_id']: r for r in fetch_records()}
    catalog = []
    matcher = StructureMatcher(ltol=1e-5, stol=1e-5, angle_tol=0.001,
                               primitive_cell=False, scale=False)
    for index, (formula, category, phase, material_id) in enumerate(SELECTION, 1):
        doc = records[material_id]
        supplemental = category == 'AB2O3_reference'
        group = 'ab2o3_reference' if supplemental else 'stable'
        destination = ROOT / 'crystals' / group
        for sub in ['cif', 'vasp', 'extxyz', 'conventional_cif', 'metadata']:
            (destination / sub).mkdir(parents=True, exist_ok=True)
        assert doc['deprecated'] is False and doc['theoretical'] is False
        assert doc['database_IDs'].get('icsd'), material_id
        if not supplemental:
            assert doc['is_stable'] is True and abs(doc['energy_above_hull']) < 1e-8, material_id
        else:
            assert doc['is_stable'] is False and 0 < doc['energy_above_hull'] < 0.05
        structure = Structure.from_dict(without_null_fields(doc['structure']))
        assert structure.is_ordered
        assert len(structure) == doc['nsites']
        assert structure.composition.reduced_composition == Composition(formula).reduced_composition
        assert np.isfinite(structure.cart_coords).all()
        assert np.isfinite(structure.lattice.matrix).all() and structure.volume > 0
        distances = structure.distance_matrix
        np.fill_diagonal(distances, np.inf)
        minimum_distance = float(distances.min())
        assert minimum_distance > 0.7, (formula, minimum_distance)
        alias = numeric_alias(material_id)
        label = f'{index:02d}_{formula}_{phase}_{alias}'
        paths = {fmt: str((destination / folder / f'{label}.{extension}').relative_to(ROOT))
                 for fmt, folder, extension in [('cif', 'cif', 'cif'), ('vasp', 'vasp', 'vasp'),
                                                 ('extxyz', 'extxyz', 'extxyz'),
                                                 ('conventional_cif', 'conventional_cif', 'cif')]}
        # These three files retain the actual MP relaxed cell/coordinates. CIF is P1
        # with all atoms explicit, avoiding rounding or symmetry refinement.
        CifWriter(structure, symprec=None, significant_figures=10).write_file(ROOT / paths['cif'])
        Poscar(structure, comment=f'{formula} | {material_id} | MP {VERSION}').write_file(ROOT / paths['vasp'])
        atoms = AseAtomsAdaptor.get_atoms(structure)
        # Arbitrary site properties can contain nested values not representable in
        # extxyz. Full original properties remain in the MP JSON document.
        for key in list(atoms.arrays):
            if key not in ('numbers', 'positions'):
                del atoms.arrays[key]
        atoms.info.clear()
        atoms.info.update(material_id=material_id, legacy_numeric_id=alias, formula=formula,
                          mp_is_stable=bool(doc['is_stable']), energy_above_hull_eV_atom=doc['energy_above_hull'])
        atoms.pbc = True
        write(ROOT / paths['extxyz'], atoms, format='extxyz')
        analyzer = SpacegroupAnalyzer(structure, symprec=0.1, angle_tolerance=5)
        conventional = analyzer.get_conventional_standard_structure()
        CifWriter(conventional, symprec=None, significant_figures=10).write_file(ROOT / paths['conventional_cif'])
        assert conventional.composition.reduced_composition == structure.composition.reduced_composition
        for fmt in ['cif', 'vasp']:
            recovered = Structure.from_file(ROOT / paths[fmt])
            assert matcher.fit(structure, recovered), (formula, fmt)
        recovered_atoms = read(ROOT / paths['extxyz'])
        assert recovered_atoms.pbc.all() and len(recovered_atoms) == len(structure)
        assert np.allclose(recovered_atoms.cell.array, structure.lattice.matrix, atol=1e-7)
        assert np.allclose(recovered_atoms.positions, structure.cart_coords, atol=1e-7)
        record = dict(id=label, formula=formula, mp_formula=doc['formula_pretty'], category=category,
                      collection=group, phase=phase, material_id=material_id, legacy_numeric_id=alias,
                      mp_url=f'https://materialsproject.org/materials/{material_id}', database_version=VERSION,
                      is_stable=bool(doc['is_stable']), energy_above_hull_eV_atom=doc['energy_above_hull'],
                      stability_label='MP_hull_stable' if not supplemental else 'experimental_near_hull_reference_NOT_hull_stable',
                      theoretical=bool(doc['theoretical']), icsd_ids=doc['database_IDs']['icsd'],
                      mp_spacegroup=doc['symmetry']['symbol'], mp_spacegroup_number=doc['symmetry']['number'],
                      detected_spacegroup=analyzer.get_space_group_symbol(), atoms=len(structure),
                      conventional_atoms=len(conventional), volume_A3=structure.volume,
                      density_g_cm3=structure.density, minimum_periodic_distance_A=minimum_distance,
                      cell_parameters_A_deg=list(structure.lattice.abc) + list(structure.lattice.angles),
                      source_url=SOURCE, structure_source='Materials Project DFT-relaxed structure, unmodified cell',
                      conventional_transform='pymatgen conventional standard cell; symprec=0.1 A; may symmetrize positions',
                      source_warnings=doc.get('warnings', []), license=doc.get('builder_meta', {}).get('license'),
                      **paths)
        record['sha256'] = {fmt: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                            for fmt, path in paths.items()}
        metadata = destination / 'metadata' / f'{label}.json'
        record['metadata'] = str(metadata.relative_to(ROOT))
        dump(metadata, {'catalog_record': record, 'original_mp_summary': doc})
        catalog.append(record)
        print(f'{label}: {record["mp_spacegroup"]}, E_hull={1000*doc["energy_above_hull"]:.4f} meV/atom, '
              f'MP stable={doc["is_stable"]}, {len(structure)} atoms', flush=True)
    assert len(catalog) == 32
    assert len({r['material_id'] for r in catalog}) == 32
    dest = ROOT / 'crystals'
    dump(dest / 'catalog.json', {'database_version': VERSION, 'stable_count': 30,
                                'ab2o3_reference_count': 2, 'crystals': catalog})
    fields = ['id', 'formula', 'category', 'collection', 'phase', 'material_id', 'legacy_numeric_id',
              'mp_spacegroup', 'is_stable', 'energy_above_hull_eV_atom', 'theoretical',
              'atoms', 'conventional_atoms', 'cif', 'vasp', 'extxyz', 'conventional_cif', 'mp_url']
    with (dest / 'catalog.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(catalog)
    dump(dest / 'generation_versions.json', {p: importlib.metadata.version(p)
                                            for p in ['pymatgen', 'pymatgen-core', 'duckdb', 'ase', 'numpy', 'spglib']})
    print('Crystal library: 30 hull-stable + 2 labeled AB2O3 references; all round-trip checked.', flush=True)


if __name__ == '__main__':
    main()
