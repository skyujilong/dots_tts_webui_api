from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from dots_tts_webui_api.chunking import chunk_text_by_newline
from dots_tts_webui_api.db import connect, create_job, get_chunks, get_events, get_job, init_db
from dots_tts_webui_api.main import create_app
from dots_tts_webui_api.schemas import DbChunkInput, JobCreateRequest
from dots_tts_webui_api.worker import SynthesisWorker


def test_db_and_worker_mock_end_to_end(test_settings):
    conn = connect(test_settings.db_path)
    init_db(conn)
    req = JobCreateRequest(text="第一段内容\n第二段内容", silence_ms=100, chunk_min_chars=1, chunk_max_chars=1200)
    chunks = [
        DbChunkInput(chunk_index=chunk.chunk_index, text=chunk.text, char_start=chunk.char_start, char_end=chunk.char_end)
        for chunk in chunk_text_by_newline(req.text, 1, 1200)
    ]
    create_job(
        conn,
        job_id="job-worker",
        text=req.text,
        text_sha256=hashlib.sha256(req.text.encode()).hexdigest(),
        request=req.model_dump(),
        chunks=chunks,
    )

    worker = SynthesisWorker(settings=test_settings)
    assert worker.run_once(conn) is True

    job = get_job(conn, "job-worker")
    assert job["status"] == "succeeded"
    assert job["completed_chunks"] == len(chunks)
    assert Path(job["final_wav_path"]).exists()
    assert Path(job["final_text_path"]).read_text(encoding="utf-8") == "第一段内容\n\n第二段内容"
    assert all(chunk["status"] == "succeeded" for chunk in get_chunks(conn, "job-worker"))
    assert get_events(conn, "job-worker")[-1]["message"] == "job succeeded"
    conn.close()


def test_api_smoke(test_settings, tmp_path):
    with TestClient(create_app(test_settings)) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["mode"] == "mock"
        assert health.json()["worker_running"] is True

        config = client.get("/api/config")
        assert config.status_code == 200
        assert config.json()["defaults"]["silence_ms"] == 500

        source = tmp_path / "voice.wav"
        sf.write(source, np.zeros(1600, dtype=np.float32), 16000)
        with source.open("rb") as handle:
            voice = client.post(
                "/api/voices",
                data={"name": "男22", "prompt_text": "hello"},
                files={"audio": ("voice.wav", handle, "audio/wav")},
            )
        assert voice.status_code == 200, voice.text
        assert client.get("/api/voices").json()[0]["name"] == "男22"
        assert client.get("/api/voices/男22/audio").status_code == 200

        empty_voice = client.post(
            "/api/voices",
            data={"name": "empty_voice", "prompt_text": "hello"},
            files={"audio": ("voice.wav", b"", "audio/wav")},
        )
        assert empty_voice.status_code == 400
        assert empty_voice.json()["detail"] == "audio file is empty"

        preset_job = client.post(
            "/api/jobs",
            json={"text": "使用已保存音色", "voice_name": "男22", "chunk_min_chars": 1},
        )
        assert preset_job.status_code == 200, preset_job.text

        job = client.post("/api/jobs", json={"text": "第一段\n第二段", "silence_ms": 50, "chunk_min_chars": 1})
        assert job.status_code == 200, job.text
        job_id = job.json()["job_id"]
        status = {}
        for _ in range(200):
            response = client.get(f"/api/jobs/{job_id}")
            assert response.status_code == 200
            status = response.json()
            if status["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.02)
        assert status["status"] == "succeeded", status
        assert client.get(f"/api/jobs/{job_id}/artifacts/final.wav").status_code == 200
        job_artifact_dir = test_settings.artifact_dir / job_id
        assert job_artifact_dir.exists()
        assert client.get(f"/api/jobs/{job_id}/artifacts/../manifest.json").status_code in {404, 405}
        delete_job = client.delete(f"/api/jobs/{job_id}")
        assert delete_job.status_code == 200, delete_job.text
        assert delete_job.json() == {"deleted": True}
        assert client.get(f"/api/jobs/{job_id}").status_code == 404
        assert not job_artifact_dir.exists()

        cancel_job = client.post("/api/jobs", json={"text": "取消测试", "chunk_min_chars": 1})
        assert cancel_job.status_code == 200
        cancel_id = cancel_job.json()["job_id"]
        cancel = client.post(f"/api/jobs/{cancel_id}/cancel")
        assert cancel.status_code == 200

        assert client.delete("/api/voices/男22").status_code == 200
        assert client.get("/api/voices").json() == []


def test_web_assets(test_settings):
    with TestClient(create_app(test_settings)) as client:
        index = client.get("/")
        assert index.status_code == 200
        for needle in [
            'id="jobForm"',
            'id="voiceSelect"',
            'id="language"',
            'id="progressBar"',
            'id="durationText"',
            'id="historyBody"',
            "/static/app.js",
        ]:
            assert needle in index.text
        js = client.get("/static/app.js")
        assert js.status_code == 200
        for endpoint in ["/api/config", "/api/voices", "/api/jobs", "/api/jobs/form", "final.wav", "manifest.json"]:
            assert endpoint in js.text
        assert "durationText" in js.text
        assert "formatDuration" in js.text
        css = client.get("/static/styles.css")
        assert css.status_code == 200
        assert "@media" in css.text
