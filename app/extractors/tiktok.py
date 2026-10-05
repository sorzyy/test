"""Extraction native TikTok : vidéos sans filigrane et diaporamas photo (+ musique)."""

from __future__ import annotations

import json
import re

from ..models import MediaItem
from ..netutil import cookie_header, cookies_for, http_client
from ..services import ServiceMatch, detect
from . import ExtractResult

_REHYDRATION = re.compile(
    r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S)
_SIGI = re.compile(r'<script[^>]+id="SIGI_STATE"[^>]*>(.*?)</script>', re.S)


async def resolve_short_link(url: str) -> str | None:
    """vm.tiktok.com / vt.tiktok.com / tiktok.com/t/... -> lien complet."""
    async with http_client(follow_redirects=False, headers={"User-Agent": "curl/8.5.0"}) as client:
        for _ in range(5):
            r = await client.get(url)
            location = r.headers.get("location")
            if not location:
                m = re.search(r'<a href="(https://[^"]+)"', r.text or "")
                location = m.group(1) if m else None
            if not location:
                return None
            location = location.replace("&amp;", "&")
            if re.search(r"/(?:video|photo)/\d+", location):
                return location
            url = location
    return None


def find_item_struct(html: str) -> tuple[dict | None, str | None]:
    """Renvoie (itemStruct, code_erreur) depuis le HTML d'une page TikTok."""
    m = _REHYDRATION.search(html or "")
    if m:
        try:
            data = json.loads(m.group(1))
        except ValueError:
            return None, "fetch.fail"
        detail = (data.get("__DEFAULT_SCOPE__") or {}).get("webapp.video-detail")
        if not detail:
            return None, "fetch.fail"
        status = detail.get("statusCode")
        if status not in (None, 0) or detail.get("statusMsg"):
            msg = str(detail.get("statusMsg") or "")
            if status == 10216 or "private" in msg.lower():
                return None, "content.private"
            return None, "content.unavailable"
        item = (detail.get("itemInfo") or {}).get("itemStruct")
        return (item, None) if item else (None, "content.empty")
    m = _SIGI.search(html or "")
    if m:
        try:
            data = json.loads(m.group(1))
            items = (data.get("ItemModule") or {})
            item = next(iter(items.values()), None)
            return (item, None) if item else (None, "content.empty")
        except ValueError:
            pass
    return None, "fetch.fail"


def parse_item(item: dict, post_id: str, cookie: str) -> ExtractResult:
    result = ExtractResult("tiktok-native")
    author = item.get("author")
    result.author = author.get("uniqueId") if isinstance(author, dict) else author
    result.title = (item.get("desc") or "").strip()
    if item.get("isContentClassified"):
        result.error = "content.age"
        return result
    headers = {"Referer": "https://www.tiktok.com/"}
    if cookie:
        headers["Cookie"] = cookie
    base = dict(title=result.title, headers=headers)
    video = item.get("video") or {}
    music = item.get("music") or {}
    images = (item.get("imagePost") or {}).get("images") or []

    if images:
        for i, img in enumerate(images, 1):
            urls = ((img.get("imageURL") or {}).get("urlList")) or []
            if not urls:
                continue
            url = next((u for u in urls if ".jpeg?" in u or ".jpg?" in u), urls[0])
            result.items.append(MediaItem(type="photo", source="direct", url=url, thumbnail=url, ext="jpg",
                                          id=f"{post_id}_{i}", width=img.get("imageWidth"),
                                          height=img.get("imageHeight"), **base))
        audio_url = music.get("playUrl") or video.get("playAddr")
        if audio_url:
            ext = "mp3" if "mime_type=audio_mpeg" in audio_url or ".mp3" in audio_url else "m4a"
            result.audio = MediaItem(type="audio", source="direct", url=audio_url, ext=ext,
                                     id=f"{post_id}_audio", duration=music.get("duration"),
                                     **{**base, "title": music.get("title") or result.title})
        if not result.ok:
            result.error = "content.empty"
        return result

    play = video.get("playAddr")
    # bitrateInfo contient les variantes h264 sans filigrane
    variants = []
    for b in video.get("bitrateInfo") or []:
        urls = ((b.get("PlayAddr") or {}).get("UrlList")) or []
        if urls:
            codec = str(b.get("CodecType") or "")
            variants.append((("h264" in codec), b.get("Bitrate") or 0, urls[-1]))
    if variants:
        variants.sort(reverse=True)
        play = variants[0][2]
    if play:
        result.items.append(MediaItem(
            type="video", source="direct", url=play, ext="mp4", id=post_id,
            thumbnail=video.get("originCover") or video.get("cover"),
            duration=video.get("duration"), width=video.get("width"), height=video.get("height"),
            has_audio=True, **base))
    if music.get("playUrl"):
        result.audio = MediaItem(type="audio", source="direct", url=music["playUrl"], ext="mp3",
                                 id=f"{post_id}_audio", **{**base, "title": music.get("title") or result.title})
    if not result.items:
        result.error = "content.empty"
    return result


async def extract(match: ServiceMatch) -> ExtractResult:
    post_id = match.post_id
    if not post_id and match.kind == "short":
        full = await resolve_short_link(match.url)
        if full:
            post_id = detect(full).post_id
    if not post_id:
        return ExtractResult("tiktok-native", error="link.unsupported")

    cookies = cookies_for("tiktok.com")
    async with http_client(headers={"Cookie": cookie_header(cookies)} if cookies else None) as client:
        try:
            # toujours /video/, même pour les diaporamas photo
            r = await client.get(f"https://www.tiktok.com/@i/video/{post_id}")
        except Exception as exc:
            return ExtractResult("tiktok-native", error="fetch.fail", detail=str(exc)[:200])
        item, error = find_item_struct(r.text)
        if not item:
            return ExtractResult("tiktok-native", error=error or "fetch.fail")
        jar = {**cookies, **{c.name: c.value for c in client.cookies.jar}}
        return parse_item(item, post_id, cookie_header(jar))
