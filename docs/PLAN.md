# dots.tts 二次封装服务 — 总体设计

> 本项目 `dots_tts_webui_api` 在上游 `dots.tts` 的**生成能力**之上，补齐"生产化"缺失的部分：
> 任务提交、按换行切块、SQLite 排队、单 worker 顺序执行、进度轮询、音频/文本/`.tts` 产物合并、自有 Web UI。
> **不修改上游、不 copy 上游核心代码**，把 `dots.tts` 作为**依赖**引入。

---

## 1. 目标与范围

- 输入：一大段（可多行）文本 + TTS 参数（可选 prompt 音频克隆音色）。
- 处理：按换行切块 → 入队 → 单 worker 逐块调用 dots.tts 生成 → 合并。
- 输出：`final.wav`（按 `silence_ms` 拼接）、`final.txt`、`final.tts`（自定义清单）、`manifest.json`。
- 两套运行模式：
  - **mock 模式（默认）**：不导入上游、不加载 torch、不下载模型；本地 Mac M4 可全链路开发。
  - **real 模式**：`DOTS_MOCK_TTS=0`，懒加载上游 `dots.tts` 真实生成。

---

## 2. 整体架构

```
┌─────────────┐   POST /api/jobs        ┌──────────────┐
│  Web UI      │ ──────────────────────▶ │  FastAPI      │
│ (我们自己写) │   GET  /api/jobs/{id}    │  api.py       │
└─────────────┘ ◀────────────────────── └──────┬───────┘
       ▲  轮询进度/产物                          │ 写入
       │                                         ▼
       │                                ┌──────────────┐
       │                                │  SQLite       │
       │                                │ jobs/chunks/  │
       │                                │ job_events    │
       │                                └──────┬───────┘
       │                                       │ claim 最老 queued
       │                                       ▼
       │                                ┌──────────────┐   每 chunk 一次
       └──── final.wav / events ◀──────│  Worker       │ ───────────────┐
                                        │ (独立线程)    │                 │
                                        └──────┬───────┘                 ▼
                                               │              ┌────────────────────┐
                                               │  调用 adapter │  TtsAdapter         │
                                               └─────────────▶│  - MockTtsAdapter   │
                                                              │  - UpstreamDotsAdapter│
                                                              └─────────┬──────────┘
                                                                        │ real 模式
                                                                        ▼
                                                              ┌────────────────────┐
                                                              │ dots.tts (依赖)     │
                                                              │ DotsTtsRuntime      │
                                                              └────────────────────┘
```

**核心原则**

- FastAPI 只负责"收任务 / 查任务 / 下产物"，**不阻塞**：模型生成在独立 worker 线程跑。
- SQLite 是唯一的任务状态来源（job/chunk/event）。
- 单 worker 顺序处理，避免大模型并发占显存。
- adapter 把"是否真实生成"隔离在一层，API/队列/产物逻辑与模型完全解耦。

---

## 3. 如何引用 dots.tts（核心决策：方案 A）

### 3.1 结论

把 **dots.tts 当依赖引入**，并**直接面向核心库 `dots_tts.runtime.DotsTtsRuntime`**，
**不** import 上游的 `apps.gradio.service.GradioAppService`。

原因（已核对上游 `pyproject.toml`）：

- 上游打包配置 `package-dir "" = "src"` + `packages.find include = ["dots_tts*"]`，
  **只有 `src/dots_tts` 被打包**；`apps/gradio/` 是仓库根下的 demo，**不是可安装包**。
- 一旦把 dots.tts 当 pip 依赖装，`apps.gradio` 根本 import 不到。
- `GradioAppService` 还调用了一堆 `runtime._process_text` 等**私有方法**（带 `# noqa: SLF001`），
  绑定它=绑定上游内部实现，易碎，且会拖入无关的 `gradio` 依赖。

### 3.2 依赖声明

```toml
# pyproject.toml
[project.optional-dependencies]
real = [
    # 本地开发：路径依赖
    "dots.tts @ file:///Users/nbe01/workspace/dots.tts",
    # 上线：建议改成 git tag 锁版本
    # "dots.tts @ git+https://<repo>/dots.tts@<tag>",
]
```

