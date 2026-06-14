import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db
from .api import router as api_router
from .config import Settings, get_settings
from .logging_config import configure_logging
from .web import router as web_router
from .worker import SynthesisWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    settings.ensure_directories()
    configure_logging(settings)

    conn = db.connect(settings.db_path)
    db.init_db(conn)
    reset_count = db.reset_running_jobs(conn)
    worker = SynthesisWorker(settings=settings)
    worker.start()

    app.state.db_conn = conn
    app.state.worker = worker

    logger.info(
        "starting dots-tts-webui-api mode=%s data_dir=%s artifact_dir=%s reset_running_jobs=%s",
        settings.mode,
        settings.data_dir,
        settings.artifact_dir,
        reset_count,
    )
    try:
        yield
    finally:
        logger.info("stopping dots-tts-webui-api")
        worker.stop()
        conn.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="dots.tts batch synthesis", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings or get_settings()
    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(api_router)
    app.include_router(web_router)
    return app


app = create_app()
