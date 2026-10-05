"""Extraction native X / Twitter : photos, vidéos et gifs sans compte.

1. API "syndication" (celle des tweets intégrés sur les sites web)
2. API publique fxtwitter en secours
"""

from __future__ import annotations

import math
from urllib.parse import urlsplit, urlunsplit

from ..models import MediaItem
from ..netutil import http_client
from ..services import ServiceMatch
from . import ExtractResult

_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def js_to_radix(value: float, radix: int = 36) -> str:
    """Réplique exacte de Number.prototype.toString(radix) de V8 (DoubleToRadixCString)."""
    if value == 0:
        return "0"
    negative = value < 0
    value = abs(value)
    integer = math.floor(value)
    fraction = value - integer
    delta = max(0.5 * (math.nextafter(value, math.inf) - value), math.nextafter(0.0, 1.0))
    frac_digits: list[str] = []
    if fraction >= delta:
        while True:
            fraction *= radix
            delta *= radix
            digit = int(fraction)
            frac_digits.append(_DIGITS[digit])
            fraction -= digit
            if fraction > 0.5 or (fraction == 0.5 and (digit & 1)):
                if fraction + delta > 1:
                    # arrondi supérieur avec propagation de la retenue
                    while True:
                        if not frac_digits:
                            integer += 1
                            break
                        last = frac_digits.pop()
                        d = _DIGITS.index(last)
                        if d + 1 < radix:
                            frac_digits.append(_DIGITS[d + 1])
                            break
                    break
            if not fraction >= delta:
                break
    # partie entière, avec les mêmes arrondis flottants que V8 au-delà de 2^53
    int_digits = []
    integer = float(integer)
    while integer / radix >= 2.0 ** 53:
        integer /= radix
        int_digits.append("0")
    while True:
        rem = math.fmod(integer, radix)
        int_digits.append(_DIGITS[int(rem)])
        integer = (integer - rem) / radix
        if integer <= 0:
            break
    out = "".join(reversed(int_digits))
    if frac_digits:
        out += "." + "".join(frac_digits)
    return ("-" if negative else "") + out


def syndication_token(tweet_id: str) -> str:
    raw = js_to_radix((int(tweet_id) / 1e15) * math.pi, 36)
    return raw.replace("0", "").replace(".", "")


def orig_photo(url: str) -> str:
    """URL d'une photo pbs.twimg.com en qualité originale."""
    parts = urlsplit(url)
    if "pbs.twimg.com" not in parts.netloc:
        return url
    path = parts.path.split(":")[0]
    if "." in path.rsplit("/", 1)[-1]:
        base, ext = path.rsplit(".", 1)
        return urlunsplit((parts.scheme, parts.netloc, base, f"format={ext}&name=orig", ""))
    return urlunsplit((parts.scheme, parts.netloc, path, "name=orig", ""))


def _best_mp4(variants: list[dict]) -> dict | None:
    mp4 = [v for v in variants or [] if (v.get("content_type") or v.get("type")) == "video/mp4" and (v.get("url") or v.get("src"))]
    if not mp4:
        return None
    return max(mp4, key=lambda v: v.get("bitrate") or 0)


def parse_syndication(data: dict, tweet_id: str) -> ExtractResult:
    result = ExtractResult("syndication")
    if not isinstance(data, dict) or data.get("__typename") == "TweetTombstone":
        result.error = "content.unavailable"
        return result
    user = data.get("user") or {}
    result.author = user.get("screen_name")
    result.title = (data.get("text") or "").strip()
    medias = data.get("mediaDetails") or []
    for i, m in enumerate(medias, 1):
        mtype = m.get("type")
        thumb = m.get("media_url_https")
        info = m.get("original_info") or {}
        common = dict(title=result.title, id=f"{tweet_id}_{i}", width=info.get("width"), height=info.get("height"),
                      headers={"Referer": "https://x.com/"})
        if mtype == "photo" and thumb:
            result.items.append(MediaItem(type="photo", source="direct", url=orig_photo(thumb),
                                          thumbnail=thumb, ext="jpg", **common))
        elif mtype in ("video", "animated_gif"):
            best = _best_mp4((m.get("video_info") or {}).get("variants") or [])
            if not best:
                continue
            duration = (m.get("video_info") or {}).get("duration_millis")
            result.items.append(MediaItem(
                type="gif" if mtype == "animated_gif" else "video", source="direct", url=best["url"],
                thumbnail=thumb, ext="mp4", duration=duration / 1000 if duration else None, **common))
    if not result.items:
        result.error = "content.empty"
    return result


def parse_fxtwitter(data: dict, tweet_id: str) -> ExtractResult:
    result = ExtractResult("fxtwitter")
    tweet = (data or {}).get("tweet") or {}
    if not tweet:
        result.error = "content.unavailable" if (data or {}).get("code") == 404 else "fetch.fail"
        return result
    result.title = (tweet.get("text") or "").strip()
    result.author = (tweet.get("author") or {}).get("screen_name")
    media = tweet.get("media") or {}
    all_media = media.get("all") or (media.get("photos") or []) + (media.get("videos") or [])
    for i, m in enumerate(all_media, 1):
        mtype = m.get("type")
        url = m.get("url")
        if not url:
            continue
        common = dict(title=result.title, id=f"{tweet_id}_{i}", width=m.get("width"), height=m.get("height"),
                      headers={"Referer": "https://x.com/"})
        if mtype == "photo":
            result.items.append(MediaItem(type="photo", source="direct", url=orig_photo(url),
                                          thumbnail=url, ext="jpg", **common))
        elif mtype in ("video", "gif"):
            best = _best_mp4(m.get("variants") or []) or {"url": url}
            result.items.append(MediaItem(type=mtype, source="direct", url=best.get("url") or best.get("src"),
                                          thumbnail=m.get("thumbnail_url"), ext="mp4",
                                          duration=m.get("duration"), **common))
    if not result.items:
        result.error = "content.empty"
    return result


async def extract(match: ServiceMatch) -> ExtractResult:
    tweet_id = match.post_id
    if not tweet_id:
        return ExtractResult("twitter-native", error="link.unsupported")
    async with http_client() as client:
        result = ExtractResult("syndication", error="fetch.fail")
        try:
            r = await client.get("https://cdn.syndication.twimg.com/tweet-result", params={
                "id": tweet_id, "token": syndication_token(tweet_id), "lang": "en",
            })
            if r.status_code == 200 and r.content:
                result = parse_syndication(r.json(), tweet_id)
            elif r.status_code == 404:
                result = ExtractResult("syndication", error="content.unavailable")
        except Exception as exc:  # réseau, JSON invalide...
            result = ExtractResult("syndication", error="fetch.fail", detail=str(exc)[:200])
        if result.ok:
            return result
        try:
            r = await client.get(f"https://api.fxtwitter.com/{match.username or 'i'}/status/{tweet_id}")
            fx = parse_fxtwitter(r.json(), tweet_id)
            if fx.ok:
                return fx
        except Exception:
            pass
        return result