- mock 开发：`pip install -e .`（不装 `real`，完全不碰 torch）。
- real 部署：`pip install -e '.[real]'`。

### 3.3 真实生成只需这层薄 glue（约 100 行，写在 `UpstreamDotsAdapter`）

上游公开 API（已核对 `src/dots_tts/runtime.py`）：

- 构造：`DotsTtsRuntime.from_pretrained(path, *, precision, optimize, max_generate_length)`
- 生成：`runtime.generate(*, text, prompt_audio_path, prompt_text, template_name, language, speaker_scale, ode_method, num_steps, guidance_scale, normalize_text) -> dict`
  返回 `{"audio": Tensor, "sample_rate": int, "time_used": float, "rtf": float, "fid": str, "profiling": dict | None}`
- 流式：`runtime.generate_stream(...)` 同签名，`yield torch.Tensor`
- 采样率：`runtime.sample_rate`
- 随机种子：`from dots_tts.utils.util import seed_everything`

参考实现骨架：

```python
class UpstreamDotsAdapter:
    def __init__(self, settings):
        self._settings = settings
        self._runtime = None  # 懒加载

    def _ensure_runtime(self):
        if self._runtime is not None:
            return self._runtime
        model = self._settings.model_name_or_path
        # 关键安全闸：本地路径不存在且不允许下载 → 直接报错，绝不下载
        from pathlib import Path
        if not Path(model).expanduser().exists() and not self._settings.allow_model_download:
            raise RuntimeError(
                f"模型路径不存在且未允许下载: {model} "
                f"(设 DOTS_ALLOW_MODEL_DOWNLOAD=1 才允许下载)"
            )
        from dots_tts.runtime import DotsTtsRuntime
        from dots_tts.utils.util import seed_everything
        self._seed_everything = seed_everything
        self._runtime = DotsTtsRuntime.from_pretrained(
            model,
            precision=self._settings.precision,
            optimize=self._settings.optimize,
            max_generate_length=self._settings.max_generate_length,
        )
        return self._runtime

    def synthesize_chunk(self, *, text, out_wav_path, params):
        runtime = self._ensure_runtime()
        self._seed_everything(params.seed)
        result = runtime.generate(
            text=text,
            prompt_audio_path=params.prompt_audio_path,
            prompt_text=params.prompt_text,
            template_name=params.template_name,   # "tts"
            language=params.language,              # None / 语言码 / "auto_detect"
            speaker_scale=params.speaker_scale,
            ode_method=params.ode_method,
            num_steps=params.num_steps,
            guidance_scale=params.guidance_scale,
            normalize_text=params.normalize_text,  # 默认 False，见 §4.2 决策
        )
        import soundfile as sf
        waveform = result["audio"].detach().float().cpu().squeeze().numpy()
        sf.write(out_wav_path, waveform, result["sample_rate"])
        return {
            "wav_path": str(out_wav_path),
            "sample_rate": result["sample_rate"],
            "metrics": {
                "rtf": result["rtf"],
                "elapsed_seconds": result["time_used"],
                "request_id": result["fid"],
                "profiling": result.get("profiling"),
            },
            "tts_text": text,
        }
```

> 注意（按上游语义）：**有 `prompt_text` 就必须有 `prompt_audio_path`**（上游 `runtime._prepare_inputs` 会 `raise ValueError("prompt_text requires prompt_audio_path.")`）；
> 反之允许**只传音频不传转写**，也允许两者都不传（用默认音色）。
> 同一 job 内所有 chunk 复用**同一 seed + 同一 prompt 音频**以保持音色一致。

---

## 4. 参考上游 UI，封装我们自己的新 UI

### 4.1 上游 UI 是什么、为什么不用

- 上游 UI = `apps/gradio/app.py`（Gradio Blocks），是单页演示界面。
- 它面向"一段文本一次生成"，**没有队列、没有大文本切块、没有任务持久化**，正是我们要补的。
- 因此 **UI 层无论如何都要自己写**（这与方案 A/B 无关）。

### 4.2 从上游 UI 借鉴哪些字段/交互

