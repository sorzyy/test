"""Extraction via yt-dlp (vidéos de quasiment tous les sites)."""

from __future__ import annotations

import json
from typing import Any

from ..config import settings
from ..errors import classify, last_error_line
from ..models import MediaItem
from ..services import ServiceMatch
from ..tools import cookies_copy, run, ytdlp_base_args
from ..workers import pool
from . import ExtractResult, kind_from_ext

# Champs volumineux inutiles pour télécharger : on les retire du cache.
_STRIP_KEYS = ("automatic_captions", "subtitles", "comments", "heatmap", "chapters",
               "requested_subtitles", "thumbnails_extra", "_format_sort_fields_extra")


# Clients YouTube essayés quand le client par défaut est bloqué ("not a bot").
YOUTUBE_FALLBACK_ARGS = ["--extractor-args", "youtube:player_client=tv_simply,tv,web_safari,mweb,android_vr"]


async def extract(match: ServiceMatch, extra_args: list[str] | None = None) -> ExtractResult:
    with cookies_copy() as cookies:
        # les avertissements restent dans stderr : ils expliquent un échec
        args = ytdlp_base_args(cookies, warnings=True) + (extra_args or []) + [
            "--playlist-end", str(settings.max_items)]
        if match.service == "instagram":
            # les photos d'un carrousel n'ont pas de "format" vidéo
            args.append("--ignore-no-formats-error")
        if match.service == "youtube" and match.kind == "playlist":
            args.append("--flat-playlist")
        args += ["--", match.url]
        if pool is not None:
            # processus yt-dlp déjà chaud : pas de 1,3 s de démarrage
            data, res = await pool.extract(args[3:], settings.extract_timeout)
        else:
            res = await run(args[:3] + ["-J"] + args[3:], settings.extract_timeout)
            data = _parse_json(res.stdout)

    if res.timed_out:
        return ExtractResult("yt-dlp", error="fetch.timeout")
    if not isinstance(data, dict):
        return ExtractResult("yt-dlp", error=classify(res.stderr), detail=last_error_line(res.stderr))
    result = parse_info(data, match)
    for item in result.items:
        if item.source == "ytdlp":
            item.extra_args = list(extra_args or [])
    if not result.ok and res.stderr.strip():
        # ex. formats YouTube écartés faute de PO token : l'explication est dans les avertissements
        result.detail = last_error_line(res.stderr)
        if result.error == "content.empty" and classify(res.stderr) != "fetch.fail":
            result.error = classify(res.stderr)
    return result


def _parse_json(stdout: str) -> dict | None:
    if not stdout.strip():
        return None
    try:
        return json.loads(stdout.strip().splitlines()[-1])
    except ValueError:
        return None


def best_thumbnail(info: dict) -> str | None:
    thumbs = [t for t in (info.get("thumbnails") or []) if isinstance(t, dict) and t.get("url")]
    if thumbs:
        def score(t):
            return (t.get("preference") or 0, (t.get("width") or 0) * (t.get("height") or 0))
        # yt-dlp trie déjà du pire au meilleur ; on départage quand même par taille
        best = max(enumerate(thumbs), key=lambda it: (score(it[1]), it[0]))[1]
        return best["url"]
    return info.get("thumbnail")


def _media_type(formats: list[dict]) -> str:
    if all(kind_from_ext(f.get("ext")) == "photo" for f in formats):
        return "photo"
    if all(f.get("vcodec") == "none" or (f.get("vcodec") is None and kind_from_ext(f.get("ext")) == "audio")
           for f in formats):
        return "audio"
    return "video"


def _has_audio(formats: list[dict]) -> bool | None:
    if not formats:
        return None
    if any(f.get("acodec") not in (None, "none") for f in formats):
        return True
    if all(f.get("acodec") == "none" for f in formats):
        return False
    return None


def _clean(info: dict) -> dict:
    return {k: v for k, v in info.items() if k not in _STRIP_KEYS}


def parse_info(data: dict[str, Any], match: ServiceMatch) -> ExtractResult:
    result = ExtractResult("yt-dlp")
    is_playlist = data.get("_type") == "playlist"
    entries = [e for e in (data.get("entries") or [])] if is_playlist else [data]
    result.title = data.get("title") or data.get("fulltitle") or ""
    result.author = data.get("uploader") or data.get("channel") or data.get("uploader_id")
    page_url = data.get("webpage_url") or data.get("original_url") or match.url
    live_seen = False

    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            continue
        title = entry.get("title") or result.title
        common = dict(
            title=title or "",
            id=str(entry.get("id") or ""),
            thumbnail=best_thumbnail(entry),
            duration=entry.get("duration"),
            width=entry.get("width"),
            height=entry.get("height"),
            page_url=entry.get("webpage_url") if not is_playlist else page_url,
            playlist_index=index if is_playlist else None,
        )
        if entry.get("_type") in ("url", "url_transparent"):
            # entrée "plate" : on la ré-extraira au moment du téléchargement
            common["page_url"] = entry.get("url") or entry.get("webpage_url")
            common["playlist_index"] = None
            result.items.append(MediaItem(type="video", source="ytdlp", **common))
            continue
        if entry.get("is_live") or entry.get("live_status") in ("is_live", "is_upcoming"):
            live_seen = True
            continue

        formats = [f for f in (entry.get("formats") or []) if isinstance(f, dict)]
        if not formats and entry.get("url"):
            formats = [entry]
        photo_fields = {k: common[k] for k in ("title", "id", "duration", "width", "height")}
        if not formats:
            # Instagram : les photos d'un carrousel arrivent sans format,
            # l'image en pleine résolution est la meilleure miniature.
            if match.service == "instagram" and common["thumbnail"]:
                result.items.append(MediaItem(
                    type="photo", source="direct", url=common["thumbnail"], thumbnail=common["thumbnail"],
                    ext="jpg", headers={"Referer": "https://www.instagram.com/"}, **photo_fields,
                ))
            continue

        mtype = _media_type(formats)
        if mtype == "photo":
            best = formats[-1]
            result.items.append(MediaItem(
                type="photo", source="direct", url=best.get("url"), ext=best.get("ext"),
                thumbnail=common["thumbnail"] or best.get("url"),
                headers=dict(best.get("http_headers") or {}), **photo_fields,
            ))
            continue

        result.items.append(MediaItem(
            type=mtype, source="ytdlp", info=_clean(entry), ext=entry.get("ext"),
            has_audio=_has_audio(formats), **common,
        ))

    if not result.items:
        result.error = "content.live" if live_seen else "content.empty"
    return result
