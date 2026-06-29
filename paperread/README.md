# Paperread Projects

This directory contains local, detached copies of paper-reading research code:

- `ReactionSeek/`
- `NERRE/`
- `surface/`

The nested `.git` directories were removed intentionally. These copies are now
ordinary source directories managed only by the parent Genkai_Agent repository.

API configuration is shared with Genkai Agent through:

```text
agents/Agent/.env
```

The helper `genkai_api_config.py` loads `LLM_API_KEY`, `LLM_BASE_URL`, and
`LLM_MODEL` from that file and provides compatibility shims for legacy OpenAI
SDK calls in these projects.

## Surface-focused tools

`paperread/surface/` contains a surface-research extraction layer assembled from
the reusable parts of `ReactionSeek` and `NERRE`.

- `extract_surface_conditions.py`: table-oriented extraction for methods and procedures
- `standardize_surface_time.py`: time normalization for surface workflows
- `extract_surface_relations.py`: JSON relation extraction for abstracts and discussion text

## Dependency Notes

The upstream projects pin conflicting OpenAI SDK versions:

- ReactionSeek: `openai==1.76`
- NERRE: `openai==0.27.7`

Genkai Agent uses the already installed OpenAI SDK instead. Do not downgrade
`openai` in the project `.venv` unless you intend to isolate these tools in a
separate virtual environment.

`ChemDataExtractor==1.3.0` depends on the old `DAWG` package, which does not
build cleanly on Python 3.12. `DAWG2` is installed instead because it provides
the importable `dawg` module needed at runtime.