参考 `apps/gradio/app.py` 的 `run_synthesis(...)` 与 `service.metadata()`，提炼出**对用户有意义的参数**搬到我们的表单：

| 参数 | 来源 | 我们的处理 |
|------|------|-----------|
| `text` | 主输入 | 改成大文本 textarea，支持多行 |
| `prompt_audio` + `prompt_text` | 音色克隆 | 上传音频 + 文本，整 job 复用 |
| `template_name` | runtime 合法值：`tts` / `instruction_tts` / `text_to_audio` / `tts_interleave` | 下拉，默认 `tts`；非调试模式只暴露 `tts`（上游 Gradio 非 DEBUG 也固定 `tts`） |
| `language` | `none` / `auto_detect` / 语言码（70+ 种，见上游 `apps/gradio/languages.py`） | 下拉，默认 none；白名单由 `/api/config` 的 `supported_languages` 字段返回，前端动态渲染 |
| `num_steps` | 默认 10 | Slider / 数字输入，范围 **[1, 32]**，step 1 |
| `guidance_scale` | 默认 1.2 | Slider / 数字输入，范围 **[1.0, 3.0]**，step 0.1 |
| `seed` | 默认 42 | 数字输入 |
| `normalize_text` | 默认 False | **硬编码 `False`，不暴露给用户**。上游默认也是 False；若后续需要可改为 UI 可选 |

**高级设置（折叠区，上游 Gradio 非 DEBUG 模式也隐藏这些）**：

| 参数 | 来源 | 我们的处理 |
|------|------|-----------|
| `speaker_scale` | 默认 1.5 | Slider / 数字输入，范围 **[0.0, 3.0]**，step 0.1 |
| `ode_method` | 默认 euler | 下拉白名单 |

**我们新增、上游没有的**：

- `chunk_min_chars`（切块阈值）
- `silence_ms`（段间静音）
- 进度条 / 已完成 chunk 数 / 任务事件流 / 历史任务列表

### 4.3 新 UI 技术选型

- 轻量优先：`templates/index.html` + `static/app.js`（vanilla JS）+ `static/styles.css`。
- 交互：提交后存 `job_id`，每秒轮询 `GET /api/jobs/{job_id}`，渲染状态/进度/事件；
  成功后显示 `<audio controls>` 与各产物下载链接。

### 4.4 UI 布局与交互设计

页面为**单页应用**，自上而下分为以下区域：

#### 4.4.1 页面结构

