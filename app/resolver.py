"""Analyse d'un lien : choisit les extracteurs selon la plateforme et fusionne leurs résultats."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass

from .config import settings
from .errors import AppError, most_specific
from .extractors import ExtractResult
from .extractors import gallerydl, instagram, tiktok, twitter, ytdlp
from .models import MediaItem, Resolved
from .netutil import ensure_public_host, normalize_input_url
from .services import ServiceMatch, detect

log = logging.getLogger("saphir.resolver")


@dataclass
class _Entry:
    expires: float
    resolved: Resolved


_STORE: dict[str, _Entry] = {}


def store(resolved: Resolved) -> str:
    token = secrets.token_urlsafe(16)
    _STORE[token] = _Entry(time.time() + settings.cache_ttl, resolved)
    return token


def get(token: str) -> Resolved:
    entry = _STORE.get(token)
    if not entry or entry.expires < time.time():
        _STORE.pop(token, None)
        raise AppError("token.expired", status=404)
    return entry.resolved


def purge_expired() -> None:
    now = time.time()
    for token in [t for t, e in _STORE.items() if e.expires < now]:
        _STORE.pop(token, None)


def merge_ordered(primary: list[MediaItem], videos: list[MediaItem]) -> list[MediaItem]:
    """Garde l'ordre (et les photos) de `primary` et remplace ses vidéos, dans l'ordre,
    par celles de yt-dlp (qui offrent le choix de qualité / codec)."""
    pool = [v for v in videos if v.type in ("video", "gif") and v.source == "ytdlp"]
    out: list[MediaItem] = []
    for item in primary:
        if item.type in ("video", "gif") and pool:
            replacement = pool.pop(0)
            replacement.type = item.type
            replacement.thumbnail = replacement.thumbnail or item.thumbnail
            out.append(replacement)
        else:
            out.append(item)
    out.extend(pool)
    return out


def _fail(results: list[ExtractResult]) -> AppError:
    codes = [r.error for r in results if r.error]
    details = "; ".join(f"{r.engine}: {r.detail}" for r in results if r.detail)
    return AppError(most_specific(codes), detail=details or None, status=422)


def _finish(match: ServiceMatch, main: ExtractResult, used: list[ExtractResult], items=None, audio=None) -> Resolved:
    titled = next((r for r in [main, *used] if r.title), main)
    authored = next((r for r in [main, *used] if r.author), main)
    return Resolved(
        service=match.service, url=match.url, title=titled.title or "", author=authored.author,
        items=items if items is not None else main.items,
        audio=audio if audio is not None else main.audio,
        engines=[r.engine for r in used if r.ok],
    )


async def _youtube_or_generic(match: ServiceMatch) -> Resolved:
    y = await ytdlp.extract(match)
    if not y.ok and match.service == "youtube" and y.error in ("fetch.bot", "content.login", "fetch.fail"):
        retry = await ytdlp.extract(match, ytdlp.YOUTUBE_FALLBACK_ARGS)
        if retry.ok:
            return _finish(match, retry, [retry])
    if y.ok:
        return _finish(match, y, [y])
    g = await gallerydl.extract(match.url)
    if g.ok:
        return _finish(match, g, [g])
    raise _fail([y, g])


async def _instagram(match: ServiceMatch) -> Resolved:
    if match.kind == "share":
        full = await instagram.resolve_share(match.url)
        if full:
            match = detect(full)
    y = await ytdlp.extract(match)
    if y.ok:
        return _finish(match, y, [y])
    n = await instagram.extract(match)
    if n.ok:
        return _finish(match, n, [n])
    g = await gallerydl.extract(match.url)
    if g.ok:
        return _finish(match, g, [g])
    raise _fail([y, n, g])


async def _twitter(match: ServiceMatch) -> Resolved:
    if not match.post_id:
        return await _youtube_or_generic(match)
    y, n = await asyncio.gather(ytdlp.extract(match), twitter.extract(match))
    if n.ok:
        items = merge_ordered(n.items, y.items if y.ok else [])
        return _finish(match, n, [n, y], items=items)
    if y.ok:
        return _finish(match, y, [y])
    g = await gallerydl.extract(match.url)
    if g.ok:
        return _finish(match, g, [g])
    raise _fail([y, n, g])


async def _tiktok(match: ServiceMatch) -> Resolved:
    if match.kind == "short":
        full = await tiktok.resolve_short_link(match.url)
        if full:
            match = detect(full)
    is_photo = match.kind == "photo"
    if is_photo:
        y = ExtractResult("yt-dlp", error="link.unsupported")
        n = await tiktok.extract(match)
    else:
        y, n = await asyncio.gather(ytdlp.extract(match), tiktok.extract(match))
    if n.ok and any(i.type == "photo" for i in n.items):
        # diaporama : photos + musique
        return _finish(match, n, [n])
    if y.ok:
        return _finish(match, y, [y, n], audio=n.audio)
    if n.ok:
        return _finish(match, n, [n])
    g = await gallerydl.extract(match.url)
    if g.ok:
        return _finish(match, g, [g])
    raise _fail([y, n, g])


_STRATEGIES = {
    "youtube": _youtube_or_generic,
    "instagram": _instagram,
    "twitter": _twitter,
    "tiktok": _tiktok,
    "generic": _youtube_or_generic,
}


async def resolve(raw_url: str) -> tuple[str, Resolved]:
    url = normalize_input_url(raw_url)
    await ensure_public_host(url)
    match = detect(url)
    started = time.monotonic()
    resolved = await _STRATEGIES[match.service](match)
    log.info("resolved %s via %s in %.1fs (%d items)", match.service, ",".join(resolved.engines),
             time.monotonic() - started, len(resolved.items))

    if settings.max_duration:
        too_long = [i for i in resolved.items if i.duration and i.duration > settings.max_duration]
        if too_long and len(too_long) == len(resolved.items):
            raise AppError("content.too_long", status=422)
        resolved.items = [i for i in resolved.items if i not in too_long]

    return store(resolved), resolved
