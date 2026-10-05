"""Options de téléchargement et traduction en arguments yt-dlp / ffmpeg."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

QUALITIES = ("max", "4320", "2160", "1440", "1080", "720", "480", "360", "240", "144")
AUDIO_FORMATS = ("mp3", "best", "m4a", "opus", "ogg", "wav")
AUDIO_BITRATES = ("320", "256", "192", "128", "96", "64")


class Options(BaseModel):
    mode: Literal["auto", "audio", "mute"] = "auto"
    quality: str = "1080"
    codec: Literal["h264", "av1", "vp9", "best"] = "h264"
    audio_format: str = "mp3"
    audio_bitrate: str = "320"
    convert_gif: bool = True

    @field_validator("quality")
    @classmethod
    def _quality(cls, v: str) -> str:
        v = str(v).lower().rstrip("p")
        return v if v in QUALITIES else "1080"

    @field_validator("audio_format")
    @classmethod
    def _audio_format(cls, v: str) -> str:
        v = str(v).lower()
        return v if v in AUDIO_FORMATS else "mp3"

    @field_validator("audio_bitrate")
    @classmethod
    def _bitrate(cls, v: str) -> str:
        v = str(v)
        return v if v in AUDIO_BITRATES else "320"


_CODEC_SORT = {"h264": "vcodec:h264", "av1": "vcodec:av01", "vp9": "vcodec:vp9"}


def ytdlp_format_args(opts: Options) -> list[str]:
    if opts.mode == "audio":
        # la conversion est faite ensuite par saphir (ffmpeg), plus fiable que -x
        return ["-f", "ba/b"]

    res = "res" if opts.quality == "max" else f"res:{opts.quality}"
    sort: list[str] = []
    if opts.codec == "best":
        sort = [res]
    else:
        sort = [_CODEC_SORT[opts.codec], res]
    sort.append("acodec:opus" if opts.codec == "vp9" else "acodec:aac")

    fmt = "bv*+ba/b" if opts.mode == "auto" else "bv/bv*/b"
    merge = "webm/mkv" if opts.codec == "vp9" else "mp4"
    return ["-f", fmt, "-S", ",".join(sort), "--merge-output-format", merge]


def ffmpeg_audio_args(opts: Options, src_ext: str | None) -> tuple[list[str], str]:
    """Arguments ffmpeg pour convertir en audio (hors "best", géré à part). Renvoie (args, extension)."""
    fmt = opts.audio_format
    br = f"{opts.audio_bitrate}k"
    if fmt == "mp3":
        return ["-vn", "-c:a", "libmp3lame", "-b:a", br], "mp3"
    if fmt == "m4a":
        return ["-vn", "-c:a", "aac", "-b:a", br], "m4a"
    if fmt == "opus":
        return ["-vn", "-c:a", "libopus", "-b:a", br], "opus"
    if fmt == "ogg":
        return ["-vn", "-c:a", "libvorbis", "-b:a", br], "ogg"
    return ["-vn", "-c:a", "pcm_s16le"], "wav"
