from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Annotated, Any

from pydantic import ValidationError
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from . import db
from .chunking import chunk_text_by_newline
from .config import Settings
from .schemas import (
    ConfigResponse,
    DbChunkInput,
    HealthResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobEventResponse,
    JobListItem,
    JobStatusResponse,
    SUPPORTED_AUDIO_SUFFIXES,
    SUPPORTED_LANGUAGE_CODE_BY_NAME,
    SUPPORTED_ODE_METHODS,
    SUPPORTED_TEMPLATE_NAMES,
    TtsParams,
    VoicePresetResponse,
)
from .voices import delete_voice, discover_voices, ensure_inside_root, get_voice_audio_path, save_voice, validate_audio_suffix

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(request: Request):
    return request.app.state.db_conn


def _artifact_url(job_id: str, path: str | None) -> str | None:
    if not path:
        return None
    return f"/api/jobs/{job_id}/artifacts/{Path(path).name}"


def _timeline_url(settings: Settings, job_id: str) -> str | None:
    """推导 timeline.json 的下载地址。

    timeline 不入库（schema 用 IF NOT EXISTS，旧库不会迁移新列），
    因此以产物文件是否实际存在为准：存在才返回 URL，缺失返回 None，
    避免返回一个指向不存在文件的伪 URL 掩盖问题。
    """
    timeline_path = ensure_inside_root(settings.artifact_dir / job_id / "timeline.json", settings.artifact_dir)
    if not timeline_path.is_file():
        return None
    return f"/api/jobs/{job_id}/artifacts/timeline.json"


def _sentences_url(settings: Settings, job_id: str) -> str | None:
    """推导 sentences.json 的下载地址。

    与 timeline 同理不入库，以文件是否实际存在为准：句级对齐是可失败的增强项，
    失败时文件不存在则返回 None，避免给出指向不存在文件的伪 URL 掩盖问题。
    """
    sentences_path = ensure_inside_root(settings.artifact_dir / job_id / "sentences.json", settings.artifact_dir)
    if not sentences_path.is_file():
        return None
    return f"/api/jobs/{job_id}/artifacts/sentences.json"


def _voice_response(preset) -> VoicePresetResponse:
    return VoicePresetResponse(
        name=preset.name,
        audio_url=preset.audio_url,
        prompt_text=preset.prompt_text,
        created_at=preset.created_at,
    )


