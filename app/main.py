"""Serveur web : interface + API."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Union
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, jobs, resolver, updater
from .config import settings
from .errors import AppError
from .formats import Options
from .netutil import ensure_public_host, http_client
from .services import SUPPORTED_SERVICES
from .tools import js_runtimes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("saphir")

STATIC = Path(__file__).parent / "static"
STARTED = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    tasks = [asyncio.create_task(jobs.cleanup_loop())]
    if settings.auto_update:
        tasks.append(asyncio.create_task(updater.update_loop()))
    log.info("saphir %s prêt — cookies: %s, js: %s, PO token: %s", __version__,
             "oui" if settings.cookies_file else "non", ",".join(js_runtimes()) or "aucun",
             settings.pot_provider_url or "non")
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="saphir", version=__version__, lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
# l'interface peut être servie ailleurs (ex. GitHub Pages) : on autorise les appels cross-origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    expose_headers=["Content-Disposition"],
)


@app.exception_handler(AppError)
async def _app_error(request: Request, exc: AppError):
    return JSONResponse({"error": exc.to_dict()}, status_code=exc.status)


# --- sécurité : clé d'API optionnelle + limite de débit ---------------------

def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd and settings.trust_proxy:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def require_key(request: Request) -> None:
    if not settings.api_key:
        return
    auth = request.headers.get("authorization", "")
    key = auth.split(" ", 1)[1] if " " in auth else auth
    key = key or request.query_params.get("key", "")
    if key != settings.api_key:
        raise AppError("auth.required", status=401)


_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request) -> None:
    if settings.rate_limit_per_minute <= 0:
        return
    now = time.time()
    q = _hits[_client_ip(request)]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= settings.rate_limit_per_minute:
        raise AppError("rate.exceeded", status=429)
    q.append(now)


# --- API principale -----------------------------------------------------------

class ResolveBody(BaseModel):
    url: str


class JobBody(BaseModel):
    token: str
    index: Union[int, str] = 0  # index, "audio" ou "all"
    options: Options = Options()


def _resolved_payload(token: str, r) -> dict:
    return {
        "token": token,
        "service": r.service,
        "title": r.title,
        "author": r.author,
        "items": [item.public(i) for i, item in enumerate(r.items)],
        "audio": r.audio.public(-1) if r.audio else None,
        "engines": r.engines,
    }


@app.post("/api/resolve", dependencies=[Depends(require_key), Depends(rate_limit)])
async def api_resolve(body: ResolveBody):
    token, resolved = await resolver.resolve(body.url)
    return _resolved_payload(token, resolved)


@app.post("/api/jobs", dependencies=[Depends(require_key)])
async def api_create_job(body: JobBody):
    resolved = resolver.get(body.token)
    job = jobs.create_job(resolved, body.index, body.options)
    return job.public()


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    return jobs.get_job(job_id).public()


def _attachment(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    ascii_name = ascii_name.replace('"', "").replace("\\", "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _file_response(job: jobs.Job) -> FileResponse:
    if job.status != "done" or not job.path or not job.path.exists():
        raise AppError("job.notfound", status=404)
    return FileResponse(job.path, headers={"Content-Disposition": _attachment(job.filename),
                                           "Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}/file")
async def api_job_file(job_id: str):
    return _file_response(jobs.get_job(job_id))


@app.get("/api/thumb/{token}/{index}")
async def api_thumb(token: str, index: str):
    resolved = resolver.get(token)
    try:
        item = resolved.audio if index == "audio" else resolved.items[int(index)]
    except (ValueError, IndexError):
        raise AppError("content.empty", status=404)
    if not item or not item.thumbnail:
        raise AppError("content.empty", status=404)
    await ensure_public_host(item.thumbnail)
    client = http_client()
    try:
        req = client.build_request("GET", item.thumbnail, headers=item.headers)
        r = await client.send(req, stream=True)
    except Exception:
        await client.aclose()
        raise AppError("fetch.fail", status=502)
    if r.status_code >= 400:
        await r.aclose()
        await client.aclose()
        raise AppError("fetch.fail", status=502)

    async def body():
        sent = 0
        try:
            async for chunk in r.aiter_bytes(64 * 1024):
                sent += len(chunk)
                if sent > 25 * 1024 * 1024:
                    break
                yield chunk
        finally:
            await r.aclose()
            await client.aclose()

    return StreamingResponse(body(), media_type=r.headers.get("content-type", "image/jpeg"),
                             headers={"Cache-Control": "private, max-age=1800"})


@app.get("/api/status")
async def api_status():
    return {
        "name": "saphir",
        "version": __version__,
        "uptime": int(time.time() - STARTED),
        "versions": updater.versions(),
        "update": {"auto": settings.auto_update, "channel": settings.update_channel,
                   "last_check": updater.state["last_check"], "last_result": updater.state["last_result"]},
        "cookies": bool(settings.cookies_file or settings.cookies_from_browser),
        "po_token_provider": bool(settings.pot_provider_url),
        "js_runtimes": js_runtimes(),
        "services": SUPPORTED_SERVICES,
        "auth_required": bool(settings.api_key),
        "limits": {"max_duration": settings.max_duration, "max_filesize_mb": settings.max_filesize_mb},
    }


@app.post("/api/update", dependencies=[Depends(require_key)])
async def api_update(request: Request):
    if not settings.api_key and _client_ip(request) not in ("127.0.0.1", "::1", "localhost"):
        raise AppError("auth.required", status=401)
    return await updater.update_now()


# --- API compatible Cobalt (v10+) ------------------------------------------
# Permet d'utiliser les clients Cobalt existants (raccourcis iOS, extensions…)
# en pointant simplement sur ce serveur.

_COBALT_ERRORS = {
    "link.invalid": "error.api.link.invalid", "link.empty": "error.api.link.missing",
    "link.unsupported": "error.api.link.unsupported", "link.private": "error.api.link.invalid",
    "content.private": "error.api.content.post.private", "content.login": "error.api.content.post.private",
    "content.age": "error.api.content.post.age", "content.geo": "error.api.content.video.region",
    "content.unavailable": "error.api.content.video.unavailable", "content.live": "error.api.content.video.live",
    "content.too_long": "error.api.content.too_long", "content.empty": "error.api.fetch.empty",
    "content.no_audio": "error.api.content.video.no_audio",
    "fetch.rate": "error.api.fetch.rate", "fetch.bot": "error.api.youtube.login",
    "rate.exceeded": "error.api.rate_exceeded", "auth.required": "error.api.auth.key.missing",
}


def _cobalt_options(body: dict) -> Options:
    codec = body.get("youtubeVideoCodec") or "h264"
    return Options(
        mode=body.get("downloadMode") if body.get("downloadMode") in ("auto", "audio", "mute") else "auto",
        quality=str(body.get("videoQuality") or "1080"),
        codec=codec if codec in ("h264", "av1", "vp9") else "h264",
        audio_format=body.get("audioFormat") or "mp3",
        audio_bitrate=str(body.get("audioBitrate") or "128"),
        convert_gif=body.get("convertGif", True) is not False,
    )


def _encode_opts(opts: Options) -> str:
    return base64.urlsafe_b64encode(opts.model_dump_json().encode()).decode().rstrip("=")


def _decode_opts(raw: str) -> Options:
    try:
        return Options.model_validate_json(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except Exception:
        return Options()


def _predict_ext(item, opts: Options) -> str:
    if item.type == "photo":
        return item.ext or "jpg"
    if item.type == "gif" and opts.convert_gif and opts.mode != "audio":
        return "gif"
    if opts.mode == "audio" or item.type == "audio":
        return {"best": item.ext or "m4a", "ogg": "ogg"}.get(opts.audio_format, opts.audio_format)
    return "webm" if opts.codec == "vp9" and item.source == "ytdlp" else "mp4"


@app.get("/", include_in_schema=False)
async def index(request: Request):
    if "application/json" in request.headers.get("accept", "") and "text/html" not in request.headers.get("accept", ""):
        base = settings.public_url or str(request.base_url).rstrip("/")
        return {"cobalt": {"version": "10.0.0-saphir", "url": base, "startTime": str(int(STARTED * 1000)),
                           "services": [s["id"] for s in SUPPORTED_SERVICES if s["id"] != "generic"]},
                "saphir": {"version": __version__}}
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.post("/", include_in_schema=False, dependencies=[Depends(require_key)])
async def cobalt_api(request: Request):
    try:
        rate_limit(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise AppError("link.invalid")
        opts = _cobalt_options(body)
        token, resolved = await resolver.resolve(str(body.get("url") or ""))
    except AppError as err:
        return JSONResponse({"status": "error", "error": {"code": _COBALT_ERRORS.get(err.code, "error.api.fetch.fail")}},
                            status_code=400)
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"status": "error", "error": {"code": "error.api.invalid_body"}}, status_code=400)

    base = settings.public_url or str(request.base_url).rstrip("/")
    o = _encode_opts(opts)

    def tunnel(index) -> str:
        return f"{base}/tunnel?t={token}&i={index}&o={o}"

    def fname(item, index) -> str:
        multiple = len(resolved.items) > 1 and index != "audio"
        return jobs.build_filename(resolved, item, _predict_ext(item, opts),
                                   index if multiple and isinstance(index, int) else None)

    items = resolved.items
    if opts.mode == "audio" and resolved.audio and all(i.type == "photo" for i in items):
        return {"status": "tunnel", "url": tunnel("audio"), "filename": fname(resolved.audio, "audio")}
    if len(items) == 1:
        return {"status": "tunnel", "url": tunnel(0), "filename": fname(items[0], 0)}
    picker = [{"type": "photo" if i.type == "photo" else ("gif" if i.type == "gif" else "video"),
               "url": tunnel(n), "thumb": f"{base}/api/thumb/{token}/{n}" if i.thumbnail else None}
              for n, i in enumerate(items)]
    payload = {"status": "picker", "picker": picker}
    if resolved.audio:
        payload["audio"] = tunnel("audio")
        payload["audioFilename"] = fname(resolved.audio, "audio")
    return payload


@app.get("/tunnel", include_in_schema=False)
async def cobalt_tunnel(t: str, i: str, o: str = ""):
    resolved = resolver.get(t)
    selection: Union[int, str] = i if i in ("audio", "all") else int(i) if i.isdigit() else "invalid"
    job = jobs.create_job(resolved, selection, _decode_opts(o))
    await job.done_event.wait()
    if job.status != "done":
        err = job.error or AppError("download.fail")
        return JSONResponse({"error": err.to_dict()}, status_code=502)
    return _file_response(job)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return Response((STATIC / "manifest.webmanifest").read_text(), media_type="application/manifest+json")
