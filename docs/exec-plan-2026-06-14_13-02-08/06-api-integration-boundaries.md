# 06-api-integration-boundaries

## Goal
Wire FastAPI routes, startup/shutdown, DB initialization, worker lifecycle, and safe file-serving boundaries.

## Depends on
- `05-core-worker-domain`
- `04-adapters-audio-voices`
- `03-schemas-db-contracts`

## Do
1. Add `api.py` routes for health, config, voices, job creation/query/list/cancel, form upload, and artifact download.
2. Add `web.py` and update `main.py` to initialize settings, logging, DB, voice service, worker lifecycle, API router, and static/template mounts.
3. Enforce root-contained artifact/voice downloads, upload size/suffix validation, request validation, and safe config exposure.
4. Ensure startup resets interrupted running jobs and starts exactly one worker thread.

## Verify
Run immediately after this step:
1. `uv run python -m compileall src`.
2. FastAPI TestClient smoke for `/api/health`, `/api/config`, voice CRUD, job submit/query/cancel, and artifact path rejection.

## Notes
- Added `api.py` routes for health, config, voice CRUD/audio, JSON job creation, multipart job creation, job list/status/cancel, and artifact downloads.
- Added `web.py` placeholder root page for the later UI step.
- Updated `main.py` to initialize settings, logging, SQLite schema, reset interrupted running jobs, start/stop one `SynthesisWorker`, and include API/web routers.
- Enforced upload suffix/size checks and root-contained voice/artifact paths.
- Verification `uv run python -m compileall src` passed.
- Verification FastAPI TestClient smoke passed for `/api/health`, `/api/config`, voice create/list/audio/delete, job submit/query/cancel, final artifact download, and artifact path rejection.
