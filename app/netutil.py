"""Validation des URLs, client HTTP partagé et cookies."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from http.cookiejar import MozillaCookieJar
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import settings
from .errors import AppError

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def normalize_input_url(raw: str) -> str:
    """Nettoie ce que l'utilisateur colle (espaces, texte autour, schéma manquant)."""
    url = (raw or "").strip()
    # Les applis mobiles partagent souvent "Regarde ça ! https://..."
    for token in url.split():
        if token.startswith(("http://", "https://")):
            url = token
            break
    if not url:
        raise AppError("link.empty")
    if "://" not in url:
        url = "https://" + url
    if any(c.isspace() for c in url):
        raise AppError("link.invalid")
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host:
        raise AppError("link.invalid")
    if "." not in host and ":" not in host and host != "localhost":
        raise AppError("link.invalid")
    if len(url) > 2048:
        raise AppError("link.invalid")
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, parts.query, parts.fragment))


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def ensure_public_host(url: str) -> None:
    """Refuse les URLs pointant vers le réseau interne (protection SSRF)."""
    if settings.allow_private_urls:
        return
    host = urlsplit(url).hostname or ""
    if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal")):
        raise AppError("link.private")
    try:
        ipaddress.ip_address(host)
        candidates = [host]
    except ValueError:
        try:
            loop = asyncio.get_running_loop()
            infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            candidates = [info[4][0] for info in infos]
        except OSError:
            # Résolution impossible ici : on laisse les extracteurs échouer
            # proprement (le proxy sortant peut résoudre à notre place).
            return
    if any(not _is_public_ip(ip) for ip in candidates):
        raise AppError("link.private")


def load_cookie_jar() -> MozillaCookieJar | None:
    if not settings.cookies_file:
        return None
    jar = MozillaCookieJar()
    try:
        jar.load(str(settings.cookies_file), ignore_discard=True, ignore_expires=True)
    except (OSError, ValueError):
        return None
    return jar


def cookies_for(domain: str) -> dict[str, str]:
    """Cookies du fichier cookies.txt correspondant à un domaine (ex. 'instagram.com')."""
    jar = load_cookie_jar()
    if not jar:
        return {}
    return {c.name: c.value for c in jar if c.domain.lstrip(".").endswith(domain)}


def cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def http_client(**kwargs) -> httpx.AsyncClient:
    headers = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
    headers.update(kwargs.pop("headers", {}) or {})
    return httpx.AsyncClient(
        headers=headers,
        timeout=kwargs.pop("timeout", httpx.Timeout(20.0, read=60.0)),
        follow_redirects=kwargs.pop("follow_redirects", True),
        proxy=settings.proxy,
        http2=False,
        **kwargs,
    )
