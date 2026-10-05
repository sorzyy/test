"""Téléchargements en tâche de fond, avec suivi de progression."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from .config import settings
from .errors import AppError, classify, last_error_line
from .formats import Options, ffmpeg_audio_args, ytdlp_format_args
from .models import MediaItem, Resolved
from .netutil import ensure_public_host, http_client
from .tools import cookies_copy, ffmpeg, ffprobe_streams, run, ytdlp_base_args

log = logging.getLogger("saphir.jobs")

Selection = Union[int, str]  # index d'un élément, "audio" ou "all"

_PROGRESS_PREFIX = "[[P]]"
_PROGRESS_TEMPLATE = (
    "download:" + _PROGRESS_PREFIX +
    "%(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
    "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s"
)

_CONTENT_TYPES = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "image/heic": "heic",
    "image/avif": "avif", "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov",
    "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/ogg": "ogg", "audio/opus": "opus",
    "audio/wav": "wav", "audio/aac": "aac",
}


@dataclass
class Job:
    id: str
    service: str
    status: str = "queued"  # queued | downloading | processing | done | error
    progress: float | None = None  # 0..100
    speed: float | None = None  # octets/s
    eta: int | None = None
    phase: str = ""
    error: AppError | None = None
    path: Path | None = None
    filename: str = ""
    size: int | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    task: asyncio.Task | None = None
    done_event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def workdir(self) -> Path:
        return settings.temp_dir / "jobs" / self.id

    def public(self) -> dict:
        data = {
            "id": self.id, "status": self.status, "phase": self.phase,
            "progress": round(self.progress, 1) if self.progress is not None else None,
            "speed": self.speed, "eta": self.eta, "filename": self.filename, "size": self.size,
        }
        if self.error:
            data["error"] = self.error.to_dict()
        if self.status == "done":
            data["url"] = f"/api/jobs/{self.id}/file"
        return data


JOBS: dict[str, Job] = {}


class _Gate:
    """Empêche une mise à jour de yt-dlp pendant qu'un téléchargement tourne."""

    def __init__(self):
        self.active = 0
        self._open: asyncio.Event | None = None
        self._idle: asyncio.Event | None = None
        self._sem: asyncio.Semaphore | None = None

    def _init(self):
        if self._open is None:
            self._open = asyncio.Event()
            self._open.set()
            self._idle = asyncio.Event()
            self._idle.set()
            self._sem = asyncio.Semaphore(settings.max_concurrent_jobs)

    async def __aenter__(self):
        self._init()
        await self._open.wait()
        await self._sem.acquire()
        self.active += 1
        self._idle.clear()

    async def __aexit__(self, *exc):
        self.active -= 1
        self._sem.release()
        if self.active == 0:
            self._idle.set()

    async def exclusive(self):
        """Ferme la porte et attend que les téléchargements en cours se terminent."""
        self._init()
        self._open.clear()
        await self._idle.wait()

    def reopen(self):
        self._init()
        self._open.set()


gate = _Gate()


def get_job(job_id: str) -> Job:
    job = JOBS.get(job_id)
    if not job:
        raise AppError("job.notfound", status=404)
    return job


def create_job(resolved: Resolved, selection: Selection, opts: Options) -> Job:
    targets = _targets(resolved, selection, opts)
    job = Job(id=secrets.token_urlsafe(12), service=resolved.service)
    JOBS[job.id] = job
    job.task = asyncio.create_task(_run(job, resolved, targets, selection, opts))
    return job


def _targets(resolved: Resolved, selection: Selection, opts: Options) -> list[MediaItem]:
    if selection == "audio":
        if not resolved.audio:
            raise AppError("content.empty", status=404)
        return [resolved.audio]
    if selection == "all":
        if not resolved.items:
            raise AppError("content.empty", status=404)
        return list(resolved.items)
    try:
        index = int(selection)
        item = resolved.items[index]
    except (ValueError, IndexError):
        raise AppError("content.empty", status=404)
    # mode audio sur un diaporama : on renvoie la musique
    if opts.mode == "audio" and item.type == "photo" and resolved.audio:
        return [resolved.audio]
    return [item]


