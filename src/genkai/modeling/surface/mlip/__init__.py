"""Energy models and search samplers shared by the builders and the screening searches.

- ``calculators``: calculator construction (none / emt / mace / uma), UMA task-head checks and
  evidence levels.
- ``search_sampler``: Optuna samplers (TPE and the shared periodic GP).
- ``mlip_config``: ``genkai.yaml`` profiles, MLIP Python environments and model-free checks.

Depends only on ``genkai.modeling.surface.structure_io``; it must not import builders, screening or app.
"""
