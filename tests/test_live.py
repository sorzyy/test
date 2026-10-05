"""Tests contre les vraies plateformes (réseau requis).

Lancer avec :  RUN_LIVE=1 pytest -m live -v
Les liens viennent des suites de tests de yt-dlp et gallery-dl (contenus officiels et stables).
"""

import os
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="RUN_LIVE=1 pour activer"),
]

CASES = [
    # (id, url, types attendus (préfixe), mode)
    ("youtube-video", "https://www.youtube.com/watch?v=jNQXAC9IVRw", ["video"], "auto"),
    ("youtube-short", "https://www.youtube.com/shorts/BGQWPY4IigY", ["video"], "auto"),
    ("youtube-audio", "https://youtu.be/jNQXAC9IVRw", ["video"], "audio"),
    ("youtube-1080-av1", "https://www.youtube.com/watch?v=aqz-KE-bpKQ", ["video"], "auto"),
    ("instagram-reel", "https://www.instagram.com/reel/Chunk8-jurw/", ["video"], "auto"),
    ("instagram-video-post", "https://www.instagram.com/p/Bqxp0VSBgJg/", ["video"], "auto"),
    ("instagram-photo", "https://www.instagram.com/p/BqvsDleB3lV/", ["photo"], "auto"),
    ("instagram-carousel", "https://www.instagram.com/p/BoHk1haB5tM/", None, "auto"),
    ("instagram-audio", "https://www.instagram.com/p/Bqxp0VSBgJg/", ["video"], "audio"),
    ("twitter-video", "https://x.com/historyinmemes/status/1790637656616943991", ["video"], "auto"),
    ("twitter-video-audio", "https://x.com/historyinmemes/status/1790637656616943991", ["video"], "audio"),
    ("twitter-photos", "https://twitter.com/perrypumas/status/894001459754180609",
     ["photo", "photo", "photo", "photo"], "auto"),
    ("tiktok-video", "https://www.tiktok.com/@memezar/video/7449708266168274208", ["video"], "auto"),
    ("tiktok-video-mute", "https://www.tiktok.com/@memezar/video/7449708266168274208", ["video"], "mute"),
    ("tiktok-video-via-photo-link", "https://www.tiktok.com/@memezar/photo/7449708266168274208", ["video"], "auto"),
    ("tiktok-slideshow", "https://www.tiktok.com/@chillezy/photo/7240568259186019630", ["photo"], "auto"),
    ("tiktok-slideshow-audio", "https://www.tiktok.com/@chillezy/photo/7240568259186019630", ["photo"], "audio"),
]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    settings.auto_update = False
    settings.rate_limit_per_minute = 0
    settings.temp_dir = tmp_path_factory.mktemp("live")
    with TestClient(main.app) as c:
        yield c


@pytest.mark.parametrize("name,url,expected,mode", CASES, ids=[c[0] for c in CASES])
def test_live(client, name, url, expected, mode):
    started = time.time()
    res = client.post("/api/resolve", json={"url": url}).json()
    if res.get("error", {}).get("code") == "fetch.bot":
        # IP de datacenter bloquée par la plateforme : pas un bug de saphir
        pytest.skip(f"{name}: IP du runner bloquée (anti-bot)")
    assert "error" not in res, f"{name}: {res.get('error')}"
    types = [i["type"] for i in res["items"]]
    print(f"\n[{name}] engines={res['engines']} items={types} audio={bool(res['audio'])} "
          f"title={res['title'][:60]!r} ({time.time() - started:.1f}s)")
    if expected:
        assert types[:len(expected)] == expected
    else:
        assert len(types) >= 2

    index = "audio" if mode == "audio" and res["audio"] and all(t == "photo" for t in types) else 0
    job = client.post("/api/jobs", json={"token": res["token"], "index": index,
                                         "options": {"mode": mode, "quality": "720"}}).json()
    while job["status"] not in ("done", "error"):
        time.sleep(0.5)
        job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "done", f"{name}: {job.get('error')}"
    r = client.get(job["url"])
    assert r.status_code == 200 and len(r.content) > 1000
    print(f"[{name}] -> {job['filename']} ({len(r.content)} octets, {time.time() - started:.1f}s)")