async def _run(job: Job, resolved: Resolved, targets: list[MediaItem], selection: Selection, opts: Options):
    try:
        async with gate:
            job.workdir.mkdir(parents=True, exist_ok=True)
            if selection == "all" and len(targets) > 1:
                await _run_zip(job, resolved, targets, opts)
            else:
                item = targets[0]
                path = await download_item(job, item, opts, job.workdir, label="")
                index = resolved.items.index(item) if item in resolved.items else None
                multiple = len(resolved.items) > 1
                job.filename = build_filename(resolved, item, path.suffix.lstrip("."),
                                              index if multiple else None)
                job.path = path
            job.size = job.path.stat().st_size if job.path else None
            if settings.max_filesize_mb and job.size and job.size > settings.max_filesize_mb * 1024 * 1024:
                raise AppError("content.too_big", status=413)
            job.status, job.progress, job.phase = "done", 100.0, ""
    except AppError as err:
        job.status, job.error = "error", err
    except asyncio.CancelledError:
        job.status, job.error = "error", AppError("download.fail")
        raise
    except Exception as exc:  # garde-fou : on ne laisse jamais une tâche mourir en silence
        log.exception("job %s failed", job.id)
        job.status, job.error = "error", AppError("download.fail", detail=str(exc)[:300])
    finally:
        job.finished = time.time()
        job.done_event.set()


async def _run_zip(job: Job, resolved: Resolved, targets: list[MediaItem], opts: Options):
    zip_path = job.workdir / "archive.zip"
    total = len(targets)
    used: set[str] = set()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for i, item in enumerate(targets):
            sub = job.workdir / f"{i:03d}"
            sub.mkdir(exist_ok=True)
            # pas de conversion audio pour les photos d'une archive
            item_opts = opts if item.type in ("video", "audio") else opts.model_copy(update={"mode": "auto"})
            path = await download_item(job, item, item_opts, sub, label=f"{i + 1}/{total}", overall=(i, total))
            name = f"{i + 1:02d} - " + build_filename(resolved, item, path.suffix.lstrip("."), None)
            while name in used:
                name = "_" + name
            used.add(name)
            zf.write(path, name)
            path.unlink(missing_ok=True)
    job.path = zip_path
    job.filename = build_filename(resolved, None, "zip", None)


async def download_item(job: Job, item: MediaItem, opts: Options, workdir: Path, label: str,
                        overall: tuple[int, int] | None = None) -> Path:
    job.status = "downloading"
    job.phase = label
    if item.source == "ytdlp":
        path = await _ytdlp_download(job, item, opts, workdir, overall)
        if opts.mode == "mute":
            path = await _strip_audio(job, path)
        return path

    path = await _direct_download(job, item, workdir, overall)
    if item.type in ("photo",):
        return path
    if item.type == "gif" and opts.mode != "audio":
        return await _to_gif(job, path) if opts.convert_gif else path
    if opts.mode == "audio":
        return await _to_audio(job, path, opts)
    if opts.mode == "mute":
        return await _strip_audio(job, path)
    return path


def _set_progress(job: Job, fraction: float, overall: tuple[int, int] | None):
    fraction = max(0.0, min(1.0, fraction))
    if overall:
        done, total = overall
        job.progress = (done + fraction) / total * 100
    else:
        job.progress = fraction * 100


