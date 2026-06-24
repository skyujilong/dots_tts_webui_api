# dots-tts-webui-api 后端接口文档

本文档描述 `dots.tts batch synthesis` 服务对外暴露的全部 HTTP 接口。所有业务接口统一挂载在 `/api` 前缀下（见 `src/dots_tts_webui_api/api.py`），另有一个返回 Web 页面的根路由（`src/dots_tts_webui_api/web.py`）。

- 服务标题 / 版本：`dots.tts batch synthesis` / `0.1.0`
- 默认监听地址：`http://127.0.0.1:8080`（由 `DOTS_API_HOST` / `DOTS_API_PORT` 配置）
- 交互式文档：FastAPI 自带 `GET /docs`（Swagger UI）与 `GET /openapi.json`
- 请求体格式：除特别说明（`multipart/form-data` 表单上传）外，均为 `application/json`
- 时间字段：ISO-8601 `datetime` 字符串

---

## 目录

- [运行与状态](#运行与状态)
  - [GET /](#get-)
  - [GET /api/health](#get-apihealth)
  - [GET /api/config](#get-apiconfig)
- [音色预设（Voices）](#音色预设voices)
  - [GET /api/voices](#get-apivoices)
  - [POST /api/voices](#post-apivoices)
  - [GET /api/voices/{name}/audio](#get-apivoicesnameaudio)
  - [DELETE /api/voices/{name}](#delete-apivoicesname)
- [任务（Jobs）](#任务jobs)
  - [POST /api/jobs](#post-apijobs)
  - [POST /api/jobs/form](#post-apijobsform)
  - [GET /api/jobs](#get-apijobs)
  - [GET /api/jobs/{job_id}](#get-apijobsjob_id)
  - [POST /api/jobs/{job_id}/cancel](#post-apijobsjob_idcancel)
  - [DELETE /api/jobs/{job_id}](#delete-apijobsjob_id)
  - [GET /api/jobs/{job_id}/artifacts/{artifact_name}](#get-apijobsjob_idartifactsartifact_name)
- [数据模型](#数据模型)
- [枚举与取值范围](#枚举与取值范围)
- [典型调用流程](#典型调用流程)

---

## 运行与状态

### `GET /`

返回 Web 控制台页面（`templates/index.html`），`Content-Type: text/html`。非 JSON 接口，仅供浏览器访问。

---

### `GET /api/health`

健康检查与运行态查询，可用于探活和监控。

**响应 `200`（`HealthResponse`）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ok` | `bool` | 固定为 `true`，表示服务进程存活 |
| `mode` | `"mock"` \| `"real"` | 当前 TTS 模式（由 `DOTS_MOCK_TTS` 决定） |
| `worker_running` | `bool` | 后台合成 worker 是否在运行 |
| `model_loaded` | `bool` | 真实模型是否已加载（mock 模式下通常为 `false`） |
| `queue` | `object<string,int>` | 各状态任务数量统计，键为任务状态 |

```json
{
  "ok": true,
  "mode": "mock",
  "worker_running": true,
  "model_loaded": false,
  "queue": { "queued": 0, "running": 0, "succeeded": 3 }
}
```

---

### `GET /api/config`

返回前端所需的运行配置：支持的枚举、默认参数、参数范围与上限。前端依据此接口渲染参数表单。

**响应 `200`（`ConfigResponse`）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `mock_tts` | `bool` | 是否为 mock 模式 |
| `supported_languages` | `object<string,string>` | 语言显示名 → 语言代码映射 |
| `supported_template_names` | `string[]` | 支持的模板名 |
| `supported_ode_methods` | `string[]` | 支持的 ODE 求解方法 |
| `defaults` | `object` | 各参数默认值（见下） |
| `ranges` | `object` | 各数值参数的 `min`/`max`/`step` |
| `max_job_chars` | `int` | 单个任务文本最大字符数 |
| `voice_max_audio_size_mb` | `int` | 上传音频文件大小上限（MB） |

`defaults` 包含：`silence_ms`、`chunk_min_chars`、`chunk_max_chars`、`num_steps`、`guidance_scale`、`speaker_scale`、`ode_method`、`seed`。

`ranges` 当前包含：
- `num_steps`: `{ "min": 1, "max": 32, "step": 1 }`
- `guidance_scale`: `{ "min": 1.0, "max": 3.0, "step": 0.1 }`
- `speaker_scale`: `{ "min": 0.0, "max": 3.0, "step": 0.1 }`

---

## 音色预设（Voices）

音色预设由音频样本 + 可选提示文本组成，存储于 `DOTS_VOICES_DIR` 目录。创建任务时可通过 `voice_name` 引用预设，避免每次上传音频。

### `GET /api/voices`

列出所有已保存的音色预设。

**响应 `200`（`VoicePresetResponse[]`）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | `string` | 音色名 |
| `audio_url` | `string` | 音频访问地址（指向 `GET /api/voices/{name}/audio`） |
| `prompt_text` | `string \| null` | 该音色对应的提示文本 |
| `created_at` | `datetime` | 创建时间 |

---

### `POST /api/voices`

上传音频创建一个音色预设。请求体为 `multipart/form-data`。

**表单字段**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | `string` | 是 | 音色名，仅允许中文、字母、数字、下划线、连字符；长度受 `DOTS_VOICE_NAME_MAX_LENGTH`（默认 64）限制 |
| `audio` | `file` | 是 | 音频文件，后缀须为 `.wav/.mp3/.flac/.m4a/.ogg`，大小不超过 `voice_max_audio_size_mb`（默认 20MB） |
| `prompt_text` | `string` | 否 | 与音频匹配的参考文本 |

**响应 `200`**：`VoicePresetResponse`。

**错误**

| 状态码 | 场景 |
| --- | --- |
| `400` | 音频格式不支持 / 文件为空 / 名称非法（`detail` 给出具体原因） |
| `413` | 音频文件超过大小上限 |

```bash
curl -X POST http://127.0.0.1:8080/api/voices \
  -F "name=narrator" \
  -F "prompt_text=这是一段参考文本" \
  -F "audio=@sample.wav"
```

---

### `GET /api/voices/{name}/audio`

下载 / 播放指定音色的音频文件，返回 `FileResponse`（音频字节流）。

**错误**：`404`（音色不存在或名称非法）。

---

### `DELETE /api/voices/{name}`

删除指定音色预设。

**响应 `200`**：`{ "deleted": true }`

**错误**

| 状态码 | 场景 |
| --- | --- |
| `400` | 名称非法 |
| `404` | 音色不存在 |

---

## 任务（Jobs）

任务是一次批量合成的工作单元。提交文本后，服务按换行将文本切分为若干 chunk，由后台 worker 串行合成并最终拼接为整段音频。任务为异步处理，需通过轮询查询状态与产物。

### `POST /api/jobs`

以 JSON 提交合成任务。引用已有音色时使用 `voice_name`；如需直接指定本地音频路径，可用 `prompt_audio_path`（需要服务可访问该路径）。

**请求体（`JobCreateRequest`）**

| 字段 | 类型 | 默认 | 约束 / 说明 |
| --- | --- | --- | --- |
| `text` | `string` | — | **必填**，非空且非纯空白；长度不超过 `max_job_chars` |
| `template_name` | `string` | `"tts"` | 取值见[枚举](#枚举与取值范围) |
| `language` | `string \| null` | `null` | `null` / `auto_detect` / 支持的语言代码 |
| `num_steps` | `int` | `10` | `1 ≤ x ≤ 32` |
| `guidance_scale` | `float` | `1.2` | `1.0 ≤ x ≤ 3.0` |
| `speaker_scale` | `float` | `1.5` | `0.0 ≤ x ≤ 3.0` |
| `ode_method` | `string` | `"euler"` | 取值见[枚举](#枚举与取值范围) |
| `seed` | `int` | `42` | 随机种子 |
| `normalize_text` | `bool` | `false` | 是否对文本做规范化 |
| `silence_ms` | `int` | `500` | `≥ 0`，chunk 间静音时长（毫秒） |
| `chunk_min_chars` | `int \| null` | `null` | `≥ 1`，为空时用服务默认值（180） |
| `chunk_max_chars` | `int \| null` | `null` | `≥ 1`，为空时用服务默认值（1200） |
| `prompt_audio_path` | `string \| null` | `null` | 本地参考音频路径，后缀须受支持 |
| `prompt_text` | `string \| null` | `null` | 参考文本，使用时须同时提供 `prompt_audio_path` 或 `voice_name` |
| `voice_name` | `string \| null` | `null` | 引用已保存音色；与 `prompt_audio_path` 互斥 |

**跨字段校验**
- `prompt_text` 存在时，必须提供 `prompt_audio_path` 或 `voice_name`。
- `voice_name` 与 `prompt_audio_path` 不能同时提供。
- 同时设置时须满足 `chunk_min_chars ≤ chunk_max_chars`。

**响应 `200`（`JobCreateResponse`）**

```json
{ "job_id": "8f3c...", "poll_url": "/api/jobs/8f3c..." }
```

**错误**

| 状态码 | 场景 |
| --- | --- |
| `400` | 切分后无有效 chunk / 引用的 `voice_name` 不存在 |
| `413` | 文本长度超过 `max_job_chars` |
| `422` | 请求体字段校验失败（FastAPI 标准校验错误） |

```bash
curl -X POST http://127.0.0.1:8080/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"text":"第一段\n第二段","voice_name":"narrator","num_steps":12}'
```

---

### `POST /api/jobs/form`

与 `POST /api/jobs` 等价，但使用 `multipart/form-data`，可在同一请求中**直接上传**参考音频（无需预先创建音色）。上传的音频保存在该任务的 `input/` 目录下作为 `prompt_audio_path`。

**表单字段**：`text`（必填）、`prompt_audio`（文件，可选）、`prompt_text`、`silence_ms`、`num_steps`、`guidance_scale`、`speaker_scale`、`ode_method`、`template_name`、`language`、`seed`、`chunk_min_chars`、`chunk_max_chars`。语义与约束同 `JobCreateRequest`，未传字段按默认值处理。

**响应 `200`**：`JobCreateResponse`。

**错误**

| 状态码 | 场景 |
| --- | --- |
| `400` | 音频格式不支持 / 音频为空 / 字段校验失败（`detail` 为校验错误列表） |
| `413` | 音频文件超过大小上限 / 文本超长 |

```bash
curl -X POST http://127.0.0.1:8080/api/jobs/form \
  -F "text=要合成的文本" \
  -F "prompt_audio=@ref.wav" \
  -F "prompt_text=参考文本" \
  -F "num_steps=12"
```

---

### `GET /api/jobs`

分页列出任务（按创建时间倒序，具体排序见 `db.list_jobs`）。

**查询参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `status` | `string \| null` | `null` | 按任务状态过滤 |
| `limit` | `int` | `50` | 返回条数，自动收敛到 `[1, 200]` |

**响应 `200`（`JobListItem[]`）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `string` | 任务 ID |
| `status` | `JobStatus` | 任务状态 |
| `text_sha256` | `string` | 文本 SHA-256 |
| `text_preview` | `string` | 文本预览（最多 80 字，超出加 `…`） |
| `chunk_count` | `int` | 总 chunk 数 |
| `completed_chunks` | `int` | 已完成 chunk 数 |
| `created_at` / `updated_at` | `datetime` | 创建 / 更新时间 |

---

### `GET /api/jobs/{job_id}`

查询单个任务的完整状态，含 chunk 明细、事件日志与产物地址。轮询此接口跟踪进度。

**响应 `200`（`JobStatusResponse`）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `string` | 任务 ID |
| `status` | `JobStatus` | 任务状态 |
| `chunk_count` | `int` | 总 chunk 数 |
| `completed_chunks` | `int` | 已完成 chunk 数 |
| `error_code` / `error_message` | `string \| null` | 失败时的错误码与信息 |
| `final_wav_url` | `string \| null` | 最终音频地址（产物就绪后非空） |
| `final_text_url` | `string \| null` | 最终文本地址 |
| `final_tts_url` | `string \| null` | 最终 `.tts` 文件地址 |
| `final_timeline_url` | `string \| null` | 时间轴文件 `timeline.json` 地址（产物就绪且文件存在时非空） |
| `final_sentences_url` | `string \| null` | 句级时间轴 `sentences.json` 地址（仅在开启句级对齐且对齐成功时非空） |
| `manifest_url` | `string \| null` | 清单文件地址 |
| `chunks` | `ChunkStatusResponse[]` | 各 chunk 状态明细 |
| `events` | `JobEventResponse[]` | 事件日志 |
| `created_at` / `updated_at` / `started_at` / `completed_at` / `cancelled_at` | `datetime \| null` | 各阶段时间戳 |

**错误**：`404`（任务不存在）。

---

### `POST /api/jobs/{job_id}/cancel`

请求取消任务。仅置位取消标记，由 worker 在合适时机响应。

**响应 `200`**：`{ "cancel_requested": true | false }`（`false` 表示当前状态无法取消，例如已完成）。

**错误**：`404`（任务不存在）。

---

### `DELETE /api/jobs/{job_id}`

删除任务及其产物目录。运行中的任务不可直接删除。

**响应 `200`**：`{ "deleted": true | false }`

**错误**

| 状态码 | 场景 |
| --- | --- |
| `404` | 任务不存在 |
| `409` | 任务处于 `running` 或 `cancel_requested`，需先取消 |

---

### `GET /api/jobs/{job_id}/artifacts/{artifact_name}`

下载任务产物文件，返回 `FileResponse`。

**`artifact_name` 仅允许以下取值**：`final.wav`、`final.txt`、`final.tts`、`timeline.json`、`sentences.json`、`manifest.json`。

**`timeline.json`（时间轴清单，`dots_tts_webui_api.timeline.v1`）**

按样本精确累加（含 chunk 间静音）得到的每段在成品音频中的起止位置，单位为毫秒整数，与 `final.wav` 波形严格对齐，可直接用作字幕 / 对轴参考。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `format` | `string` | 固定为 `dots_tts_webui_api.timeline.v1` |
| `job_id` | `string` | 任务 ID |
| `silence_ms` | `int` | chunk 间静音时长（毫秒） |
| `sample_rate` | `int` | 采样率 |
| `chunk_count` | `int` | chunk 总数 |
| `duration_ms` | `int` | 成品音频总时长（毫秒） |
| `chunks` | `object[]` | 每段：`chunk_index`、`text`、`start_ms`、`end_ms`、`duration_ms` |

```json
{
  "format": "dots_tts_webui_api.timeline.v1",
  "job_id": "bf8e86aa…",
  "silence_ms": 500,
  "sample_rate": 16000,
  "chunk_count": 2,
  "duration_ms": 2000,
  "chunks": [
    { "chunk_index": 0, "text": "第一段", "start_ms": 0, "end_ms": 1000, "duration_ms": 1000 },
    { "chunk_index": 1, "text": "第二段", "start_ms": 1500, "end_ms": 2000, "duration_ms": 500 }
  ]
}
```

**`sentences.json`（句级时间轴，`dots_tts_webui_api.sentences.v1`）**

> ⚠️ **与 `timeline.json` 的本质区别**：`timeline.json` 是逐样本精确的 **chunk 级**时间轴；
> `sentences.json` 是**句级**时间轴，通过事后强制对齐（torchaudio MMS_FA + 拼音罗马化）估算得到，
> 属于 **估计值**（`precision: "estimated"`），句边界通常有几十到一两百毫秒误差，适合做字幕/对轴参考。

该产物**仅在开启句级对齐时生成**：

- 由 `DOTS_ENABLE_SENTENCE_ALIGNMENT` 控制，**real 模式默认开启、mock 模式默认关闭**。
- 对齐是增强项：若对齐失败（依赖缺失、模型下载失败等），主产物（`final.wav` / `timeline.json` 等）
  不受影响、任务仍为 `succeeded`，但 `sentences.json` 不生成、`final_sentences_url` 为 `null`，
  并在任务事件中记录一条 `warning`（`message="sentence alignment skipped"`）。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `format` | `string` | 固定为 `dots_tts_webui_api.sentences.v1` |
| `job_id` | `string` | 任务 ID |
| `sample_rate` | `int` | 采样率 |
| `duration_ms` | `int` | 成品音频总时长（毫秒） |
| `precision` | `string` | 固定为 `estimated`，表明为对齐估计值（区别于 timeline 的逐样本精确） |
| `method` / `alignment_model` | `string` | 对齐方法与模型（`torchaudio.MMS_FA+pypinyin` / `MMS_FA`） |
| `note` | `string` | 提示文字（估计值、精确时间见 timeline.json） |
| `sentences` | `object[]` | 每句：`sentence_index`、`chunk_index`、`text`、`start_ms`、`end_ms`、`duration_ms`、`confidence`（可选） |

```json
{
  "format": "dots_tts_webui_api.sentences.v1",
  "job_id": "bf8e86aa…",
  "sample_rate": 16000,
  "duration_ms": 12345,
  "precision": "estimated",
  "method": "torchaudio.MMS_FA+pypinyin",
  "alignment_model": "MMS_FA",
  "note": "句级时间为强制对齐估计值，非逐样本精确；精确 chunk 时间见 timeline.json",
  "sentences": [
    { "sentence_index": 0, "chunk_index": 0, "text": "第一句。", "start_ms": 0, "end_ms": 980, "duration_ms": 980, "confidence": 0.83 }
  ]
}
```

**错误**：`404`（文件名不在白名单内 / 文件不存在）。

---

## 响度归一化（Loudness Normalization）

合并多个 chunk 时，可选地对音频做 **LUFS 感知响度归一化**，把段间忽大忽小的音量拉平到统一标准。

> TTS 逐段合成时各段响度天然有差异。归一化采用 **ffmpeg `loudnorm`（EBU R128 / ITU-R BS.1770）双次扫描**，目标 **-16 LUFS**（旁白/广播标准）、真峰上限 **-1.5 dBTP**（防削顶爆音）。

归一化分两道，**都做**：

1. **每个 chunk 单独归一化**（拼接前）——直接解决"段与段音量不一致"，段内自然抑扬保留。
2. **整条成品再归一化一次**（写出 `final.wav` 后）——整体精确落到 -16 LUFS。

均使用 `linear=true` + 固定采样率：只施加线性增益，**不重采样、不改变样本数**，因此 `timeline.json` / `sentences.json` 的毫秒时间轴不会漂移；归一化后还有**长度守卫**，样本数若变化即报错回退，绝不让时间轴静默偏移。

- 由 `DOTS_ENABLE_LOUDNORM` 控制，**real 模式默认开启、mock 模式默认关闭**（mock/开发环境通常无 ffmpeg）。
- **依赖系统 `ffmpeg`**（须在 PATH 上，且支持 `loudnorm` filter）。
- 归一化是增强项：若 ffmpeg 缺失或归一化失败，**主产物 `final.wav` 仍生成（为未归一化的可用音频）、任务仍为 `succeeded`**，但会在任务事件中记录一条 `warning`（`message="loudness normalization skipped"`，`data.error` 含具体原因）。这样"以为归一化了其实没有"的情况一定可见，不会被静默掩盖。

---

## 数据模型

### `JobStatus`（任务状态）
`queued` → `running` → (`succeeded` | `failed` | `cancelled`)；取消过程中存在中间态 `cancel_requested`。

### `ChunkStatus`（分片状态）
`pending` | `running` | `succeeded` | `failed` | `skipped`。

### `ChunkStatusResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `int` | chunk 主键 |
| `chunk_index` | `int` | chunk 序号 |
| `status` | `ChunkStatus` | chunk 状态 |
| `char_start` / `char_end` | `int` | 在原文中的字符区间 |
| `wav_path` | `string \| null` | 该 chunk 的音频路径 |
| `error_message` | `string \| null` | 错误信息 |
| `started_at` / `completed_at` | `datetime \| null` | 起止时间 |

### `JobEventResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `int` | 事件 ID |
| `chunk_id` | `int \| null` | 关联 chunk（任务级事件为 `null`） |
| `level` | `"info" \| "warning" \| "error"` | 事件级别 |
| `message` | `string` | 事件消息 |
| `data` | `object \| null` | 附加数据 |
| `created_at` | `datetime` | 发生时间 |

---

## 枚举与取值范围

| 名称 | 取值 | 来源 |
| --- | --- | --- |
| `template_name` | `tts`、`instruction_tts`、`text_to_audio`、`tts_interleave` | `SUPPORTED_TEMPLATE_NAMES` |
| `ode_method` | `euler` | `SUPPORTED_ODE_METHODS` |
| 音频后缀 | `.wav`、`.mp3`、`.flac`、`.m4a`、`.ogg` | `SUPPORTED_AUDIO_SUFFIXES` |
| `language` | `null` / `auto_detect` / 60+ 语言代码（`en`、`zh`、`ja` …） | `SUPPORTED_LANGUAGE_CODE_BY_NAME` |
| `voice_name` | 仅中文、字母、数字、`_`、`-` | `VOICE_NAME_PATTERN` |

完整语言列表见 `GET /api/config` 返回的 `supported_languages`（显示名 → 代码）。

数值参数范围（同 `GET /api/config` 的 `ranges`）：
- `num_steps`：`1 ~ 32`
- `guidance_scale`：`1.0 ~ 3.0`
- `speaker_scale`：`0.0 ~ 3.0`

---

## 典型调用流程

1. `GET /api/config` 获取默认值、枚举与范围，渲染参数表单。
2. （可选）`POST /api/voices` 上传音色，或在提交时直接使用 `POST /api/jobs/form` 上传参考音频。
3. `POST /api/jobs`（或 `/api/jobs/form`）创建任务，得到 `job_id` 与 `poll_url`。
4. 轮询 `GET /api/jobs/{job_id}`，直到 `status` 进入终态（`succeeded` / `failed` / `cancelled`）。
5. 成功后通过 `final_wav_url` 等地址（即 `GET /api/jobs/{job_id}/artifacts/{artifact_name}`）下载产物。
6. 需要时 `POST /api/jobs/{job_id}/cancel` 取消，或 `DELETE /api/jobs/{job_id}` 清理。

> 提示：所有接口的实时 Schema 与“试用”功能可访问 `GET /docs`（Swagger UI），机器可读规范见 `GET /openapi.json`。
