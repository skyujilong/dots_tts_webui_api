from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .schemas import DbChunkInput


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'cancel_requested', 'succeeded', 'failed', 'cancelled')),
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    request_json TEXT NOT NULL,
    chunk_count INTEGER NOT NULL CHECK (chunk_count >= 0),
    completed_chunks INTEGER NOT NULL DEFAULT 0 CHECK (completed_chunks >= 0),
    error_code TEXT,
    error_message TEXT,
    final_wav_path TEXT,
    final_text_path TEXT,
    final_tts_path TEXT,
    manifest_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    cancelled_at TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    text TEXT NOT NULL,
    char_start INTEGER NOT NULL CHECK (char_start >= 0),
    char_end INTEGER NOT NULL CHECK (char_end >= 0),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')),
    wav_path TEXT,
    text_path TEXT,
    tts_path TEXT,
    metrics_json TEXT,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(job_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
    level TEXT NOT NULL CHECK (level IN ('info', 'warning', 'error')),
    message TEXT NOT NULL,
    data_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_chunks_job_index ON chunks(job_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id, id);
"""


TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("request_json", "metrics_json", "data_json"):
        if key in data and data[key] is not None:
            data[key.removesuffix("_json")] = json.loads(data.pop(key))
    return data


def create_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    text: str,
    text_sha256: str,
    request: dict[str, Any],
    chunks: list[DbChunkInput],
) -> None:
    now = utc_now()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO jobs (
                id, status, text, text_sha256, request_json, chunk_count,
                completed_chunks, created_at, updated_at
            ) VALUES (?, 'queued', ?, ?, ?, ?, 0, ?, ?)
            """,
            (job_id, text, text_sha256, json.dumps(request, ensure_ascii=False), len(chunks), now, now),
        )
        conn.executemany(
            """
            INSERT INTO chunks (job_id, chunk_index, text, char_start, char_end, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            [(job_id, chunk.chunk_index, chunk.text, chunk.char_start, chunk.char_end) for chunk in chunks],
        )
        add_event(conn, job_id=job_id, level="info", message="job queued", commit=False)


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def list_jobs(conn: sqlite3.Connection, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [row_to_dict(row) for row in rows if row is not None]


def get_chunks(conn: sqlite3.Connection, job_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM chunks WHERE job_id = ? ORDER BY chunk_index",
        (job_id,),
    ).fetchall()
    return [row_to_dict(row) for row in rows if row is not None]


def get_events(conn: sqlite3.Connection, job_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM job_events WHERE job_id = ? ORDER BY id DESC LIMIT ?",
        (job_id, limit),
    ).fetchall()
    return [row_to_dict(row) for row in reversed(rows) if row is not None]


def add_event(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    level: str,
    message: str,
    chunk_id: int | None = None,
    data: dict[str, Any] | None = None,
    commit: bool = True,
) -> int:
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO job_events (job_id, chunk_id, level, message, data_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (job_id, chunk_id, level, message, json.dumps(data, ensure_ascii=False) if data else None, now),
    )
    if commit:
        conn.commit()
    return int(cursor.lastrowid)


def claim_next_job(conn: sqlite3.Connection) -> dict[str, Any] | None:
    now = utc_now()
    with transaction(conn):
        row = conn.execute(
            "SELECT id FROM jobs WHERE status IN ('queued', 'cancel_requested') ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        job_id = row["id"]
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = CASE status WHEN 'queued' THEN 'running' ELSE status END,
                started_at = CASE status WHEN 'queued' THEN COALESCE(started_at, ?) ELSE started_at END,
                updated_at = ?
            WHERE id = ? AND status IN ('queued', 'cancel_requested')
            """,
            (now, now, job_id),
        )
        if cursor.rowcount != 1:
            return None
        add_event(conn, job_id=job_id, level="info", message="job claimed", commit=False)
    return get_job(conn, job_id)


