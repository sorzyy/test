import asyncio

import pytest

from app import resolver
from app.errors import AppError, classify
from app.extractors import ExtractResult
from app.formats import Options, ytdlp_format_args
from app.models import MediaItem


def run(coro):
    return asyncio.run(coro)


def photo(n):
    return MediaItem(type="photo", source="direct", url=f"https://img/{n}.jpg", thumbnail=f"https://img/{n}.jpg")


def native_video(n):
    return MediaItem(type="video", source="direct", url=f"https://vid/{n}.mp4", thumbnail=f"https://t/{n}.jpg")


def yt_video(n):
    return MediaItem(type="video", source="ytdlp", info={"id": str(n)}, page_url="https://x")


@pytest.fixture
def no_network(monkeypatch):
    async def ok(url):
        return None
    monkeypatch.setattr(resolver, "ensure_public_host", ok)


def test_merge_ordered_replaces_videos_keeps_photo_order():
    out = resolver.merge_ordered([photo(1), native_video(2), photo(3)], [yt_video("a")])
    assert [(i.type, i.source) for i in out] == [("photo", "direct"), ("video", "ytdlp"), ("photo", "direct")]
    assert out[1].thumbnail == "https://t/2.jpg"


def test_merge_ordered_keeps_native_when_ytdlp_missing():
    out = resolver.merge_ordered([native_video(1)], [])
    assert out[0].source == "direct"


def test_twitter_mixed_tweet(monkeypatch, no_network):
    async def fake_ytdlp(match):
        return ExtractResult("yt-dlp", items=[yt_video("v")], title="t")

    async def fake_native(match):
        return ExtractResult("syndication", items=[photo(1), native_video(2)], title="tweet", author="nasa")

    monkeypatch.setattr(resolver.ytdlp, "extract", fake_ytdlp)
    monkeypatch.setattr(resolver.twitter, "extract", fake_native)
    token, res = run(resolver.resolve("https://x.com/nasa/status/123"))
    assert [i.type for i in res.items] == ["photo", "video"]
    assert res.items[1].source == "ytdlp"
    assert res.author == "nasa" and resolver.get(token) is res


def test_twitter_photo_only_when_ytdlp_fails(monkeypatch, no_network):
    async def fake_ytdlp(match):
        return ExtractResult("yt-dlp", error="content.empty")

    async def fake_native(match):
        return ExtractResult("syndication", items=[photo(1), photo(2)])

    monkeypatch.setattr(resolver.ytdlp, "extract", fake_ytdlp)
    monkeypatch.setattr(resolver.twitter, "extract", fake_native)
    _, res = run(resolver.resolve("https://twitter.com/a/status/1"))
    assert [i.type for i in res.items] == ["photo", "photo"]


def test_tiktok_slideshow_skips_ytdlp(monkeypatch, no_network):
    called = []

    async def fake_ytdlp(match):
        called.append(match.url)
        return ExtractResult("yt-dlp", error="link.unsupported")

    async def fake_native(match):
        return ExtractResult("tiktok-native", items=[photo(1), photo(2)],
                             audio=MediaItem(type="audio", source="direct", url="https://m.mp3"))

    monkeypatch.setattr(resolver.ytdlp, "extract", fake_ytdlp)
    monkeypatch.setattr(resolver.tiktok, "extract", fake_native)
    _, res = run(resolver.resolve("https://www.tiktok.com/@a/photo/7240568259186019630"))
    assert not called
    assert len(res.items) == 2 and res.audio is not None


def test_tiktok_video_prefers_ytdlp_and_keeps_music(monkeypatch, no_network):
    async def fake_ytdlp(match):
        return ExtractResult("yt-dlp", items=[yt_video("v")])

    async def fake_native(match):
        return ExtractResult("tiktok-native", items=[native_video(1)],
                             audio=MediaItem(type="audio", source="direct", url="https://m.mp3"))

    monkeypatch.setattr(resolver.ytdlp, "extract", fake_ytdlp)
    monkeypatch.setattr(resolver.tiktok, "extract", fake_native)
    _, res = run(resolver.resolve("https://www.tiktok.com/@a/video/1"))
    assert res.items[0].source == "ytdlp" and res.audio is not None


