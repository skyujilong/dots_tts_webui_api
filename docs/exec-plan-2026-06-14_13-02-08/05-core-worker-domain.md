# 05-core-worker-domain

## Goal
Implement chunking, domain orchestration helpers, and the single worker thread that processes queued jobs sequentially.

## Depends on
- `04-adapters-audio-voices`
- `03-schemas-db-contracts`

## Do
1. Add `chunking.py` with newline-first chunking, blank-line removal, max-char soft split fallback, and preprocessed offsets.
2. Add worker job orchestration to claim jobs, process chunks in order through the selected adapter, write chunk artifacts, merge final outputs, handle cancellation, errors, and restart recovery.
3. Keep synthesis in a single background thread and never on FastAPI request handlers.
4. Record concise job events and avoid logging full user text.

## Verify
Run immediately after this step:
1. `uv run python -m compileall src`.
2. Targeted chunking smoke for newline/min/max/blank-line behavior.
3. Targeted worker smoke using mock adapter and temp DB/artifact dir to generate final artifacts end-to-end.

## Notes
- Added `chunking.py` with CRLF normalization, blank-line removal, newline-first chunking, max-char punctuation fallback, and preprocessed offsets.
- Added `worker.py` with `SynthesisWorker`, single background thread lifecycle, queued job claim, chunk-by-chunk adapter calls, cancellation checks between chunks, final artifact merge, restart reset, and concise events/logs.
- Adjusted `db.claim_next_job` so queued jobs are atomically claimed while already cancel-requested jobs can be consumed and marked cancelled.
- Verification `uv run python -m compileall src` passed.
- Verification chunking smoke passed for blank lines, newline min split, no-newline short input, max-char fallback, and empty input.
- Verification worker smoke passed using temp SQLite DB and mock adapter: generated chunks, final WAV/TXT/TTS/manifest, succeeded job, and succeeded chunks/events.
