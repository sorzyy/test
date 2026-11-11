import base64
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app import pinyin as py
from app.config import Settings, get_settings
from app.schemas import ScanRequest
from app.tutor import Tutor, TutorError, assemble, decode_image, demo_data

# Plus petit JPEG valide possible (1x1 px).
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQAB"
    "AQAAAAAAAAAAAAAAAAAAAAP/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AKAA/9k="
)
JPEG_B64 = base64.b64encode(JPEG).decode()


# ---------- pinyin ----------

@pytest.mark.parametrize(
    "hanzi,pinyin",
    [
        ("椅子", "yǐ zi"),
        ("杯子", "bēi zi"),
        ("东西", "dōng xi"),  # le dictionnaire dit dōng xī : ton neutre toléré
        ("衣服", "yī fu"),
        ("绿", "lǜ"),
        ("电脑", "diàn-nǎo"),
    ],
)
def test_pinyin_ok(hanzi, pinyin):
    assert py.check(hanzi, pinyin).ok


@pytest.mark.parametrize(
    "hanzi,pinyin,reason",
    [
        ("椅子", "yí zi", "dictionnaire"),  # mauvais ton
        ("椅子", "yǐzi", "syllabes"),  # syllabes collées : on ne peut pas vérifier
        ("碗", "wǎng", "dictionnaire"),  # mauvaise syllabe
        ("chair", "chair", "caractères"),
    ],
)
def test_pinyin_ko(hanzi, pinyin, reason):
    res = py.check(hanzi, pinyin)
    assert not res.ok
    assert reason in res.reason


def test_syllable_to_numbered():
    assert py.syllable_to_numbered("yǐ") == "yi3"
    assert py.syllable_to_numbered("zi") == "zi5"
    assert py.syllable_to_numbered("Lǜ") == "lv4"
    assert py.syllable_to_numbered("shì.") == "shi4"


# ---------- images ----------

def test_decode_image_data_url():
    mt, b64 = decode_image("data:image/jpeg;base64," + JPEG_B64, 10**6)
    assert mt == "image/jpeg" and base64.b64decode(b64) == JPEG


def test_decode_image_errors():
    with pytest.raises(TutorError) as e:
        decode_image("pas du base64 !!", 10**6)
    assert e.value.status == 400
    with pytest.raises(TutorError) as e:
        decode_image(base64.b64encode(b"hello world").decode(), 10**6)
    assert e.value.status == 415
    with pytest.raises(TutorError) as e:
        decode_image(JPEG_B64, 10)
    assert e.value.status == 413


# ---------- logique de la leçon ----------

def test_status_and_new_word_limit():
    data = demo_data(ScanRequest(image="x"))
    # 椅子 connu, 碗 et 桌子 nouveaux, mais un seul mot nouveau autorisé.
    req = ScanRequest(image="x", known=["椅子"], max_new=1)
    res = assemble(data, req, model="m")
    assert [(w.hanzi, w.status) for w in res.words] == [("椅子", "known"), ("碗", "new")]
    # La voix ne répète pas les mots connus, mais présente le nouveau en entier.
    texts = [s.text for s in res.speech]
    assert "椅子" not in texts
    assert texts[:5] == ["碗", "bol", "一个碗", "碗在桌子上。", "Le bol est sur la table."]
    assert texts[-1] == res.teacher.zh


def test_review_word_speech_is_active_recall():
    data = demo_data(ScanRequest(image="x"))
    res = assemble(data, ScanRequest(image="x", learning=["椅子"], max_new=0), model="m")
    assert [w.status for w in res.words] == ["review"]
    assert [s.lang for s in res.speech] == ["zh-CN", "fr-FR", "zh-CN"]


def test_model_output_is_sanitized():
    data = demo_data(ScanRequest(image="x"))
    data["objects"].insert(0, dict(data["objects"][0], hanzi="chair"))  # pas du chinois
    data["objects"].append(dict(data["objects"][0]))  # doublon
    data["objects"][1]["hsk"] = 42
    res = assemble(data, ScanRequest(image="x", max_new=5), model="m")
    assert [w.hanzi for w in res.words] == ["椅子", "碗", "桌子"]
    assert res.words[0].hsk == 7


def test_challenge():
    req = ScanRequest(image="x", challenge="碗")
    res = assemble(demo_data(req), req, model=None, demo=True)
    assert res.challenge.found and res.challenge.target == "碗"
    assert res.speech[0].lang == "fr-FR"


# ---------- appel à Claude (simulé) ----------

class FakeMessages:
    def __init__(self, payload, stop_reason="end_turn"):
        self.payload = payload
        self.stop_reason = stop_reason
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            model=kwargs["model"],
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(self.payload))],
        )


def fake_client(messages):
    return SimpleNamespace(beta=SimpleNamespace(messages=messages))


def run(coro):
    import asyncio

    return asyncio.run(coro)


def test_tutor_request_shape():
    msgs = FakeMessages(demo_data(ScanRequest(image="x")))
    tutor = Tutor(Settings(demo=False, model="claude-opus-5-5", effort="low"), client=fake_client(msgs))
    res = run(tutor.scan(ScanRequest(image=JPEG_B64, known=["椅子"], learning=["碗"])))
    assert res.model == "claude-opus-5-5" and not res.demo
    kw = msgs.kwargs
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["effort"] == "low"
    assert kw["fallbacks"] == "default"
    image, text = kw["messages"][0]["content"]
    assert image["source"]["media_type"] == "image/jpeg"
    assert "connus : 椅子" in text["text"] and "apprentissage : 碗" in text["text"]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_tutor_refusal():
    tutor = Tutor(Settings(demo=False), client=fake_client(FakeMessages({}, stop_reason="refusal")))
    with pytest.raises(TutorError) as e:
        run(tutor.scan(ScanRequest(image=JPEG_B64)))
    assert e.value.status == 422


# ---------- API HTTP ----------

@pytest.fixture
def client():
    main._tutor = None
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
    main._tutor = None


def test_health_and_index(client):
    main.app.dependency_overrides[get_settings] = lambda: Settings(demo=True)
    assert client.get("/api/health").json()["demo"] is True
    r = client.get("/")
    assert r.status_code == 200 and "Lǎoshī" in r.text
    assert client.get("/app.js").status_code == 200


def test_scan_demo(client):
    main.app.dependency_overrides[get_settings] = lambda: Settings(demo=True)
    r = client.post("/api/scan", json={"image": JPEG_B64})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["demo"] is True
    assert body["words"][0]["hanzi"] == "椅子"
    assert body["words"][0]["pinyin_check"]["ok"] is True


def test_scan_token(client):
    main.app.dependency_overrides[get_settings] = lambda: Settings(demo=True, access_token="secret")
    assert client.post("/api/scan", json={"image": JPEG_B64}).status_code == 401
    r = client.post("/api/scan", json={"image": JPEG_B64}, headers={"X-Laoshi-Token": "secret"})
    assert r.status_code == 200


def test_scan_bad_image(client):
    main.app.dependency_overrides[get_settings] = lambda: Settings(demo=True)
    assert client.post("/api/scan", json={"image": "????"}).status_code == 400
