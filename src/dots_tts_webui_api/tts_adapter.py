from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import soundfile as sf

from .config import Settings
from .schemas import TtsParams


@dataclass(frozen=True)
class SynthesisResult:
    wav_path: str
    sample_rate: int
    metrics: dict[str, Any] = field(default_factory=dict)
    tts_text: str = ""


class TtsAdapter(Protocol):
    @property
    def model_loaded(self) -> bool: ...

    def synthesize_chunk(self, *, text: str, out_wav_path: Path, params: TtsParams) -> SynthesisResult: ...


class MockTtsAdapter:
    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def model_loaded(self) -> bool:
        return False

    def synthesize_chunk(self, *, text: str, out_wav_path: Path, params: TtsParams) -> SynthesisResult:
        out_wav_path.parent.mkdir(parents=True, exist_ok=True)
        duration = min(
            self._settings.mock_max_chunk_seconds,
            max(self._settings.mock_min_chunk_seconds, len(text) * self._settings.mock_seconds_per_char),
        )
        sample_rate = self._settings.mock_sample_rate
        sample_count = max(1, round(duration * sample_rate))
        t = np.linspace(0.0, duration, sample_count, endpoint=False, dtype=np.float32)
        frequency = 220.0 + (abs(hash(text)) % 220)
        envelope = np.minimum(1.0, np.linspace(0.0, 1.0, sample_count, dtype=np.float32) * 20.0)
        waveform = (0.08 * np.sin(2.0 * math.pi * frequency * t) * envelope).astype(np.float32)
        sf.write(out_wav_path, waveform, sample_rate)
        return SynthesisResult(
            wav_path=str(out_wav_path),
            sample_rate=sample_rate,
            metrics={
                "adapter": "mock",
                "elapsed_seconds": 0.0,
                "duration_seconds": duration,
                "rtf": 0.0,
                "sample_count": sample_count,
            },
            tts_text=text,
        )


class UpstreamDotsAdapter:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._runtime: Any | None = None
        self._seed_everything: Any | None = None

    @property
    def model_loaded(self) -> bool:
        return self._runtime is not None

    def _ensure_runtime(self) -> Any:
        if self._runtime is not None:
            return self._runtime
        model = self._settings.model_name_or_path
        if not model:
            raise RuntimeError("DOTS_MODEL_NAME_OR_PATH is required in real mode")
        model_path = Path(model).expanduser()
        if not model_path.exists() and not self._settings.allow_model_download:
            raise RuntimeError(
                f"model path does not exist and downloads are disabled: {model} "
                "(set DOTS_ALLOW_MODEL_DOWNLOAD=1 to allow upstream download)"
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

    def synthesize_chunk(self, *, text: str, out_wav_path: Path, params: TtsParams) -> SynthesisResult:
        runtime = self._ensure_runtime()
        if self._seed_everything is None:
            raise RuntimeError("seed helper not initialized")
        out_wav_path.parent.mkdir(parents=True, exist_ok=True)
        self._seed_everything(params.seed)
        result = runtime.generate(
            text=text,
            prompt_audio_path=params.prompt_audio_path,
            prompt_text=params.prompt_text,
            template_name=params.template_name,
            language=params.language,
            speaker_scale=params.speaker_scale,
            ode_method=params.ode_method,
            num_steps=params.num_steps,
            guidance_scale=params.guidance_scale,
            normalize_text=params.normalize_text,
        )
        waveform = result["audio"].detach().float().cpu().squeeze().numpy()
        sample_rate = int(result["sample_rate"])
        sf.write(out_wav_path, waveform, sample_rate)
        return SynthesisResult(
            wav_path=str(out_wav_path),
            sample_rate=sample_rate,
            metrics={
                "rtf": result.get("rtf"),
                "elapsed_seconds": result.get("time_used"),
                "request_id": result.get("fid"),
                "profiling": result.get("profiling"),
            },
            tts_text=text,
        )


def create_tts_adapter(settings: Settings) -> TtsAdapter:
    if settings.mock_tts:
        return MockTtsAdapter(settings)
    return UpstreamDotsAdapter(settings)
