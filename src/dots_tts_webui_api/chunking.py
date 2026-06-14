from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    text: str
    char_start: int
    char_end: int


SPLIT_PATTERN = re.compile(r"[。！？.!?\n]")


def preprocess_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line for line in normalized.split("\n") if line.strip())


def _find_first_period_split(text: str, start: int, min_chars: int, max_chars: int, stop: int) -> int | None:
    search_start = start + min_chars
    search_stop = min(stop, start + max_chars)
    candidates = [
        index
        for index in (text.find(".", search_start, search_stop), text.find("。", search_start, search_stop))
        if index != -1
    ]
    if not candidates:
        return None
    return min(candidates) + 1


def _split_oversized(text: str, start: int, max_chars: int) -> list[tuple[str, int, int]]:
    pieces: list[tuple[str, int, int]] = []
    cursor = 0
    length = len(text)
    while cursor < length:
        remaining = length - cursor
        if remaining <= max_chars:
            piece = text[cursor:]
            if piece.strip():
                pieces.append((piece, start + cursor, start + length))
            break

        window = text[cursor : cursor + max_chars]
        split_at = -1
        for match in SPLIT_PATTERN.finditer(window):
            split_at = match.end()
        if split_at <= 0:
            split_at = max_chars

        piece = text[cursor : cursor + split_at]
        if piece.strip():
            pieces.append((piece, start + cursor, start + cursor + split_at))
        cursor += split_at
        while cursor < length and text[cursor] == "\n":
            cursor += 1
    return pieces


def chunk_text_by_newline(text: str, min_chars: int, max_chars: int) -> list[TextChunk]:
    if min_chars <= 0 or max_chars <= 0:
        raise ValueError("min_chars and max_chars must be positive")
    if min_chars > max_chars:
        raise ValueError("min_chars must be <= max_chars")

    preprocessed = preprocess_text(text)
    if not preprocessed:
        return []

    chunks: list[tuple[str, int, int]] = []
    start = 0
    length = len(preprocessed)
    while start < length:
        while start < length and preprocessed[start] == "\n":
            start += 1
        if start >= length:
            break

        newline_index = preprocessed.find("\n", start + min_chars)
        if newline_index == -1:
            end = length
        elif newline_index - start <= max_chars:
            end = newline_index
        else:
            period_end = _find_first_period_split(preprocessed, start, min_chars, max_chars, newline_index)
            end = period_end if period_end is not None else newline_index

        chunk_text = preprocessed[start:end]
        if chunk_text.strip():
            chunks.append((chunk_text, start, end))
        start = end

    final: list[TextChunk] = []
    for chunk_text, start, end in chunks:
        pieces = [(chunk_text, start, end)] if len(chunk_text) <= max_chars else _split_oversized(chunk_text, start, max_chars)
        for piece_text, piece_start, piece_end in pieces:
            if piece_text.strip():
                final.append(
                    TextChunk(
                        chunk_index=len(final),
                        text=piece_text,
                        char_start=piece_start,
                        char_end=piece_end,
                    )
                )
    return final
