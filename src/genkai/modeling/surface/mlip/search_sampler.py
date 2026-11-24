"""Periodic Matérn search for surface translations, orientations, and site choices."""

from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Iterable

import numpy as np
from optuna.distributions import CategoricalDistribution, FloatDistribution, IntDistribution
from optuna.samplers import BaseSampler, RandomSampler, TPESampler
from optuna.search_space import IntersectionSearchSpace
from optuna.study import StudyDirection
from optuna.trial import TrialState
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize
from scipy.spatial.distance import cdist
from scipy.special import ndtr
from scipy.stats import qmc


DEFAULT_SAMPLER = "periodic_gp"
SAMPLERS = (DEFAULT_SAMPLER, "tpe")


def add_sampler_argument(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--sampler", choices=SAMPLERS, default=DEFAULT_SAMPLER,
        help=f"Search optimizer (default: {DEFAULT_SAMPLER}).",
    )


def make_sampler(
    name: str, *, seed: int | None = None, periodic: Iterable[str] = (), categorical: Iterable[str] = (),
) -> BaseSampler:
    if name == DEFAULT_SAMPLER:
        return PeriodicGPSampler(seed=seed, periodic=periodic, categorical=categorical)
    if name == "tpe":
        return TPESampler(seed=seed)
    raise ValueError(f"Unknown sampler {name!r}; choose from {', '.join(SAMPLERS)}.")


def sobol(count: int, seed: int, dimensions: int) -> np.ndarray:
    engine = qmc.Sobol(d=dimensions, scramble=True, rng=np.random.default_rng(seed))
    return engine.random_base2((count - 1).bit_length())[:count]


class PeriodicGP:
    """Fit Matérn 5/2 scales and maximize expected improvement over Sobol points."""

    def __init__(self, seed, dimensions, periodic_axes, categorical_axes=None):
        self.rng = np.random.default_rng(seed)
        self.log_scales = np.full(dimensions, np.log(0.3))
        self.periodic_axes = frozenset(periodic_axes)
        self.categorical_axes = dict(categorical_axes or {})
        self.scale_axes = np.repeat(np.arange(dimensions), [1 + (i in self.periodic_axes) for i in range(dimensions)])
        categorical = np.isin(self.scale_axes, list(self.categorical_axes))
        self.category_columns = np.flatnonzero(categorical)
        self.numeric_columns = ~categorical

    def features(self, points):
        columns = []
        for axis, coordinate in enumerate(points.T):
            if axis in self.periodic_axes:
                angle = 2 * np.pi * coordinate
                columns.extend((0.5 * np.cos(angle), 0.5 * np.sin(angle)))
            elif axis in self.categorical_axes:
                count = self.categorical_axes[axis]
                columns.append(np.minimum(np.floor(coordinate * count), count - 1))
            else:
                columns.append(coordinate)
        return np.column_stack(columns)

    def covariance(self, left, right, log_scales):
        scales = np.exp(log_scales)[self.scale_axes]
        if self.category_columns.size:
            numeric = self.numeric_columns
            squared = cdist(left[:, numeric] / scales[numeric], right[:, numeric] / scales[numeric], "sqeuclidean")
            for column in self.category_columns:
                squared += (left[:, column, None] != right[:, column]) / scales[column] ** 2
            distance = np.sqrt(5.0 * squared)
        else:
            distance = np.sqrt(5.0) * cdist(left / scales, right / scales)
        return (1.0 + distance + distance**2 / 3.0) * np.exp(-distance)

    def suggest(self, points, energies):
        x = self.features(np.asarray(points))
        y = np.asarray(energies)
        y = (y - y.mean()) / max(float(y.std()), 1e-8)
        noise = 1e-4 * np.eye(len(y))

        def factor(scales):
            return cho_factor(self.covariance(x, x, scales) + noise, lower=True, check_finite=False)

        def loss(scales):
            chol = factor(scales)
            penalty = 0.1 * np.square(scales - np.log(0.3)).sum()
            return 0.5 * y @ cho_solve(chol, y) + np.log(np.diag(chol[0])).sum() + penalty

        fit = minimize(loss, self.log_scales, method="L-BFGS-B",
                       bounds=[(np.log(0.03), np.log(4.0))] * len(self.log_scales))
        if np.isfinite(fit.fun) and fit.fun <= loss(self.log_scales):
            self.log_scales = fit.x
        chol = factor(self.log_scales)
        pool = sobol(1024, int(self.rng.integers(0, 2**32)), len(self.log_scales))
        cross = self.covariance(x, self.features(pool), self.log_scales)
        mean = cross.T @ cho_solve(chol, y)
        std = np.sqrt(np.maximum(1.0 - (cross * cho_solve(chol, cross)).sum(axis=0), 1e-12))
        improvement = y.min() - mean
        z = improvement / std
        expected = improvement * ndtr(z) + std * np.exp(-0.5 * z**2) / np.sqrt(2 * np.pi)
        return pool[int(expected.argmax())]


