from __future__ import annotations

import re
from dataclasses import dataclass


# 段落边界字符：在句末标点基础上增加子句标点（逗号/分号/冒号/顿号），
# 使长句被进一步拆分为更短的子句段，每段有独立时间戳，更适合字幕/对轴。
# 标点归属到它前面的段落。
SENTENCE_BOUNDARY = "。！？.!?\n，；、;,:"


@dataclass(frozen=True)
class SentenceSpan:
    """一个段落（子句或句子）在 chunk 文本中的位置。

    char_start/char_end 是该段在 chunk 文本中的字符区间 [start, end)，
    标点归属到它前面的段落。
    """

    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class TokenTiming:
    """单个对齐 token 的结果。

    char_start/char_end 标记该 token 来自原文的哪个字符区间，
    start_s/end_s 是它在 chunk 音频内的相对秒，score 为对齐置信度（可选）。
    """

    char_start: int
    char_end: int
    start_s: float
    end_s: float
    score: float | None = None


@dataclass(frozen=True)
class SentenceTiming:
    """一个段落（子句或句子）的对齐时间（chunk 内相对秒，估计值）。

    confidence 为该段覆盖 token 的置信度均值，拿不到时为 None。
    """

    text: str
    char_start: int
    char_end: int
    start_s: float
    end_s: float
    confidence: float | None = None


def split_sentences(text: str) -> list[SentenceSpan]:
    """按句末/子句标点与换行把文本切成段落，并记录每段的字符区间。

    在句末标点（。！？.!?）基础上额外按子句标点（，；、;,:）切分，
    使长句拆分为更短的子句段。标点归属到前一段；去掉边界标点与空白后
    无实质内容的片段（如纯标点 "."、空白行）被跳过。返回的区间相对于
    传入的 text，供后续把 token 时间聚合回段落边界使用。
    """

    def has_content(piece: str) -> bool:
        # 去掉边界标点与空白后仍有字符，才算一个真正的段落
        return bool(piece.strip(SENTENCE_BOUNDARY).strip())

    spans: list[SentenceSpan] = []
    start = 0
    length = len(text)
    for index, char in enumerate(text):
        if char in SENTENCE_BOUNDARY:
            piece = text[start : index + 1]
            if has_content(piece):
                spans.append(SentenceSpan(text=piece, char_start=start, char_end=index + 1))
            start = index + 1
    # 处理结尾无标点的残句
    if start < length:
        piece = text[start:length]
        if has_content(piece):
            spans.append(SentenceSpan(text=piece, char_start=start, char_end=length))
    return spans


def aggregate_token_timings(
    sentences: list[SentenceSpan],
    tokens: list[TokenTiming],
) -> list[SentenceTiming]:
    """把 token 级对齐时间聚合到段级（纯逻辑，便于单测）。

    对每段取落在其字符区间内的 token：起始时间用首 token 的 start_s，
    结束时间用尾 token 的 end_s。段内无任何 token（如纯标点/数字被丢弃）
    时跳过该段——不臆造时间，避免用伪数据掩盖对齐缺口。
    """
    results: list[SentenceTiming] = []
    for span in sentences:
        covered = [
            tok
            for tok in tokens
            if tok.char_start >= span.char_start and tok.char_end <= span.char_end
        ]
        if not covered:
            continue
        start_s = min(tok.start_s for tok in covered)
        end_s = max(tok.end_s for tok in covered)
        scores = [tok.score for tok in covered if tok.score is not None]
        confidence = sum(scores) / len(scores) if scores else None
        results.append(
            SentenceTiming(
                text=span.text,
                char_start=span.char_start,
                char_end=span.char_end,
                start_s=start_s,
                end_s=end_s,
                confidence=confidence,
            )
        )
    return results


# region 强制对齐实现（重依赖隔离区，所有 torch/torchaudio/pypinyin 均 lazy import）

# emission 声学模型单例缓存：模型加载昂贵，首个 chunk 触发后全局复用。
# 键为 device 字符串，值为 (bundle, model, dictionary)。
_ALIGN_MODEL_CACHE: dict[str, object] = {}


def _romanize_with_spans(text: str) -> list[tuple[str, int, int]]:
    """把文本逐字符罗马化为 (token, char_start, char_end) 列表。

    汉字转无声调拼音（一个汉字→一个拼音音节 token，区间为该字单字符），
    ASCII 字母按连续词聚合为一个 token 并小写，数字/标点/空白丢弃
    （不参与对齐）。返回的字符区间用于把对齐结果还原回句子边界。
    """
    from pypinyin import Style, lazy_pinyin

    tokens: list[tuple[str, int, int]] = []
    ascii_buffer: list[str] = []
    ascii_start = -1

    def flush_ascii(end: int) -> None:
        nonlocal ascii_start
        if ascii_buffer:
            tokens.append(("".join(ascii_buffer).lower(), ascii_start, end))
            ascii_buffer.clear()
            ascii_start = -1

    for index, char in enumerate(text):
        if "一" <= char <= "鿿":
            # 汉字：先收掉缓冲的英文词，再单字转拼音
            flush_ascii(index)
            syllable = lazy_pinyin(char, style=Style.NORMAL)
            if syllable and syllable[0].strip():
                tokens.append((syllable[0].lower(), index, index + 1))
        elif char.isascii() and char.isalpha():
            if not ascii_buffer:
                ascii_start = index
            ascii_buffer.append(char)
        else:
            # 数字/标点/空白：作为英文词边界，自身不参与对齐
            flush_ascii(index)
    flush_ascii(len(text))
    return tokens


