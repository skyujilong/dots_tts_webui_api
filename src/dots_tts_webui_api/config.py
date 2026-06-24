from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOTS_", env_file=".env", extra="ignore")

    api_host: str = "127.0.0.1"
    api_port: int = 8080

    data_dir: Path = Path(".data")
    db_path: Path = Path(".data/jobs.sqlite3")
    artifact_dir: Path = Path(".data/artifacts")
    voices_dir: Path = Path(".data/voices")
    log_file: Path = Path(".data/logs/app.log")
    log_level: str = "INFO"

    mock_tts: bool = True
    allow_model_download: bool = False
    model_name_or_path: str = ""
    execution_mode: Literal["generate", "generate_stream"] = "generate"
    precision: str = "bfloat16"
    optimize: bool = False
    max_generate_length: int = 500

    # 句级强制对齐开关。None 表示"未显式设置"，由 model_validator 按模式推导：
    # real 模式默认开启、mock 模式默认关闭（避免 mock 下无 torch 时反复降级记 warning）。
    # 显式设置 DOTS_ENABLE_SENTENCE_ALIGNMENT 时以用户值为准。
    enable_sentence_alignment: bool | None = None
    # 对齐声学模型运行设备；真机有 GPU 可设 "cuda" 提速。
    alignment_device: str = "cpu"

    chunk_min_chars: int = 180
    chunk_max_chars: int = 1200
    default_silence_ms: int = 500
    max_job_chars: int = 200_000
    worker_poll_interval_seconds: float = 1.0
    chunk_timeout_seconds: int = 600
    voice_max_audio_size_mb: int = 20
    voice_name_max_length: int = 64

    default_num_steps: int = 10
    default_guidance_scale: float = 1.2
    default_speaker_scale: float = 1.5
    default_ode_method: str = "euler"
    default_seed: int = 42

    mock_sample_rate: int = 48_000
    mock_seconds_per_char: float = 0.035
    mock_min_chunk_seconds: float = 0.35
    mock_max_chunk_seconds: float = 8.0

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("chunk_min_chars", "chunk_max_chars", "max_job_chars", "max_generate_length")
    @classmethod
    def positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @field_validator("worker_poll_interval_seconds", "mock_seconds_per_char", "mock_min_chunk_seconds", "mock_max_chunk_seconds")
    @classmethod
    def positive_floats(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @model_validator(mode="after")
    def _resolve_sentence_alignment_default(self) -> "Settings":
        # 未显式设置时按模式推导：real 默认开、mock 默认关。
        if self.enable_sentence_alignment is None:
            object.__setattr__(self, "enable_sentence_alignment", not self.mock_tts)
        return self

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.artifact_dir, self.voices_dir, self.log_file.parent):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def mode(self) -> str:
        return "mock" if self.mock_tts else "real"


@lru_cache
def get_settings() -> Settings:
    return Settings()
