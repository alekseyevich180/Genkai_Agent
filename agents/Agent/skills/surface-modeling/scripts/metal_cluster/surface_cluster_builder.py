import argparse
import json
import sys
from pathlib import Path

from ase import Atoms
from ase.io import read, write

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
SCRIPTS_ROOT = SCRIPT_DIR.parent
for path in (REPO_ROOT, SCRIPTS_ROOT, SCRIPT_DIR):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

try:
    from cluster.metal.bcc import build_bcc110_bridge_cluster
    from cluster.metal.fcc import build_fcc111_cluster, resolve_fcc_rows
    from cluster.metal.hcp import build_hcp0001_cluster, parse_row_sequence as parse_hcp_rows
    from cluster.metal.cluster_builder import (
        build_nanocluster,
        resolve_cluster_element,
        resolve_lattice_constants,
    )
except ModuleNotFoundError:
    from bcc import build_bcc110_bridge_cluster
    from fcc import build_fcc111_cluster, resolve_fcc_rows
    from hcp import build_hcp0001_cluster, parse_row_sequence as parse_hcp_rows
    from cluster_builder import (
        build_nanocluster,
        resolve_cluster_element,
        resolve_lattice_constants,
    )

from surface.materials_project_slab import (
    download_stable_surface,
    fetch_bulk_structure,
    validate_surface_slab,
)


MP_SPACEGROUP_TO_CLUSTER_STRUCTURE = {
    "Im-3m": "bcc",
    "Fm-3m": "fcc",
    "P6_3/mmc": "hcp",
    "P63/mmc": "hcp",
}


def place_cluster_on_surface(
    slab: Atoms,
    cluster: Atoms,
    x_frac: float,
    y_frac: float,
    z_height: float,
    phi: float,
    theta: float,
    psi: float,
) -> Atoms:
    placed_cluster = cluster.copy()
    placed_cluster.euler_rotate(phi=phi, theta=theta, psi=psi)

    xy_position = (slab.cell.array.T @ [x_frac, y_frac, 0.0])[:2]
    slab_top_z = float(slab.positions[:, 2].max())
    cluster_bottom_z = float(placed_cluster.positions[:, 2].min())

    placed_cluster.translate(
        [
            float(xy_position[0]),
            float(xy_position[1]),
            slab_top_z + z_height - cluster_bottom_z,
        ]
    )
    return slab + placed_cluster