def _load_alignment_model(device: str):
    """懒加载并缓存 MMS_FA 强制对齐模型（含 bundle / model / 字典）。"""
    cached = _ALIGN_MODEL_CACHE.get(device)
    if cached is not None:
        return cached

    import torch  # noqa: F401  # 触发后端初始化
    from torchaudio.pipelines import MMS_FA as bundle

    model = bundle.get_model().to(device)
    dictionary = bundle.get_dict()
    entry = (bundle, model, dictionary)
    _ALIGN_MODEL_CACHE[device] = entry
    return entry


def align_chunk_sentences(
    waveform,
    sample_rate: int,
    text: str,
    *,
    device: str = "cpu",
) -> list[SentenceTiming]:
    """对单个 chunk 的波形做强制对齐，返回句级相对时间（估计值）。

    流程：句切分 → 逐字符拼音罗马化（保留字符区间）→ 映射 MMS_FA 字典 token →
    forced_align 得每 token 帧区间 → 帧率以实际 emission 长度反算成秒 →
    按句字符区间聚合 token 时间。

    waveform 接受一维 numpy 数组或 torch.Tensor（单声道，chunk 原始采样率）。
    任何依赖缺失或对齐失败由调用方捕获——本函数不吞错，让问题可暴露。
    """
    import torch
    import torchaudio.functional as AF

    sentences = split_sentences(text)
    if not sentences:
        return []

    bundle, model, dictionary = _load_alignment_model(device)

    # 统一成 [1, time] 的 float32 张量，并重采样到对齐模型要求的采样率
    if not isinstance(waveform, torch.Tensor):
        wav = torch.as_tensor(waveform, dtype=torch.float32)
    else:
        wav = waveform.to(dtype=torch.float32)
    if wav.ndim == 1:
        wav = wav.unsqueeze(0)
    target_sr = bundle.sample_rate
    if sample_rate != target_sr:
        wav = AF.resample(wav, orig_freq=sample_rate, new_freq=target_sr)
    wav = wav.to(device)

    # 罗马化并映射字典：保留每个 token 的源字符区间与其字典 id 序列
    romanized = _romanize_with_spans(text)
    token_ids: list[int] = []
    # token_ids 中每个 id 对应的源字符区间，用于把帧区间还原到字符位置
    id_spans: list[tuple[int, int]] = []
    for token, char_start, char_end in romanized:
        ids = [dictionary[ch] for ch in token if ch in dictionary]
        for tid in ids:
            token_ids.append(tid)
            id_spans.append((char_start, char_end))
    if not token_ids:
        return []

    with torch.inference_mode():
        emission, _ = model(wav)
        targets = torch.tensor([token_ids], dtype=torch.int32, device=device)
        aligned, scores = AF.forced_align(emission, targets, blank=0)

    # 帧→秒：以实际 emission 帧数反算每帧时长，不写死常数
    num_frames = emission.size(1)
    audio_seconds = wav.size(-1) / target_sr
    seconds_per_frame = audio_seconds / num_frames if num_frames > 0 else 0.0

    aligned_ids = aligned[0].tolist()
    score_list = scores[0].tolist() if scores is not None else None

    # 合并连续相同 token 的帧区间，得到每个 target token 的 [start_frame, end_frame)
    token_timings: list[TokenTiming] = []
    cursor = 0  # 指向 id_spans / token_ids 的位置
    frame = 0
    total = len(aligned_ids)
    while frame < total and cursor < len(token_ids):
        if aligned_ids[frame] == 0:
            # blank 帧，跳过
            frame += 1
            continue
        start_frame = frame
        # 同一 target token 可能占多帧，推进到下一个非重复 token
        while frame < total and aligned_ids[frame] == aligned_ids[start_frame]:
            frame += 1
        end_frame = frame
        char_start, char_end = id_spans[cursor]
        frame_scores = (
            [s for s in score_list[start_frame:end_frame]] if score_list is not None else []
        )
        token_timings.append(
            TokenTiming(
                char_start=char_start,
                char_end=char_end,
                start_s=start_frame * seconds_per_frame,
                end_s=end_frame * seconds_per_frame,
                score=(sum(frame_scores) / len(frame_scores)) if frame_scores else None,
            )
        )
        cursor += 1

    return aggregate_token_timings(sentences, token_timings)

# endregion 强制对齐实现
