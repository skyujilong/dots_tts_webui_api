from __future__ import annotations

from pathlib import Path

import pytest

from dots_tts_webui_api.config import Settings


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data/jobs.sqlite3",
        artifact_dir=tmp_path / "data/artifacts",
        voices_dir=tmp_path / "data/voices",
        log_file=tmp_path / "data/logs/app.log",
        mock_tts=True,
        worker_poll_interval_seconds=0.01,
    )
