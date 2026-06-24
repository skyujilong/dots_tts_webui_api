from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_TEMPLATE_NAMES = ("tts", "instruction_tts", "text_to_audio", "tts_interleave")
SUPPORTED_ODE_METHODS = ("euler",)
SUPPORTED_AUDIO_SUFFIXES = (".wav", ".mp3", ".flac", ".m4a", ".ogg")
SUPPORTED_LANGUAGE_CODE_BY_NAME = {
    "Auto Detect": "auto_detect",
    "Afrikaans": "af",
    "Arabic": "ar",
    "Armenian": "hy",
    "Azerbaijani": "az",
    "Belarusian": "be",
    "Bosnian": "bs",
    "Bulgarian": "bg",
    "Catalan": "ca",
    "Chinese": "zh",
    "Croatian": "hr",
    "Czech": "cs",
    "Danish": "da",
    "Dutch": "nl",
    "English": "en",
    "Estonian": "et",
    "Finnish": "fi",
    "French": "fr",
    "Galician": "gl",
    "German": "de",
    "Greek": "el",
    "Hebrew": "he",
    "Hindi": "hi",
    "Hungarian": "hu",
    "Icelandic": "is",
    "Indonesian": "id",
    "Italian": "it",
    "Japanese": "ja",
    "Kannada": "kn",
    "Kazakh": "kk",
    "Korean": "ko",
    "Latvian": "lv",
    "Lithuanian": "lt",
    "Macedonian": "mk",
    "Malay": "ms",
    "Marathi": "mr",
    "Maori": "mi",
    "Nepali": "ne",
    "Norwegian": "no",
    "Persian": "fa",
    "Polish": "pl",
    "Portuguese": "pt",
    "Romanian": "ro",
    "Russian": "ru",
    "Serbian": "sr",
    "Slovak": "sk",
    "Slovenian": "sl",
    "Spanish": "es",
    "Swahili": "sw",
    "Swedish": "sv",
    "Tagalog": "tl",
    "Tamil": "ta",
    "Thai": "th",
    "Turkish": "tr",
    "Ukrainian": "uk",
    "Urdu": "ur",
    "Vietnamese": "vi",
    "Welsh": "cy",
}
SUPPORTED_LANGUAGE_CODES = frozenset(SUPPORTED_LANGUAGE_CODE_BY_NAME.values())
VOICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-一-鿿]+$")

JobStatus = Literal["queued", "running", "cancel_requested", "succeeded", "failed", "cancelled"]
ChunkStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]
EventLevel = Literal["info", "warning", "error"]


class TtsParams(BaseModel):
    template_name: str = "tts"
    language: str | None = None
    num_steps: int = Field(default=10, ge=1, le=32)
    guidance_scale: float = Field(default=1.2, ge=1.0, le=3.0)
    speaker_scale: float = Field(default=1.5, ge=0.0, le=3.0)
    ode_method: str = "euler"
    seed: int = 42
    normalize_text: bool = False
    silence_ms: int = Field(default=500, ge=0)
    chunk_min_chars: int | None = Field(default=None, ge=1)
    chunk_max_chars: int | None = Field(default=None, ge=1)
    prompt_audio_path: str | None = None
    prompt_text: str | None = None
    voice_name: str | None = None

    @field_validator("template_name")
    @classmethod
    def validate_template_name(cls, value: str) -> str:
        if value not in SUPPORTED_TEMPLATE_NAMES:
            raise ValueError(f"template_name must be one of {SUPPORTED_TEMPLATE_NAMES}")
        return value

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        if value in (None, "", "none"):
            return None
        if value not in SUPPORTED_LANGUAGE_CODES:
            raise ValueError("language must be None, auto_detect, or a supported language code")
        return value

    @field_validator("ode_method")
    @classmethod
    def validate_ode_method(cls, value: str) -> str:
        if value not in SUPPORTED_ODE_METHODS:
            raise ValueError(f"ode_method must be one of {SUPPORTED_ODE_METHODS}")
        return value

    @field_validator("voice_name")
    @classmethod
    def validate_voice_name(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not VOICE_NAME_PATTERN.fullmatch(value):
            raise ValueError("voice_name must contain only Chinese characters, letters, digits, underscores, and dashes")
        return value

    @field_validator("prompt_audio_path")
    @classmethod
    def validate_prompt_audio_suffix(cls, value: str | None) -> str | None:
        if not value:
            return None
        suffix = Path(value).suffix.lower()
        if suffix and suffix not in SUPPORTED_AUDIO_SUFFIXES:
            raise ValueError(f"prompt audio suffix must be one of {SUPPORTED_AUDIO_SUFFIXES}")
        return value

    @model_validator(mode="after")
    def validate_prompt_semantics(self) -> TtsParams:
        if self.prompt_text and not self.prompt_audio_path and not self.voice_name:
            raise ValueError("prompt_text requires prompt_audio_path or voice_name")
        if self.voice_name and self.prompt_audio_path:
            raise ValueError("voice_name and prompt_audio_path are mutually exclusive")
        if self.chunk_min_chars and self.chunk_max_chars and self.chunk_min_chars > self.chunk_max_chars:
            raise ValueError("chunk_min_chars must be <= chunk_max_chars")
        return self


class JobCreateRequest(TtsParams):
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class JobCreateResponse(BaseModel):
    job_id: str
    poll_url: str


class ChunkStatusResponse(BaseModel):
    id: int
    chunk_index: int
    status: ChunkStatus
    char_start: int
    char_end: int
    wav_path: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class JobEventResponse(BaseModel):
    id: int
    chunk_id: int | None = None
    level: EventLevel
    message: str
    data: dict[str, Any] | None = None
    created_at: datetime


class JobStatusResponse(BaseModel):
    id: str
    status: JobStatus
    chunk_count: int
    completed_chunks: int
    error_code: str | None = None
    error_message: str | None = None
    final_wav_url: str | None = None
    final_text_url: str | None = None
    final_tts_url: str | None = None
    final_timeline_url: str | None = None
    manifest_url: str | None = None
    chunks: list[ChunkStatusResponse] = Field(default_factory=list)
    events: list[JobEventResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class JobListItem(BaseModel):
    id: str
    status: JobStatus
    text_sha256: str
    text_preview: str
    chunk_count: int
    completed_chunks: int
    created_at: datetime
    updated_at: datetime


class VoicePresetResponse(BaseModel):
    name: str
    audio_url: str
    prompt_text: str | None = None
    created_at: datetime


class ConfigResponse(BaseModel):
    mock_tts: bool
    supported_languages: dict[str, str]
    supported_template_names: tuple[str, ...]
    supported_ode_methods: tuple[str, ...]
    defaults: dict[str, Any]
    ranges: dict[str, dict[str, int | float]]
    max_job_chars: int
    voice_max_audio_size_mb: int


class HealthResponse(BaseModel):
    ok: bool
    mode: Literal["mock", "real"]
    worker_running: bool
    model_loaded: bool
    queue: dict[str, int] = Field(default_factory=dict)


class DbChunkInput(BaseModel):
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_offsets(self) -> DbChunkInput:
        if self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        return self


class DbJobSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    text: str
    text_sha256: str
    request_json: dict[str, Any]
    chunk_count: int
    completed_chunks: int
