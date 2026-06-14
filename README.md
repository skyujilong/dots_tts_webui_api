# dots-tts-webui-api

A production-oriented FastAPI wrapper and lightweight web UI for `dots.tts` batch synthesis.

默认开发模式是 mock TTS：**不会 import upstream `dots_tts`，不会加载 torch，也不会下载模型**。适合本地只看 UI / API 流程。

## Requirements

- Python `>=3.11`
- [`uv`](https://docs.astral.sh/uv/) for Python environment and dependency management
- Optional real mode dependency: a local upstream `dots.tts` source checkout
- Optional real mode model directory: a local Dots model path such as `models/rednote-hilab/dots.tts-mf`

## Environment files

The app reads the literal `.env` file in the project root.

- `.env.example` is only a template.
- `run.sh` also sources `.env` before starting the service.
- If `.env` is missing, code defaults and process environment variables are used.

Create your local config with:

```bash
cp .env.example .env
```

Important prefix: all app settings use `DOTS_`.

## Quick start: UI/mock mode

Use this when you only want to view the web UI and test queue/progress/artifacts without real model loading.

`.env`:

```env
DOTS_API_HOST=127.0.0.1
DOTS_API_PORT=8080
DOTS_MOCK_TTS=1
```

Run:

```bash
uv sync --extra test
./run.sh
```

Open:

```text
http://127.0.0.1:8080/
```

Stop background service:

```bash
./stop.sh
```

You can also run foreground dev server with reload:

```bash
DOTS_MOCK_TTS=1 uv run uvicorn dots_tts_webui_api.main:app --host 127.0.0.1 --port 8080 --reload
```

## Server/Docker host binding

For local-only access:

```env
DOTS_API_HOST=127.0.0.1
```

For Docker, server deployment, or external browser access:

```env
DOTS_API_HOST=0.0.0.0
DOTS_API_PORT=8080
```

Then access the service through the server IP/domain and mapped port.

## Real mode with upstream dots.tts

Real mode treats upstream `dots.tts` as an external dependency. This project does **not** copy upstream code and does **not** hardcode a machine-specific path in `pyproject.toml`.

Example server layout:

```text
/root/dots_tts_webui_api        # this project
/root/dots.tts                  # upstream dots.tts checkout
/root/dots.tts/models/rednote-hilab/dots.tts-mf
```

`.env`:

```env
DOTS_API_HOST=0.0.0.0
DOTS_API_PORT=8080
DOTS_MOCK_TTS=0
DOTS_TTS_REPO_PATH=/root/dots.tts
DOTS_ALLOW_MODEL_DOWNLOAD=0
DOTS_MODEL_NAME_OR_PATH=/root/dots.tts/models/rednote-hilab/dots.tts-mf
```

Run:

```bash
./run.sh
```

When `DOTS_MOCK_TTS=0`, `run.sh` will:

1. create/sync the project `.venv` if needed;
2. install upstream `dots.tts` into this project environment with:
   ```bash
   uv pip install --python .venv/bin/python -e "$DOTS_TTS_REPO_PATH"
   ```
3. add `$DOTS_TTS_REPO_PATH/src` to `PYTHONPATH` as an import fallback;
4. verify:
   ```python
   import dots_tts
   from dots_tts.runtime import DotsTtsRuntime
   ```
5. start `.venv/bin/uvicorn` in the background.

### Why install dots.tts if that project can already run?

Python imports are per-process and per-environment. If `/root/dots.tts` can run inside its own directory or conda/uv environment, that does not automatically make `dots_tts` importable from this API service running under `/root/dots_tts_webui_api/.venv`.

The API process needs one of these:

- upstream installed into the same Python environment;
- or `PYTHONPATH=/root/dots.tts/src` plus all upstream dependencies already installed;
- or running the API with the same interpreter/environment that already runs `dots.tts`.

The provided `run.sh` chooses the isolated `.venv` approach and installs upstream there. The first real-mode run may download/install large Python dependencies such as torch/NVIDIA wheels/pynini. That is dependency installation, not model download.

## Model path and download behavior

Recommended production setting:

```env
DOTS_ALLOW_MODEL_DOWNLOAD=0
DOTS_MODEL_NAME_OR_PATH=/root/dots.tts/models/rednote-hilab/dots.tts-mf
```

With downloads disabled, real mode fails early if `DOTS_MODEL_NAME_OR_PATH` does not exist. This prevents accidental model downloads on production machines.

`DOTS_MODEL_NAME_OR_PATH` should point directly to the model directory containing files like:

```text
config.json
llm_config.json
latent_stats.pt
model.safetensors
vocoder.safetensors
speaker_encoder.safetensors
```

Tokenizer files must also be available in that directory because upstream loads the tokenizer locally.

## Important environment variables

### Server

```env
DOTS_API_HOST=127.0.0.1
DOTS_API_PORT=8080
```

### Local state

```env
DOTS_DATA_DIR=.data
DOTS_DB_PATH=.data/jobs.sqlite3
DOTS_ARTIFACT_DIR=.data/artifacts
DOTS_VOICES_DIR=.data/voices
DOTS_LOG_FILE=.data/logs/app.log
DOTS_LOG_LEVEL=INFO
```

These directories are created automatically on startup. Job artifacts are written under `DOTS_ARTIFACT_DIR`. Saved voice presets are file-based under `DOTS_VOICES_DIR`; they are not stored in a separate SQLite table.

### Runtime

```env
DOTS_MOCK_TTS=1
DOTS_TTS_REPO_PATH=
DOTS_ALLOW_MODEL_DOWNLOAD=0
DOTS_MODEL_NAME_OR_PATH=
DOTS_EXECUTION_MODE=generate
DOTS_PRECISION=bfloat16
DOTS_OPTIMIZE=0
DOTS_MAX_GENERATE_LENGTH=500
```

### Chunking and queue limits

```env
DOTS_CHUNK_MIN_CHARS=180
DOTS_CHUNK_MAX_CHARS=1200
DOTS_DEFAULT_SILENCE_MS=500
DOTS_MAX_JOB_CHARS=200000
DOTS_WORKER_POLL_INTERVAL_SECONDS=1.0
DOTS_CHUNK_TIMEOUT_SECONDS=600
DOTS_VOICE_MAX_AUDIO_SIZE_MB=20
DOTS_VOICE_NAME_MAX_LENGTH=64
```

Chunking behavior:

- The UI loads these defaults from `/api/config`.
- Per-job submitted values override env defaults.
- Normal splitting finds the first newline after `DOTS_CHUNK_MIN_CHARS`.
- If that newline would create a chunk larger than `DOTS_CHUNK_MAX_CHARS`, the splitter first tries the first Chinese/English period after min chars: `。` or `.`.
- If no safe period exists, fallback splitting still guarantees chunks do not exceed max.

### Default TTS parameters

```env
DOTS_DEFAULT_NUM_STEPS=10
DOTS_DEFAULT_GUIDANCE_SCALE=1.2
DOTS_DEFAULT_SPEAKER_SCALE=1.5
DOTS_DEFAULT_ODE_METHOD=euler
DOTS_DEFAULT_SEED=42
```

## Run scripts

Start in background:

```bash
./run.sh
```

The script writes:

```text
.data/server.pid
.data/logs/server.log
```

Stop background process:

```bash
./stop.sh
```

`stop.sh` first uses `.data/server.pid`, then falls back to finding the uvicorn process.

## Logs

Application logs are written to:

```text
DOTS_LOG_FILE=.data/logs/app.log
```

`run.sh` stdout/stderr are written to:

```text
.data/logs/server.log
```

Production logs intentionally avoid full input text and prompt text. They log IDs, lengths, SHA256 hashes, paths, selected synthesis parameters, chunk indexes, timing, and artifact metadata to help diagnose production issues without leaking full text content.

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

## Tests

```bash
uv run pytest
uv run python -m compileall src
```

## Design notes

See `docs/PLAN.md` and `docs/ARCHITECTURE_CONSTRAINTS.md` for design details.
