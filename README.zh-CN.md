# dots-tts-webui-api

[English documentation](README.md)

一个面向生产使用的 `dots.tts` FastAPI 封装服务和轻量 Web UI，支持长文本切块、队列、进度轮询、音色预设和产物下载。

默认开发模式是 mock TTS：**不会 import upstream `dots_tts`，不会加载 torch，也不会下载模型**。适合本地只看 UI / API 流程。

## 环境要求

- Python `>=3.11`
- [`uv`](https://docs.astral.sh/uv/) 管理 Python 环境和依赖
- real mode 需要本地 upstream `dots.tts` 源码仓库
- real mode 需要本地模型目录，或 Hugging Face 模型 repo id

## 环境文件

应用读取项目根目录下的 `.env` 文件。

- `.env.example` 只是模板。
- `run.sh` 启动前也会加载 `.env`。
- 如果没有 `.env`，会使用代码默认值和进程环境变量。

创建本地配置：

```bash
cp .env.example .env
```

重要前缀：所有应用配置都使用 `DOTS_`。

## 快速启动：UI/mock 模式

如果只想看页面效果、测试队列/进度/产物流程，不想加载真实模型，使用这个模式。

`.env`:

```env
DOTS_API_HOST=127.0.0.1
DOTS_API_PORT=8080
DOTS_MOCK_TTS=1
```

启动：

```bash
uv sync --extra test
./run.sh
```

打开：

```text
http://127.0.0.1:8080/
```

停止后台服务：

```bash
./stop.sh
```

前台开发模式热重载：

```bash
DOTS_MOCK_TTS=1 uv run uvicorn dots_tts_webui_api.main:app --host 127.0.0.1 --port 8080 --reload
```

## 服务器和 Docker 监听地址

仅本机访问：

```env
DOTS_API_HOST=127.0.0.1
```

Docker、服务器、外部浏览器访问：

```env
DOTS_API_HOST=0.0.0.0
DOTS_API_PORT=8080
```

然后通过服务器 IP/域名和映射端口访问服务。

## 使用 upstream dots.tts 的 real mode

real mode 把 upstream `dots.tts` 当作外部依赖。本项目**不复制 upstream 核心代码**，也**不在 `pyproject.toml` 里硬编码机器相关路径**。

服务器目录示例：

```text
/root/dots_tts_webui_api        # 当前项目
/root/dots.tts                  # upstream 源码仓库
/root/dots.tts/models/rednote-hilab/dots.tts-mf  # 可选本地模型
```

### 方案 A：让 upstream 自动下载模型

```env
DOTS_API_HOST=0.0.0.0
DOTS_API_PORT=8080
DOTS_MOCK_TTS=0
DOTS_TTS_REPO_PATH=/root/dots.tts
DOTS_ALLOW_MODEL_DOWNLOAD=1
DOTS_MODEL_NAME_OR_PATH=rednote-hilab/dots.tts-mf
```

### 方案 B：强制只使用本地模型

```env
DOTS_API_HOST=0.0.0.0
DOTS_API_PORT=8080
DOTS_MOCK_TTS=0
DOTS_TTS_REPO_PATH=/root/dots.tts
DOTS_ALLOW_MODEL_DOWNLOAD=0
DOTS_MODEL_NAME_OR_PATH=/root/dots.tts/models/rednote-hilab/dots.tts-mf
```

启动：

```bash
./run.sh
```

当 `DOTS_MOCK_TTS=0` 时，`run.sh` 会：

1. 如果需要，创建或同步项目 `.venv`；
2. 把 upstream `dots.tts` 安装到当前项目环境：
   ```bash
   uv pip install --python .venv/bin/python -e "$DOTS_TTS_REPO_PATH"
   ```
3. 把 `$DOTS_TTS_REPO_PATH/src` 加到 `PYTHONPATH` 作为 import 兜底；
4. 验证导入：
   ```python
   import dots_tts
   from dots_tts.runtime import DotsTtsRuntime
   ```
5. 后台启动 `.venv/bin/uvicorn`。

### 为什么 dots.tts 自己能跑，这里还要安装？

Python import 是按进程和环境隔离的。`/root/dots.tts` 在自己的目录或 conda/uv 环境里能跑，不代表当前 API 服务的 `/root/dots_tts_webui_api/.venv` 自动能 import 到 `dots_tts`。

API 进程需要满足其中一种：

- upstream 被安装到同一个 Python 环境；
- 或者设置 `PYTHONPATH=/root/dots.tts/src`，并且当前环境已安装 upstream 的所有依赖；
- 或者直接用能运行 `dots.tts` 的同一个解释器/环境启动 API。

当前 `run.sh` 选择隔离 `.venv` 方案，并把 upstream 安装进去。第一次 real mode 启动可能会安装 torch、NVIDIA wheels、pynini 等大依赖；这是 Python 依赖安装，不是模型下载。

## 模型路径和下载行为

`DOTS_MODEL_NAME_OR_PATH` 会直接传给 upstream：

```python
DotsTtsRuntime.from_pretrained(model_name_or_path)
```

它可以是 Hugging Face repo id，也可以是本地模型目录。

### 自动下载

```env
DOTS_ALLOW_MODEL_DOWNLOAD=1
DOTS_MODEL_NAME_OR_PATH=rednote-hilab/dots.tts-mf
```

行为：

1. wrapper 先检查 `DOTS_MODEL_NAME_OR_PATH` 非空；
2. `Path("rednote-hilab/dots.tts-mf").exists()` 通常为 false；
3. 因为允许下载，wrapper 不拦截；
4. upstream 收到 `rednote-hilab/dots.tts-mf`；
5. upstream 把它当 Hugging Face repo id 下载并缓存模型。

常见 upstream 模型 id：

```text
rednote-hilab/dots.tts-base
rednote-hilab/dots.tts-soar
rednote-hilab/dots.tts-mf
```

### 仅本地模型

```env
DOTS_ALLOW_MODEL_DOWNLOAD=0
DOTS_MODEL_NAME_OR_PATH=/root/dots.tts/models/rednote-hilab/dots.tts-mf
```

行为：

1. wrapper 检查本地路径是否存在；
2. 如果存在，upstream 直接加载该目录；
3. 如果不存在，任务提前失败，不尝试下载模型。

本地模型目录应直接包含如下文件：

```text
config.json
llm_config.json
latent_stats.pt
model.safetensors
vocoder.safetensors
speaker_encoder.safetensors
```

该目录还需要 tokenizer 相关文件，因为 upstream 会从该目录本地加载 tokenizer。

### 重要区别

`DOTS_TTS_REPO_PATH` 是 upstream 源码仓库路径，`run.sh` 用它来安装/import `dots_tts` 代码。

```env
DOTS_TTS_REPO_PATH=/root/dots.tts
```

`DOTS_MODEL_NAME_OR_PATH` 是 upstream runtime 使用的模型 id 或模型目录。

```env
DOTS_MODEL_NAME_OR_PATH=rednote-hilab/dots.tts-mf
# 或
DOTS_MODEL_NAME_OR_PATH=/root/dots.tts/models/rednote-hilab/dots.tts-mf
```

这两个配置不是同一个东西。

## 重要环境变量

### 服务监听

```env
DOTS_API_HOST=127.0.0.1
DOTS_API_PORT=8080
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOTS_API_HOST` | `127.0.0.1` | Uvicorn 监听 host。本机访问用 `127.0.0.1`；Docker/服务器外部访问用 `0.0.0.0`。 |
| `DOTS_API_PORT` | `8080` | Uvicorn 监听端口。 |

### 本地状态文件

```env
DOTS_DATA_DIR=.data
DOTS_DB_PATH=.data/jobs.sqlite3
DOTS_ARTIFACT_DIR=.data/artifacts
DOTS_VOICES_DIR=.data/voices
DOTS_LOG_FILE=.data/logs/app.log
DOTS_LOG_LEVEL=INFO
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOTS_DATA_DIR` | `.data` | 本地运行数据根目录，启动时自动创建。 |
| `DOTS_DB_PATH` | `.data/jobs.sqlite3` | SQLite 数据库文件，保存 jobs、chunks、events。 |
| `DOTS_ARTIFACT_DIR` | `.data/artifacts` | 生成产物根目录，每个任务有自己的子目录。 |
| `DOTS_VOICES_DIR` | `.data/voices` | 保存音色预设目录。音频和 prompt 文本以文件形式保存，不单独入 SQLite 表。 |
| `DOTS_LOG_FILE` | `.data/logs/app.log` | 应用日志文件路径。 |
| `DOTS_LOG_LEVEL` | `INFO` | Python 日志等级，会自动转成大写。 |

这些目录会在启动时自动创建。

### 运行模式

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

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOTS_MOCK_TTS` | `1` | `1/true` 使用 mock TTS。mock mode 不 import upstream `dots_tts`，不加载 torch，不下载模型。`0` 启用 real mode。 |
| `DOTS_TTS_REPO_PATH` | empty | 本地 upstream `dots.tts` 源码仓库路径，例如 `/root/dots.tts`。`DOTS_MOCK_TTS=0` 时 `run.sh` 需要它来安装/import upstream 代码。**这不是模型路径。** |
| `DOTS_ALLOW_MODEL_DOWNLOAD` | `0` | wrapper 层的下载开关。`0` 时 `DOTS_MODEL_NAME_OR_PATH` 必须是存在的本地路径；`1` 时允许把 `rednote-hilab/dots.tts-mf` 这类 repo id 传给 upstream 下载/缓存。 |
| `DOTS_MODEL_NAME_OR_PATH` | empty | 模型目录或 Hugging Face repo id，会传给 upstream `DotsTtsRuntime.from_pretrained()`。real mode 下必须非空。本地加载用 `/root/dots.tts/models/rednote-hilab/dots.tts-mf`；自动下载用 `rednote-hilab/dots.tts-mf` 并设置 `DOTS_ALLOW_MODEL_DOWNLOAD=1`。 |
| `DOTS_EXECUTION_MODE` | `generate` | 预留执行模式配置。当前 adapter 使用 upstream `generate`。 |
| `DOTS_PRECISION` | `bfloat16` | 传给 upstream runtime 的精度配置。 |
| `DOTS_OPTIMIZE` | `0` | 是否启用 upstream 的优化/compile 行为。 |
| `DOTS_MAX_GENERATE_LENGTH` | `500` | 传给 upstream runtime 的最大生成长度。 |

### 切块和队列限制

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

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOTS_CHUNK_MIN_CHARS` | `180` | 目标最小 chunk 字符数。通常达到这个长度后找下一个换行切分。 |
| `DOTS_CHUNK_MAX_CHARS` | `1200` | chunk 最大字符数。如果下一个换行会超过这个值，先尝试找 min 后的第一个 `。` 或 `.`，最后 fallback 保证不超过 max。 |
| `DOTS_DEFAULT_SILENCE_MS` | `500` | 合并最终 wav 时，chunk 之间插入的静音毫秒数。 |
| `DOTS_MAX_JOB_CHARS` | `200000` | 单个任务允许的最大输入文本长度。 |
| `DOTS_WORKER_POLL_INTERVAL_SECONDS` | `1.0` | 没有 queued job 时后台 worker 的 sleep 间隔。 |
| `DOTS_CHUNK_TIMEOUT_SECONDS` | `600` | 单个 chunk 的超时/限制配置。 |
| `DOTS_VOICE_MAX_AUDIO_SIZE_MB` | `20` | 上传音色/参考音频的最大大小。 |
| `DOTS_VOICE_NAME_MAX_LENGTH` | `64` | 保存音色预设名称的最大长度。 |

切块行为：

- UI 会从 `/api/config` 读取这些默认值。
- 每个任务提交的值可以覆盖 env 默认值。
- 正常切分会在超过 `DOTS_CHUNK_MIN_CHARS` 后找第一个换行。
- 如果该换行会导致 chunk 超过 `DOTS_CHUNK_MAX_CHARS`，会先找 min 后第一个中文/英文句号：`。` 或 `.`。
- 如果没有安全句号，fallback 仍会保证 chunk 不超过 max。

### 默认 TTS 参数

```env
DOTS_DEFAULT_NUM_STEPS=10
DOTS_DEFAULT_GUIDANCE_SCALE=1.2
DOTS_DEFAULT_SPEAKER_SCALE=1.5
DOTS_DEFAULT_ODE_METHOD=euler
DOTS_DEFAULT_SEED=42
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOTS_DEFAULT_NUM_STEPS` | `10` | 默认生成步数，显示在 UI 中，请求未覆盖时使用。 |
| `DOTS_DEFAULT_GUIDANCE_SCALE` | `1.2` | 默认 guidance scale，传给 upstream generation。 |
| `DOTS_DEFAULT_SPEAKER_SCALE` | `1.5` | 默认 speaker/reference 强度，传给 upstream generation。 |
| `DOTS_DEFAULT_ODE_METHOD` | `euler` | 默认 ODE 方法。 |
| `DOTS_DEFAULT_SEED` | `42` | 默认随机种子。 |

### Mock 音频生成

```env
DOTS_MOCK_SAMPLE_RATE=48000
DOTS_MOCK_SECONDS_PER_CHAR=0.035
DOTS_MOCK_MIN_CHUNK_SECONDS=0.35
DOTS_MOCK_MAX_CHUNK_SECONDS=8.0
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOTS_MOCK_SAMPLE_RATE` | `48000` | mock wav 文件采样率。 |
| `DOTS_MOCK_SECONDS_PER_CHAR` | `0.035` | mock 音频时长和文本长度的换算系数。 |
| `DOTS_MOCK_MIN_CHUNK_SECONDS` | `0.35` | 每个 chunk 的最短 mock 音频时长。 |
| `DOTS_MOCK_MAX_CHUNK_SECONDS` | `8.0` | 每个 chunk 的最长 mock 音频时长。 |

## 启停脚本

后台启动：

```bash
./run.sh
```

脚本写入：

```text
.data/server.pid
.data/logs/server.log
```

停止后台进程：

```bash
./stop.sh
```

`stop.sh` 会优先使用 `.data/server.pid`，找不到时再通过 uvicorn 进程名兜底查找。

## 日志

应用日志写入：

```text
DOTS_LOG_FILE=.data/logs/app.log
```

`run.sh` 的 stdout/stderr 写入：

```text
.data/logs/server.log
```

生产日志刻意避免记录完整输入文本和完整 prompt 文本。日志会记录 ID、长度、SHA256 hash、路径、合成参数、chunk index、耗时和产物元数据，方便排查生产问题，同时减少文本泄漏风险。

## API 快速检查

```bash
curl -X POST http://127.0.0.1:8080/api/jobs \
  -H 'content-type: application/json' \
  -d '{"text":"第一段\n第二段\n第三段","silence_ms":500,"chunk_min_chars":1}'
```

然后轮询返回的 `poll_url`，直到 `status` 变成 `succeeded`，再下载产物。

```bash
curl -O http://127.0.0.1:8080/api/jobs/<job_id>/artifacts/final.wav
curl -O http://127.0.0.1:8080/api/jobs/<job_id>/artifacts/manifest.json
```

## 测试

```bash
uv run pytest
uv run python -m compileall src
```

## 设计说明

更多设计细节见 `docs/PLAN.md` 和 `docs/ARCHITECTURE_CONSTRAINTS.md`。
