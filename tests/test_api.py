import pytest
from fastapi.testclient import TestClient

from app import jobs, main, resolver
from app.config import settings
from app.models import MediaItem, Resolved


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "auto_update", False)
    with TestClient(main.app) as c:
        yield c


def _fake_resolve(items, audio=None):
    async def fake(url):
        r = Resolved(service="instagram", url=url, title="Mon post", author="moi", items=items, audio=audio,
                     engines=["test"])
        return resolver.store(r), r
    return fake


def test_status(client):
    data = client.get("/api/status").json()
    assert data["name"] == "saphir" and data["versions"]["yt-dlp"]
    assert any(s["id"] == "tiktok" for s in data["services"])


def test_index_html_and_cobalt_info(client):
    assert "saphir" in client.get("/", headers={"accept": "text/html"}).text
    info = client.get("/", headers={"accept": "application/json"}).json()
    assert "cobalt" in info and "instagram" in info["cobalt"]["services"]


def test_resolve_error_payload(client):
    r = client.post("/api/resolve", json={"url": "pas un lien"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "link.invalid"


def test_resolve_payload(client, monkeypatch):
    items = [MediaItem(type="photo", source="direct", url="https://i/1.jpg", thumbnail="https://i/1.jpg"),
             MediaItem(type="video", source="ytdlp", info={"id": "v"}, duration=5.0)]
    monkeypatch.setattr(main.resolver, "resolve", _fake_resolve(items))
    data = client.post("/api/resolve", json={"url": "https://www.instagram.com/p/x/"}).json()
    assert [i["type"] for i in data["items"]] == ["photo", "video"]
    assert data["items"][0]["hasThumbnail"] and not data["items"][1]["hasThumbnail"]
    assert "info" not in data["items"][1] and "url" not in data["items"][0]  # rien d'interne n'est exposé


def test_cobalt_picker_and_tunnel_urls(client, monkeypatch):
    items = [MediaItem(type="photo", source="direct", url="https://i/1.jpg", thumbnail="https://i/1.jpg"),
             MediaItem(type="gif", source="direct", url="https://v/2.mp4", thumbnail="https://t/2.jpg")]
    audio = MediaItem(type="audio", source="direct", url="https://m.mp3", ext="mp3")
    monkeypatch.setattr(main.resolver, "resolve", _fake_resolve(items, audio))
    data = client.post("/", json={"url": "https://www.tiktok.com/@a/photo/1"},
                       headers={"accept": "application/json"}).json()
    assert data["status"] == "picker"
    assert [p["type"] for p in data["picker"]] == ["photo", "gif"]
    assert "/tunnel?t=" in data["picker"][0]["url"] and data["audio"].endswith(data["audio"].split("&o=")[1])
    assert data["audioFilename"].endswith(".mp3")


def test_cobalt_single_tunnel_and_audio_mode(client, monkeypatch):
    items = [MediaItem(type="photo", source="direct", url="https://i/1.jpg")]
    audio = MediaItem(type="audio", source="direct", url="https://m.mp3", ext="mp3")
    monkeypatch.setattr(main.resolver, "resolve", _fake_resolve(items, audio))
    single = client.post("/", json={"url": "https://x"}).json()
    assert single["status"] == "tunnel" and single["filename"] == "Mon post.jpg"
    audio_only = client.post("/", json={"url": "https://x", "downloadMode": "audio"}).json()
    assert audio_only["status"] == "tunnel" and "i=audio" in audio_only["url"]


def test_cobalt_error_shape(client):
    data = client.post("/", json={"url": "nope"}).json()
    assert data == {"status": "error", "error": {"code": "error.api.link.invalid"}}


def test_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    assert client.post("/api/resolve", json={"url": "x"}).status_code == 401
    r = client.post("/api/resolve", json={"url": "pas un lien"}, headers={"Authorization": "Api-Key secret"})
    assert r.status_code == 400


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
    main._hits.clear()
    codes = [client.post("/api/resolve", json={"url": "pas un lien"}).status_code for _ in range(3)]
    assert codes == [400, 400, 429]
    main._hits.clear()


def test_unknown_job(client):
    assert client.get("/api/jobs/nope").json()["error"]["code"] == "job.notfound"


def test_build_filename():
    r = Resolved(service="twitter", url="u", title="Regarde ça https://t.co/abc  #wow", author="nasa")
    assert jobs.build_filename(r, None, "mp4", None) == "Regarde ça #wow.mp4"
    assert jobs.build_filename(r, None, "jpg", 1) == "Regarde ça #wow (2).jpg"
    r2 = Resolved(service="tiktok", url="u", title="")
    item = MediaItem(type="video", source="direct", id="123")
    assert jobs.build_filename(r2, item, "mp4", None) == "tiktok_123.mp4"
    long = Resolved(service="youtube", url="u", title="a/b:c*d?" + "x" * 200)
    name = jobs.build_filename(long, None, "mp4", None)
    assert "/" not in name and len(name) <= 84


def test_cors_for_external_frontend(client):
    r = client.options("/api/resolve", headers={"Origin": "https://sorzyy.github.io",
                                                "Access-Control-Request-Method": "POST",
                                                "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] in ("*", "https://sorzyy.github.io")
