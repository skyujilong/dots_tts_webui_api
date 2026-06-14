# 09-final-integration-verification

## Goal
Perform final mock integration verification and document any optional real-mode smoke steps that require a local model.

## Depends on
- `08-tests-docs-cleanup`

## Do
1. Run the full automated test suite and compile checks.
2. Start the app in mock mode if needed and exercise an end-to-end job flow through API or UI-observable endpoints.
3. Confirm final artifacts are generated and downloadable.
4. Document real-mode smoke command and any skipped checks that require local model assets.

## Verify
Run immediately after this step:
1. `uv run pytest`.
2. Mock end-to-end API or app smoke showing submit → succeeded → final artifact download.
3. `git status --short` to summarize final changed files.

## Notes
- Verification `uv run pytest` passed: 10 tests passed, 1 upstream Starlette TestClient deprecation warning.
- Verification `uv run python -m compileall src` passed.
- Final mock end-to-end API smoke passed: submitted 3-line text, polled to `succeeded`, downloaded `final.wav`, `final.txt`, `final.tts`, and `manifest.json`, and confirmed final text content.
- Real-mode smoke was not run because it requires a local dots.tts model path; README documents the command with `DOTS_MOCK_TTS=0 DOTS_ALLOW_MODEL_DOWNLOAD=0 DOTS_MODEL_NAME_OR_PATH=/path/to/local/model`.
- Final `git status --short` shows untracked project files: `.env.example`, `README.md`, `docs/`, `pyproject.toml`, `src/`, `tests/`, and `uv.lock`.