def test_instagram_fallback_chain(monkeypatch, no_network):
    calls = []

    async def fake_ytdlp(match):
        calls.append("yt-dlp")
        return ExtractResult("yt-dlp", error="content.login", detail="empty media response")

    async def fake_native(match):
        calls.append("native")
        return ExtractResult("instagram-native", error="fetch.fail")

    async def fake_gdl(url, options=None):
        calls.append("gallery-dl")
        return ExtractResult("gallery-dl", items=[photo(1)])

    monkeypatch.setattr(resolver.ytdlp, "extract", fake_ytdlp)
    monkeypatch.setattr(resolver.instagram, "extract", fake_native)
    monkeypatch.setattr(resolver.gallerydl, "extract", fake_gdl)
    _, res = run(resolver.resolve("https://www.instagram.com/p/BoHk1haB5tM/"))
    assert calls == ["yt-dlp", "native", "gallery-dl"]
    assert res.engines == ["gallery-dl"]


def test_all_engines_fail_gives_most_specific_error(monkeypatch, no_network):
    async def fail(code):
        return ExtractResult("x", error=code)

    monkeypatch.setattr(resolver.ytdlp, "extract", lambda m: fail("fetch.fail"))
    monkeypatch.setattr(resolver.instagram, "extract", lambda m: fail("content.login"))
    monkeypatch.setattr(resolver.gallerydl, "extract", lambda u, options=None: fail("content.private"))
    with pytest.raises(AppError) as exc:
        run(resolver.resolve("https://www.instagram.com/p/BoHk1haB5tM/"))
    assert exc.value.code == "content.private"


def test_private_hosts_are_refused():
    with pytest.raises(AppError) as exc:
        run(resolver.resolve("http://127.0.0.1:8080/x"))
    assert exc.value.code == "link.private"
    with pytest.raises(AppError):
        run(resolver.resolve("http://169.254.169.254/latest/meta-data"))


def test_expired_token():
    with pytest.raises(AppError) as exc:
        resolver.get("nope")
    assert exc.value.code == "token.expired"


@pytest.mark.parametrize("stderr,code", [
    ("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies-from-browser", "fetch.bot"),
    ("ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate", "content.age"),
    ("ERROR: [Instagram] abc: Instagram sent an empty media response. Check if this post is accessible", "content.login"),
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "content.private"),
    ("ERROR: [youtube] abc: Video unavailable", "content.unavailable"),
    ("ERROR: Unsupported URL: https://example.com/", "link.unsupported"),
    ("ERROR: [TikTok] 1: HTTP Error 429: Too Many Requests", "fetch.rate"),
    ("ERROR: [twitter] 1: No video could be found in this tweet", "content.empty"),
    ("something weird", "fetch.fail"),
])
def test_classify(stderr, code):
    assert classify(stderr) == code


def test_format_args():
    assert ytdlp_format_args(Options()) == ["-f", "bv*+ba/b", "-S", "vcodec:h264,res:1080,acodec:aac",
                                            "--merge-output-format", "mp4"]
    assert ytdlp_format_args(Options(codec="vp9", quality="max"))[3] == "vcodec:vp9,res,acodec:opus"
    assert ytdlp_format_args(Options(codec="best", quality="2160p"))[3] == "res:2160,acodec:aac"
    assert ytdlp_format_args(Options(mode="mute"))[1] == "bv/bv*/b"
    assert ytdlp_format_args(Options(mode="audio", audio_format="ogg")) == ["-f", "ba/b"]
    assert Options(quality="9999", audio_format="flac", audio_bitrate="1").model_dump()["quality"] == "1080"
