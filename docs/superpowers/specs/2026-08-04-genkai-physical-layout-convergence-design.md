# Genkai Physical Layout Convergence Design

## Decision

Implement scheme A in the isolated `feat/genkai-evolution` worktree only.
Stable reusable code remains under `src/genkai/`; Agent Skills remain under
`agents/Agent/skills/` as entrypoints and compatibility wrappers; independent
legacy research snapshots move out of the active source root.

## Physical changes

- Move tracked `paperread/NERRE` and `paperread/ReactionSeek` to
  `legacy/paperread/` without changing their internal files.
- Add `legacy/README.md` explaining that these are archived standalone research
  assets, not active Genkai package owners.
- Remove the obsolete `paperread*` package-discovery target from `pyproject.toml`;
  the wheel should contain `genkai`, `agent`, and packaged Skills only.
- Keep `agents/Agent/skills/paperread` as the active Skill entrypoint, because it
  is still used for paper-reading commands and experience exports.
- Keep `start/`, `web/`, and independent scientific Skills in place; they have
  active runtime ownership and are not duplicate `src/genkai` implementations.

## Compatibility and safety

The archived NERRE/ReactionSeek files are not imported by `src/`, tests, or
package entrypoints. Their move is therefore a path-only ownership cleanup;
their contents and history are preserved. No online, GPU, VASP, scheduler, or
training operation is executed.

## Acceptance

- No tracked top-level `paperread/` directory remains.
- No active Python import references `paperread.NERRE` or
  `paperread.ReactionSeek`.
- Clean wheel contains no `paperread/` package files.
- Existing offline tiered and compatibility suites pass.