```
┌─────────────────────────────────────────────────────┐
│  Header：dots.tts · 批量合成服务                      │
│  副标题 + mock/real 模式标识                           │
├──────────────────────┬──────────────────────────────┤
│  左栏：输入区         │  右栏：输出区                   │
│                      │                              │
│  ┌─ 音色选择 ──────┐ │  ┌─ 任务状态 ──────────────┐ │
│  │ [下拉] 已存音色  │ │  │ 状态标签 / 进度条        │ │
│  │  或 "自定义上传" │ │  │ 已完成 chunk / 总 chunk  │ │
│  ├─────────────────┤ │  └─────────────────────────┘ │
│  │ 参考音频(上传)   │ │                              │
│  │ 参考音频转写     │ │                              │
│  │ [☑ 保存为音色]  │ │                              │
│  │  音色名称输入    │ │                              │
│  └─────────────────┘ │                              │
│                      │                              │
│  ┌─ 待合成文本 ────┐ │  ┌─ 生成音频 ──────────────┐ │
│  │ 大文本 textarea │ │  │ <audio controls>        │ │
│  │ (多行)          │ │  │ 下载：wav / txt / tts    │ │
│  └─────────────────┘ │  └─────────────────────────┘ │
│                      │                              │
│  ┌─ 基本参数 ──────┐ │  ┌─ 任务事件日志 ──────────┐ │
│  │ num_steps       │ │  │ 时间 | 级别 | 消息      │ │
│  │ guidance_scale  │ │  │ (滚动列表)              │ │
│  │ seed            │ │  └─────────────────────────┘ │
│  │ silence_ms      │ │                              │
│  │ chunk_min_chars │ │                              │
│  └─────────────────┘ │                              │
│                      │                              │
│  ┌─ ⚙️ 高级设置 ──┐ │                              │
│  │ speaker_scale   │ │                              │
│  │ ode_method      │ │                              │
│  │ template_name   │ │                              │
│  │ language        │ │                              │
│  └─ (默认折叠) ────┘ │                              │
│                      │                              │
│  [ 🚀 提交任务 ]     │                              │
├──────────────────────┴──────────────────────────────┤
│  底部：历史任务列表                                    │
│  ┌─ 最近任务 ──────────────────────────────────────┐ │
│  │ ID | 状态 | 文本摘要 | chunk数 | 创建时间 | 操作 │ │
│  │ (点击行 → 加载该任务到右栏)                      │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

#### 4.4.2 交互流程

1. **页面加载**：
   - `GET /api/config` → 动态填充 `language`、`template_name` 下拉、各参数默认值与范围；显示 mock/real 模式标识。
   - `GET /api/voices` → 获取已保存的音色列表，填充「音色」下拉（含 "不使用 / No Preset" + "自定义上传"）。
2. **音色选择与管理**（参考上游 Gradio 的 Voice Preset 下拉交互）：
   - **选择已存音色**：下拉选中 → 自动填入参考音频（`<audio>` 预览）与转写文本，用户无需再上传。
   - **自定义上传**：下拉选 "自定义上传" → 显示上传音频 + 转写文本输入框。
   - **保存为新音色**：勾选「保存为音色」→ 输入音色名称 → 提交任务时同时 `POST /api/voices`，或单独点「保存音色」按钮。
   - **删除音色**：已存音色旁显示删除按钮 → `DELETE /api/voices/{name}`。
3. **提交任务**：
   - 选择已存音色：`POST /api/jobs`（JSON，传 `voice_name`，服务端自动解析音频路径与转写）。
   - 自定义上传音频：`POST /api/jobs/form`（multipart/form-data，传音频文件 + `prompt_text`）。
   - 提交后按钮置灰，显示 spinner。
4. **轮询进度**：每秒 `GET /api/jobs/{job_id}` → 更新进度条（`completed_chunks / chunk_count`）、状态标签、事件日志列表。
5. **完成**：
   - `succeeded` → 显示 `<audio controls src="/api/jobs/{id}/artifacts/final.wav">`，下载链接（`final.wav`、`final.txt`、`final.tts`、`manifest.json`）。
   - `failed` → 红色错误提示，显示 `error_message`。
6. **取消**：运行中显示"取消"按钮 → `POST /api/jobs/{job_id}/cancel` → 轮询到 `cancelled` 后更新状态。
7. **历史任务**：底部表格 `GET /api/jobs`，点击行加载该任务到右栏查看产物/重新下载。

#### 4.4.3 响应式与样式

- 桌面端左右双栏（各 50%），移动端堆叠为单栏。
- 状态标签用颜色区分：`queued`（灰）、`running`（蓝+动画）、`succeeded`（绿）、`failed`（红）、`cancelled`（黄）。
- 高级设置默认折叠，点击展开；参考上游 Gradio 的 `⚙️ Settings` Accordion 交互。
- 进度条：线性进度 `completed_chunks / chunk_count`，百分比文字。

### 4.5 音色库（Voice Preset）设计

参考上游 `apps/gradio/service.py` 的 `PromptPreset` / `discover_prompt_presets()` / `prompt_text` 映射文件模式，
但**扩展为支持用户通过 API/UI 上传管理**（上游只支持启动时从目录静态发现）。

#### 4.5.1 存储结构

```
{DOTS_DATA_DIR}/voices/
  {name}.{ext}        # 参考音频，保存上传时的原始格式（不转码）
  prompt_text         # 映射文件，格式同上游：每行 "name|转写文本"
```

- 上游 `prompt_text` 映射文件格式：每行 `name|text`，`#` 开头为注释，空行跳过。
- 音色名 `name` 即音频文件的 stem（不含扩展名），全局唯一，限 `[a-zA-Z0-9_-]`，最长 64 字符。
- 支持的音频格式：`.wav / .mp3 / .flac / .m4a / .ogg`（与上游 `PROMPT_AUDIO_SUFFIXES` 一致），**保存原格式不转码**；上游 `runtime._load_prompt_audio` 内部会自行重采样，无需我们转码。
- `created_at`：取音频文件的 mtime（`Path.stat().st_mtime`），不单独持久化。

