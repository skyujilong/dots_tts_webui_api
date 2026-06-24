from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


@dataclass(frozen=True)
class ChunkArtifact:
    chunk_index: int
    text: str
    wav_path: Path
    text_path: Path
    tts_path: Path
    metrics: dict[str, Any]
    # 真实送入模型的文本（normalize_text 开启时可能与 text 不同）。
    # 句级对齐应基于它而非展示文本；为空时回退用 text。
    tts_text: str = ""


@dataclass(frozen=True)
class FinalArtifacts:
    final_wav_path: Path
    final_text_path: Path
    final_tts_path: Path
    manifest_path: Path
    timeline_path: Path
    sample_rate: int
    duration_seconds: float
    # 句级对齐产物路径；未开启或对齐失败时为 None。
    sentences_path: Path | None = None
    # 对齐失败原因（供 worker 写 warning event）；成功或未开启时为 None。
    alignment_error: str | None = None
    # 响度归一化失败/降级原因（供 worker 写 warning event）；成功或未开启时为 None。
    loudnorm_error: str | None = None


def write_chunk_text_artifacts(*, chunk_dir: Path, chunk_index: int, text: str, metrics: dict[str, Any]) -> tuple[Path, Path]:
    chunk_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{chunk_index:04d}"
    text_path = chunk_dir / f"{stem}.txt"
    tts_path = chunk_dir / f"{stem}.tts"
    text_path.write_text(text, encoding="utf-8")
    tts_path.write_text(
        json.dumps(
            {
                "chunk_index": chunk_index,
                "text": text,
                "metrics": metrics,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return text_path, tts_path


def merge_artifacts(
    *,
    job_id: str,
    job_dir: Path,
    chunks: list[ChunkArtifact],
    silence_ms: int,
    enable_sentence_alignment: bool = False,
    alignment_device: str = "cpu",
    enable_loudnorm: bool = False,
) -> FinalArtifacts:
    if not chunks:
        raise ValueError("cannot merge an empty chunk list")
    ordered = sorted(chunks, key=lambda chunk: chunk.chunk_index)

    # 响度归一化第一道（拉平段间音量）：在读样本拼接之前，对每个 chunk wav
    # 单独做 loudnorm 写到 chunks/normalized/，后续读归一化后的版本来拼接。
    # 失败/无 ffmpeg 时降级——回退用原始 wav，并记录原因（不静默）。
    loudnorm_error: str | None = None
    read_paths = [chunk.wav_path for chunk in ordered]
    if enable_loudnorm:
        try:
            read_paths = _normalize_chunks(job_dir=job_dir, ordered=ordered)
        except Exception as exc:  # noqa: BLE001 - 归一化失败需降级但保留原因
            loudnorm_error = f"per-chunk loudnorm skipped: {exc.__class__.__name__}: {exc}"

    arrays: list[np.ndarray] = []
    sample_rate: int | None = None
    for wav_path in read_paths:
        data, current_sample_rate = sf.read(wav_path, dtype="float32", always_2d=False)
        if sample_rate is None:
            sample_rate = int(current_sample_rate)
        elif sample_rate != int(current_sample_rate):
            raise ValueError("all chunks in a job must have the same sample rate")
        arrays.append(np.asarray(data, dtype=np.float32))
    assert sample_rate is not None

    silence_samples = round(sample_rate * silence_ms / 1000)
    silence_shape = (silence_samples,) if arrays[0].ndim == 1 else (silence_samples, arrays[0].shape[1])
    silence = np.zeros(silence_shape, dtype=np.float32)
    joined: list[np.ndarray] = []
    # 按样本精确累加每段在成品音频中的起止位置（含 chunk 间静音），
    # 由样本数除以采样率换算为毫秒整数，保证与 final.wav 波形严格对齐。
    timeline_entries: list[dict[str, Any]] = []
    # 记录每个 chunk 在 final.wav 中的起始样本偏移，供句级对齐叠加为绝对时间。
    chunk_start_samples: list[int] = []
    cursor_samples = 0
    for index, array in enumerate(arrays):
        chunk = ordered[index]
        start_samples = cursor_samples
        chunk_start_samples.append(start_samples)
        end_samples = start_samples + array.shape[0]
        start_ms = round(start_samples * 1000 / sample_rate)
        end_ms = round(end_samples * 1000 / sample_rate)
        timeline_entries.append(
            {
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": end_ms - start_ms,
            }
        )
        joined.append(array)
        cursor_samples = end_samples
        if index != len(arrays) - 1 and silence_samples > 0:
            joined.append(silence)
            cursor_samples += silence_samples
    final_audio = np.concatenate(joined, axis=0)

    job_dir.mkdir(parents=True, exist_ok=True)
    final_wav_path = job_dir / "final.wav"
    final_text_path = job_dir / "final.txt"
    final_tts_path = job_dir / "final.tts"
    manifest_path = job_dir / "manifest.json"
    timeline_path = job_dir / "timeline.json"

    sf.write(final_wav_path, final_audio, sample_rate)
    final_text_path.write_text("\n\n".join(chunk.text for chunk in ordered), encoding="utf-8")

    # 响度归一化第二道（整条精确落到目标 LUFS）：对已写出的 final.wav 再做一次
    # 线性 loudnorm。linear=true + 固定采样率只乘增益、不改样本数；归一化后用
    # 长度守卫校验，样本数若变化则视为破坏时间轴，回退保留原始 final.wav 并记录。
    if enable_loudnorm:
        try:
            _normalize_final(final_wav_path, sample_rate=sample_rate, expected_samples=len(final_audio))
        except Exception as exc:  # noqa: BLE001 - 归一化失败需降级但保留原因
            detail = f"final loudnorm skipped: {exc.__class__.__name__}: {exc}"
            loudnorm_error = f"{loudnorm_error}; {detail}" if loudnorm_error else detail

    chunk_entries = [
        {
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "wav_path": str(chunk.wav_path),
            "text_path": str(chunk.text_path),
            "tts_path": str(chunk.tts_path),
            "metrics": chunk.metrics,
        }
        for chunk in ordered
    ]
    tts_payload = {
        "format": "dots_tts_webui_api.final_tts.v1",
        "job_id": job_id,
        "silence_ms": silence_ms,
        "chunk_count": len(ordered),
        "chunks": chunk_entries,
    }
    manifest_payload = {
        "job_id": job_id,
        "silence_ms": silence_ms,
        "chunk_count": len(ordered),
        "sample_rate": sample_rate,
        "duration_seconds": len(final_audio) / sample_rate,
        "artifacts": {
            "final_wav_path": str(final_wav_path),
            "final_text_path": str(final_text_path),
            "final_tts_path": str(final_tts_path),
            "manifest_path": str(manifest_path),
            "timeline_path": str(timeline_path),
        },
        "chunks": chunk_entries,
    }
    timeline_payload = {
        "format": "dots_tts_webui_api.timeline.v1",
        "job_id": job_id,
        "silence_ms": silence_ms,
        "sample_rate": sample_rate,
        "chunk_count": len(ordered),
        "duration_ms": round(len(final_audio) * 1000 / sample_rate),
        "chunks": timeline_entries,
    }
    final_tts_path.write_text(json.dumps(tts_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    timeline_path.write_text(json.dumps(timeline_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 句级强制对齐：增强产物，必须在主产物（wav/tts/manifest/timeline）写完之后进行。
    # 整段包在独立 try/except 中，任何失败都不影响已落盘的主产物，也不让 job 失败；
    # 失败原因如实回传给 worker 记录 warning event，不静默吞错。
    sentences_path: Path | None = None
    alignment_error: str | None = None
    if enable_sentence_alignment:
        try:
            sentences_path = _write_sentences(
                job_id=job_id,
                job_dir=job_dir,
                ordered=ordered,
                arrays=arrays,
                chunk_start_samples=chunk_start_samples,
                sample_rate=sample_rate,
                total_samples=len(final_audio),
                device=alignment_device,
            )
        except Exception as exc:  # noqa: BLE001 - 对齐失败需降级但保留原因
            alignment_error = f"{exc.__class__.__name__}: {exc}"

    return FinalArtifacts(
        final_wav_path=final_wav_path,
        final_text_path=final_text_path,
        final_tts_path=final_tts_path,
        manifest_path=manifest_path,
        timeline_path=timeline_path,
        sample_rate=sample_rate,
        duration_seconds=len(final_audio) / sample_rate,
        sentences_path=sentences_path,
        alignment_error=alignment_error,
        loudnorm_error=loudnorm_error,
    )


def _write_sentences(
    *,
    job_id: str,
    job_dir: Path,
    ordered: list[ChunkArtifact],
    arrays: list[np.ndarray],
    chunk_start_samples: list[int],
    sample_rate: int,
    total_samples: int,
    device: str,
) -> Path | None:
    """对每个 chunk 做句级强制对齐，叠加 chunk 偏移得绝对毫秒，写 sentences.json。

    句在 chunk 内的相对秒由 alignment.align_chunk_sentences 给出（估计值），
    叠加该 chunk 在 final.wav 的起始偏移得到相对成品的绝对时间。
    所有句子均无对齐结果时返回 None（不产出空文件）。
    """
    # 延迟到此处 import：alignment 内部再 lazy import torch/torchaudio/pypinyin，
    # mock 环境缺这些依赖时由调用方 try/except 捕获并降级。
    from .alignment import align_chunk_sentences

    sentence_entries: list[dict[str, Any]] = []
    sentence_index = 0
    for chunk, array, start_samples in zip(ordered, arrays, chunk_start_samples):
        # 对齐基于真实送模型文本（tts_text），展示仍用原文 text；tts_text 为空时回退
        align_text = chunk.tts_text or chunk.text
        offset_ms = round(start_samples * 1000 / sample_rate)
        timings = align_chunk_sentences(array, sample_rate, align_text, device=device)
        for timing in timings:
            start_ms = offset_ms + round(timing.start_s * 1000)
            end_ms = offset_ms + round(timing.end_s * 1000)
            entry: dict[str, Any] = {
                "sentence_index": sentence_index,
                "chunk_index": chunk.chunk_index,
                "text": timing.text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": end_ms - start_ms,
            }
            if timing.confidence is not None:
                entry["confidence"] = round(timing.confidence, 4)
            sentence_entries.append(entry)
            sentence_index += 1

    if not sentence_entries:
        return None

    sentences_path = job_dir / "sentences.json"
    sentences_payload = {
        "format": "dots_tts_webui_api.sentences.v1",
        "job_id": job_id,
        "sample_rate": sample_rate,
        "duration_ms": round(total_samples * 1000 / sample_rate),
        "precision": "estimated",
        "method": "torchaudio.MMS_FA+pypinyin",
        "alignment_model": "MMS_FA",
        "note": "句级时间为强制对齐估计值，非逐样本精确；精确 chunk 时间见 timeline.json",
        "sentences": sentence_entries,
    }
    sentences_path.write_text(
        json.dumps(sentences_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return sentences_path


def _normalize_chunks(*, job_dir: Path, ordered: list[ChunkArtifact]) -> list[Path]:
    """对每个 chunk wav 单独做响度归一化，返回归一化后用于拼接的路径列表。

    无 ffmpeg 直接抛错由调用方降级；任一段失败也抛错（整体回退原始 wav），
    不做"部分归一化部分不归一化"的半成品，避免段间响度反而更不一致。
    归一化后强校验采样率与样本数不变，否则视为破坏时间轴而报错。
    """
    from .loudness import ffmpeg_available, normalize_file

    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found on PATH")

    normalized_dir = job_dir / "chunks" / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    for chunk in ordered:
        src_info = sf.info(chunk.wav_path)
        dst = normalized_dir / f"{chunk.chunk_index:04d}.wav"
        normalize_file(chunk.wav_path, dst, sample_rate=int(src_info.samplerate))
        dst_info = sf.info(dst)
        # 守卫：线性归一化不应改变采样率或样本数，变了说明时间轴会漂移
        if int(dst_info.samplerate) != int(src_info.samplerate) or dst_info.frames != src_info.frames:
            raise RuntimeError(
                f"chunk {chunk.chunk_index} loudnorm changed length "
                f"({src_info.frames}@{src_info.samplerate} -> {dst_info.frames}@{dst_info.samplerate})"
            )
        out_paths.append(dst)
    return out_paths


def _normalize_final(final_wav_path: Path, *, sample_rate: int, expected_samples: int) -> None:
    """对整条 final.wav 原地做响度归一化（写临时文件后替换）。

    linear=true + 固定采样率只乘增益、不改样本数；归一化后校验样本数与
    expected_samples 一致才替换原文件，否则报错并保留原始 final.wav，
    确保 timeline.json / sentences.json 的毫秒时间轴始终对得上波形。
    """
    from .loudness import ffmpeg_available, normalize_file

    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found on PATH")

    tmp_path = final_wav_path.with_suffix(".loudnorm.wav")
    normalize_file(final_wav_path, tmp_path, sample_rate=sample_rate)
    info = sf.info(tmp_path)
    if int(info.samplerate) != sample_rate or info.frames != expected_samples:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"final loudnorm changed length ({expected_samples}@{sample_rate} -> {info.frames}@{info.samplerate})"
        )
    tmp_path.replace(final_wav_path)
