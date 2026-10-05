"""Structures de données partagées."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MediaItem:
    type: str  # video | photo | gif | audio
    source: str  # ytdlp | direct
    title: str = ""
    id: str = ""
    thumbnail: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    ext: str | None = None
    # source == "direct" : URL du fichier + en-têtes nécessaires
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    # source == "ytdlp" : dictionnaire d'info complet (rejoué au téléchargement)
    info: dict[str, Any] | None = None
    # pour re-extraire si l'info a expiré
    page_url: str | None = None
    playlist_index: int | None = None
    has_audio: bool | None = None

    def public(self, index: int) -> dict:
        return {
            "index": index,
            "type": self.type,
            "title": self.title,
            "id": self.id,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "ext": self.ext,
            "hasThumbnail": bool(self.thumbnail),
        }


@dataclass
class Resolved:
    service: str
    url: str
    title: str = ""
    author: str | None = None
    items: list[MediaItem] = field(default_factory=list)
    # bande-son d'un diaporama (TikTok) : proposée en mode audio
    audio: MediaItem | None = None
    engines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        d = asdict(self)
        d.pop("items")
        d.pop("audio")
        return d
