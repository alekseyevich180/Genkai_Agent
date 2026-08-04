# Genkai Structure Baseline

Measured on 2026-08-03 in the `Genkai_Evolution` linked worktree at commit
`9837c19`, before Task 10–11 production-code changes.

## Worktree and validation baseline

- Branch: `feat/genkai-evolution`
- Related baseline regressions: 97 passed, 16 subtests passed
- Warnings: 42 existing ASE, spglib, and Google ADK deprecation warnings
- Bare `pytest` is not on the login-shell `PATH`; validation uses
  `../.venv/bin/python -m pytest`.

## Top-level directories

```text
.github
.pytest_cache
Genkai.egg-info
agents
build
data
docs
paperread
src
start
tests
web
work_logs
```

`.pytest_cache`, `Genkai.egg-info`, and `build` are local/generated state rather
than target architecture components.

## Stable Genkai packages

The source tree already contains these first-level packages under
`src/genkai/`:

```text
compute
contracts
datasets
literature
mlip
modeling
skills
workflow
workflows
```

Before convergence, `src/genkai/literature/` contains only `__init__.py` and
the single-file `surface.py` saved-extraction facade.

## Legacy surface ownership

Before convergence, `paperread/surface/` owns:

```text
core
examples
experience
experience/material_classes
extraction
modeling
pipeline
```

It also owns package-level `__init__.py`, `__main__.py`, `cli.py`, and
`README.md`. The canonical material-class store contains 20 JSON files.

## Reverse dependency baseline

At the 2026-08-03 baseline, two `src/genkai -> paperread` imports existed and
were deferred to Task 12:

```text
src/genkai/modeling/ptomodel.py
  -> paperread.surface.modeling.job_bundle.build_modeling_checklist
  -> paperread.surface.modeling.ptomodel.build_ptomodel_payload
```

No `src/genkai -> agents.Agent.skills` Python import existed. Architecture
tests encoded the two entries above as an exact allowlist that could not grow;
`src/genkai/literature/` received no exception.

The 2026-08-04 PToModel convergence slice removed both imports and the legacy
`paperread/surface/modeling/` owner. The architecture gate now uses an empty
allowlist; this section retains the measured pre-migration baseline.

## CLI baseline

`pyproject.toml` declares:

```text
agent = agent.init.start_agent:main
genkai-workflow = genkai.cli:main
```

The old surface package separately provides `python -m paperread.surface`.

## Wheel baseline

The source baseline wheel was built offline with:

```bash
../.venv/bin/python -m pip wheel --no-build-isolation --no-deps \
  --wheel-dir /tmp/genkai_baseline_wheel .
```

Measured wheel contents:

- total archive entries: 274
- `paperread/surface/**/*.py`: 26
- `genkai/literature/**`: 2
- packaged surface material-class JSON files: 0 of 20
- console scripts: `agent`, `genkai-workflow`

Task 11 must reverse the production-code ownership and package all 20 canonical
JSON assets without introducing another console-script name.
