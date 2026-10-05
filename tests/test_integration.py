"""Tests de bout en bout hors ligne : vrai yt-dlp / gallery-dl / ffmpeg sur un serveur HTTP local."""

import functools
import io
import json
import shutil
import subprocess
import threading
import time
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg requis")


def _ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def media_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("media")
    _ff("-f", "lavfi", "-i", "color=c=blue:s=64x48", "-frames:v", "1", str(root / "photo.jpg"))
    _ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "2", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(root / "clip.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25", "-f", "lavfi", "-i", "sine=frequency=880",
        "-t", "2", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(root / "clip2.mp4"))
    (root / "dash").mkdir()
    _ff("-f", "lavfi", "-i", "testsrc=size=640x480:rate=25", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3",
        "-map", "0:v", "-map", "0:v", "-map", "1:a", "-c:v:0", "libx264", "-s:v:0", "640x480",
        "-c:v:1", "libx264", "-s:v:1", "320x240", "-c:a", "aac", "-pix_fmt", "yuv420p",
        "-f", "dash", "-adaptation_sets", "id=0,streams=0,1 id=1,streams=2", str(root / "dash" / "manifest.mpd"))
    (root / "page.html").write_text(
        '<html><head><title>Deux clips</title></head><body>'
        '<video src="clip.mp4" poster="photo.jpg"></video><video src="clip2.mp4"></video></body></html>')
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    old = (settings.allow_private_urls, settings.auto_update, settings.temp_dir, settings.rate_limit_per_minute)
    settings.allow_private_urls, settings.auto_update = True, False
    settings.temp_dir = tmp_path_factory.mktemp("work")
    settings.rate_limit_per_minute = 0
    with TestClient(main.app) as c:
        yield c
    settings.allow_private_urls, settings.auto_update, settings.temp_dir, settings.rate_limit_per_minute = old


def _download(client, url, index=0, **options):
    res = client.post("/api/resolve", json={"url": url}).json()
    assert "error" not in res, res
    job = client.post("/api/jobs", json={"token": res["token"], "index": index, "options": options}).json()
    deadline = time.time() + 120
    while job["status"] not in ("done", "error"):
        assert time.time() < deadline
        time.sleep(0.2)
        job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "done", job
    return job, client.get(job["url"])


def _streams(content: bytes, tmp_path) -> list[tuple[str, str]]:
    path = tmp_path / "probe.bin"
    path.write_bytes(content)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    return [(s["codec_type"], s["codec_name"]) for s in json.loads(out).get("streams", [])]


def test_video_auto(client, media_server, tmp_path):
    job, r = _download(client, f"{media_server}/clip.mp4")
    assert job["filename"] == "clip.mp4"
    assert _streams(r.content, tmp_path) == [("video", "h264"), ("audio", "aac")]
    assert "attachment" in r.headers["content-disposition"]


@pytest.mark.parametrize("options,expected,ext", [
    ({"mode": "audio"}, [("audio", "mp3")], "mp3"),
    ({"mode": "audio", "audio_format": "best"}, [("audio", "aac")], "m4a"),
    ({"mode": "audio", "audio_format": "opus", "audio_bitrate": "96"}, [("audio", "opus")], "opus"),
    ({"mode": "mute"}, [("video", "h264")], "mp4"),
])
def test_modes(client, media_server, tmp_path, options, expected, ext):
    job, r = _download(client, f"{media_server}/clip.mp4", **options)
    assert job["filename"].endswith("." + ext)
    assert _streams(r.content, tmp_path) == expected


def test_dash_merge_and_quality(client, media_server, tmp_path):
    job, r = _download(client, f"{media_server}/dash/manifest.mpd")
    assert _streams(r.content, tmp_path) == [("video", "h264"), ("audio", "aac")]
    big = len(r.content)
    _, small = _download(client, f"{media_server}/dash/manifest.mpd", quality="240")
    assert len(small.content) < big


def test_photo_direct_link(client, media_server, tmp_path):
    res = client.post("/api/resolve", json={"url": f"{media_server}/photo.jpg"}).json()
    assert res["items"][0]["type"] == "photo"
    thumb = client.get(f"/api/thumb/{res['token']}/0")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    job, r = _download(client, f"{media_server}/photo.jpg")
    assert job["filename"] == "photo.jpg" and r.content[:2] == b"\xff\xd8"


def test_multi_item_page_and_zip(client, media_server, tmp_path):
    res = client.post("/api/resolve", json={"url": f"{media_server}/page.html"}).json()
    assert res["title"] == "Deux clips" and len(res["items"]) == 2
    job, r = _download(client, f"{media_server}/page.html", index="all")
    assert job["filename"] == "Deux clips.zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 2 and all(n.endswith(".mp4") for n in names)


def test_cobalt_tunnel_end_to_end(client, media_server, tmp_path):
    data = client.post("/", json={"url": f"{media_server}/clip.mp4", "downloadMode": "audio"}).json()
    assert data["status"] == "tunnel" and data["filename"].endswith(".mp3")
    path = data["url"].split("://", 1)[1].split("/", 1)[1]
    r = client.get("/" + path)
    assert r.status_code == 200
    assert _streams(r.content, tmp_path) == [("audio", "mp3")]


def test_not_found_error(client, media_server):
    res = client.post("/api/resolve", json={"url": f"{media_server}/missing"}).json()
    assert res["error"]["code"] == "content.unavailable"


def test_direct_download_fallbacks(client, media_server, tmp_path):
    from app import resolver
    from app.models import MediaItem, Resolved

    items = [
        # 1re URL morte, la 2e marche
        MediaItem(type="video", source="direct", url=f"{media_server}/dead.mp4",
                  fallback_urls=[f"{media_server}/clip.mp4"], ext="mp4", title="a"),
        # toutes les URL directes mortes : yt-dlp repart de la page
        MediaItem(type="video", source="direct", url=f"{media_server}/dead.mp4", ext="mp4", title="b",
                  page_url=f"{media_server}/clip2.mp4"),
    ]
    token = resolver.store(Resolved(service="tiktok", url="u", title="t", items=items))
    for index in (0, 1):
        job = client.post("/api/jobs", json={"token": token, "index": index, "options": {}}).json()
        while job["status"] not in ("done", "error"):
            time.sleep(0.2)
            job = client.get(f"/api/jobs/{job['id']}").json()
        assert job["status"] == "done", job
        assert _streams(client.get(job["url"]).content, tmp_path) == [("video", "h264"), ("audio", "aac")]
