from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    template_path = Path(__file__).with_name("templates") / "index.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))