#### 4.5.2 服务端逻辑

- **启动加载**：`discover_voices(voices_dir)` 扫描 `voices/` 目录 + 读 `prompt_text` 映射文件 → 构建内存 `dict[name, VoicePreset]`。
- **上传保存**：`POST /api/voices` → 校验名称合法性、音频格式与大小 → 保存音频文件 → 追加/更新 `prompt_text` 映射行 → 刷新内存缓存。
- **删除**：`DELETE /api/voices/{name}` → 删除音频文件 → 从 `prompt_text` 移除对应行 → 刷新缓存。
- **Job 引用**：`POST /api/jobs` 传 `voice_name` 时，服务端从缓存中解析出 `audio_path` + `prompt_text`，
  写入 job 的 `request_json`，整个 job 所有 chunk 复用同一音色。

#### 4.5.3 与上游的对齐

| 上游 dots.tts Gradio | 我们的服务 |
|---------------------|----------|
| `default_prompts/` 目录 + `prompt_text` 映射文件 | `{DOTS_DATA_DIR}/voices/` + 同格式 `prompt_text` 映射文件 |
| `discover_prompt_presets()` 启动时静态扫描 | `discover_voices()` 启动时扫描 + API 动态增删后刷新缓存 |
| `PromptPreset(name, audio_path, prompt_text)` | `VoicePreset(name, audio_path, prompt_text, created_at)` |
| Gradio Dropdown 选择 → 自动填充音频 + 转写 | 前端下拉选择 → 自动填充预览 + 转写 |
| 不支持用户上传保存 | 支持 `POST /api/voices` 上传保存 + `DELETE` 删除 |

---

## 5. 配置（环境变量）

默认 mock，保证 Mac M4 可开发：

```env
DOTS_API_HOST=127.0.0.1
DOTS_API_PORT=8080

DOTS_DATA_DIR=.data
DOTS_DB_PATH=.data/jobs.sqlite3
DOTS_ARTIFACT_DIR=.data/artifacts
DOTS_VOICES_DIR=.data/voices             # 音色库目录
DOTS_LOG_FILE=.data/logs/app.log
DOTS_LOG_LEVEL=INFO

# 运行模式
DOTS_MOCK_TTS=1
DOTS_ALLOW_MODEL_DOWNLOAD=0
DOTS_MODEL_NAME_OR_PATH=
DOTS_EXECUTION_MODE=generate          # generate / generate_stream（上游默认 generate_stream；此处选 generate 因为我们按 chunk 逐段调用，不需要流式拼接，非流式更简单且易于超时控制）
DOTS_PRECISION=bfloat16
DOTS_OPTIMIZE=0
DOTS_MAX_GENERATE_LENGTH=500

# 切块 & 任务限制
DOTS_CHUNK_MIN_CHARS=180
DOTS_CHUNK_MAX_CHARS=1200             # 兜底，避免无换行超长段
DOTS_DEFAULT_SILENCE_MS=500
DOTS_MAX_JOB_CHARS=200000
DOTS_WORKER_POLL_INTERVAL_SECONDS=1.0
DOTS_CHUNK_TIMEOUT_SECONDS=600        # 见 §9
DOTS_VOICE_MAX_AUDIO_SIZE_MB=20        # 单个音色音频最大大小
DOTS_VOICE_NAME_MAX_LENGTH=64          # 音色名称最大长度

# 默认 TTS 参数
DOTS_DEFAULT_NUM_STEPS=10
DOTS_DEFAULT_GUIDANCE_SCALE=1.2
DOTS_DEFAULT_SPEAKER_SCALE=1.5
DOTS_DEFAULT_ODE_METHOD=euler
DOTS_DEFAULT_SEED=42

# mock 假音频
DOTS_MOCK_SAMPLE_RATE=48000
DOTS_MOCK_SECONDS_PER_CHAR=0.035
DOTS_MOCK_MIN_CHUNK_SECONDS=0.35
DOTS_MOCK_MAX_CHUNK_SECONDS=8.0
```

