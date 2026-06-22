---
name: abacus
description: Skill for executing ABACUS DFT materials calculations. Help users set up, run, and analyze ABACUS calculations.
metadata:
  tools: []
  dependent_skills: []
  tags:
    - DFT
    - ABACUS
---
Operate ABACUS safely with minimal steps and strict validation.

Must‑follow sequence
- `abacus_prepare` first to create an inputs directory (INPUT, STRU, pseudopotentials, orbitals).
- `check_abacus_input` to validate inputs BEFORE any calculation submission.
- Then run exactly ONE calculation tool per step.
- `collect_abacus_*_results` AFTER the corresponding calculation completes.

Rules
- Never pass raw structure files to property tools; always use the prepared inputs directory.
- Confirm critical parameters with the user; prefer plane‑wave basis unless the user requests otherwise.
- If inputs are missing or invalid, stop and request the minimal fix.
- Never invent tools; only call from the allowlist.

Outputs
- Report absolute paths and essential metrics (e.g., final energy). Keep summaries tight and actionable.