def get_geometric_center(atoms: Atoms):
    return atoms.positions.mean(axis=0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a metal cluster and optionally build/place it on a surface."
    )
    parser.add_argument("--surface", type=Path, default=None, help="Existing surface slab file readable by ASE; bulk cells are rejected.")
    parser.add_argument("--surface_formula", "--surface-formula", dest="surface_formula", default=None, help="Download this bulk formula from Materials Project and generate its stable-facet slab.")
    parser.add_argument("--surface_mp_id", "--surface-mp-id", dest="surface_mp_id", default=None, help="Download this Materials Project bulk entry and generate its stable-facet slab.")
    parser.add_argument("--surface_facet", "--surface-facet", dest="surface_facet", default=None, help="Explicit reviewed Miller index; otherwise use the stable-facet registry.")
    parser.add_argument("--slab_min_size", "--slab-min-size", dest="slab_min_size", type=float, default=12.0)
    parser.add_argument("--slab_vacuum", "--slab-vacuum", dest="slab_vacuum", type=float, default=15.0)
    parser.add_argument("--slab_repeat_xy", "--slab-repeat-xy", dest="slab_repeat_xy", default="2,2")
    parser.add_argument("--cluster_element", type=str, default=None, help="Metal element symbol, e.g. Pt.")
    parser.add_argument(
        "--cluster_bulk_file",
        type=Path,
        default=None,
        help="Optional elemental bulk CIF/structure file used to infer the metal and lattice scale.",
    )
    parser.add_argument(
        "--cluster_structures",
        nargs="+",
        default=None,
        choices=["fcc", "hcp", "bcc"],
        help="Target crystal structures to build.",
    )
    parser.add_argument(
        "--cluster_from_mp",
        "--cluster-from-mp",
        dest="cluster_from_mp",
        action="store_true",
        help="Download the elemental bulk reference from Materials Project and use its stable crystal structure/lattice.",
    )
    parser.add_argument("--cluster_mp_id", "--cluster-mp-id", dest="cluster_mp_id", default=None)
    parser.add_argument("--cluster_atoms", type=int, default=None, help="Target atom count for the cluster.")
    parser.add_argument("--cluster_layers", type=int, default=None, help="Number of radial shells to keep.")
    parser.add_argument("--cluster_radius", type=float, default=None, help="Cluster radius in Angstrom (legacy mode).")
    parser.add_argument("--stack_layers", type=int, default=None, help="Requested stacking layers for row-based bcc clusters.")
    parser.add_argument("--bcc_rows", type=int, default=None, help="Number of staggered rows for bcc {110} bridge clusters.")
    parser.add_argument(
        "--bcc_max_row_atoms",
        type=int,
        default=None,
        help="Maximum atom count in each long bottom row for bcc {110} bridge clusters.",
    )
    parser.add_argument("--cluster_a", type=float, default=None, help="Manual lattice constant a.")
    parser.add_argument("--cluster_c", type=float, default=None, help="Manual lattice constant c for hcp.")
    parser.add_argument("--fcc_rows", type=str, default=None, help="Bottom row sequence for fcc {111}, e.g. 4,3,2,1.")
    parser.add_argument(
        "--fcc_row_profile",
        type=str,
        default="auto",
        choices=["auto", "custom", "triangle", "hexagon", "trapezoid", "rectangle"],
        help="Bottom-layer fcc {111} row profile.",
    )
    parser.add_argument("--fcc_max_row_atoms", type=int, default=None, help="Maximum fcc bottom-row atom count.")
    parser.add_argument("--fcc_row_count", type=int, default=None, help="Number of fcc bottom rows.")
    parser.add_argument("--fcc_stacking_mode", type=str, default="ABC", choices=["ABC", "AB"], help="Compact stacking mode.")
    parser.add_argument("--fcc_layers", type=int, default=None, help="Number of fcc {111} stacking layers.")
    parser.add_argument("--hcp_rows", type=str, default=None, help="Bottom row sequence for hcp {0001}, e.g. 3,2,3.")
    parser.add_argument("--hcp_layers", type=int, default=1, help="Number of hcp {0001} stacking layers, ABAB.")
    parser.add_argument("--x_frac", type=float, default=0.5, help="Fractional x position on the slab cell.")
    parser.add_argument("--y_frac", type=float, default=0.5, help="Fractional y position on the slab cell.")
    parser.add_argument("--z_height", type=float, default=2.5, help="Initial gap between slab top and cluster bottom in Angstrom.")
    parser.add_argument("--phi", type=float, default=0.0, help="Euler rotation phi in degrees.")
    parser.add_argument("--theta", type=float, default=0.0, help="Euler rotation theta in degrees.")
    parser.add_argument("--psi", type=float, default=0.0, help="Euler rotation psi in degrees.")
    parser.add_argument("--output_dir", type=Path, default=Path("simple_cluster_on_surface_output"))
    args = parser.parse_args()

    surface_source_count = sum(value is not None for value in (args.surface, args.surface_formula, args.surface_mp_id))
    if surface_source_count > 1:
        raise ValueError("Use only one of --surface, --surface-formula, or --surface-mp-id.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    mp_surface_manifest = None
    surface_path = args.surface
    if args.surface_formula or args.surface_mp_id:
        repeat_xy = tuple(int(item) for item in args.slab_repeat_xy.split(","))
        if len(repeat_xy) != 2 or min(repeat_xy) < 1:
            raise ValueError("--slab-repeat-xy requires two positive integers, e.g. 2,2.")
        mp_surface_manifest = download_stable_surface(
            args.output_dir / "surface_inputs",
            formula=args.surface_formula,
            material_id=args.surface_mp_id,
            explicit_facet=args.surface_facet,
            min_slab_size=args.slab_min_size,
            min_vacuum_size=args.slab_vacuum,
            repeat_xy=repeat_xy,
        )
        surface_path = Path(mp_surface_manifest["files"]["surface_slab"])

    mp_cluster_metadata = None
    if args.cluster_from_mp or args.cluster_mp_id:
        if not args.cluster_element and not args.cluster_mp_id:
            raise ValueError("--cluster-from-mp requires --cluster-element unless --cluster-mp-id is supplied.")
        cluster_bulk, mp_cluster_metadata = fetch_bulk_structure(
            formula=args.cluster_element if not args.cluster_mp_id else None,
            material_id=args.cluster_mp_id,
        )
        cluster_bulk_path = args.output_dir / "cluster_bulk_from_materials_project.cif"
        cluster_bulk.to(filename=str(cluster_bulk_path), fmt="cif")
        args.cluster_bulk_file = cluster_bulk_path
        if not args.cluster_element:
            species = list(cluster_bulk.composition.as_dict())
            if len(species) != 1:
                raise ValueError("The selected cluster MP entry is not elemental; provide a reviewed cluster element.")
            args.cluster_element = species[0]
        if args.cluster_structures is None:
            spg = str(mp_cluster_metadata.get("spacegroup_symbol") or "")
            mapped_structure = MP_SPACEGROUP_TO_CLUSTER_STRUCTURE.get(spg)
            if not mapped_structure:
                raise ValueError(f"Cannot map Materials Project space group {spg!r} to fcc/hcp/bcc cluster mode.")
            args.cluster_structures = [mapped_structure]

    if args.cluster_structures is None:
        args.cluster_structures = ["fcc", "hcp", "bcc"]

    use_bcc_bridge = "bcc" in args.cluster_structures and args.bcc_rows is not None and args.bcc_max_row_atoms is not None
    use_hcp_rows = "hcp" in args.cluster_structures and args.hcp_rows is not None
    use_fcc_rows = (
        "fcc" in args.cluster_structures
        and args.fcc_layers is not None
        and (
            args.fcc_rows is not None
            or (
                args.fcc_row_profile != "custom"
                and args.fcc_row_profile != "auto"
                and args.fcc_max_row_atoms is not None
                and (args.fcc_row_profile in {"triangle", "hexagon"} or args.fcc_row_count is not None)
            )
        )
    )
    selected_modes = [args.cluster_atoms is not None, args.cluster_layers is not None, args.cluster_radius is not None]
    if not use_bcc_bridge and not use_fcc_rows and not use_hcp_rows and sum(selected_modes) != 1:
        raise ValueError("Provide exactly one of --cluster_atoms, --cluster_layers, or --cluster_radius.")
    if use_bcc_bridge and args.stack_layers is None:
        raise ValueError("bcc bridge clusters require --stack_layers.")

    element = resolve_cluster_element(args.cluster_element, args.cluster_bulk_file)
    slab = read(surface_path) if surface_path is not None else None
    slab_check = validate_surface_slab(slab) if slab is not None else None
    generated_files: list[str] = []

    size_tag = (
        f"bccrows{args.bcc_rows}_maxrow{args.bcc_max_row_atoms}_L{args.stack_layers}"
        if use_bcc_bridge
        else
        f"hcprows{args.hcp_rows.replace(',', '-')}_L{args.hcp_layers}"
        if use_hcp_rows
        else
        f"fccrows{args.fcc_rows.replace(',', '-')}_L{args.fcc_layers}_{args.fcc_stacking_mode}"
        if use_fcc_rows and args.fcc_rows is not None
        else
        f"fcc{args.fcc_row_profile}{args.fcc_max_row_atoms}x{args.fcc_row_count}_L{args.fcc_layers}_{args.fcc_stacking_mode}"
        if use_fcc_rows
        else
        f"atoms{args.cluster_atoms}"
        if args.cluster_atoms is not None
        else f"layers{args.cluster_layers}"
        if args.cluster_layers is not None
        else f"r{float(args.cluster_radius):.1f}"
    )

    for structure in args.cluster_structures:
        if structure == "hcp" and use_hcp_rows:
            lattice_a, lattice_c = resolve_lattice_constants(element, "hcp", args.cluster_a, args.cluster_c, bulk_file=args.cluster_bulk_file)
            bottom_rows = parse_hcp_rows(args.hcp_rows)
            cluster, _ = build_hcp0001_cluster(
                element=element,
                row_sequence=bottom_rows,
                layers=args.hcp_layers,
                lattice_a=lattice_a,
                lattice_c=lattice_c,
            )
        elif structure == "fcc" and use_fcc_rows:
            lattice_a, _ = resolve_lattice_constants(element, "fcc", args.cluster_a, None, bulk_file=args.cluster_bulk_file)
            bottom_rows = resolve_fcc_rows(
                rows_text=args.fcc_rows,
                row_profile=args.fcc_row_profile,
                max_row_atoms=args.fcc_max_row_atoms,
                row_count=args.fcc_row_count,
            )
            cluster, _ = build_fcc111_cluster(
                element=element,
                row_sequence=bottom_rows,
                layers=args.fcc_layers,
                lattice_a=lattice_a,
                stacking_mode=args.fcc_stacking_mode,
            )
        elif structure == "bcc" and use_bcc_bridge:
            lattice_a, _ = resolve_lattice_constants(element, "bcc", args.cluster_a, None, bulk_file=args.cluster_bulk_file)
            cluster, _, _ = build_bcc110_bridge_cluster(
                element=element,
                max_row_atoms=args.bcc_max_row_atoms,
                row_count=args.bcc_rows,
                layers=args.stack_layers,
                lattice_a=lattice_a,
            )
        else:
            cluster = build_nanocluster(
                element=element,
                structure=structure,
                atom_count=args.cluster_atoms,
                radius=args.cluster_radius,
                layers=args.cluster_layers,
                a=args.cluster_a,
                c=args.cluster_c,
                bulk_file=args.cluster_bulk_file,
            )
        cluster.positions -= get_geometric_center(cluster)

        prefix = args.output_dir / f"{element}_{structure}_{size_tag}"

        if slab is not None:
            combined = place_cluster_on_surface(
                slab=slab,
                cluster=cluster,
                x_frac=args.x_frac,
                y_frac=args.y_frac,
                z_height=args.z_height,
                phi=args.phi,
                theta=args.theta,
                psi=args.psi,
            )
            combined_path = prefix.with_name(prefix.name + "_on_surface").with_suffix(".cif")
            write(combined_path, combined)
            generated_files.append(str(combined_path))
            print(combined_path.name)
        else:
            cluster_path = prefix.with_name(prefix.name + "_cluster").with_suffix(".cif")
            write(cluster_path, cluster)
            generated_files.append(str(cluster_path))
            print(cluster_path.name)

    manifest = {
        "schema_version": "1.0",
        "task": "surface_cluster_builder",
        "inputs": {
            "surface": str(surface_path) if surface_path else None,
            "cluster_element": element,
            "cluster_structures": args.cluster_structures,
            "cluster_atoms": args.cluster_atoms,
            "cluster_layers": args.cluster_layers,
            "cluster_radius_A": args.cluster_radius,
        },
        "materials_project": {
            "surface": mp_surface_manifest["source"] if mp_surface_manifest else None,
            "cluster": mp_cluster_metadata,
            "api_key_persisted": False,
        },
        "facet": mp_surface_manifest["facet"] if mp_surface_manifest else {"selection_source": "existing_slab" if slab is not None else None},
        "checks": {
            "bulk_used_directly_for_loading": False if slab is not None else None,
            "surface_is_slab": slab_check,
            "cluster_size_resolved": args.cluster_atoms is not None or args.cluster_layers is not None or args.cluster_radius is not None,
        },
        "files": {"generated_models": generated_files},
    }
    manifest_path = args.output_dir / "modeling_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(manifest_path.name)


if __name__ == "__main__":
    main()
