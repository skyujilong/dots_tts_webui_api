from __future__ import annotations

import logging
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from . import db
from .audio import ChunkArtifact, merge_artifacts, write_chunk_text_artifacts
from .config import Settings
from .schemas import TtsParams
from .tts_adapter import TtsAdapter, create_tts_adapter

logger = logging.getLogger(__name__)


class SynthesisWorker:
    def __init__(self, *, settings: Settings, adapter: TtsAdapter | None = None):
        self.settings = settings
        self.adapter = adapter or create_tts_adapter(settings)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def model_loaded(self) -> bool:
        return self.adapter.model_loaded

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run_forever, name="dots-tts-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def run_forever(self) -> None:
        conn = db.connect(self.settings.db_path)
        db.init_db(conn)
        db.reset_running_jobs(conn)
        while not self._stop_event.is_set():
            try:
                processed = self.run_once(conn)
            except Exception:
                logger.exception("worker loop failed")
                processed = False
            if not processed:
                self._stop_event.wait(self.settings.worker_poll_interval_seconds)
        conn.close()

    def run_once(self, conn: Any | None = None) -> bool:
        owns_conn = conn is None
        if conn is None:
            conn = db.connect(self.settings.db_path)
            db.init_db(conn)
        try:
            job = db.claim_next_job(conn)
            if job is None:
                return False
            self.process_job(conn, job["id"])
            return True
        finally:
            if owns_conn:
                conn.close()

    def process_job(self, conn: Any, job_id: str) -> None:
        job = db.get_job(conn, job_id)
        if job is None:
            return
        if job["status"] == "cancel_requested":
            db.mark_job_status(conn, job_id=job_id, status="cancelled")
            return

        params = TtsParams.model_validate(job["request"])
        logger.info(
            "job synthesis params job_id=%s mode=%s text_len=%s text_sha256=%s prompt_text_len=%s "
            "prompt_audio_path=%s language=%s template_name=%s num_steps=%s guidance_scale=%s "
            "speaker_scale=%s ode_method=%s seed=%s normalize_text=%s silence_ms=%s chunk_min_chars=%s chunk_max_chars=%s",
            job_id,
            self.settings.mode,
            len(job["text"]),
            job["text_sha256"],
            len(params.prompt_text) if params.prompt_text else 0,
            params.prompt_audio_path,
            params.language,
            params.template_name,
            params.num_steps,
            params.guidance_scale,
            params.speaker_scale,
            params.ode_method,
            params.seed,
            params.normalize_text,
            params.silence_ms,
            params.chunk_min_chars,
            params.chunk_max_chars,
        )
        job_dir = self.settings.artifact_dir / job_id
        chunk_dir = job_dir / "chunks"
        artifacts: list[ChunkArtifact] = []
        try:
            while True:
                job = db.get_job(conn, job_id)
                if job is None:
                    return
                if job["status"] == "cancel_requested":
                    db.mark_job_status(conn, job_id=job_id, status="cancelled")
                    return

                chunk = db.get_next_pending_chunk(conn, job_id)
                if chunk is None:
                    break

                db.mark_chunk_running(conn, chunk["id"])
                logger.info(
                    "chunk synthesis start job_id=%s chunk_id=%s chunk_index=%s text_len=%s char_start=%s char_end=%s "
                    "language=%s template_name=%s num_steps=%s guidance_scale=%s speaker_scale=%s ode_method=%s seed=%s",
                    job_id,
                    chunk["id"],
                    chunk["chunk_index"],
                    len(chunk["text"]),
                    chunk["char_start"],
                    chunk["char_end"],
                    params.language,
                    params.template_name,
                    params.num_steps,
                    params.guidance_scale,
                    params.speaker_scale,
                    params.ode_method,
                    params.seed,
                )
                out_wav_path = chunk_dir / f"{chunk['chunk_index']:04d}.wav"
                started = time.monotonic()
                try:
                    result = self.adapter.synthesize_chunk(
                        text=chunk["text"],
                        out_wav_path=out_wav_path,
                        params=params,
                    )
                    elapsed = time.monotonic() - started
                    logger.info(
                        "chunk synthesis succeeded job_id=%s chunk_id=%s chunk_index=%s elapsed_seconds=%.3f "
                        "sample_rate=%s wav_path=%s metrics=%s",
                        job_id,
                        chunk["id"],
                        chunk["chunk_index"],
                        elapsed,
                        result.sample_rate,
                        result.wav_path,
                        result.metrics,
                    )
                    if elapsed > self.settings.chunk_timeout_seconds:
                        raise TimeoutError(f"chunk exceeded timeout: {elapsed:.2f}s")
                    text_path, tts_path = write_chunk_text_artifacts(
                        chunk_dir=chunk_dir,
                        chunk_index=chunk["chunk_index"],
                        text=chunk["text"],
                        metrics=result.metrics,
                    )
                    db.mark_chunk_succeeded(
                        conn,
                        chunk_id=chunk["id"],
                        wav_path=result.wav_path,
                        text_path=str(text_path),
                        tts_path=str(tts_path),
                        metrics=result.metrics,
                    )
                    artifacts.append(
                        ChunkArtifact(
                            chunk_index=chunk["chunk_index"],
                            text=chunk["text"],
                            wav_path=Path(result.wav_path),
                            text_path=text_path,
                            tts_path=tts_path,
                            metrics=result.metrics,
                            tts_text=result.tts_text,
                        )
                    )
                except Exception as exc:
                    message = str(exc) or exc.__class__.__name__
                    db.mark_chunk_failed(conn, chunk_id=chunk["id"], error_message=message)
                    db.mark_job_status(
                        conn,
                        job_id=job_id,
                        status="failed",
                        error_code=exc.__class__.__name__,
                        error_message=message,
                    )
                    logger.error("job %s chunk %s failed: %s", job_id, chunk["chunk_index"], message)
                    return

            artifacts = []
            for chunk in db.get_chunks(conn, job_id):
                if chunk["status"] == "succeeded":
                    artifacts.append(
                        ChunkArtifact(
                            chunk_index=chunk["chunk_index"],
                            text=chunk["text"],
                            wav_path=Path(chunk["wav_path"]),
                            text_path=Path(chunk["text_path"]),
                            tts_path=Path(chunk["tts_path"]),
                            metrics=chunk.get("metrics") or {},
                            # db 未持久化 tts_text 列，重建时回退用展示文本。
                            # normalize_text=False（默认）时二者一致，对齐无影响；
                            # 开启 normalize_text 时句级对齐可能因文本差异略有偏移。
                            tts_text=chunk["text"],
                        )
                    )

            final = merge_artifacts(
                job_id=job_id,
                job_dir=job_dir,
                chunks=artifacts,
                silence_ms=params.silence_ms,
                enable_sentence_alignment=self.settings.enable_sentence_alignment,
                alignment_device=self.settings.alignment_device,
                enable_loudnorm=self.settings.enable_loudnorm,
            )
            db.mark_job_status(
                conn,
                job_id=job_id,
                status="succeeded",
                final_wav_path=str(final.final_wav_path),
                final_text_path=str(final.final_text_path),
                final_tts_path=str(final.final_tts_path),
                manifest_path=str(final.manifest_path),
            )
            # 句级对齐失败不影响 job 成功，但需如实记录便于排查（不静默吞错）。
            if final.alignment_error is not None:
                logger.warning("job %s sentence alignment skipped: %s", job_id, final.alignment_error)
                db.add_event(
                    conn,
                    job_id=job_id,
                    level="warning",
                    message="sentence alignment skipped",
                    data={"error": final.alignment_error},
                )
            # 响度归一化失败/降级同样不影响 job 成功（成品已是未归一化的可用音频），
            # 但需如实记录，避免"以为归一化了其实没有"（不静默吞错）。
            if final.loudnorm_error is not None:
                logger.warning("job %s loudness normalization skipped: %s", job_id, final.loudnorm_error)
                db.add_event(
                    conn,
                    job_id=job_id,
                    level="warning",
                    message="loudness normalization skipped",
                    data={"error": final.loudnorm_error},
                )
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            db.add_event(conn, job_id=job_id, level="error", message="job failed", data={"traceback": traceback.format_exc(limit=5)})
            db.mark_job_status(
                conn,
                job_id=job_id,
                status="failed",
                error_code=exc.__class__.__name__,
                error_message=message,
            )
            logger.error("job %s failed: %s", job_id, message)
