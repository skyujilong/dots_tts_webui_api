from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from dots_tts_webui_api.alignment import (
    SentenceSpan,
    TokenTiming,
    aggregate_token_timings,
    split_sentences,
)
from dots_tts_webui_api.audio import ChunkArtifact, merge_artifacts


def test_split_sentences_keeps_punctuation_and_spans():
    spans = split_sentences("第一句。第二句！结尾无标点")
    assert [(s.char_start, s.char_end, s.text) for s in spans] == [
        (0, 4, "第一句。"),
        (4, 8, "第二句！"),
        (8, 13, "结尾无标点"),
    ]


def test_split_sentences_skips_blank():
    # 连续标点/空白不产生空句
    spans = split_sentences("。。\n好的。")
    assert [s.text for s in spans] == ["好的。"]


def test_aggregate_takes_first_last_token_per_sentence():
    spans = split_sentences("第一句。第二句。")  # [0,4) 与 [4,8)
    tokens = [
        TokenTiming(0, 1, 0.0, 0.5, 0.9),
        TokenTiming(1, 2, 0.5, 1.0, 0.7),  # -> 句0: 0.0~1.0
        TokenTiming(4, 5, 2.0, 2.5, 0.8),  # -> 句1: 2.0~3.0
        TokenTiming(5, 6, 2.5, 3.0, 0.6),
    ]
    result = aggregate_token_timings(spans, tokens)
    assert len(result) == 2
    assert (result[0].start_s, result[0].end_s) == (0.0, 1.0)
    assert abs(result[0].confidence - 0.8) < 1e-9
    assert (result[1].start_s, result[1].end_s) == (2.0, 3.0)


def test_aggregate_skips_sentence_without_tokens():
    # 句内无任何 token（如纯标点）时不臆造时间，应被跳过
    spans = split_sentences("123。好的。")
    tokens = [TokenTiming(4, 5, 1.0, 1.5, None)]  # 仅覆盖第二句的"好"
    result = aggregate_token_timings(spans, tokens)
    assert [r.text for r in result] == ["好的。"]
    assert result[0].confidence is None


def _make_chunks(test_settings, texts: list[str]) -> tuple[Path, list[ChunkArtifact]]:
    """构造若干 mock chunk wav，返回 job_dir 与 ChunkArtifact 列表。"""
    from dots_tts_webui_api.audio import write_chunk_text_artifacts
    from dots_tts_webui_api.schemas import TtsParams
    from dots_tts_webui_api.tts_adapter import MockTtsAdapter

    adapter = MockTtsAdapter(test_settings)
    params = TtsParams(silence_ms=200)
    job_dir = test_settings.artifact_dir / "job-align"
    chunk_dir = job_dir / "chunks"
    chunks = []
    for index, text in enumerate(texts):
        result = adapter.synthesize_chunk(text=text, out_wav_path=chunk_dir / f"{index:04d}.wav", params=params)
        text_path, tts_path = write_chunk_text_artifacts(
            chunk_dir=chunk_dir, chunk_index=index, text=text, metrics=result.metrics
        )
        chunks.append(
            ChunkArtifact(index, text, Path(result.wav_path), text_path, tts_path, result.metrics, result.tts_text)
        )
    return job_dir, chunks


def test_alignment_disabled_keeps_existing_behavior(test_settings):
    # 默认不开对齐：sentences 产物不生成、无错误、timeline 照常
    job_dir, chunks = _make_chunks(test_settings, ["第一段。", "第二段。"])
    final = merge_artifacts(job_id="job-align", job_dir=job_dir, chunks=chunks, silence_ms=200)
    assert final.sentences_path is None
    assert final.alignment_error is None
    assert final.timeline_path.exists()


def test_alignment_enabled_degrades_without_torch(test_settings):
    # mock 环境无 torch：开启对齐应优雅降级——记录错误、不产出 sentences、主产物仍在
    job_dir, chunks = _make_chunks(test_settings, ["第一段。"])
    final = merge_artifacts(
        job_id="job-align", job_dir=job_dir, chunks=chunks, silence_ms=200, enable_sentence_alignment=True
    )
    assert final.sentences_path is None
    assert final.alignment_error is not None  # 如实记录原因，不静默吞错
    assert final.final_wav_path.exists()
    assert not (job_dir / "sentences.json").exists()


def test_artifact_whitelist_accepts_sentences_json(test_settings, tmp_path):
    from fastapi.testclient import TestClient

    from dots_tts_webui_api.main import create_app

    app = create_app(test_settings)
    with TestClient(app) as client:
        # 不存在时返回 404（文件名在白名单内但文件未生成）
        resp = client.get("/api/jobs/nonexistent/artifacts/sentences.json")
        assert resp.status_code == 404
