# 08-tests-docs-cleanup

## Goal
Add reusable tests and update project documentation/examples now that the main backend and UI paths exist.

## Depends on
- `07-web-ui-workflows`

## Do
1. Add pytest coverage for chunking, audio merge, voice helpers, DB lifecycle, worker mock end-to-end, and API smoke paths.
2. Update README with uv-based setup, mock run, API examples, and real-mode notes.
3. Add or refine `.env.example` comments and cleanup generated/transient artifacts from the repo tree.
4. Ensure tests use temp directories and do not require upstream dots.tts or torch in mock mode.

## Verify
Run immediately after this step:
1. `uv run pytest`.
2. `uv run python -m compileall src`.

## Notes
- Added pytest coverage under `tests/` for chunking, audio merge/mock adapter, voice helpers, DB + worker mock end-to-end, API smoke, and web/static assets.
- Updated `README.md` with uv setup, test commands, mock UI run, API quick check, artifact download examples, and real-mode safety note.
- Added comments to `.env.example` sections for server, local state, runtime mode, chunking/queue limits, default TTS params, and mock audio generation.
- Verification `uv run pytest` passed: 10 tests passed, 1 upstream Starlette TestClient deprecation warning.
- Verification `uv run python -m compileall src` passed.