async def _direct_download(job: Job, item: MediaItem, workdir: Path, overall) -> Path:
    if not item.url:
        raise AppError("content.empty")
    await ensure_public_host(item.url)
    limit = settings.max_filesize_mb * 1024 * 1024 if settings.max_filesize_mb else 0
    tmp = workdir / "download.part"
    started = time.monotonic()
    async with http_client(timeout=None) as client:
        try:
            async with client.stream("GET", item.url, headers=item.headers) as r:
                if r.status_code >= 400:
                    raise AppError("fetch.fail" if r.status_code != 404 else "content.unavailable",
                                   detail=f"HTTP {r.status_code}")
                total = int(r.headers.get("content-length") or 0)
                if limit and total > limit:
                    raise AppError("content.too_big", status=413)
                ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
                received = 0
                with open(tmp, "wb") as fh:
                    async for chunk in r.aiter_bytes(256 * 1024):
                        fh.write(chunk)
                        received += len(chunk)
                        if limit and received > limit:
                            raise AppError("content.too_big", status=413)
                        elapsed = max(time.monotonic() - started, 0.001)
                        job.speed = received / elapsed
                        if total:
                            _set_progress(job, received / total, overall)
                            job.eta = int((total - received) / job.speed) if job.speed else None
        except AppError:
            raise
        except Exception as exc:
            raise AppError("download.fail", detail=str(exc)[:300])
    if received == 0:
        raise AppError("download.fail", detail="fichier vide")
    ext = item.ext or _CONTENT_TYPES.get(ctype) or "bin"
    if ctype in _CONTENT_TYPES and item.type in ("photo",):
        ext = _CONTENT_TYPES[ctype]  # ex. Instagram qui sert du webp/heic
    final = workdir / f"media.{ext}"
    tmp.rename(final)
    return final


def _parse_progress(line: str) -> tuple[str, int, int, float | None, int | None] | None:
    if not line.startswith(_PROGRESS_PREFIX):
        return None
    parts = line[len(_PROGRESS_PREFIX):].split("|")
    if len(parts) != 6:
        return None

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    status, done, total, estimate, speed, eta = parts
    total_bytes = num(total) or num(estimate) or 0
    return status, int(num(done) or 0), int(total_bytes), num(speed), int(num(eta)) if num(eta) else None


async def _ytdlp_download(job: Job, item: MediaItem, opts: Options, workdir: Path, overall) -> Path:
    phases = 1
    if item.info and opts.mode == "auto":
        phases = 2 if not item.has_audio or any(
            f.get("vcodec") == "none" for f in item.info.get("formats") or []) else 1
    state = {"phase": 0}

    async def on_line(line: str):
        parsed = _parse_progress(line)
        if parsed:
            status, done, total, speed, eta = parsed
            job.speed, job.eta = speed, eta
            if total:
                frac = (state["phase"] + done / total) / phases
                _set_progress(job, min(frac, 0.99), overall)
            if status == "finished":
                state["phase"] = min(state["phase"] + 1, phases - 1)
        elif line.startswith(("[Merger]", "[ExtractAudio]", "[VideoConvertor]", "[FixupM3u8]", "[VideoRemuxer]")):
            job.status = "processing"

    last_error = ""
    attempts: list[list[str]] = []
    if item.info:
        info_path = workdir / "info.json"
        info_path.write_text(json.dumps(item.info), encoding="utf-8")
        attempts.append(["--load-info-json", str(info_path)])
    if item.page_url:
        extra = ["--playlist-items", str(item.playlist_index)] if item.playlist_index else []
        attempts.append(extra + ["--", item.page_url])
    if not attempts:
        raise AppError("content.empty")

    for attempt in attempts:
        for leftover in workdir.glob("media.*"):
            leftover.unlink(missing_ok=True)
        with cookies_copy() as cookies:
            cmd = ytdlp_base_args(cookies) + ytdlp_format_args(opts) + [
                "--newline", "--progress", "--progress-template", _PROGRESS_TEMPLATE,
                "--no-mtime", "--concurrent-fragments", "4",
                "-o", str(workdir / "media.%(ext)s"),
            ]
            if settings.max_filesize_mb:
                cmd += ["--max-filesize", f"{settings.max_filesize_mb}M"]
            cmd += attempt
            res = await run(cmd, settings.download_timeout, on_stdout_line=on_line)
        output = _find_output(workdir)
        if res.ok and output:
            return output
        last_error = res.stderr if not res.timed_out else "timed out"
        log.warning("yt-dlp download attempt failed: %s", last_error_line(last_error))
        state["phase"] = 0
    code = classify(last_error)
    raise AppError(code if code != "fetch.fail" else "download.fail", detail=last_error_line(last_error))


_FINAL_RE = re.compile(r"media\.[A-Za-z0-9]+")