安全约束：

- `DOTS_MOCK_TTS=1` 时**绝不**导入上游、**绝不**触发下载。
- `DOTS_MOCK_TTS=0` 且 `DOTS_ALLOW_MODEL_DOWNLOAD=0` 时，`DOTS_MODEL_NAME_OR_PATH` 必须是**已存在的本地路径**，否则任务失败并给清晰错误（adapter 在 import 上游前先用 `Path.exists()` 拦截）。

---

## 6. 切块规则 `chunk_text_by_newline(text, min_chars, max_chars)`

1. 统一 `\r\n` / `\r` → `\n`。
2. **预处理（切块前第一步）**：用正则**删除所有“仅含空白的空行”**（只有回车、或只有空格/制表符的行），避免无意义空行干扰切块与生成：
   - 删空白行：`text = re.sub(r"(?m)^[ \t]*\n", "", text)`（或等价于 `"\n".join(line for line in text.split("\n") if line.strip())`）。
   - 顺带去除首尾空白行，多个连续空行压缩为无（不保留空行作为段落间隔；段间间隔由 `silence_ms` 控制）。
3. 以换行为**唯一主切点**，不按句号/逗号切碎。
4. 从开头累计字符；当前 chunk 超过 `min_chars`（默认 180）后，遇到的下一个换行就是切点。
5. chunk 内保留原有 `\n`，不改写内容。
6. 结尾无换行时，剩余内容作为最后一个 chunk；不为凑 180 硬切。
7. 不产生纯空 chunk（经步骤 2 预处理后已无空白行，此条作最终兜底）。
8. **兜底**：单个 chunk 超过 `max_chars` 时，按句末标点（。！？.!?\n）软切，避免超长段超过模型能力。
9. 每个 chunk 记录 `chunk_index / text / char_start / char_end`（注意：`char_start/char_end` 基于**预处理后**的文本偏移）。
10. 用 `DOTS_MAX_JOB_CHARS` 限制单任务总文本（在预处理前的原始文本上校验）。

---

## 7. SQLite schema 与队列（开启 WAL）

- `jobs`：`id, status, text, text_sha256, request_json, chunk_count, completed_chunks,
  error_code, error_message, final_wav_path, final_text_path, final_tts_path, manifest_path,
  created_at, updated_at, started_at, completed_at, cancelled_at`
- `chunks`：`id, job_id, chunk_index, text, char_start, char_end, status, wav_path, text_path,
  tts_path, metrics_json, error_message, started_at, completed_at`
- `job_events`：`id, job_id, chunk_id, level, message, data_json, created_at`

状态机：

- job：`queued → running → succeeded | failed`；`cancel_requested → cancelled`
- chunk：`pending → running → succeeded | failed | skipped`

队列规则：

- worker 用**原子 `UPDATE ... WHERE status='queued'`** claim 最老的一个 job。
- 按 `chunk_index` 顺序处理。
- 取消正在运行的 job：**不打断当前模型调用**，只在 chunk 之间停止。
- claim 用原子 `UPDATE` 仅作**防御性**写法；本服务为单进程单 worker（见 §10.4），不依赖多进程抢占。

---

## 8. API 设计

- `GET  /api/health` → `ok / mode / worker_running / model_loaded / 队列统计`
- `GET  /api/config` → 前端安全配置（mock 模式、默认 silence、chunk 阈值、最大文本、参数白名单）；
  包含 `supported_languages`（从上游 `apps/gradio/languages.py` 的 `SUPPORTED_LANGUAGE_CODE_BY_NAME` 内嵌）、
  `supported_template_names`、各参数范围（`num_steps` 1–32、`guidance_scale` 1.0–3.0、`speaker_scale` 0.0–3.0）
