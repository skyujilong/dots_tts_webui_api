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


@dataclass(frozen=True)
class FinalArtifacts:
    final_wav_path: Path
    final_text_path: Path
    final_tts_path: Path
    manifest_path: Path
    sample_rate: int
    duration_seconds: float


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


def merge_artifacts(*, job_id: str, job_dir: Path, chunks: list[ChunkArtifact], silence_ms: int) -> FinalArtifacts:
    if not chunks:
        raise ValueError("cannot merge an empty chunk list")
    ordered = sorted(chunks, key=lambda chunk: chunk.chunk_index)
    arrays: list[np.ndarray] = []
    sample_rate: int | None = None
    for chunk in ordered:
        data, current_sample_rate = sf.read(chunk.wav_path, dtype="float32", always_2d=False)
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
    for index, array in enumerate(arrays):
        joined.append(array)
        if index != len(arrays) - 1 and silence_samples > 0:
            joined.append(silence)
    final_audio = np.concatenate(joined, axis=0)

    job_dir.mkdir(parents=True, exist_ok=True)
    final_wav_path = job_dir / "final.wav"
    final_text_path = job_dir / "final.txt"
    final_tts_path = job_dir / "final.tts"
    manifest_path = job_dir / "manifest.json"

    sf.write(final_wav_path, final_audio, sample_rate)
    final_text_path.write_text("\n\n".join(chunk.text for chunk in ordered), encoding="utf-8")

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
        },
        "chunks": chunk_entries,
    }
    final_tts_path.write_text(json.dumps(tts_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return FinalArtifacts(
        final_wav_path=final_wav_path,
        final_text_path=final_text_path,
        final_tts_path=final_tts_path,
        manifest_path=manifest_path,
        sample_rate=sample_rate,
        duration_seconds=len(final_audio) / sample_rate,
    )
