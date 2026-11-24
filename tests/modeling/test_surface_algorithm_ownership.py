import importlib
from pathlib import Path


def test_surface_algorithm_modules_have_library_owners() -> None:
    modules = (
        "genkai.modeling.surface.builders.slab",
        "genkai.modeling.surface.builders.vacancy",
        "genkai.modeling.surface.builders.adsorbate",
        "genkai.modeling.surface.builders.materials_project_slab",
        "genkai.modeling.surface.screening.cluster_search",
        "genkai.modeling.surface.builders.metal_cluster.bcc",
        "genkai.modeling.surface.builders.metal_cluster.fcc",
        "genkai.modeling.surface.builders.metal_cluster.hcp",
        "genkai.modeling.surface.builders.metal_cluster.cluster_builder",
        "genkai.modeling.surface.builders.metal_cluster.surface_cluster_builder",
        "genkai.modeling.surface.structure_io",
        "genkai.modeling.surface.builders.sites",
        "genkai.modeling.surface.builders.substrate",
        "genkai.modeling.surface.builders.sam",
        "genkai.modeling.surface.builders.amorphous_overlayer",
        "genkai.modeling.surface.builders.amorphous_slab",
        "genkai.modeling.surface.builders.amorphous_bulk",
        "genkai.modeling.surface.mlip.calculators",
        "genkai.modeling.surface.screening.sam_search",
        "genkai.modeling.surface.screening.amorphous_screen",
        "genkai.modeling.surface.app.jobs",
    )
    for name in modules:
        module = importlib.import_module(name)
        # as_posix keeps the ownership check portable to Windows paths.
        assert "/src/genkai/modeling/surface/" in Path(module.__file__).as_posix()


def test_deterministic_surface_helpers_are_available() -> None:
    from genkai.modeling.surface.builders.adsorbate import maximum_non_overlapping_site_groups
    from genkai.modeling.surface.builders.materials_project_slab import parse_miller_index
    from genkai.modeling.surface.builders.vacancy import parse_vacancy_counts

    assert parse_vacancy_counts("1,2", oxygen_count=5) == [1, 2]
    assert maximum_non_overlapping_site_groups([(0, 1), (1, 2), (2, 3)]) == 2
    assert parse_miller_index("0,0,0,1") == (0, 0, 1)


def test_surface_cluster_builder_uses_library_slab_and_cluster_modules() -> None:
    from genkai.modeling.surface.builders.metal_cluster import surface_cluster_builder

    assert surface_cluster_builder.place_cluster_on_surface
    assert surface_cluster_builder.get_geometric_center
