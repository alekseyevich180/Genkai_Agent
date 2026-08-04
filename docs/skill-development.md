# Stable skill development

Stable skills are decision and invocation layers over `src/genkai/`; they must
not maintain a second copy of domain rules. Temporary experiments remain under
`.workspace/skills/`, and candidate implementations may remain in built-in
skill `scripts/` until their artifact and failure boundaries are proven.

A stable `SKILL.md` frontmatter declares:

```yaml
metadata:
  maturity: stable
  domain: mlip
  tools: [run_skill_script]
  dependent_skills: []
  consumes: [dataset@1]
  produces: [model@1]
  entrypoints: [scripts/run.py]
```

The description must begin with `Use when` and state the trigger and adjacent
boundaries. `evaluations/cases.yaml` must contain non-empty `positive`,
`negative`, and `boundary` groups. Entrypoints must exist inside the skill
directory, and dependencies must name installed skills.

Run the contract checks before promotion:

```bash
pytest tests/skills/test_builtin_skill_contracts.py \
  tests/skills/test_skill_boundaries.py -v
```

Promotion also requires a successful path, a failure gate, formal artifact
inputs/outputs, no implicit working directory, and a validation report that
does not confuse dry-run with real scientific execution.
