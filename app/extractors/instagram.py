"""Extraction native Instagram (posts, reels, carrousels, photos).

Plusieurs méthodes sont essayées dans l'ordre, sans puis avec cookies :
API mobile, page "embed", API GraphQL du site web.
"""

from __future__ import annotations

import json
import random
import re
import secrets
import string
import time

from ..models import MediaItem
from ..netutil import BROWSER_UA, cookie_header, cookies_for, http_client
from ..services import ServiceMatch, detect
from . import ExtractResult

APP_ID = "936619743392459"
GQL_DOC_ID = "8845758582119845"
_B64 = string.ascii_uppercase + string.ascii_lowercase + string.digits + "-_"

MOBILE_HEADERS = {
    "x-ig-app-locale": "en_US",
    "x-ig-device-locale": "en_US",
    "x-ig-mapped-locale": "en_US",
    "user-agent": "Instagram 275.0.0.27.98 Android (33/13; 280dpi; 720x1423; Xiaomi; Redmi 7; onclite; qcom; en_US; 458229237)",
    "accept-language": "en-US",
    "x-fb-http-engine": "Liger",
    "x-fb-client-ip": "True",
    "x-fb-server-cluster": "True",
}

EMBED_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "max-age=0",
    "Dnt": "1",
    "Sec-Ch-Ua": '"Chromium";v="140", "Google Chrome";v="140", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": BROWSER_UA,
}

MEDIA_HEADERS = {"Referer": "https://www.instagram.com/"}


def shortcode_to_media_id(shortcode: str) -> str | None:
    code = shortcode[:11]
    if not code or any(c not in _B64 for c in code):
        return None
    n = 0
    for c in code:
        n = n * 64 + _B64.index(c)
    return str(n)


def _largest(versions: list[dict]) -> dict | None:
    versions = [v for v in versions or [] if v.get("url")]
    if not versions:
        return None
    return max(versions, key=lambda v: (v.get("width") or 0) * (v.get("height") or 0))


def _photo(url: str, idx: str, title: str, w=None, h=None) -> MediaItem:
    return MediaItem(type="photo", source="direct", url=url, thumbnail=url, ext="jpg", id=idx,
                     title=title, width=w, height=h, headers=dict(MEDIA_HEADERS))


def _video(url: str, thumb: str | None, idx: str, title: str, w=None, h=None, duration=None) -> MediaItem:
    return MediaItem(type="video", source="direct", url=url, thumbnail=thumb, ext="mp4", id=idx,
                     title=title, width=w, height=h, duration=duration, has_audio=True,
                     headers=dict(MEDIA_HEADERS))


def parse_mobile_item(data: dict, shortcode: str) -> ExtractResult:
    """Format de l'API mobile / "nouveau" format (carousel_media, video_versions...)."""
    result = ExtractResult("instagram-native")
    result.author = (data.get("user") or {}).get("username")
    result.title = ((data.get("caption") or {}).get("text") or "").strip()
    nodes = data.get("carousel_media") or [data]
    for i, node in enumerate(nodes, 1):
        idx = f"{shortcode}_{i}" if len(nodes) > 1 else shortcode
        image = _largest((node.get("image_versions2") or {}).get("candidates") or [])
        video = _largest(node.get("video_versions") or [])
        if video:
            result.items.append(_video(video["url"], image and image["url"], idx, result.title,
                                       video.get("width"), video.get("height"), node.get("video_duration")))
        elif image:
            result.items.append(_photo(image["url"], idx, result.title, image.get("width"), image.get("height")))
    if not result.items:
        result.error = "content.empty"
    return result


def parse_gql_media(media: dict, shortcode: str) -> ExtractResult:
    """Format GraphQL / embed (shortcode_media, edge_sidecar_to_children...)."""
    result = ExtractResult("instagram-native")
    result.author = (media.get("owner") or {}).get("username")
    edges = ((media.get("edge_media_to_caption") or {}).get("edges")) or []
    if edges:
        result.title = ((edges[0].get("node") or {}).get("text") or "").strip()
    children = [e.get("node") or {} for e in ((media.get("edge_sidecar_to_children") or {}).get("edges") or [])]
    nodes = children or [media]
    for i, node in enumerate(nodes, 1):
        idx = f"{shortcode}_{i}" if len(nodes) > 1 else shortcode
        dims = node.get("dimensions") or {}
        if node.get("is_video") and node.get("video_url"):
            result.items.append(_video(node["video_url"], node.get("display_url"), idx, result.title,
                                       dims.get("width"), dims.get("height"), node.get("video_duration")))
        elif node.get("display_url"):
            result.items.append(_photo(node["display_url"], idx, result.title, dims.get("width"), dims.get("height")))
    if not result.items:
        result.error = "content.empty"
    return result


