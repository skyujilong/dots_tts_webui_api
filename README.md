# dots-tts-webui-api

[中文文档](README.zh-CN.md)

A production-oriented FastAPI wrapper and lightweight web UI for `dots.tts` batch synthesis.

Default development mode is mock TTS: it **does not import upstream `dots_tts`, does not load torch, and does not download models**. Use it for local UI/API workflow checks.

## Requirements

- Python `>=3.11`
- [`uv`](https://docs.astral.sh/uv/) for Python environment and dependency management
- Real mode requires a local upstream `dots.tts` source checkout
- Real mode needs either a local model directory or a Hugging Face repo id

## Environment files

The app reads the literal `.env` file in the project root.

- `.env.example` is only a template.
- `run.sh` also sources `.env` before starting the service.
- If `.env` is missing, code defaults and process environment variables are used.

Create your local config:

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

Foreground dev server with reload:

```bash
DOTS_MOCK_TTS=1 uv run uvicorn dots_tts_webui_api.main:app --host 127.0.0.1 --port 8080 --reload
```

## Server/Docker host binding

Local-only access:

```env
DOTS_API_HOST=127.0.0.1
```

Docker/server/external browser access:

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
/root/dots.tts/models/rednote-hilab/dots.tts-mf  # optional local model
```

### Option A: let upstream download the model

```env
DOTS_API_HOST=0.0.0.0
DOTS_API_PORT=8080
DOTS_MOCK_TTS=0
DOTS_TTS_REPO_PATH=/root/dots.tts
DOTS_ALLOW_MODEL_DOWNLOAD=1
DOTS_MODEL_NAME_OR_PATH=rednote-hilab/dots.tts-mf
```

### Option B: force local model only

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
2. install upstream `dots.tts` into this project environment:
   ```bash
   uv pip install --python .venv/bin/python -e "$DOTS_TTS_REPO_PATH"
   ```
3. add `$DOTS_TTS_REPO_PATH/src` to `PYTHONPATH` as an import fallback;
4. verify imports:
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

`DOTS_MODEL_NAME_OR_PATH` is passed directly to upstream:

```python
DotsTtsRuntime.from_pretrained(model_name_or_path)
```

It can be either a Hugging Face repo id or a local model directory.

### Automatic download

```env
DOTS_ALLOW_MODEL_DOWNLOAD=1
DOTS_MODEL_NAME_OR_PATH=rednote-hilab/dots.tts-mf
```

Behavior:

1. this wrapper checks that `DOTS_MODEL_NAME_OR_PATH` is not empty;
2. `Path("rednote-hilab/dots.tts-mf").exists()` is normally false;
3. because `DOTS_ALLOW_MODEL_DOWNLOAD=1`, this wrapper does not block;
4. upstream receives `rednote-hilab/dots.tts-mf`;
5. upstream treats it as a Hugging Face repo id and downloads/caches the model.

Common upstream model ids:

```text
rednote-hilab/dots.tts-base
rednote-hilab/dots.tts-soar
rednote-hilab/dots.tts-mf
```

### Local model only

```env
DOTS_ALLOW_MODEL_DOWNLOAD=0
DOTS_MODEL_NAME_OR_PATH=/root/dots.tts/models/rednote-hilab/dots.tts-mf
```

Behavior:

1. this wrapper checks the local path exists;
2. if it exists, upstream loads that directory directly;
3. if it does not exist, the job fails early and no model download is attempted.

The local model directory should directly contain files like:

```text
config.json
llm_config.json
latent_stats.pt
model.safetensors
vocoder.safetensors
speaker_encoder.safetensors
```

Tokenizer files must also be available in that directory because upstream loads the tokenizer locally.

### Important distinction

`DOTS_TTS_REPO_PATH` is the upstream source-code checkout path, used by `run.sh` so this service can import `dots_tts`.

```env
DOTS_TTS_REPO_PATH=/root/dots.tts
```

`DOTS_MODEL_NAME_OR_PATH` is the model id or model directory used by upstream runtime.

```env
DOTS_MODEL_NAME_OR_PATH=rednote-hilab/dots.tts-mf
# or
DOTS_MODEL_NAME_OR_PATH=/root/dots.tts/models/rednote-hilab/dots.tts-mf
```

These two settings are not the same thing.

## Important environment variables

### Server

```env
DOTS_API_HOST=127.0.0.1
DOTS_API_PORT=8080
```

| Variable | Default | Description |
| --- | --- | --- |
| `DOTS_API_HOST` | `127.0.0.1` | Uvicorn bind host. Use `127.0.0.1` for local-only access; use `0.0.0.0` for Docker/server/external access. |
| `DOTS_API_PORT` | `8080` | Uvicorn bind port. |

### Local state

```env
DOTS_DATA_DIR=.data
DOTS_DB_PATH=.data/jobs.sqlite3
DOTS_ARTIFACT_DIR=.data/artifacts
DOTS_VOICES_DIR=.data/voices
DOTS_LOG_FILE=.data/logs/app.log
DOTS_LOG_LEVEL=INFO
```

| Variable | Default | Description |
| --- | --- | --- |
| `DOTS_DATA_DIR` | `.data` | Local runtime data root, created automatically. |
| `DOTS_DB_PATH` | `.data/jobs.sqlite3` | SQLite database file for jobs, chunks, and events. |
| `DOTS_ARTIFACT_DIR` | `.data/artifacts` | Generated job outputs root; each job writes under its own subdirectory. |
| `DOTS_VOICES_DIR` | `.data/voices` | Saved voice preset root. Voice audio and prompt text are file-based here, not stored in a separate SQLite table. |
| `DOTS_LOG_FILE` | `.data/logs/app.log` | Application log file path. |
| `DOTS_LOG_LEVEL` | `INFO` | Python logging level, normalized to uppercase. |

These directories are created automatically on startup.

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

| Variable | Default | Description |
| --- | --- | --- |
| `DOTS_MOCK_TTS` | `1` | `1/true` uses mock TTS. Mock mode never imports upstream `dots_tts`, never loads torch, and never downloads models. `0` enables real mode. |
| `DOTS_TTS_REPO_PATH` | empty | Local upstream `dots.tts` source checkout path, for example `/root/dots.tts`. Required by `run.sh` when `DOTS_MOCK_TTS=0` so it can install/import upstream code. **This is not the model path.** |
| `DOTS_ALLOW_MODEL_DOWNLOAD` | `0` | Wrapper-side gate for repo-id downloads. If `0`, `DOTS_MODEL_NAME_OR_PATH` must be an existing local path. If `1`, a non-existing value such as `rednote-hilab/dots.tts-mf` is allowed through to upstream, which may download/cache from Hugging Face. |
| `DOTS_MODEL_NAME_OR_PATH` | empty | Model directory or Hugging Face repo id passed to upstream `DotsTtsRuntime.from_pretrained()`. In real mode it must be non-empty. Use `/root/dots.tts/models/rednote-hilab/dots.tts-mf` for local loading, or `rednote-hilab/dots.tts-mf` with `DOTS_ALLOW_MODEL_DOWNLOAD=1` for automatic download. |
| `DOTS_EXECUTION_MODE` | `generate` | Reserved execution mode setting. Current adapter uses upstream `generate`. |
| `DOTS_PRECISION` | `bfloat16` | Precision passed to upstream runtime. |
| `DOTS_OPTIMIZE` | `0` | Whether to enable upstream optimization/compile behavior. |
| `DOTS_MAX_GENERATE_LENGTH` | `500` | Max generation length passed to upstream runtime. |

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

| Variable | Default | Description |
| --- | --- | --- |
| `DOTS_CHUNK_MIN_CHARS` | `180` | Target minimum chunk size. The splitter normally waits until this length, then looks for the next newline. |
| `DOTS_CHUNK_MAX_CHARS` | `1200` | Hard maximum chunk size. If the next newline would exceed this value, the splitter first tries the first `。` or `.` after min length, then falls back to safe max splitting. |
| `DOTS_DEFAULT_SILENCE_MS` | `500` | Silence inserted between generated chunk wavs during final merge. |
| `DOTS_MAX_JOB_CHARS` | `200000` | Maximum accepted input text length per job. |
| `DOTS_WORKER_POLL_INTERVAL_SECONDS` | `1.0` | Background worker sleep interval when no queued job is available. |
| `DOTS_CHUNK_TIMEOUT_SECONDS` | `600` | Per-chunk timeout/limit setting used by worker flow. |
| `DOTS_VOICE_MAX_AUDIO_SIZE_MB` | `20` | Maximum uploaded voice/reference audio size. |
| `DOTS_VOICE_NAME_MAX_LENGTH` | `64` | Maximum saved voice preset name length. |

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

| Variable | Default | Description |
| --- | --- | --- |
| `DOTS_DEFAULT_NUM_STEPS` | `10` | Default synthesis step count shown in UI and used when a request does not override it. |
| `DOTS_DEFAULT_GUIDANCE_SCALE` | `1.2` | Default guidance scale passed to upstream generation. |
| `DOTS_DEFAULT_SPEAKER_SCALE` | `1.5` | Default speaker/reference strength passed to upstream generation. |
| `DOTS_DEFAULT_ODE_METHOD` | `euler` | Default ODE method passed to upstream generation. |
| `DOTS_DEFAULT_SEED` | `42` | Default random seed for generation. |

### Mock audio generation

```env
DOTS_MOCK_SAMPLE_RATE=48000
DOTS_MOCK_SECONDS_PER_CHAR=0.035
DOTS_MOCK_MIN_CHUNK_SECONDS=0.35
DOTS_MOCK_MAX_CHUNK_SECONDS=8.0
```

| Variable | Default | Description |
| --- | --- | --- |
| `DOTS_MOCK_SAMPLE_RATE` | `48000` | Sample rate for generated mock wav files. |
| `DOTS_MOCK_SECONDS_PER_CHAR` | `0.035` | Mock duration multiplier by text length. |
| `DOTS_MOCK_MIN_CHUNK_SECONDS` | `0.35` | Minimum mock audio duration per chunk. |
| `DOTS_MOCK_MAX_CHUNK_SECONDS` | `8.0` | Maximum mock audio duration per chunk. |

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

Then poll the returned `poll_url` until `status` is `succeeded` and download.

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
