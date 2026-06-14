from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .schemas import SUPPORTED_AUDIO_SUFFIXES, VOICE_NAME_PATTERN

PROMPT_TEXT_FILE = "prompt_text"


@dataclass(frozen=True)
class VoicePreset:
    name: str
    audio_path: Path
    prompt_text: str | None
    created_at: datetime

    @property
    def audio_url(self) -> str:
        return f"/api/voices/{self.name}/audio"


def validate_voice_name(name: str, *, max_length: int = 64) -> str:
    if not name or len(name) > max_length or not VOICE_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"voice name must match {VOICE_NAME_PATTERN.pattern} and be at most {max_length} characters")
    return name


def validate_audio_suffix(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        raise ValueError(f"audio suffix must be one of {SUPPORTED_AUDIO_SUFFIXES}")


def ensure_inside_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"path is outside root: {path}")
    return resolved


def read_prompt_texts(voices_dir: Path) -> dict[str, str]:
    mapping_path = voices_dir / PROMPT_TEXT_FILE
    if not mapping_path.exists():
        return {}
    mapping: dict[str, str] = {}
    for line in mapping_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "|" not in line:
            continue
        name, text = line.split("|", 1)
        name = name.strip()
        if name:
            mapping[name] = text
    return mapping


def write_prompt_texts(voices_dir: Path, mapping: dict[str, str]) -> None:
    voices_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = voices_dir / PROMPT_TEXT_FILE
    lines = [f"{name}|{text}" for name, text in sorted(mapping.items())]
    mapping_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def discover_voices(voices_dir: Path) -> dict[str, VoicePreset]:
    voices_dir.mkdir(parents=True, exist_ok=True)
    prompt_texts = read_prompt_texts(voices_dir)
    presets: dict[str, VoicePreset] = {}
    for audio_path in sorted(voices_dir.iterdir()):
        if not audio_path.is_file() or audio_path.name == PROMPT_TEXT_FILE:
            continue
        if audio_path.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
            continue
        name = audio_path.stem
        if not VOICE_NAME_PATTERN.fullmatch(name):
            continue
        stat = audio_path.stat()
        presets[name] = VoicePreset(
            name=name,
            audio_path=audio_path,
            prompt_text=prompt_texts.get(name),
            created_at=datetime.fromtimestamp(stat.st_mtime, UTC),
        )
    return presets


def save_voice(
    *,
    voices_dir: Path,
    name: str,
    source_audio_path: Path,
    prompt_text: str | None,
    max_name_length: int = 64,
    max_audio_size_mb: int = 20,
) -> VoicePreset:
    validate_voice_name(name, max_length=max_name_length)
    validate_audio_suffix(source_audio_path)
    if not source_audio_path.exists() or not source_audio_path.is_file():
        raise ValueError(f"audio file does not exist: {source_audio_path}")
    max_bytes = max_audio_size_mb * 1024 * 1024
    if source_audio_path.stat().st_size > max_bytes:
        raise ValueError(f"audio file exceeds {max_audio_size_mb} MB")

    voices_dir.mkdir(parents=True, exist_ok=True)
    dest = voices_dir / f"{name}{source_audio_path.suffix.lower()}"
    ensure_inside_root(dest, voices_dir)
    for existing in voices_dir.glob(f"{name}.*"):
        if existing.is_file() and existing.name != dest.name:
            existing.unlink()
    shutil.copyfile(source_audio_path, dest)

    mapping = read_prompt_texts(voices_dir)
    if prompt_text:
        mapping[name] = prompt_text
    else:
        mapping.pop(name, None)
    write_prompt_texts(voices_dir, mapping)
    return discover_voices(voices_dir)[name]


def delete_voice(*, voices_dir: Path, name: str, max_name_length: int = 64) -> bool:
    validate_voice_name(name, max_length=max_name_length)
    voices_dir.mkdir(parents=True, exist_ok=True)
    removed = False
    for audio_path in voices_dir.glob(f"{name}.*"):
        if audio_path.is_file() and audio_path.suffix.lower() in SUPPORTED_AUDIO_SUFFIXES:
            ensure_inside_root(audio_path, voices_dir)
            audio_path.unlink()
            removed = True
    mapping = read_prompt_texts(voices_dir)
    if name in mapping:
        mapping.pop(name, None)
        write_prompt_texts(voices_dir, mapping)
        removed = True
    return removed


def get_voice_audio_path(*, voices_dir: Path, name: str, max_name_length: int = 64) -> Path:
    validate_voice_name(name, max_length=max_name_length)
    presets = discover_voices(voices_dir)
    if name not in presets:
        raise FileNotFoundError(name)
    return ensure_inside_root(presets[name].audio_path, voices_dir)
