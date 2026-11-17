from importlib.resources import files

from genkai.modeling.ptomodel import _load_surface_modeling_parameter_schema


def test_canonical_task_schema_is_owned_by_genkai() -> None:
    resource = files("genkai.modeling.schema").joinpath(
        "task_parameter_schema.json"
    )

    assert resource.is_file()
    registry = _load_surface_modeling_parameter_schema()
    assert registry["schema_version"] == "1.0"
    assert set(registry["tasks"]) == {
        "slab_generation",
        "vacancy_landscape",
        "adsorbate_landscape",
        "surface_cluster_builder",
        "surface_cluster_mlip_search",
    }
    assert registry["schema_path"] == (
        "genkai.modeling.schema:task_parameter_schema.json"
    )
    assert registry["schema_resource"] == (
        "genkai.modeling.schema:task_parameter_schema.json"
    )
    assert all(
        task["script"].startswith("genkai.modeling.surface.")
        for task in registry["tasks"].values()
    )


def test_energy_task_schemas_expose_mace_parameters() -> None:
    registry = _load_surface_modeling_parameter_schema()
    for name in ("slab_generation", "vacancy_landscape", "adsorbate_landscape", "surface_cluster_mlip_search"):
        parameters = registry["tasks"][name]["parameters"]
        assert "mace" in parameters["calculator"]["choices"]
        assert parameters["mace_model"]["type"] == "path"
        assert parameters["mace_dtype"]["choices"] == ["float32", "float64"]