def _discrete_count(distribution):
    if isinstance(distribution, CategoricalDistribution):
        return len(distribution.choices)
    if isinstance(distribution, IntDistribution):
        return (distribution.high - distribution.low) // distribution.step + 1
    return 0


def _encode(value, distribution):
    if isinstance(distribution, CategoricalDistribution):
        return (distribution.to_internal_repr(value) + 0.5) / len(distribution.choices)
    if isinstance(distribution, IntDistribution):
        return ((value - distribution.low) // distribution.step + 0.5) / _discrete_count(distribution)
    return (value - distribution.low) / (distribution.high - distribution.low)


def _decode(value, distribution):
    if isinstance(distribution, FloatDistribution):
        return float(distribution.low + value * (distribution.high - distribution.low))
    index = min(int(value * _discrete_count(distribution)), _discrete_count(distribution) - 1)
    if isinstance(distribution, CategoricalDistribution):
        return distribution.choices[index]
    return distribution.low + index * distribution.step


class PeriodicGPSampler(BaseSampler):
    """Fit the benchmark GP to the stable joint space of an Optuna study."""

    def __init__(self, *, seed=None, periodic=(), categorical=(), n_startup_trials=8):
        if n_startup_trials < 2:
            raise ValueError("At least two startup trials are required.")
        self._rng = np.random.default_rng(seed)
        self._independent = RandomSampler(seed=seed)
        self._intersection = IntersectionSearchSpace()
        self._periodic = frozenset(periodic)
        self._categorical = frozenset(categorical)
        self._startup = n_startup_trials
        self._space = None
        self._gp = None
        self._starts = None

    def infer_relative_search_space(self, study, trial):
        return {
            name: dist
            for name, dist in self._intersection.calculate(study).items()
            if not dist.single() and (
                isinstance(dist, CategoricalDistribution)
                or (isinstance(dist, IntDistribution) and name in self._categorical and not dist.log)
                or (isinstance(dist, FloatDistribution) and not dist.log and dist.step is None)
            )
        }

    def sample_independent(self, study, trial, param_name, param_distribution):
        return self._independent.sample_independent(study, trial, param_name, param_distribution)

    def reseed_rng(self):
        self._independent.reseed_rng()
        self._rng = np.random.default_rng()
        self._space = None

    def sample_relative(self, study, trial, search_space):
        if not search_space:
            return {}
        space = tuple(search_space.items())
        if space != self._space:
            categories = {
                i: _discrete_count(dist) for i, (_, dist) in enumerate(space)
                if isinstance(dist, (CategoricalDistribution, IntDistribution))
            }
            periodic_axes = [
                i for i, (name, dist) in enumerate(space)
                if name in self._periodic and isinstance(dist, FloatDistribution)
            ]
            self._gp = PeriodicGP(int(self._rng.integers(0, 2**32)), len(space), periodic_axes, categories)
            self._starts = sobol(self._startup, int(self._rng.integers(0, 2**32)), len(space))
            self._space = space
        trials = [t for t in study.get_trials(deepcopy=False, states=(TrialState.COMPLETE,)) if np.isfinite(t.value)]
        if len(trials) < self._startup:
            point = self._starts[len(trials)]
        else:
            sign = -1 if study.direction == StudyDirection.MAXIMIZE else 1
            if len(trials) > 96:
                # Keep recent trials and the best earlier ones to bound the cost of an exact GP fit.
                trials = sorted(trials[:-48], key=lambda t: sign * t.value)[:48] + trials[-48:]
            points = [[_encode(t.params[name], dist) for name, dist in space] for t in trials]
            point = self._gp.suggest(points, [sign * t.value for t in trials])
        return {name: _decode(value, dist) for value, (name, dist) in zip(point, space, strict=True)}
