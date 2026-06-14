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
    current_parts: list[str] = []
    current_start = 0
    cursor = 0
    lines = preprocessed.split("\n")
    for line_index, line in enumerate(lines):
        line_start = cursor
        line_end = line_start + len(line)
        if not current_parts:
            current_start = line_start
        current_parts.append(line)
        current_text = "\n".join(current_parts)
        cursor = line_end + (1 if line_index != len(lines) - 1 else 0)
        if len(current_text) >= min_chars:
            chunks.append((current_text, current_start, line_end))
            current_parts = []
    if current_parts:
        current_text = "\n".join(current_parts)
        chunks.append((current_text, current_start, len(preprocessed)))

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
