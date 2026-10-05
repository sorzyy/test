"""Extraction via gallery-dl (photos, carrousels, galeries : ~300 sites)."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from ..config import settings
from ..errors import classify, last_error_line
from ..models import MediaItem
from ..tools import cookies_copy, gallerydl_base_args, run
from . import ExtractResult, kind_from_ext

MSG_URL = 3
MSG_QUEUE = 6


async def extract(url: str, options: list[str] | None = None) -> ExtractResult:
    with cookies_copy() as cookies:
        cmd = gallerydl_base_args(cookies) + ["-j", "--range", f"1-{settings.max_items}"]
        for opt in options or []:
            cmd += ["-o", opt]
        cmd += ["--", url]
        res = await run(cmd, settings.extract_timeout)
    if res.timed_out:
        return ExtractResult("gallery-dl", error="fetch.timeout")
    try:
        messages = json.loads(res.stdout) if res.stdout.strip() else None
    except ValueError:
        messages = None
    if not isinstance(messages, list):
        return ExtractResult("gallery-dl", error=classify(res.stderr), detail=last_error_line(res.stderr))
    return parse_messages(messages, url, res.stderr)


def _referer(page_url: str) -> str:
    parts = urlsplit(page_url)
    return f"{parts.scheme}://{parts.netloc}/"


def _author(kw: dict) -> str | None:
    for key in ("username", "author", "user", "uploader"):
        value = kw.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("nick") or value.get("screen_name") or value.get("uniqueId")
        if isinstance(value, str) and value:
            return value
    return None


def parse_messages(messages: list, page_url: str, stderr: str = "") -> ExtractResult:
    result = ExtractResult("gallery-dl")
    referer = _referer(page_url)
    errors: list[str] = []
    for msg in messages:
        if not isinstance(msg, list) or not msg:
            continue
        mtype = msg[0]
        if mtype == -1 and len(msg) > 1 and isinstance(msg[1], dict):
            errors.append(f"{msg[1].get('error', '')}: {msg[1].get('message', '')}")
            continue
        if mtype not in (MSG_URL, MSG_QUEUE) or len(msg) < 3:
            continue
        url, kw = msg[1], msg[2] if isinstance(msg[2], dict) else {}
        if not isinstance(url, str):
            continue
        title = (kw.get("description") or kw.get("content") or kw.get("title")
                 or kw.get("desc") or kw.get("filename") or "")
        if not result.title:
            result.title = str(title)[:300]
            result.author = _author(kw)
        common = dict(
            title=str(title)[:300],
            id=str(kw.get("media_id") or kw.get("id") or kw.get("filename") or ""),
            width=kw.get("width") if isinstance(kw.get("width"), int) else None,
            height=kw.get("height") if isinstance(kw.get("height"), int) else None,
        )
        if url.startswith("ytdl:") or mtype == MSG_QUEUE:
            # gallery-dl délègue cette vidéo à yt-dlp
            target = url[5:] if url.startswith("ytdl:") else url
            if target.startswith("http"):
                result.items.append(MediaItem(type="video", source="ytdlp", page_url=target, **common))
            continue
        ext = (kw.get("extension") or urlsplit(url).path.rsplit(".", 1)[-1]).lower()
        kind = kind_from_ext(ext)
        if kind is None:
            continue
        item = MediaItem(type=kind, source="direct", url=url, ext=ext,
                         headers={"Referer": referer}, **common)
        if kind in ("photo", "gif"):
            item.thumbnail = url
        else:
            item.thumbnail = kw.get("display_url") or kw.get("thumbnail") or kw.get("cover")
            if isinstance(kw.get("duration"), (int, float)):
                item.duration = float(kw["duration"])
        if kind == "audio" and result.audio is None and kw.get("post_type") == "image":
            # diaporama TikTok : la musique accompagne les photos
            result.audio = item
            continue
        result.items.append(item)

    if not result.ok:
        result.error = classify("\n".join(errors) + "\n" + stderr) if (errors or stderr.strip()) else "content.empty"
        result.detail = (errors[-1] if errors else last_error_line(stderr)) or None
    return result