- `GET  /api/voices` → 已保存音色列表：`[{name, audio_url, prompt_text, created_at}]`（`created_at` 取音频文件 mtime）
- `POST /api/voices`（multipart）→ 上传参考音频 + prompt_text + name → 保存到音色库，返回 `{name, audio_url, prompt_text}`
- `GET  /api/voices/{name}/audio` → 返回该音色的参考音频文件（供 UI `<audio>` 预览；路径校验须在 `DOTS_VOICES_DIR` 内）
- `DELETE /api/voices/{name}` → 删除指定音色（删除音频文件 + 映射记录）
- `POST /api/jobs`（JSON）→ 创建 job + chunks，返回 `job_id` + `poll_url`；
  支持 `voice_name` 字段（服务端解析对应音频路径与 prompt_text），**或** 传 `prompt_audio_path` + `prompt_text`
- `POST /api/jobs/form`（multipart）→ 支持上传 prompt 音频（一次性使用，不保存到音色库）
- `GET  /api/jobs/{job_id}` → 状态/进度/错误/chunk 状态/产物链接
- `GET  /api/jobs` → 最近任务列表（可按 status 过滤）
- `POST /api/jobs/{job_id}/cancel`
- `GET  /api/jobs/{job_id}/artifacts/{final.wav|final.txt|final.tts|manifest.json}`
  → 下载前必须校验解析后路径在 `DOTS_ARTIFACT_DIR` 内（防路径穿越）。

---

## 9. Worker、产物与合并

### 9.1 任务目录

```
{DOTS_ARTIFACT_DIR}/{job_id}/
  input/                # 上传的 prompt 音频等
  chunks/0000.wav 0000.txt 0000.tts ...
  final.wav  final.txt  final.tts  manifest.json
```

### 9.2 处理流程

1. claim job → `running`。
2. 逐 chunk → `running` → 调 adapter 生成 chunk WAV → 写 `.txt` / `.tts` → `succeeded` → `completed_chunks++`。
3. 全部完成 → 合并音频/文本/`.tts` → 写 manifest → job `succeeded`。
4. 任何异常记 traceback，DB 记 job/chunk 错误，**worker 循环继续处理后续任务**。

### 9.3 音频合并（`soundfile` + `numpy`）

- 同一 job 内所有 chunk 由同一 adapter 生成，采样率恒定（real=`runtime.sample_rate`，mock=`DOTS_MOCK_SAMPLE_RATE`），直接采用该采样率。
- 静音样本数：`round(sample_rate * silence_ms / 1000)`。
- 拼接：`chunk0 + silence + chunk1 + ... + chunkN`，结尾默认不加静音。

### 9.4 文本 / `.tts` 合并

- `final.txt`：按 chunk 顺序，`\n\n` 分隔，保留原文。
- `final.tts`：**自定义结构化清单**（上游无 `.tts` 产物），含 job id、`silence_ms`、`chunk_count`、
  每段文本 / wav 路径 / metrics。`silence_ms` 同时写入 `manifest.json`。

---

## 10. 生产化补充（上游只做了"生成"，这里是要补齐的）

> 以下为相对原始计划新增的硬约束，务必落地。

1. **阻塞调用进线程**：`runtime.generate` 是阻塞 torch 调用，worker 必须跑在独立线程 / `run_in_executor`，禁止占用 FastAPI 事件循环。
2. **上游输出清理风险**：`GradioAppService` 那套 `_cleanup_outputs` 我们不用；用方案 A 直接 `runtime.generate` 自己写盘到 job 目录，从根上规避。产物清理统一走 §10.6 的 job 级 TTL，不引入上游的 retention 机制。
3. **重启恢复**：startup 时把 DB 中残留的 `running` job 重置为 `queued`（或标记 `interrupted`）。
4. **单进程单合成线程（硬约束，不支持多进程）**：
   - **明确不支持多进程**：禁止 `uvicorn --workers >1`，不做任何多进程兜底（硬件不足以支撑多个并发合成）。
   - **不阻塞 FastAPI event loop**：所有阻塞的 torch 生成调用必须放到独立线程 / `run_in_executor`，API 路由始终保持响应。
   - **合成串行单线程**：全局仅一个 worker 线程顺序处理 chunk，永远不并发跑多个合成。
