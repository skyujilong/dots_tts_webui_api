# 03-schemas-db-contracts

## Goal
Implement the API/data contracts and SQLite persistence layer that all worker and API code will use.

## Depends on
- `02-tooling-config-dependencies`

## Do
1. Add `schemas.py` for request/response models, TTS parameter validation, supported language/template/method whitelists, and voice/job payloads.
2. Add `db.py` with SQLite connection helpers, WAL setup, schema creation for `jobs`, `chunks`, and `job_events`, and repository functions for job/chunk/event lifecycle.
3. Include validation for prompt text/audio semantics, parameter ranges, job text length, and status values.
4. Ensure DB operations are usable from a single worker thread and FastAPI routes.

## Verify
Run immediately after this step:
1. `python3 -m compileall src`.
2. Targeted Python smoke creating an in-memory/temp DB, inserting a job with chunks, writing an event, and reading it back.

## Notes
- Added `schemas.py` with TTS parameter validation, supported language/template/method constants, job/chunk/event/voice/config/health response models, and DB input helpers.
- Added `db.py` with SQLite connection/init helpers, WAL schema for `jobs`, `chunks`, `job_events`, transaction helper, job/chunk/event lifecycle functions, cancellation, restart reset, and queue counts.
- Verification `uv run python -m compileall src` passed.
- Verification targeted DB smoke passed: created in-memory DB, inserted job/chunks, claimed job, marked a chunk succeeded, wrote/read events, and confirmed counters.
