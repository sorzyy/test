"""Téléchargement en flux direct (« tunnel », comme Cobalt).

Au lieu de tout télécharger sur le serveur puis de renvoyer le fichier, on relaie
les octets au navigateur au fur et à mesure : le téléchargement démarre tout de
suite et rien n'est écrit sur le disque. La fusion vidéo + audio, la coupure du
son ou la conversion audio se font à la volée avec ffmpeg.

Quand ce n'est pas possible (YouTube, flux segmentés, conversion gif…), `plan()`
renvoie None et l'appelant repasse par un téléchargement classique (jobs.py).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator

from .config import settings
from .errors import AppError
from .formats import Options, audio_bitrate, ytdlp_format_args
from .models import MediaItem
from .netutil import ensure_public_host, http_client

log = logging.getLogger("saphir.streaming")

STREAMABLE_PROTOCOLS = {"https", "http"}
_COOKIE_ATTRS = {"domain", "path", "expires", "max-age", "samesite", "comment", "secure", "httponly"}

# conteneur de sortie ffmpeg par format audio : (codec args, format ffmpeg, extension, type MIME)
_AUDIO_OUT = {
    "mp3": (["-c:a", "libmp3lame"], "mp3", "mp3", "audio/mpeg"),
    "m4a": (["-c:a", "aac"], "ipod", "m4a", "audio/mp4"),
    "opus": (["-c:a", "libopus"], "opus", "opus", "audio/ogg"),
    "ogg": (["-c:a", "libvorbis"], "ogg", "ogg", "audio/ogg"),
}


@dataclass
class Source:
    url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Plan:
    kind: str  # "proxy" (octets relayés tels quels) ou "ffmpeg"
    sources: list[Source]
    ext: str
    media_type: str
    ffmpeg_args: list[str] = field(default_factory=list)
    fallbacks: list[Source] = field(default_factory=list)  # autres URL pour "proxy"


def cookie_header(cookie_field: str | None) -> str | None:
    """Champ `cookies` d'un format yt-dlp ("a=1; Domain=..; Path=/; b=2…") -> en-tête Cookie."""
    if not cookie_field:
        return None
    pairs = []
    for part in cookie_field.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name.strip().lower() not in _COOKIE_ATTRS:
            pairs.append(f"{name.strip()}={value.strip()}")
    return "; ".join(pairs) or None


def _source_from_format(fmt: dict) -> Source:
    headers = {k: v for k, v in (fmt.get("http_headers") or {}).items() if isinstance(v, str)}
    cookie = cookie_header(fmt.get("cookies"))
    if cookie:
        headers["Cookie"] = cookie
    return Source(fmt["url"], headers)


def _ffmpeg_inputs(sources: list[Source]) -> list[str]:
    args: list[str] = []
    for src in sources:
        headers = "".join(f"{k}: {v}\r\n" for k, v in src.headers.items() if k.lower() != "user-agent")
        ua = next((v for k, v in src.headers.items() if k.lower() == "user-agent"), None)
        if ua:
            args += ["-user_agent", ua]
        if headers:
            args += ["-headers", headers]
        args += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5", "-i", src.url]
    return args


def _video_plan(sources: list[Source], opts: Options, container: str, fallbacks=None) -> Plan | None:
    """Plan pour une vidéo (1 source avec son, ou 2 sources vidéo + audio à fusionner)."""
    if opts.mode == "audio":
        return _audio_plan(sources[-1], opts)
    if len(sources) == 1 and opts.mode == "auto":
        return Plan("proxy", sources, container, f"video/{container}", fallbacks=fallbacks or [])
    fmt = "webm" if container == "webm" else "mp4"
    mapping = ["-map", "0:v:0"] if opts.mode == "mute" or len(sources) == 1 else ["-map", "0:v:0", "-map", "1:a:0"]
    args = _ffmpeg_inputs(sources) + mapping + ["-c", "copy"]
    if opts.mode == "mute":
        args.append("-an")
    if fmt == "mp4":
        args += ["-movflags", "frag_keyframe+empty_moov+default_base_moof"]
    return Plan("ffmpeg", sources, fmt, f"video/{fmt}", ffmpeg_args=args + ["-f", fmt, "pipe:1"])


def _audio_plan(source: Source, opts: Options) -> Plan | None:
    if opts.audio_format not in _AUDIO_OUT:
        return None  # "best" (copie sans ré-encodage) et wav : chemin classique
    codec, fmt, ext, mime = _AUDIO_OUT[opts.audio_format]
    args = _ffmpeg_inputs([source]) + ["-vn", *codec, "-b:a", audio_bitrate(opts)]
    if fmt == "ipod":
        args += ["-movflags", "frag_keyframe+empty_moov"]
    return Plan("ffmpeg", [source], ext, mime, ffmpeg_args=args + ["-f", fmt, "pipe:1"])