def _find_output(workdir: Path) -> Path | None:
    # exclut les fichiers intermédiaires de yt-dlp (media.f137.mp4, media.mp4.part...)
    files = [p for p in workdir.glob("media.*")
             if p.is_file() and _FINAL_RE.fullmatch(p.name) and p.suffix != ".json"]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


async def _strip_audio(job: Job, path: Path) -> Path:
    job.status = "processing"
    out = path.with_name(f"muted{path.suffix}")
    res = await ffmpeg(["-i", str(path), "-map", "0:v?", "-c", "copy", "-an", str(out)])
    if not res.ok or not out.exists():
        raise AppError("download.fail", detail=last_error_line(res.stderr))
    path.unlink(missing_ok=True)
    return out


async def _to_audio(job: Job, path: Path, opts: Options) -> Path:
    job.status = "processing"
    src_ext = path.suffix.lstrip(".").lower()
    streams = await ffprobe_streams(path)
    if streams and not any(s.get("codec_type") == "audio" for s in streams):
        raise AppError("content.empty", detail="pas de piste audio")
    if opts.audio_format == "best" and src_ext in ("mp3", "m4a", "opus", "ogg", "aac", "flac", "wav"):
        return path
    if opts.audio_format == src_ext:
        return path  # déjà au bon format : pas de perte de qualité
    if opts.audio_format == "best":
        codec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), "aac")
        args, ext = ["-vn", "-c:a", "copy"], {"aac": "m4a", "mp3": "mp3", "opus": "opus", "vorbis": "ogg",
                                              "flac": "flac"}.get(codec, "mka")
    else:
        args, ext = ffmpeg_audio_args(opts, src_ext)
    out = path.with_name(f"audio.{ext}")
    res = await ffmpeg(["-i", str(path), *args, "-map_metadata", "0", str(out)])
    if not res.ok or not out.exists():
        raise AppError("download.fail", detail=last_error_line(res.stderr))
    path.unlink(missing_ok=True)
    return out


async def _to_gif(job: Job, path: Path) -> Path:
    job.status = "processing"
    out = path.with_name("animation.gif")
    res = await ffmpeg([
        "-i", str(path), "-vf",
        "fps=15,scale='min(540,iw)':-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=5",
        "-loop", "0", str(out)])
    if not res.ok or not out.exists():
        return path  # si la conversion échoue, on garde le mp4
    path.unlink(missing_ok=True)
    return out


_URL_RE = re.compile(r"https?://\S+")
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def build_filename(resolved: Resolved, item: MediaItem | None, ext: str, index: int | None) -> str:
    title = (item.title if item and item.title else resolved.title) or ""
    title = _URL_RE.sub("", title)
    title = _BAD_CHARS.sub(" ", title)
    title = re.sub(r"\s+", " ", title).strip(" .-_")
    if len(title) > 80:
        title = title[:80].rsplit(" ", 1)[0].rstrip(" .-_") or title[:80]
    if not title:
        ident = (item.id if item and item.id else "") or (resolved.author or "")
        title = f"{resolved.service}_{ident}".rstrip("_")
    if index is not None and not title.endswith(f"({index + 1})"):
        title += f" ({index + 1})"
    return f"{title}.{ext}" if ext else title


async def cleanup_loop():
    from . import resolver
    while True:
        await asyncio.sleep(60)
        try:
            cleanup_expired()
            resolver.purge_expired()
        except Exception:
            log.exception("cleanup failed")


def cleanup_expired(now: float | None = None):
    now = now or time.time()
    for job_id, job in list(JOBS.items()):
        if job.finished and now - job.finished > settings.job_ttl:
            shutil.rmtree(job.workdir, ignore_errors=True)
            JOBS.pop(job_id, None)
    # dossiers orphelins (redémarrage du serveur)
    root = settings.temp_dir / "jobs"
    if root.is_dir():
        for d in root.iterdir():
            if d.name not in JOBS and now - d.stat().st_mtime > settings.job_ttl:
                shutil.rmtree(d, ignore_errors=True)
