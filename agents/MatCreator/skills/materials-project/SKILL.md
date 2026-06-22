---
name: materials-project
description: Query Materials Project data for crystal structures, stability, electronic properties, phase diagrams.
---

# Materials Project Skill

This skill provides guidance for using the Materials Project API in MatCreator workflows. It is intended for querying known inorganic materials, retrieving crystal structures, checking thermodynamic stability, comparing generated candidates with known database entries.

The API key can be obtained from the `MP_API_KEY` environment variable or provided directly by the user.


## Search Materials Project for materials matching the given criteria

Search Materials Project for materials matching the given criteria.

Parameters:
    api_key: Materials Project API key.
    search_criteria: A dictionary of search criteria. Supported keys include:
        - material_id: str, Materials Project material ID, e.g. "mp-1234".
        - formula: str, chemical formula, e.g. "TiO2".
        - elements: List[str], list of required elements, e.g. ["Ti", "O"].
        - exclude_elements: List[str], list of elements to exclude.
        - band_gap: Tuple[float, float], band gap range (min, max) in eV, e.g. (1.0, 3.0).
        - energy_above_hull: Tuple[float, float], energy above hull range (min, max) in eV/atom.
        - num_sites: Tuple[int, int], number of atomic sites range (min, max).
        - spacegroup_number: int, space group number.
        - crystal_system: str, crystal system. One of "Triclinic", "Monoclinic", "Orthorhombic", "Tetragonal", "Trigonal", "Hexagonal", or "Cubic".
        - is_gap_direct: bool, whether the material has a direct band gap.
    download_path: Download path. If provided, the returned structure files will be saved.
    limit: Maximum number of returned results.

Returns:
    A dictionary containing the search results and download status.


```python
from typing import Dict, Any, Optional
import os
import traceback

from mp_api.client import MPRester
from pymatgen.core import Structure

def search_materials_project(
    api_key: str,
    search_criteria: Dict[str, Any],
    download_path: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    
    try:
        # 构建搜索条件
        search_params = {}
        
        # 化学式搜索
        if "formula" in search_criteria:
            search_params["formula"] = search_criteria["formula"]
        
        # 元素组成搜索
        if "elements" in search_criteria:
            elements = search_criteria["elements"]
            if isinstance(elements, list):
                search_params["elements"] = elements
        
        # 排除元素
        if "exclude_elements" in search_criteria:
            exclude_elements = search_criteria["exclude_elements"]
            if isinstance(exclude_elements, list):
                search_params["exclude_elements"] = exclude_elements
        
        # 带隙范围
        if "band_gap" in search_criteria:
            band_gap_range = search_criteria["band_gap"]
            if isinstance(band_gap_range, (tuple, list)) and len(band_gap_range) == 2:
                min_bg, max_bg = band_gap_range
                search_params["band_gap"] = (min_bg, max_bg)
            elif isinstance(band_gap_range, (int, float)):
                # 单值视为下限
                search_params["band_gap"] = (band_gap_range, None)
        
        # 形成能范围
        if "energy_above_hull" in search_criteria:
            energy_range = search_criteria["energy_above_hull"]
            if isinstance(energy_range,  (tuple, list)) and len(energy_range) == 2:
                search_params["energy_above_hull"] = tuple(energy_range)
        
        # 原子数范围
        if "num_sites" in search_criteria:
            nsites_range = search_criteria["num_sites"]
            if isinstance(nsites_range, (tuple, list)) and len(nsites_range) == 2:
                search_params["num_sites"] = tuple(nsites_range)
        
        # 空间群编号
        if "spacegroup_number" in search_criteria:
            search_params["spacegroup_number"] = search_criteria["spacegroup_number"]
        
        # 晶系
        if "crystal_system" in search_criteria:
            search_params["crystal_system"] = search_criteria["crystal_system"]
        
        # 直接带隙
        if "is_gap_direct" in search_criteria:
            search_params["is_gap_direct"] = search_criteria["is_gap_direct"]
        
        search_params["num_chunks"] = 1
        search_params["chunk_size"] = limit
        # 执行搜索
        try:
            with MPRester(api_key) as mpr:
                materials_data = mpr.materials.summary.search(
                    **search_params
                )
        except Exception as query_error:
            return {
                "success": False,
                "error": f"搜索Materials Project时出错: {str(query_error)}\n{traceback.format_exc()}",
                "materials": [],
                "count": 0,
                "search_criteria": search_criteria
            }
        # 限制结果数量
        if isinstance(materials_data, list):
            materials_data = materials_data[:limit]
        else:
            materials_data = [materials_data]
        
        if not materials_data:
            return {
                "success": False,
                "error": "未找到符合条件的材料",
                "materials": [],
                "count": 0,
                "search_criteria": search_criteria
            }

        # 处理搜索结果
        materials_list = []
        for material_data in materials_data:
            try:
                
                structure: Structure = material_data.structure
                if structure is None:
                    continue
                
                material_info = {
                    "material_id": material_data.material_id,
                    "formula": structure.composition.reduced_formula,
                    "band_gap": material_data.band_gap,
                    "energy_above_hull": material_data.energy_above_hull,
                    "is_gap_direct": material_data.is_gap_direct,
                }
                
                # 如果提供了下载路径，保存结构文件
                if download_path:
                    os.makedirs(download_path, exist_ok=True)
                    filename = f"{material_data.material_id}_{structure.composition.reduced_formula}.vasp"
                    filepath = os.path.join(download_path, filename)
                    structure.to(filename=filepath, fmt="poscar")
                    material_info["downloaded_file"] = filepath
                
                materials_list.append(material_info)
                
            except Exception as material_error:
                print(f"处理材料 {material_data.material_id} 时出错: {str(material_error)}")
                continue
        
        return {
            "success": True,
            "error": None,
            "materials": materials_list,
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"搜索Materials Project时出错: {str(e)}\n{traceback.format_exc()}",
            "materials": [],
            "search_criteria": search_criteria
        }
```


## Query electronic structure data by Materials Project ID

Query electronic structure data by Materials Project ID, including band structure and density of states.

For implementation details and example code, refer to [electronic-structure.md](assets/electronic-structure.md).


## Query charge density

Use this when the task requires charge density data from Materials Project, such as charge-density visualization, bonding analysis, or comparison with local DFT results.

Example: retrieve charge density for silicon `mp-149`.

```python
from mp_api.client import MPRester

mp_id = "mp-149"  # silicon

with MPRester() as mpr:
    chgcar = mpr.get_charge_density_from_material_id(mp_id)

chgcar.write_file("CHGCAR")
```



## Query phase diagram

Use this when the task requires thermodynamic phase stability information, competing phases, or phase-diagram-based analysis.

Example: retrieve a phase diagram for a chemical system.

```python
from mp_api.client import MPRester
from emmet.core.thermo import ThermoType

chemsys = "Li-Fe-O"

with MPRester() as mpr:
    phase_diagram = mpr.materials.thermo.get_phase_diagram_from_chemsys(
        chemsys=chemsys,
        thermo_type=ThermoType.GGA_GGA_U_R2SCAN,
    )

for entry in phase_diagram.stable_entries:
    print(entry.composition.reduced_formula, entry.energy_per_atom)
```