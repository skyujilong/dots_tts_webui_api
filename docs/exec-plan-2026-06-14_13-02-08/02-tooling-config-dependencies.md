# 02-tooling-config-dependencies

## Goal
Create the Python project skeleton, dependency metadata, environment example, settings loader, and logging setup for mock-first development with optional real dots.tts support.

## Depends on
- `01-discovery-constraints`

## Do
1. Add `pyproject.toml` with FastAPI/runtime/test dependencies and `[project.optional-dependencies].real` for dots.tts.
2. Add `.env.example` matching the plan's environment variables.
3. Create `src/dots_tts_webui_api/` package with `config.py`, `logging_config.py`, and initial `main.py` shell.
4. Keep defaults in mock mode and avoid importing upstream dots.tts in base package import paths.

## Verify
Run immediately after this step:
1. `python3 -m compileall src`.
2. `python3 - <<'PY'` import settings and assert mock defaults without importing `dots_tts`.

## Notes
- Added `pyproject.toml`, `.env.example`, `README.md`, package `__init__.py`, `config.py`, `logging_config.py`, and initial `main.py` health shell.
- Installed dependencies with the user's preferred tool: `uv sync --extra test`.
- Updated README examples to use `uv sync` and `uv run`.
- Verification `uv run python -m compileall src` passed.
- Verification settings import smoke passed with `uv run python - <<'PY' ...`: default mode is `mock` and `dots_tts` is not imported.