def _sha256_text(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _job_response(request: Request, job_id: str) -> JobStatusResponse:
    conn = get_conn(request)
    job = db.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    chunks = [
        {
            "id": chunk["id"],
            "chunk_index": chunk["chunk_index"],
            "status": chunk["status"],
            "char_start": chunk["char_start"],
            "char_end": chunk["char_end"],
            "wav_path": chunk["wav_path"],
            "error_message": chunk["error_message"],
            "started_at": chunk["started_at"],
            "completed_at": chunk["completed_at"],
        }
        for chunk in db.get_chunks(conn, job_id)
    ]
    events = [
        JobEventResponse(
            id=event["id"],
            chunk_id=event["chunk_id"],
            level=event["level"],
            message=event["message"],
            data=event.get("data"),
            created_at=event["created_at"],
        )
        for event in db.get_events(conn, job_id)
    ]
    return JobStatusResponse(
        id=job["id"],
        status=job["status"],
        chunk_count=job["chunk_count"],
        completed_chunks=job["completed_chunks"],
        error_code=job["error_code"],
        error_message=job["error_message"],
        final_wav_url=_artifact_url(job_id, job["final_wav_path"]),
        final_text_url=_artifact_url(job_id, job["final_text_path"]),
        final_tts_url=_artifact_url(job_id, job["final_tts_path"]),
        final_timeline_url=_timeline_url(get_settings(request), job_id),
        final_sentences_url=_sentences_url(get_settings(request), job_id),
        manifest_url=_artifact_url(job_id, job["manifest_path"]),
        chunks=chunks,
        events=events,
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        started_at=job["started_at"],
        completed_at=job["completed_at"],
        cancelled_at=job["cancelled_at"],
    )


def _request_with_voice(settings: Settings, payload: JobCreateRequest) -> JobCreateRequest:
    if not payload.voice_name:
        return payload
    presets = discover_voices(settings.voices_dir)
    preset = presets.get(payload.voice_name)
    if preset is None:
        raise HTTPException(status_code=400, detail="voice_name not found")
    data = payload.model_dump()
    data["prompt_audio_path"] = str(preset.audio_path)
    data["prompt_text"] = preset.prompt_text
    data["voice_name"] = None
    return JobCreateRequest.model_validate(data)


def _create_job_from_payload(request: Request, payload: JobCreateRequest, *, job_id: str | None = None) -> JobCreateResponse:
    settings = get_settings(request)
    if len(payload.text) > settings.max_job_chars:
        raise HTTPException(status_code=413, detail="text exceeds DOTS_MAX_JOB_CHARS")
    payload = _request_with_voice(settings, payload)
    chunk_min = payload.chunk_min_chars or settings.chunk_min_chars
    chunk_max = payload.chunk_max_chars or settings.chunk_max_chars
    chunks = chunk_text_by_newline(payload.text, chunk_min, chunk_max)
    if not chunks:
        raise HTTPException(status_code=400, detail="text produced no chunks")

    job_id = job_id or uuid.uuid4().hex
    request_json = payload.model_dump()
    request_json["chunk_min_chars"] = chunk_min
    request_json["chunk_max_chars"] = chunk_max
    text_sha256 = hashlib.sha256(payload.text.encode("utf-8")).hexdigest()
    prompt_path = Path(payload.prompt_audio_path) if payload.prompt_audio_path else None
    logger.info(
        "job queued job_id=%s mode=%s text_len=%s text_sha256=%s prompt_text_len=%s prompt_text_sha256=%s "
        "voice_name=%s prompt_audio_path=%s prompt_audio_exists=%s prompt_audio_size=%s language=%s "
        "template_name=%s num_steps=%s guidance_scale=%s speaker_scale=%s ode_method=%s seed=%s "
        "normalize_text=%s silence_ms=%s chunk_min_chars=%s chunk_max_chars=%s chunk_count=%s",
        job_id,
        settings.mode,
        len(payload.text),
        text_sha256,
        len(payload.prompt_text) if payload.prompt_text else 0,
        _sha256_text(payload.prompt_text),
        payload.voice_name,
        str(prompt_path) if prompt_path else None,
        prompt_path.exists() if prompt_path else None,
        prompt_path.stat().st_size if prompt_path and prompt_path.exists() else None,
        payload.language,
        payload.template_name,
        payload.num_steps,
        payload.guidance_scale,
        payload.speaker_scale,
        payload.ode_method,
        payload.seed,
        payload.normalize_text,
        payload.silence_ms,
        chunk_min,
        chunk_max,
        len(chunks),
    )
    db.create_job(
        get_conn(request),
        job_id=job_id,
        text=payload.text,
        text_sha256=text_sha256,
        request=request_json,
        chunks=[
            DbChunkInput(
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
            )
            for chunk in chunks
        ],
    )
    return JobCreateResponse(job_id=job_id, poll_url=f"/api/jobs/{job_id}")


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = get_settings(request)
    worker = request.app.state.worker
    return HealthResponse(
        ok=True,
        mode=settings.mode,
        worker_running=worker.running,
        model_loaded=worker.model_loaded,
        queue=db.queue_counts(get_conn(request)),
    )


@router.get("/config", response_model=ConfigResponse)
def config(request: Request) -> ConfigResponse:
    settings = get_settings(request)
    return ConfigResponse(
        mock_tts=settings.mock_tts,
        supported_languages=SUPPORTED_LANGUAGE_CODE_BY_NAME,
        supported_template_names=SUPPORTED_TEMPLATE_NAMES,
        supported_ode_methods=SUPPORTED_ODE_METHODS,
        defaults={
            "silence_ms": settings.default_silence_ms,
            "chunk_min_chars": settings.chunk_min_chars,
            "chunk_max_chars": settings.chunk_max_chars,
            "num_steps": settings.default_num_steps,
            "guidance_scale": settings.default_guidance_scale,
            "speaker_scale": settings.default_speaker_scale,
            "ode_method": settings.default_ode_method,
            "seed": settings.default_seed,
        },
        ranges={
            "num_steps": {"min": 1, "max": 32, "step": 1},
            "guidance_scale": {"min": 1.0, "max": 3.0, "step": 0.1},
            "speaker_scale": {"min": 0.0, "max": 3.0, "step": 0.1},
        },
        max_job_chars=settings.max_job_chars,
        voice_max_audio_size_mb=settings.voice_max_audio_size_mb,
    )


@router.get("/voices", response_model=list[VoicePresetResponse])
def list_voices(request: Request) -> list[VoicePresetResponse]:
    settings = get_settings(request)
    return [_voice_response(preset) for preset in discover_voices(settings.voices_dir).values()]


@router.post("/voices", response_model=VoicePresetResponse)
async def create_voice(
    request: Request,
    name: Annotated[str, Form()],
    audio: Annotated[UploadFile, File()],
    prompt_text: Annotated[str | None, Form()] = None,
) -> VoicePresetResponse:
    settings = get_settings(request)
    suffix = Path(audio.filename or "").suffix.lower()
    if suffix not in SUPPORTED_AUDIO_SUFFIXES:
        raise HTTPException(status_code=400, detail="unsupported audio format")
    temp_dir = settings.data_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}{suffix}"
    try:
        size = 0
        max_bytes = settings.voice_max_audio_size_mb * 1024 * 1024
        with temp_path.open("wb") as handle:
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail="audio file too large")
                handle.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="audio file is empty")
        try:
            preset = save_voice(
                voices_dir=settings.voices_dir,
                name=name,
                source_audio_path=temp_path,
                prompt_text=prompt_text,
                max_name_length=settings.voice_name_max_length,
                max_audio_size_mb=settings.voice_max_audio_size_mb,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _voice_response(preset)
    finally:
        temp_path.unlink(missing_ok=True)


@router.get("/voices/{name}/audio")
def voice_audio(request: Request, name: str) -> FileResponse:
    settings = get_settings(request)
    try:
        audio_path = get_voice_audio_path(
            voices_dir=settings.voices_dir,
            name=name,
            max_name_length=settings.voice_name_max_length,
        )
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="voice not found") from None
    return FileResponse(audio_path)


