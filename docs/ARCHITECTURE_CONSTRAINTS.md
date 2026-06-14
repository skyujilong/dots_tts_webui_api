# Architecture constraints

This project wraps upstream `dots.tts` without copying or modifying upstream core code.

## Non-negotiables

- Default mode is mock TTS. Base imports must not import upstream `dots_tts`, torch, or trigger model downloads.
- Real mode is enabled only with `DOTS_MOCK_TTS=0`; upstream runtime is lazily imported inside the real adapter.
- If `DOTS_ALLOW_MODEL_DOWNLOAD=0`, real mode must reject missing local model paths before importing upstream runtime.
- FastAPI routes must not run blocking synthesis on the event loop.
- The service supports a single process and a single synthesis worker thread; no multi-process worker fallback.
- SQLite is the source of truth for jobs, chunks, and job events.
- Jobs are chunked by newline-first rules and processed sequentially by chunk index.
- Prompt semantics follow upstream behavior: `prompt_text` requires a prompt audio path; audio without text is allowed.
- Artifact and voice file downloads must resolve paths inside their configured roots.
- Logs and job events must avoid storing or printing full input text; use IDs, lengths, and hashes.

## Build order

1. Tooling and configuration.
2. Schemas, validation, and SQLite contracts.
3. Adapters, audio merge, and voice storage.
4. Chunking, worker, and domain flow.
5. API boundaries.
6. Web UI.
7. Tests, docs, cleanup, and integration verification.
