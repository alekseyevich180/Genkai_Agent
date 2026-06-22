# Query electronic structure data by Materials Project ID

Args:
    api_key: Materials Project API key.
    material_id: Materials Project ID, e.g. "mp-149".
    include_band_structure: Whether to retrieve the default line-mode band structure.
    include_dos: Whether to retrieve density of states.
    download_path: Optional directory for saving band structure and DOS JSON files.

Returns:
    A dictionary containing band structure summary, DOS summary, saved file paths, and error messages.


```python
from typing import Dict, Any, Optional
import os
import traceback

from mp_api.client import MPRester
from pymatgen.electronic_structure.core import Spin
from monty.serialization import dumpfn


def query_electronic_structure(
    api_key: str,
    material_id: str,
    include_band_structure: bool = True,
    include_dos: bool = True,
    download_path: Optional[str] = None,
) -> Dict[str, Any]:

    result = {
        "success": False,
        "error": None,
        "material_id": material_id,
        "band_structure": None,
        "dos": None,
        "saved_files": {},
    }

    try:
        if download_path:
            os.makedirs(download_path, exist_ok=True)

        with MPRester(api_key) as mpr:

            # ------------------------------------------------------------
            # 1. Default line-mode high-symmetry band structure
            # ------------------------------------------------------------
            if include_band_structure:
                try:
                    bs = mpr.get_bandstructure_by_material_id(material_id)
                    band_gap_info = bs.get_band_gap()

                    result["band_structure"] = {
                        "available": True,
                        "band_path_type": "default_line_mode_high_symmetry",
                        "is_metal": bs.is_metal(),
                        "band_gap": band_gap_info.get("energy"),
                        "is_direct": band_gap_info.get("direct"),
                        "transition": band_gap_info.get("transition"),
                        "efermi": bs.efermi,
                    }

                    if download_path:
                        bs_path = os.path.join(
                            download_path,
                            f"{material_id}_band_structure.json",
                        )
                        dumpfn(bs, bs_path)
                        result["saved_files"]["band_structure"] = bs_path

                except Exception as bs_error:
                    result["band_structure"] = {
                        "available": False,
                        "error": f"Failed to retrieve band structure: {str(bs_error)}",
                    }

            # ------------------------------------------------------------
            # 2. Density of states
            # ------------------------------------------------------------
            if include_dos:
                try:
                    dos = mpr.get_dos_by_material_id(material_id)
                    normalized_dos = dos.get_normalized()

                    spin_polarized = Spin.down in dos.densities

                    result["dos"] = {
                        "available": True,
                        "efermi": dos.efermi,
                        "structure_volume": dos.structure.volume if dos.structure else None,
                        "spin_polarized": spin_polarized,
                        "normalized": True,
                    }

                    if download_path:
                        dos_path = os.path.join(
                            download_path,
                            f"{material_id}_dos.json",
                        )
                        norm_dos_path = os.path.join(
                            download_path,
                            f"{material_id}_normalized_dos.json",
                        )

                        dumpfn(dos, dos_path)
                        dumpfn(normalized_dos, norm_dos_path)

                        result["saved_files"]["dos"] = dos_path
                        result["saved_files"]["normalized_dos"] = norm_dos_path

                except Exception as dos_error:
                    result["dos"] = {
                        "available": False,
                        "error": f"Failed to retrieve DOS: {str(dos_error)}",
                    }

        result["success"] = True
        return result

    except Exception as e:
        result["success"] = False
        result["error"] = (
            f"Error querying electronic structure data from Materials Project: {str(e)}\n"
            f"{traceback.format_exc()}"
        )
        return result
```