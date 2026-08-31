from pathlib import Path

from ase import Atoms
from ase.io import read, write

from genkai.modeling.surface import adsorbate


def _write_minimal_inputs(tmp_path: Path) -> tuple[Path, Path]:
    surface_path = tmp_path / "surface.cif"
    molecule_path = tmp_path / "H2.xyz"
    slab = Atoms(
        symbols=["Sn", "Sn", "O", "O"],
        positions=[
            [2.0, 2.0, 2.0],
            [7.0, 7.0, 2.0],
            [2.0, 7.0, 0.0],
            [7.0, 2.0, 0.0],
        ],
        cell=[10.0, 10.0, 15.0],
        pbc=[True, True, False],
    )
    hydrogen = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
    write(surface_path, slab)
    write(molecule_path, hydrogen)
    return surface_path, molecule_path


def test_programmatic_adsorbate_run_returns_generated_structures(
    tmp_path: Path, monkeypatch
) -> None:
    """Removing the programmatic runner must break real structure generation."""
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / ".matplotlib"))
    surface_path, molecule_path = _write_minimal_inputs(tmp_path)
    output_dir = tmp_path / "landscape"

    result = adsorbate.run_adsorbate_landscape(
        adsorbate.AdsorbateLandscapeConfig(
            surface=surface_path,
            molecule=molecule_path,
            output_dir=output_dir,
            site_symbols="Sn",
            coverage_counts="1",
            patterns="uniform,random",
            random_repeats=1,
            n_trials_single=1,
            calculator="none",
            max_steps=0,
            seed=42,
        )
    )

    assert isinstance(result, adsorbate.AdsorbateLandscapeResult)
    assert [path.name for path in result.structure_paths] == ["ads_1.cif", "ads_2.cif"]
    assert all(path.is_file() for path in result.structure_paths)
    assert [len(read(path)) for path in result.structure_paths] == [6, 6]
    assert result.csv_path.is_file()
    assert result.plot_path.is_file()
    assert result.best_candidate_path.is_file()