5. **超时**：per-chunk `DOTS_CHUNK_TIMEOUT_SECONDS` 超时 → 该 chunk 失败、记录、job 失败。
6. **产物保留 / 磁盘清理**：job 级 TTL 定期清理 `artifacts/`，防磁盘撑爆。
7. **访问控制**：real 模式对外暴露需加 API key / 限流 / CORS 配置。
8. **输入校验**：范围与白名单校验（参考上游 Gradio Slider 定义与 `metadata()`）：
   - `num_steps`：整数，**[1, 32]**
   - `guidance_scale`：浮点，**[1.0, 3.0]**
   - `speaker_scale`：浮点，**[0.0, 3.0]**
   - `ode_method`：白名单（当前仅 `euler`）
   - `language`：`None` / `auto_detect` / `SUPPORTED_LANGUAGE_CODE_BY_NAME` 中的合法码
   - `template_name`：白名单 `tts` / `instruction_tts` / `text_to_audio` / `tts_interleave`
   - 上传音频：格式（`.wav/.mp3/.flac/.m4a/.ogg`）与大小限制
   - `prompt_text` / `prompt_audio_path`：按上游语义校验——**有 `prompt_text` 必须有 `prompt_audio_path`**；只有音频可不传转写，两者也可都不传
9. **下载安全闸**：见 §3.3 与 §5，import 上游前 `Path.exists()` 拦截误下载。
10. **部署产物**：提供 `Dockerfile` / 启动脚本；`pyproject.toml` 用 optional-dependencies 区分 `real` 重依赖。

---

## 11. 日志

标准 `logging`：控制台 + rotating file。记录：app 启动配置摘要、job submit（id/文本长度/chunk 数/silence）、worker claim、chunk start/succeeded/failed、合并 start/done、real adapter 模型加载边界、job 终态。
**不记录完整文本**（只记长度 + hash + id）；重要事件同步写 `job_events` 供前端展示。

---

## 12. 验证

本地只验 mock：

1. 单元测试：
   - chunking：超 180 后下一个换行切块、不产生空 chunk、无换行不硬切、超 `max_chars` 软切。
   - audio：多段 mock WAV 按 `silence_ms` 合并，样本数正确。
   - DB/API：提交 / 查询 / 取消 queued。
   - worker：mock 端到端生成 final 产物。
2. 启动 mock：
   ```bash
   DOTS_MOCK_TTS=1 uvicorn dots_tts_webui_api.main:app --host 127.0.0.1 --port 8080 --reload
   ```
3. 浏览器 `http://127.0.0.1:8080/`：提交多行大文本，确认轮询/进度/音频/产物/日志。
4. API 手测：
   ```bash
   curl -X POST http://127.0.0.1:8080/api/jobs \
     -H 'content-type: application/json' \
     -d '{"text":"第一段\n第二段\n第三段","silence_ms":500}'
   ```
5. real-mode smoke（仅在本地模型路径就绪后）：
   ```bash
   DOTS_MOCK_TTS=0 DOTS_ALLOW_MODEL_DOWNLOAD=0 \
   DOTS_MODEL_NAME_OR_PATH=/path/to/local/model \
   uvicorn dots_tts_webui_api.main:app --host 0.0.0.0 --port 8080
   ```
   提交一小段文本，确认懒加载、单 chunk 生成、合并产物可下载。

---

## 13. 计划创建的文件

```
pyproject.toml                         # 元数据 + 依赖（real 为 optional）
.env.example
README.md
docs/PLAN.md                           # 本文件
src/dots_tts_webui_api/
  main.py            # FastAPI app、startup/shutdown、挂路由与静态
  config.py          # pydantic-settings 读 env
  logging_config.py  # 控制台 + rotating file
  db.py              # SQLite 连接/schema/事务/repository
  schemas.py         # API request/response 模型
  chunking.py        # 按换行切块（含 max_chars 兜底）
  tts_adapter.py     # MockTtsAdapter / UpstreamDotsAdapter（方案 A）
  audio.py           # WAV 拼接 + 静音 + 文本/.tts 合并
  worker.py          # 单 worker 线程队列处理
  api.py             # /api/* 路由（含 /api/voices）
  voices.py          # VoicePreset 模型、discover / save / delete
  web.py             # 页面路由
  templates/index.html
  static/app.js
  static/styles.css
tests/                                 # chunking / audio / db-api / worker
```