def mark_job_status(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    final_wav_path: str | None = None,
    final_text_path: str | None = None,
    final_tts_path: str | None = None,
    manifest_path: str | None = None,
) -> None:
    now = utc_now()
    completed_at = now if status in {"succeeded", "failed"} else None
    cancelled_at = now if status == "cancelled" else None
    with transaction(conn):
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, error_code = ?, error_message = ?,
                final_wav_path = COALESCE(?, final_wav_path),
                final_text_path = COALESCE(?, final_text_path),
                final_tts_path = COALESCE(?, final_tts_path),
                manifest_path = COALESCE(?, manifest_path),
                updated_at = ?,
                completed_at = COALESCE(?, completed_at),
                cancelled_at = COALESCE(?, cancelled_at)
            WHERE id = ?
            """,
            (
                status,
                error_code,
                error_message,
                final_wav_path,
                final_text_path,
                final_tts_path,
                manifest_path,
                now,
                completed_at,
                cancelled_at,
                job_id,
            ),
        )
        add_event(conn, job_id=job_id, level="error" if status == "failed" else "info", message=f"job {status}", commit=False)


def request_cancel(conn: sqlite3.Connection, job_id: str) -> bool:
    now = utc_now()
    with transaction(conn):
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = 'cancel_requested', updated_at = ?
            WHERE id = ? AND status IN ('queued', 'running')
            """,
            (now, job_id),
        )
        if cursor.rowcount == 1:
            add_event(conn, job_id=job_id, level="warning", message="cancel requested", commit=False)
            return True
    return False


def delete_job(conn: sqlite3.Connection, job_id: str) -> bool:
    with transaction(conn):
        cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return cursor.rowcount == 1


def get_next_pending_chunk(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            """
            SELECT * FROM chunks
            WHERE job_id = ? AND status = 'pending'
            ORDER BY chunk_index LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    )


def mark_chunk_running(conn: sqlite3.Connection, chunk_id: int) -> None:
    now = utc_now()
    conn.execute(
        "UPDATE chunks SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
        (now, chunk_id),
    )
    conn.commit()


def mark_chunk_succeeded(
    conn: sqlite3.Connection,
    *,
    chunk_id: int,
    wav_path: str,
    text_path: str,
    tts_path: str,
    metrics: dict[str, Any] | None = None,
) -> None:
    now = utc_now()
    with transaction(conn):
        row = conn.execute("SELECT job_id FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown chunk_id: {chunk_id}")
        job_id = row["job_id"]
        conn.execute(
            """
            UPDATE chunks
            SET status = 'succeeded', wav_path = ?, text_path = ?, tts_path = ?,
                metrics_json = ?, completed_at = ?
            WHERE id = ?
            """,
            (wav_path, text_path, tts_path, json.dumps(metrics or {}, ensure_ascii=False), now, chunk_id),
        )
        conn.execute(
            "UPDATE jobs SET completed_chunks = completed_chunks + 1, updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        add_event(conn, job_id=job_id, chunk_id=chunk_id, level="info", message="chunk succeeded", commit=False)


def mark_chunk_failed(conn: sqlite3.Connection, *, chunk_id: int, error_message: str) -> None:
    now = utc_now()
    with transaction(conn):
        row = conn.execute("SELECT job_id FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown chunk_id: {chunk_id}")
        job_id = row["job_id"]
        conn.execute(
            """
            UPDATE chunks
            SET status = 'failed', error_message = ?, completed_at = ?
            WHERE id = ?
            """,
            (error_message, now, chunk_id),
        )
        add_event(conn, job_id=job_id, chunk_id=chunk_id, level="error", message="chunk failed", data={"error": error_message}, commit=False)


def reset_running_jobs(conn: sqlite3.Connection) -> int:
    now = utc_now()
    with transaction(conn):
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = 'queued', updated_at = ?, started_at = NULL
            WHERE status = 'running'
            """,
            (now,),
        )
        conn.execute(
            "UPDATE chunks SET status = 'pending', started_at = NULL WHERE status = 'running'"
        )
    return int(cursor.rowcount)


def queue_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status").fetchall()
    return {row["status"]: int(row["count"]) for row in rows}