def parse_embed_html(html: str) -> dict | None:
    """Extrait le shortcode_media du JSON caché dans la page /embed/captioned/."""
    m = re.search(r'"init",\[\],\[(.*?)\]\],', html or "")
    if m:
        try:
            outer = json.loads(m.group(1))
            ctx = json.loads(outer.get("contextJSON") or "null")
            media = ((ctx or {}).get("gql_data") or {})
            media = media.get("shortcode_media") or media.get("xdt_shortcode_media")
            if media:
                return media
        except (ValueError, AttributeError):
            pass
    m = re.search(r'\\"gql_data\\":(\{.*?\})\}\"', html or "")
    if m:
        try:
            gql = json.loads(m.group(1).encode().decode("unicode_escape"))
            return gql.get("shortcode_media") or gql.get("xdt_shortcode_media")
        except (ValueError, UnicodeDecodeError):
            pass
    return None


def _entry_object(name: str, html: str) -> dict | None:
    m = re.search(r'\["' + re.escape(name) + r'",.*?,(\{.*?\}),\d+\]', html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _number_from_query(name: str, html: str) -> str | None:
    m = re.search(name + r"=(\d+)", html)
    return m.group(1) if m else None


class _Session:
    def __init__(self, client, cookies: dict[str, str]):
        self.client = client
        self.cookies = cookies

    @property
    def cookie(self) -> str:
        return cookie_header(self.cookies)

    async def media_id(self, shortcode: str, with_cookie: bool) -> str | None:
        headers = dict(MOBILE_HEADERS)
        if with_cookie and self.cookies:
            headers["cookie"] = self.cookie
        try:
            r = await self.client.get("https://i.instagram.com/api/v1/oembed/",
                                      params={"url": f"https://www.instagram.com/p/{shortcode}/"}, headers=headers)
            return str(r.json().get("media_id") or "").split("_")[0] or None
        except Exception:
            return None

    async def mobile_api(self, media_id: str, with_cookie: bool) -> dict | None:
        headers = dict(MOBILE_HEADERS)
        if with_cookie:
            if not self.cookies:
                return None
            headers["cookie"] = self.cookie
            if self.cookies.get("csrftoken"):
                headers["x-csrftoken"] = self.cookies["csrftoken"]
        try:
            r = await self.client.get(f"https://i.instagram.com/api/v1/media/{media_id}/info/", headers=headers)
            items = r.json().get("items") or []
            return items[0] if items else None
        except Exception:
            return None

    async def embed(self, shortcode: str, with_cookie: bool) -> dict | None:
        headers = dict(EMBED_HEADERS)
        if with_cookie:
            if not self.cookies:
                return None
            headers["cookie"] = self.cookie
        try:
            r = await self.client.get(f"https://www.instagram.com/p/{shortcode}/embed/captioned/", headers=headers)
            return parse_embed_html(r.text)
        except Exception:
            return None

    async def graphql(self, shortcode: str, with_cookie: bool) -> dict | None:
        if with_cookie and not self.cookies:
            return None
        try:
            r = await self.client.get(f"https://www.instagram.com/p/{shortcode}/", headers={
                **EMBED_HEADERS, **({"cookie": self.cookie} if with_cookie else {})})
            html = r.text
            site = _entry_object("SiteData", html) or {}
            polaris = _entry_object("PolarisSiteData", html) or {}
            web = _entry_object("DGWWebConfig", html) or {}
            push = _entry_object("InstagramWebPushInfo", html) or {}
            lsd = (_entry_object("LSD", html) or {}).get("token") or secrets.token_urlsafe(8)
            csrf = (_entry_object("InstagramSecurityConfig", html) or {}).get("csrf_token")
            anon = "; ".join(x for x in [
                csrf and f"csrftoken={csrf}",
                polaris.get("device_id") and f"ig_did={polaris['device_id']}",
                "wd=1280x720", "dpr=2",
                polaris.get("machine_id") and f"mid={polaris['machine_id']}",
                "ig_nrcb=1",
            ] if x)
            headers = {
                **EMBED_HEADERS,
                "x-ig-app-id": str(web.get("appId") or APP_ID),
                "X-FB-LSD": lsd,
                "X-CSRFToken": csrf or "",
                "X-Bloks-Version-Id": str((_entry_object("WebBloksVersioningID", html) or {}).get("versioningID") or ""),
                "x-asbd-id": "129477",
                "cookie": self.cookie if with_cookie else anon,
                "content-type": "application/x-www-form-urlencoded",
                "X-FB-Friendly-Name": "PolarisPostActionLoadPostQueryQuery",
            }
            body = {
                "__d": "www", "__a": "1",
                "__s": "::" + "".join(random.choices(string.ascii_lowercase, k=6)),
                "__hs": site.get("haste_session") or "20126.HYP:instagram_web_pkg.2.1...0",
                "__req": "b", "__ccg": "EXCELLENT",
                "__rev": str(push.get("rollout_hash") or "1019933358"),
                "__hsi": str(site.get("hsi") or "7436540909012459023"),
                "__dyn": secrets.token_urlsafe(154), "__csr": secrets.token_urlsafe(154),
                "__user": "0", "__comet_req": _number_from_query("__comet_req", html) or "7",
                "av": "0", "dpr": "2", "lsd": lsd,
                "jazoest": _number_from_query("jazoest", html) or str(random.randint(1000, 9999)),
                "__spin_r": str(site.get("__spin_r") or "1019933358"),
                "__spin_b": site.get("__spin_b") or "trunk",
                "__spin_t": str(site.get("__spin_t") or int(time.time())),
                "fb_api_caller_class": "RelayModern",
                "fb_api_req_friendly_name": "PolarisPostActionLoadPostQueryQuery",
                "variables": json.dumps({"shortcode": shortcode, "fetch_tagged_user_count": None,
                                         "hoisted_comment_id": None, "hoisted_reply_id": None}),
                "server_timestamps": "true",
                "doc_id": GQL_DOC_ID,
            }
            r = await self.client.post("https://www.instagram.com/graphql/query", data=body, headers=headers)
            data = (r.json() or {}).get("data") or {}
            return data.get("xdt_shortcode_media") or data.get("shortcode_media")
        except Exception:
            return None


async def resolve_share(url: str) -> str | None:
    """instagram.com/share/... -> URL du post (Instagram renvoie une redirection à curl)."""
    async with http_client(follow_redirects=False, headers={"User-Agent": "curl/8.5.0"}) as client:
        try:
            for _ in range(4):
                r = await client.get(url)
                loc = r.headers.get("location")
                if not loc:
                    return None
                if re.search(r"/(?:p|reels?|tv)/[\w-]+", loc):
                    return loc
                url = loc
        except Exception:
            return None
    return None


async def extract(match: ServiceMatch) -> ExtractResult:
    if match.kind == "share":
        full = await resolve_share(match.url)
        if not full:
            return ExtractResult("instagram-native", error="fetch.fail")
        match = detect(full)
    if match.kind not in ("post", "reel") or not match.post_id:
        return ExtractResult("instagram-native", error="link.unsupported")
    shortcode = match.post_id
    cookies = cookies_for("instagram.com")

    async with http_client() as client:
        s = _Session(client, cookies)
        media_id = await s.media_id(shortcode, False) or (cookies and await s.media_id(shortcode, True)) \
            or shortcode_to_media_id(shortcode)
        if media_id:
            for with_cookie in (False, True):
                item = await s.mobile_api(media_id, with_cookie)
                if item:
                    res = parse_mobile_item(item, shortcode)
                    if res.ok:
                        return res
        for method in (s.embed, s.graphql):
            for with_cookie in (False, True):
                media = await method(shortcode, with_cookie)
                if media:
                    res = parse_gql_media(media, shortcode)
                    if res.ok:
                        return res
    return ExtractResult("instagram-native", error="content.login" if not cookies else "fetch.fail")
