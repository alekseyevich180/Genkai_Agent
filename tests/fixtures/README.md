# Test fixture inventory

This directory contains deterministic, offline test inputs. No fixture is
evidence of a completed scientific calculation.

| Path | Source/provenance | Consumer | Network policy |
| --- | --- | --- | --- |
| `paper_to_mlip/` | Minimal hand-authored contract fixture | workflow/MLIP dry-run tests | offline only |
| `surface_facade/` | Small hand-authored surface structures | surface facade tests | offline only |
| `surface_literature/` | Curated compact JSON/JSONL examples | literature tests | offline only |
| `archives/papers/` | Repository-tracked paper PDFs retained for compatibility fixtures | compatibility tests and manual review | never fetched during pytest |
| `archives/generated/` | Repository-tracked generated paper/experience snapshots (`paperread_batch_experience`, `paperread_papers2_experience`, and surface full-run directories) | compatibility/reference checks | never regenerated during pytest |

Large archives are intentionally excluded from ordinary unit-test discovery.
