"""Extracteurs : yt-dlp, gallery-dl et implémentations natives par plateforme."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import MediaItem

IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "heic", "heif", "avif", "bmp", "tif", "tiff"}
VIDEO_EXTS = {"mp4", "webm", "mov", "m4v", "mkv", "avi", "flv", "ts", "3gp"}
AUDIO_EXTS = {"mp3", "m4a", "aac", "opus", "ogg", "oga", "wav", "flac", "weba"}


def kind_from_ext(ext: str | None) -> str | None:
    ext = (ext or "").lower()
    if ext == "gif":
        return "gif"
    if ext in IMAGE_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


@dataclass
class ExtractResult:
    engine: str
    items: list[MediaItem] = field(default_factory=list)
    title: str = ""
    author: str | None = None
    audio: MediaItem | None = None  # bande-son d'un diaporama
    error: str | None = None  # code d'erreur (voir errors.py)
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.items) or self.audio is not None
