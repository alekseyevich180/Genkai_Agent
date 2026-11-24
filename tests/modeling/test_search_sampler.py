import numpy as np
import optuna
import pytest

from genkai.modeling.surface.search_sampler import PeriodicGP, PeriodicGPSampler, make_sampler


def test_covariance_across_periodic_seam_and_unordered_sites():
    gp = PeriodicGP(seed=42, dimensions=2, periodic_axes=(0,), categorical_axes={1: 3})
    features = gp.features(np.array([
        [0.99, 1 / 6],
        [0.01, 1 / 6],
        [0.50, 1 / 6],
        [0.99, 1 / 2],
        [0.99, 5 / 6],
    ]))
    correlations = gp.covariance(features[:1], features, gp.log_scales)[0]
    assert correlations[0] == pytest.approx(1.0)
    assert correlations[1] > correlations[2]
    assert correlations[3] == pytest.approx(correlations[4])
    assert correlations[3] < correlations[0]


def test_mixed_optuna_search_reaches_periodic_gp_with_seeded_proposals(monkeypatch):
    fits = []
    suggest = PeriodicGP.suggest

    def record_fit(self, points, energies):
        fits.append((self.periodic_axes, self.categorical_axes, len(points)))
        return suggest(self, points, energies)

    monkeypatch.setattr(PeriodicGP, "suggest", record_fit)

    def sample():
        sampler = PeriodicGPSampler(seed=43, periodic=("azimuth",), categorical=("site",), n_startup_trials=4)
        study = optuna.create_study(sampler=sampler)
        for _ in range(7):
            trial = study.ask()
            angle = trial.suggest_float("azimuth", 0.0, 360.0)
            gap = trial.suggest_float("gap", 1.0, 3.0)
            site = trial.suggest_int("site", 2, 6, step=2)
            fixed = trial.suggest_int("fixed", 1, 1)
            assert 0.0 <= angle <= 360.0 and 1.0 <= gap <= 3.0
            assert site in (2, 4, 6) and fixed == 1
            study.tell(trial, 1 - np.cos(np.deg2rad(angle)) + (gap - 2) ** 2 + (site != 4))
        return [trial.params for trial in study.trials]

    assert sample() == sample()
    assert fits == [(frozenset({0}), {2: 3}, n) for n in (4, 5, 6, 4, 5, 6)]
    assert isinstance(make_sampler("tpe", seed=43), optuna.samplers.TPESampler)
