# dots-tts-webui-api

A production-oriented FastAPI wrapper and lightweight web UI for `dots.tts` batch synthesis.

The default development mode is mock TTS. It does not import upstream `dots_tts`, load torch, or download models.

## Development

```bash
uv sync --extra test
DOTS_MOCK_TTS=1 uv run uvicorn dots_tts_webui_api.main:app --host 127.0.0.1 --port 8080 --reload
```

Open <http://127.0.0.1:8080/> and submit multi-line text. The app polls `/api/jobs/{job_id}` and shows final artifact links when the job succeeds.

## Tests

```bash
uv run pytest
uv run python -m compileall src
```

## API quick check

```bash
curl -X POST http://127.0.0.1:8080/api/jobs \
  -H 'content-type: application/json' \
  -d '{"text":"第一段\n第二段\n第三段","silence_ms":500,"chunk_min_chars":1}'
```

Then poll the returned `poll_url` until `status` is `succeeded` and download:

```bash
curl -O http://127.0.0.1:8080/api/jobs/<job_id>/artifacts/final.wav
curl -O http://127.0.0.1:8080/api/jobs/<job_id>/artifacts/manifest.json
```

## Real mode

Install the optional dependency only when a local model path is ready:

```bash
uv sync --extra real
DOTS_MOCK_TTS=0 DOTS_ALLOW_MODEL_DOWNLOAD=0 DOTS_MODEL_NAME_OR_PATH=/path/to/local/model \
  uv run uvicorn dots_tts_webui_api.main:app --host 127.0.0.1 --port 8080
```

`DOTS_ALLOW_MODEL_DOWNLOAD=0` rejects a missing local model path before importing upstream runtime, so accidental model downloads are blocked by default.

See `docs/PLAN.md` and `docs/ARCHITECTURE_CONSTRAINTS.md` for design details.
