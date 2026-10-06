"""Configuration, entièrement pilotée par variables d'environnement."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    value = os.environ.get(name)
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _str(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass
class Settings:
    host: str = "0.0.0.0"
    port: int = 9000
    temp_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "saphir")
    # Fichier cookies au format Netscape (cookies.txt), utilisé par yt-dlp,
    # gallery-dl et les extracteurs natifs. Fortement conseillé pour Instagram.
    cookies_file: Path | None = None
    # ou lire directement les cookies d'un navigateur installé (usage local) : firefox, chrome, edge…
    cookies_from_browser: str | None = None
    # Autorise les URLs vers des IP privées / localhost (désactivé par défaut
    # pour éviter le SSRF sur une instance publique).
    allow_private_urls: bool = False
    max_concurrent_jobs: int = 4
    # processus yt-dlp gardés chauds pour l'analyse (0 = un processus par analyse)
    extract_workers: int = 2
    job_ttl: int = 900  # secondes avant suppression d'un fichier téléchargé
    cache_ttl: int = 1800  # secondes de validité d'un résultat d'analyse
    max_items: int = 50  # nombre max d'éléments d'un carrousel / playlist
    max_duration: int = 0  # durée max d'une vidéo en secondes (0 = illimité)
    max_filesize_mb: int = 0  # taille max d'un fichier (0 = illimité)
    rate_limit_per_minute: int = 30  # analyses par minute et par IP (0 = illimité)
    api_key: str | None = None  # si défini, requis dans l'en-tête Authorization
    auto_update: bool = True  # met à jour yt-dlp / gallery-dl automatiquement
    update_channel: str = "nightly"  # "nightly" (correctifs plus rapides) ou "stable"
    update_interval_hours: int = 12
    # Serveur bgutil (PO token YouTube), ex. http://bgutil:4416
    pot_provider_url: str | None = None
    # Proxy sortant pour toutes les requêtes vers les plateformes
    proxy: str | None = None
    extract_timeout: int = 90
    download_timeout: int = 1800
    public_url: str | None = None  # URL publique (API compatible Cobalt)
    trust_proxy: bool = False  # faire confiance à X-Forwarded-For (derrière un reverse proxy)
    # origines autorisées à appeler l'API depuis un navigateur (interface hébergée ailleurs)
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(
            host=_str("HOST", "0.0.0.0"),
            port=_int("PORT", 9000),
            allow_private_urls=_bool("ALLOW_PRIVATE_URLS", False),
            max_concurrent_jobs=max(1, _int("MAX_CONCURRENT_JOBS", 4)),
            extract_workers=max(0, _int("EXTRACT_WORKERS", 2)),
            job_ttl=_int("JOB_TTL", 900),
            cache_ttl=_int("CACHE_TTL", 1800),
            max_items=max(1, _int("MAX_ITEMS", 50)),
            max_duration=_int("MAX_DURATION", 0),
            max_filesize_mb=_int("MAX_FILESIZE_MB", 0),
            rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 30),
            api_key=_str("API_KEY"),
            auto_update=_bool("AUTO_UPDATE", True),
            update_channel=(_str("UPDATE_CHANNEL", "nightly") or "nightly").lower(),
            update_interval_hours=max(1, _int("UPDATE_INTERVAL_HOURS", 12)),
            pot_provider_url=_str("POT_PROVIDER_URL"),
            proxy=_str("PROXY"),
            extract_timeout=_int("EXTRACT_TIMEOUT", 90),
            download_timeout=_int("DOWNLOAD_TIMEOUT", 1800),
            public_url=_str("PUBLIC_URL"),
            trust_proxy=_bool("TRUST_PROXY", False),
            cookies_from_browser=_str("COOKIES_FROM_BROWSER"),
            cors_origins=[o.strip() for o in (_str("CORS_ORIGINS", "*") or "*").split(",") if o.strip()],
        )
        temp = _str("TEMP_DIR")
        if temp:
            s.temp_dir = Path(temp)
        cookies = _str("COOKIES_FILE")
        if cookies is None and Path("cookies.txt").is_file():
            cookies = "cookies.txt"
        if cookies:
            path = Path(cookies).expanduser()
            s.cookies_file = path if path.is_file() else None
        return s


settings = Settings.from_env()