@router.delete("/voices/{name}")
def remove_voice(request: Request, name: str) -> dict[str, bool]:
    settings = get_settings(request)
    try:
        removed = delete_voice(voices_dir=settings.voices_dir, name=name, max_name_length=settings.voice_name_max_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="voice not found")
    return {"deleted": True}


@router.post("/jobs", response_model=JobCreateResponse)
def create_job(request: Request, payload: JobCreateRequest) -> JobCreateResponse:
    return _create_job_from_payload(request, payload)


@router.post("/jobs/form", response_model=JobCreateResponse)
async def create_job_form(
    request: Request,
    text: Annotated[str, Form()],
    prompt_audio: Annotated[UploadFile | None, File()] = None,
    prompt_text: Annotated[str | None, Form()] = None,
    silence_ms: Annotated[int | None, Form()] = None,
    num_steps: Annotated[int | None, Form()] = None,
    guidance_scale: Annotated[float | None, Form()] = None,
    speaker_scale: Annotated[float | None, Form()] = None,
    ode_method: Annotated[str | None, Form()] = None,
    template_name: Annotated[str | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
    seed: Annotated[int | None, Form()] = None,
    chunk_min_chars: Annotated[int | None, Form()] = None,
    chunk_max_chars: Annotated[int | None, Form()] = None,
) -> JobCreateResponse:
    settings = get_settings(request)
    job_id = uuid.uuid4().hex
    prompt_audio_path: str | None = None
    if prompt_audio and prompt_audio.filename:
        suffix = Path(prompt_audio.filename).suffix.lower()
        if suffix not in SUPPORTED_AUDIO_SUFFIXES:
            raise HTTPException(status_code=400, detail="unsupported audio format")
        input_dir = settings.artifact_dir / job_id / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        target = ensure_inside_root(input_dir / f"prompt{suffix}", settings.artifact_dir)
        size = 0
        max_bytes = settings.voice_max_audio_size_mb * 1024 * 1024
        with target.open("wb") as handle:
            while chunk := await prompt_audio.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    shutil.rmtree(settings.artifact_dir / job_id, ignore_errors=True)
                    raise HTTPException(status_code=413, detail="audio file too large")
                handle.write(chunk)
        if size == 0:
            shutil.rmtree(settings.artifact_dir / job_id, ignore_errors=True)
            raise HTTPException(status_code=400, detail="prompt audio file is empty")
        validate_audio_suffix(target)
        prompt_audio_path = str(target)

    raw: dict[str, Any] = {
        "text": text,
        "prompt_audio_path": prompt_audio_path,
        "prompt_text": prompt_text,
        "silence_ms": silence_ms,
        "num_steps": num_steps,
        "guidance_scale": guidance_scale,
        "speaker_scale": speaker_scale,
        "ode_method": ode_method,
        "template_name": template_name,
        "language": language,
        "seed": seed,
        "chunk_min_chars": chunk_min_chars,
        "chunk_max_chars": chunk_max_chars,
    }
    try:
        payload = JobCreateRequest.model_validate({k: v for k, v in raw.items() if v is not None})
    except ValidationError as exc:
        shutil.rmtree(settings.artifact_dir / job_id, ignore_errors=True)
        raise HTTPException(status_code=400, detail=exc.errors(include_url=False)) from exc
    return _create_job_from_payload(request, payload, job_id=job_id)


@router.get("/jobs", response_model=list[JobListItem])
def jobs(request: Request, status: str | None = None, limit: int = 50) -> list[JobListItem]:
    rows = db.list_jobs(get_conn(request), status=status, limit=min(max(limit, 1), 200))
    return [
        JobListItem(
            id=row["id"],
            status=row["status"],
            text_sha256=row["text_sha256"],
            text_preview=(row["text"][:80] + ("…" if len(row["text"]) > 80 else "")),
            chunk_count=row["chunk_count"],
            completed_chunks=row["completed_chunks"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(request: Request, job_id: str) -> JobStatusResponse:
    return _job_response(request, job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict[str, bool]:
    job = db.get_job(get_conn(request), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"cancel_requested": db.request_cancel(get_conn(request), job_id)}


@router.delete("/jobs/{job_id}")
def remove_job(request: Request, job_id: str) -> dict[str, bool]:
    settings = get_settings(request)
    conn = get_conn(request)
    job = db.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] in {"queued", "running", "cancel_requested"}:
        db.request_cancel(conn, job_id)
    job_dir = ensure_inside_root(settings.artifact_dir / job_id, settings.artifact_dir)
    deleted = db.delete_job(conn, job_id)
    shutil.rmtree(job_dir, ignore_errors=True)
    return {"deleted": deleted}


@router.get("/jobs/{job_id}/artifacts/{artifact_name}")
def artifact(request: Request, job_id: str, artifact_name: str) -> FileResponse:
    if artifact_name not in {"final.wav", "final.txt", "final.tts", "manifest.json", "timeline.json", "sentences.json"}:
        raise HTTPException(status_code=404, detail="artifact not found")
    settings = get_settings(request)
    job_dir = ensure_inside_root(settings.artifact_dir / job_id, settings.artifact_dir)
    artifact_path = ensure_inside_root(job_dir / artifact_name, settings.artifact_dir)
    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(artifact_path)
