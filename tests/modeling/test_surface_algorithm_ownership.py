import importlib


def test_surface_algorithm_modules_have_library_owners() -> None:
    modules = (
        "genkai.modeling.surface.vacancy",
        "genkai.modeling.surface.adsorbate",
        "genkai.modeling.surface.materials_project_slab",
        "genkai.modeling.surface.cluster_search",
        "genkai.modeling.surface.metal_cluster.bcc",
        "genkai.modeling.surface.metal_cluster.fcc",
        "genkai.modeling.surface.metal_cluster.hcp",
        "genkai.modeling.surface.metal_cluster.cluster_builder",
        "genkai.modeling.surface.metal_cluster.surface_cluster_builder",
    )
    for name in modules:
        module = importlib.import_module(name)
        assert "/src/genkai/modeling/surface/" in str(module.__file__)


def test_deterministic_surface_helpers_are_available() -> None:
    from genkai.modeling.surface.adsorbate import maximum_non_overlapping_site_groups
    from genkai.modeling.surface.materials_project_slab import parse_miller_index
    from genkai.modeling.surface.vacancy import parse_vacancy_counts

    assert parse_vacancy_counts("1,2", oxygen_count=5) == [1, 2]
    assert maximum_non_overlapping_site_groups([(0, 1), (1, 2), (2, 3)]) == 2
    assert parse_miller_index("0,0,0,1") == (0, 0, 1)


def test_surface_cluster_builder_uses_library_slab_and_cluster_modules() -> None:
    from genkai.modeling.surface.metal_cluster import surface_cluster_builder

    assert surface_cluster_builder.place_cluster_on_surface
    assert surface_cluster_builder.get_geometric_center
