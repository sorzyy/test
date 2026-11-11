"""Serveur Lǎoshī : API pour les lunettes + appli web de test."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .schemas import ScanRequest, ScanResult
from .tutor import Tutor, TutorError

logging.basicConfig(level=logging.INFO)

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Lǎoshī — prof de chinois dans tes lunettes")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Laoshi-Token"],
)

_tutor: Tutor | None = None


def get_tutor(settings: Settings = Depends(get_settings)) -> Tutor:
    global _tutor
    if _tutor is None or _tutor.settings != settings:
        _tutor = Tutor(settings)
    return _tutor


def check_token(
    settings: Settings = Depends(get_settings),
    x_laoshi_token: str | None = Header(default=None),
) -> None:
    if settings.access_token and not secrets.compare_digest(x_laoshi_token or "", settings.access_token):
        raise HTTPException(401, "Jeton d'accès manquant ou invalide (réglages de l'appli).")


@app.get("/api/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "ok": True,
        "demo": settings.demo,
        "model": None if settings.demo else settings.model,
        "token_required": bool(settings.access_token),
    }


@app.post("/api/scan", response_model=ScanResult, dependencies=[Depends(check_token)])
async def scan(req: ScanRequest, tutor: Tutor = Depends(get_tutor)) -> ScanResult:
    try:
        return await tutor.scan(req)
    except TutorError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/", StaticFiles(directory=STATIC), name="static")
