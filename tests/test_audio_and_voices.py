from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from dots_tts_webui_api.audio import ChunkArtifact, merge_artifacts, write_chunk_text_artifacts
from dots_tts_webui_api.schemas import TtsParams
from dots_tts_webui_api.tts_adapter import MockTtsAdapter
from dots_tts_webui_api.voices import delete_voice, discover_voices, read_prompt_texts, save_voice


def test_mock_adapter_and_final_merge(test_settings):
    adapter = MockTtsAdapter(test_settings)
    params = TtsParams(silence_ms=250)
    chunk_dir = test_settings.artifact_dir / "job-1" / "chunks"
    chunks = []
    for index, text in enumerate(["第一段", "第二段"]):
        result = adapter.synthesize_chunk(text=text, out_wav_path=chunk_dir / f"{index:04d}.wav", params=params)
        text_path, tts_path = write_chunk_text_artifacts(
            chunk_dir=chunk_dir,
            chunk_index=index,
            text=text,
            metrics=result.metrics,
        )
        chunks.append(ChunkArtifact(index, text, Path(result.wav_path), text_path, tts_path, result.metrics))

    final = merge_artifacts(job_id="job-1", job_dir=test_settings.artifact_dir / "job-1", chunks=chunks, silence_ms=250)

    assert final.final_wav_path.exists()
    assert final.final_text_path.read_text(encoding="utf-8") == "第一段\n\n第二段"
    assert json.loads(final.final_tts_path.read_text(encoding="utf-8"))["chunk_count"] == 2
    manifest = json.loads(final.manifest_path.read_text(encoding="utf-8"))
    assert manifest["sample_rate"] == test_settings.mock_sample_rate
    data, sample_rate = sf.read(final.final_wav_path)
    assert sample_rate == test_settings.mock_sample_rate
    assert len(data) > 0


def _make_loudnorm_chunks(test_settings, job_id: str) -> tuple[Path, list[ChunkArtifact]]:
    """构造两段 mock chunk，返回 job_dir 与 ChunkArtifact 列表（供 loudnorm 测试复用）。"""
    adapter = MockTtsAdapter(test_settings)
    params = TtsParams(silence_ms=200)
    job_dir = test_settings.artifact_dir / job_id
    chunk_dir = job_dir / "chunks"
    chunks = []
    for index, text in enumerate(["第一段。", "第二段。"]):
        result = adapter.synthesize_chunk(text=text, out_wav_path=chunk_dir / f"{index:04d}.wav", params=params)
        text_path, tts_path = write_chunk_text_artifacts(
            chunk_dir=chunk_dir, chunk_index=index, text=text, metrics=result.metrics
        )
        chunks.append(ChunkArtifact(index, text, Path(result.wav_path), text_path, tts_path, result.metrics))
    return job_dir, chunks


def test_loudnorm_disabled_keeps_audio_untouched(test_settings):
    # 默认不开归一化：无错误，final.wav 照常生成
    job_dir, chunks = _make_loudnorm_chunks(test_settings, "job-ln-off")
    final = merge_artifacts(job_id="job-ln-off", job_dir=job_dir, chunks=chunks, silence_ms=200)
    assert final.loudnorm_error is None
    assert final.final_wav_path.exists()


def test_loudnorm_enabled_degrades_without_ffmpeg(test_settings, monkeypatch):
    # mock 环境无 ffmpeg：开启归一化应优雅降级——记录原因、final.wav 仍可用、不漂移
    import dots_tts_webui_api.loudness as loudness

    monkeypatch.setattr(loudness, "ffmpeg_available", lambda: False)
    job_dir, chunks = _make_loudnorm_chunks(test_settings, "job-ln-on")
    before, sr_before = sf.read(chunks[0].wav_path)

    final = merge_artifacts(
        job_id="job-ln-on", job_dir=job_dir, chunks=chunks, silence_ms=200, enable_loudnorm=True
    )

    assert final.loudnorm_error is not None  # 如实记录原因，不静默吞错
    assert "ffmpeg not found" in final.loudnorm_error
    assert final.final_wav_path.exists()
    # 降级后回退原始音频，采样率不变
    data, sr_after = sf.read(final.final_wav_path)
    assert sr_after == sr_before
    assert len(data) > 0


def test_voice_save_discover_delete(tmp_path):
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros(1600, dtype=np.float32), 16000)

    preset = save_voice(voices_dir=tmp_path / "voices", name="男22", source_audio_path=source, prompt_text="hello")

    assert preset.name == "男22"
    assert preset.audio_path.exists()
    assert discover_voices(tmp_path / "voices")["男22"].prompt_text == "hello"
    assert read_prompt_texts(tmp_path / "voices") == {"男22": "hello"}
    assert delete_voice(voices_dir=tmp_path / "voices", name="男22") is True
    assert discover_voices(tmp_path / "voices") == {}
    assert read_prompt_texts(tmp_path / "voices") == {}
