"""Cluster bond lengths from the embedded metal data (regression for fcc/bcc lattice constants)."""

from __future__ import annotations

import numpy as np
import pytest

from genkai.modeling.surface.metal_cluster.cluster_builder import (
    METAL_DISTANCE_DATA,
    build_nanocluster,
    get_embedded_metal_radius,
    get_embedded_nearest_neighbor_distance,
    resolve_lattice_constants,
)


@pytest.mark.parametrize(
    ("element", "structure", "lattice_a"),
    [("Pt", "fcc", 3.92), ("Au", "fcc", 4.08), ("Fe", "bcc", 2.87), ("Ti", "hcp", 2.95)],
)
def test_embedded_nearest_neighbor_distance_gives_the_bulk_lattice_constant(element, structure, lattice_a) -> None:
    # METAL_DISTANCE_DATA stores nearest-neighbour distances; fcc/bcc builders need the cubic lattice constant.
    a, _ = resolve_lattice_constants(element, structure, None, None)
    assert a == pytest.approx(lattice_a, rel=0.03)


@pytest.mark.parametrize(("element", "structure"), [("Pt", "fcc"), ("Au", "fcc"), ("Fe", "bcc"), ("Ti", "hcp")])
def test_cluster_bond_lengths_match_the_embedded_nearest_neighbor_distance(element, structure) -> None:
    cluster = build_nanocluster(element, structure, atom_count=13)
    distances = cluster.get_all_distances()
    np.fill_diagonal(distances, np.inf)
    nn = METAL_DISTANCE_DATA[(element, structure)]["nn_distance"]
    assert len(cluster) == 13
    assert distances.min() == pytest.approx(nn, rel=0.03)
    assert get_embedded_nearest_neighbor_distance(element, structure) == pytest.approx(nn)
    assert get_embedded_metal_radius(element, structure) == pytest.approx(nn / 2.0)
