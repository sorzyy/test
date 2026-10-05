"""Détection de la plateforme et normalisation des liens."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


@dataclass
class ServiceMatch:
    service: str  # youtube | instagram | twitter | tiktok | generic
    url: str  # URL normalisée à donner aux extracteurs
    post_id: str | None = None
    kind: str | None = None  # post, reel, story, share, photo, video, short...
    username: str | None = None


_YT_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
_IG_HOSTS = ("instagram.com", "ddinstagram.com", "kkinstagram.com", "instagramez.com")
_TW_HOSTS = ("twitter.com", "x.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com",
             "fixvx.com", "twittpr.com", "nitter.net", "xcancel.com")
_TT_HOSTS = ("tiktok.com", "tiktokv.com")


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def detect(url: str) -> ServiceMatch:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path or "/"

    if _host_matches(host, _YT_HOSTS):
        return _youtube(parts, host, path)
    if _host_matches(host, _IG_HOSTS):
        return _instagram(parts, path)
    if _host_matches(host, _TW_HOSTS):
        return _twitter(url, path)
    if _host_matches(host, _TT_HOSTS):
        return _tiktok(url, host, path)
    return ServiceMatch("generic", url)


def _youtube(parts, host: str, path: str) -> ServiceMatch:
    query = parse_qs(parts.query)
    video_id = None
    kind = "video"
    if host.endswith("youtu.be"):
        video_id = path.strip("/").split("/")[0] or None
    elif m := re.match(r"^/(shorts|live|embed|v|e)/([\w-]{6,})", path):
        kind = "short" if m.group(1) == "shorts" else m.group(1)
        video_id = m.group(2)
    elif "v" in query:
        video_id = query["v"][0]
    elif path.startswith("/playlist"):
        kind = "playlist"

    if video_id and re.fullmatch(r"[\w-]{11}", video_id):
        keep = {}
        if "t" in query:
            keep["t"] = query["t"][0]
        music = host.startswith("music.")
        base = "https://music.youtube.com/watch" if music else "https://www.youtube.com/watch"
        url = base + "?" + urlencode({"v": video_id, **keep})
        return ServiceMatch("youtube", url, video_id, kind)
    return ServiceMatch("youtube", urlunsplit(parts), None, kind)


def _instagram(parts, path: str) -> ServiceMatch:
    if m := re.match(r"^/share/(?:(?:p|reels?|v)/)?([\w-]+)", path):
        return ServiceMatch("instagram", f"https://www.instagram.com{path}", m.group(1), "share")
    if m := re.match(r"^/(?:[\w.]+/)?(p|reels?|tv)/([\w-]+)", path):
        kind = {"p": "post", "reel": "reel", "reels": "reel", "tv": "post"}[m.group(1)]
        sc = m.group(2)
        segment = "reel" if kind == "reel" else "p"
        return ServiceMatch("instagram", f"https://www.instagram.com/{segment}/{sc}/", sc, kind)
    if m := re.match(r"^/stories/([\w.]+)/(\d+)", path):
        return ServiceMatch("instagram", f"https://www.instagram.com/stories/{m.group(1)}/{m.group(2)}/",
                            m.group(2), "story", m.group(1))
    return ServiceMatch("instagram", urlunsplit(("https", "www.instagram.com", path, parts.query, "")))


def _twitter(url: str, path: str) -> ServiceMatch:
    m = re.match(r"^/(?:([\w]{1,20})|i(?:/web)?)/status(?:es)?/(\d+)", path) or \
        re.match(r"^/i/(?:web/)?status/(\d+)", path)
    if m:
        groups = [g for g in m.groups()]
        tweet_id = groups[-1]
        user = groups[0] if len(groups) > 1 and groups[0] not in (None, "i") else None
        norm = f"https://x.com/{user or 'i'}/status/{tweet_id}"
        return ServiceMatch("twitter", norm, tweet_id, "tweet", user)
    return ServiceMatch("twitter", url)


def _tiktok(url: str, host: str, path: str) -> ServiceMatch:
    if m := re.match(r"^/@([\w.-]*)/(video|photo)/(\d+)", path):
        user, kind, pid = m.groups()
        return ServiceMatch("tiktok", f"https://www.tiktok.com/@{user or 'i'}/{kind}/{pid}", pid, kind, user or None)
    if m := re.match(r"^/(?:share/video|embed(?:/v2)?|v)/(\d+)", path):
        pid = m.group(1)
        return ServiceMatch("tiktok", f"https://www.tiktok.com/@i/video/{pid}", pid, "video")
    if host.startswith(("vm.", "vt.")) or path.startswith("/t/"):
        return ServiceMatch("tiktok", url, None, "short")
    return ServiceMatch("tiktok", url)


SUPPORTED_SERVICES = [
    {"id": "youtube", "name": "YouTube", "note": "vidéos, shorts, music"},
    {"id": "instagram", "name": "Instagram", "note": "reels, posts, carrousels, photos"},
    {"id": "twitter", "name": "X / Twitter", "note": "vidéos, gifs, photos"},
    {"id": "tiktok", "name": "TikTok", "note": "vidéos sans filigrane, diaporamas photo"},
    {"id": "generic", "name": "+1800 autres sites",
     "note": "Reddit, Facebook, Vimeo, Twitch, SoundCloud, Pinterest, Bluesky, Dailymotion…"},
]