async def plan(item: MediaItem, opts: Options, service: str) -> Plan | None:
    if item.type == "photo":
        if not item.url:
            return None
        ext = item.ext or "jpg"
        return Plan("proxy", [Source(item.url, item.headers)], ext, f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}")
    if item.type == "gif" and opts.convert_gif and opts.mode != "audio":
        return None  # conversion en .gif : chemin classique

    if item.source == "direct":
        if not item.url:
            return None
        sources = [Source(item.url, item.headers)]
        fallbacks = [Source(u, item.headers) for u in item.fallback_urls]
        if item.type == "audio":
            if opts.mode == "audio" and opts.audio_format != (item.ext or ""):
                return _audio_plan(sources[0], opts)
            ext = item.ext or "mp3"
            return Plan("proxy", sources, ext, "audio/mpeg" if ext == "mp3" else "audio/mp4", fallbacks=fallbacks)
        return _video_plan(sources, opts, item.ext or "mp4", fallbacks)

    # élément yt-dlp : on laisse yt-dlp choisir les formats, puis on les relaie nous-mêmes
    if service == "youtube" or not item.info:
        return None  # YouTube bride les téléchargements hors yt-dlp
    from .workers import pool
    if pool is None:
        return None
    formats = await pool.select_formats(item.info, item.extra_args + ytdlp_format_args(opts))
    if not formats or any(f.get("protocol") not in STREAMABLE_PROTOCOLS or not f.get("url") for f in formats):
        return None
    sources = [_source_from_format(f) for f in formats]
    if opts.mode == "audio":
        audio = next((f for f in formats if f.get("vcodec") == "none"), formats[-1])
        return _audio_plan(_source_from_format(audio), opts)
    container = "webm" if all(f.get("ext") == "webm" for f in formats) else "mp4"
    if len(sources) == 1 and opts.mode == "auto" and formats[0].get("acodec") == "none":
        return None  # vidéo sans piste son alors qu'on en attend une : laisse yt-dlp gérer
    return _video_plan(sources, opts, container)


class Stream:
    """Flux prêt à être envoyé : le premier morceau est déjà reçu (donc l'origine répond)."""

    def __init__(self, plan_: Plan, first: bytes, rest: AsyncIterator[bytes], length: int | None, close):
        self.plan = plan_
        self.first = first
        self.rest = rest
        self.length = length
        self._close = close

    async def body(self) -> AsyncIterator[bytes]:
        try:
            if self.first:
                yield self.first
            async for chunk in self.rest:
                yield chunk
        finally:
            await self._close()


async def open_stream(p: Plan) -> Stream:
    """Ouvre la source et attend le premier octet : une erreur ici permet de repasser
    proprement par le téléchargement classique, avant d'avoir répondu au navigateur."""
    for src in p.sources + p.fallbacks:
        await ensure_public_host(src.url)
    if p.kind == "proxy":
        return await _open_proxy(p)
    return await _open_ffmpeg(p)


async def _open_proxy(p: Plan) -> Stream:
    limit = settings.max_filesize_mb * 1024 * 1024 if settings.max_filesize_mb else 0
    last_status = None
    for src in [p.sources[0], *p.fallbacks]:
        client = http_client(timeout=None)
        try:
            r = await client.send(client.build_request("GET", src.url, headers=src.headers), stream=True)
        except Exception:
            await client.aclose()
            continue
        if r.status_code >= 400:
            last_status = r.status_code
            await r.aclose()
            await client.aclose()
            continue
        length = int(r.headers.get("content-length") or 0) or None
        ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        if p.media_type.startswith("image/") and ctype.startswith("image/"):
            from .jobs import _CONTENT_TYPES  # ex. Instagram qui sert du webp ou du heic
            p.ext, p.media_type = _CONTENT_TYPES.get(ctype, p.ext), ctype
        if limit and length and length > limit:
            await r.aclose()
            await client.aclose()
            raise AppError("content.too_big", status=413)
        iterator = r.aiter_bytes(256 * 1024)
        first = await anext(iterator, b"")

        async def close(r=r, client=client):
            await r.aclose()
            await client.aclose()

        return Stream(p, first, iterator, length, close)
    raise AppError("fetch.fail", detail=f"HTTP {last_status}" if last_status else None)


async def _open_ffmpeg(p: Plan) -> Stream:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *p.ffmpeg_args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    async def close():
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.wait()

    try:
        first = await asyncio.wait_for(proc.stdout.read(256 * 1024), 30)
    except asyncio.TimeoutError:
        await close()
        raise AppError("fetch.timeout")
    if not first:
        err = (await proc.stderr.read()).decode("utf-8", "replace")
        await close()
        raise AppError("download.fail", detail=err.strip()[-300:])

    async def rest():
        while True:
            chunk = await proc.stdout.read(256 * 1024)
            if not chunk:
                break
            yield chunk

    return Stream(p, first, rest(), None, close)
