"""Le « prof » : regarde la photo avec Claude et prépare une mini-leçon."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re

import anthropic

from . import pinyin as py
from .config import Settings
from .schemas import (
    ChallengeResult,
    ScanRequest,
    ScanResult,
    Sentence,
    SpeechSegment,
    Word,
)

log = logging.getLogger("laoshi")


class TutorError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


SYSTEM_PROMPT = """\
Tu es Lǎoshī (老师), un professeur de chinois mandarin bienveillant qui vit dans les \
lunettes connectées d'un élève francophone. L'élève regarde autour de lui ; tu reçois \
une photo de ce qu'il voit et tu en fais une mini-leçon de vocabulaire.

Ce que tu enseignes doit être fiable : l'élève apprend sur cette base.
- Chinois standard de Chine continentale (普通话), caractères simplifiés.
- Pinyin avec accents de ton, syllabes séparées par une espace (« yǐ zi »), ton neutre \
sans accent. Pour le mot seul, pinyin du dictionnaire sans sandhi. Dans les phrases \
(classificateur, exemple, phrase du prof), applique le sandhi de 一 et 不 \
(« yí ge », « yì bǎ », « bú shì »).
- Choisis le mot le plus courant pour l'objet (杯子 plutôt que 玻璃杯, sauf si la \
précision est utile). Pas de mots rares ou littéraires.
- Ne nomme que des objets clairement visibles. Dans le doute, ignore l'objet.
- « tip » : une phrase en français pour retenir le mot. Décomposition du caractère \
(clé et sens) seulement si tu en es sûr (ex. 椅 contient la clé 木, le bois). \
N'invente jamais d'étymologie : si tu n'es pas sûr, donne plutôt une astuce d'usage.
- « measure » : le classificateur le plus courant pour cet objet, sous la forme \
« 一 + classificateur + mot » (一把椅子), avec pinyin et traduction.
- « example » : une phrase courte, naturelle, qui parle de la scène photographiée. Elle \
réutilise surtout des mots que l'élève connaît déjà, plus le mot cible (un seul \
élément nouveau à la fois).
- « where » : position de l'objet sur la photo en quelques mots de français \
(« à gauche, sur la table »).
- « hsk » : niveau HSK (1 à 6) du mot, 7 s'il est hors liste HSK.

Niveau de l'élève :
- debutant : phrases de 4 à 8 caractères, structures 这是…、…在…上、有…, vocabulaire HSK 1-2.
- intermediaire : phrases jusqu'à 15 caractères, vocabulaire HSK 3-4.
- avance : phrases naturelles et idiomatiques, vocabulaire libre.

Choix des objets (« objects », du plus visible au moins visible) :
- Si des mots « en cours d'apprentissage » sont visibles, mets-les en priorité : les \
revoir en contexte est ce qui les ancre.
- Ensuite au plus le nombre demandé de mots nouveaux (ni connus, ni en cours).
- Tu peux ajouter un ou deux mots déjà connus s'ils servent la phrase du prof.
- Maximum 6 objets.

« teacher » : une seule phrase que tu dis à voix haute à l'élève, en chinois, à son \
niveau, à propos de la scène. De préférence une petite question qui le fait réutiliser \
un mot (« 桌子上有什么？»). Avec pinyin et traduction.

« scene » : la scène en une courte phrase de français.

« challenge » : null s'il n'y a pas de défi. Sinon, l'élève devait trouver l'objet \
cible autour de lui : « found » dit si cet objet est bien visible sur la photo, \
« feedback » le félicite (en français, une phrase, avec le mot chinois) ou l'aide à \
chercher (où trouve-t-on souvent cet objet ?).

Confidentialité : ne décris pas et n'identifie pas les personnes, ne recopie pas le \
contenu des écrans ni des documents. Tu peux nommer des objets du quotidien seulement.
"""

_SENTENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "zh": {"type": "string"},
        "pinyin": {"type": "string"},
        "fr": {"type": "string"},
    },
    "required": ["zh", "pinyin", "fr"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "scene": {"type": "string"},
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hanzi": {"type": "string"},
                    "pinyin": {"type": "string"},
                    "fr": {"type": "string"},
                    "where": {"type": "string"},
                    "hsk": {"type": "integer"},
                    "measure": _SENTENCE_SCHEMA,
                    "example": _SENTENCE_SCHEMA,
                    "tip": {"type": "string"},
                },
                "required": ["hanzi", "pinyin", "fr", "where", "hsk", "measure", "example", "tip"],
                "additionalProperties": False,
            },
        },
        "teacher": _SENTENCE_SCHEMA,
        "challenge": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "found": {"type": "boolean"},
                        "feedback": {"type": "string"},
                    },
                    "required": ["found", "feedback"],
                    "additionalProperties": False,
                },
                {"type": "null"},
            ]
        },
    },
    "required": ["scene", "objects", "teacher", "challenge"],
    "additionalProperties": False,
}

_DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp|gif));base64,", re.I)
_MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
    b"RIFF": "image/webp",
    b"GIF8": "image/gif",
}


def decode_image(data: str, max_bytes: int) -> tuple[str, str]:
    """Renvoie (media_type, base64 propre). Lève TutorError si l'image est invalide."""
    data = data.strip()
    match = _DATA_URL.match(data)
    if match:
        data = data[match.end():]
    data = re.sub(r"\s+", "", data)
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TutorError("Image illisible (base64 invalide).", 400) from exc
    if not raw:
        raise TutorError("Image vide.", 400)
    if len(raw) > max_bytes:
        raise TutorError(f"Image trop lourde ({len(raw) // 1024} Ko). Réduis-la avant l'envoi.", 413)
    media_type = next((mt for magic, mt in _MAGIC.items() if raw.startswith(magic)), None)
    if media_type is None:
        raise TutorError("Format d'image non reconnu (JPEG, PNG, WebP ou GIF).", 415)
    return media_type, base64.b64encode(raw).decode("ascii")


_LEVEL_FR = {"debutant": "débutant", "intermediaire": "intermédiaire", "avance": "avancé"}


def build_user_text(req: ScanRequest) -> str:
    known = "、".join(req.known[:300]) or "(aucun)"
    learning = "、".join(req.learning[:300]) or "(aucun)"
    lines = [
        f"Niveau : {req.level}",
        f"Mots nouveaux maximum : {req.max_new}",
        f"Mots déjà connus : {known}",
        f"Mots en cours d'apprentissage : {learning}",
        f"Défi : trouver « {req.challenge} »" if req.challenge else "Défi : aucun",
        "Fais la mini-leçon pour cette photo.",
    ]
    return "\n".join(lines)


def _status(hanzi: str, req: ScanRequest) -> str:
    if hanzi in req.known:
        return "known"
    if hanzi in req.learning:
        return "review"
    return "new"


def build_words(objects: list[dict], req: ScanRequest) -> list[Word]:
    """Statut calculé ici (pas par le modèle), limite de mots nouveaux, vérif du pinyin."""
    words: list[Word] = []
    seen: set[str] = set()
    new_count = 0
    for obj in objects:
        hanzi = obj["hanzi"].strip()
        if not hanzi or hanzi in seen or not py.is_hanzi(hanzi):
            continue
        status = _status(hanzi, req)
        if status == "new":
            if new_count >= req.max_new:
                continue
            new_count += 1
        seen.add(hanzi)
        words.append(
            Word(
                hanzi=hanzi,
                pinyin=obj["pinyin"].strip(),
                fr=obj["fr"].strip(),
                where=obj["where"].strip(),
                hsk=max(1, min(7, int(obj["hsk"]))),
                measure=Sentence(**obj["measure"]),
                example=Sentence(**obj["example"]),
                tip=obj["tip"].strip(),
                status=status,
                pinyin_check=py.check(hanzi, obj["pinyin"]).as_dict(),
            )
        )
    return words[:6]


def build_speech(words: list[Word], teacher: Sentence, challenge: ChallengeResult | None) -> list[SpeechSegment]:
    """Ce que les lunettes disent à voix haute, dans l'ordre.

    Mot nouveau : chinois → français → classificateur → phrase d'exemple (zh puis fr).
    Mot à revoir : chinois seul, puis le sens (rappel actif : l'élève a une seconde
    pour s'en souvenir avant d'entendre la réponse).
    Mot connu : rien (on ne perd pas son temps).
    """
    segs: list[SpeechSegment] = []
    if challenge:
        segs.append(SpeechSegment(lang="fr-FR", text=challenge.feedback))
    for w in words:
        if w.status == "new":
            segs += [
                SpeechSegment(lang="zh-CN", text=w.hanzi),
                SpeechSegment(lang="fr-FR", text=w.fr),
                SpeechSegment(lang="zh-CN", text=w.measure.zh),
                SpeechSegment(lang="zh-CN", text=w.example.zh),
                SpeechSegment(lang="fr-FR", text=w.example.fr),
            ]
        elif w.status == "review":
            segs += [
                SpeechSegment(lang="zh-CN", text=w.hanzi),
                SpeechSegment(lang="fr-FR", text=f"… {w.fr}"),
            ]
    segs.append(SpeechSegment(lang="zh-CN", text=teacher.zh))
    return segs


def assemble(data: dict, req: ScanRequest, *, model: str | None, demo: bool = False) -> ScanResult:
    words = build_words(data.get("objects") or [], req)
    teacher = Sentence(**data["teacher"])
    challenge = None
    if req.challenge:
        raw = data.get("challenge") or {"found": False, "feedback": "Je n'ai pas pu vérifier le défi."}
        challenge = ChallengeResult(target=req.challenge, found=bool(raw["found"]), feedback=raw["feedback"])
    return ScanResult(
        scene=data["scene"],
        words=words,
        teacher=teacher,
        challenge=challenge,
        speech=build_speech(words, teacher, challenge),
        demo=demo,
        model=model,
    )


class Tutor:
    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None):
        self.settings = settings
        self._client = client

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic()
        return self._client

    async def scan(self, req: ScanRequest) -> ScanResult:
        media_type, b64 = decode_image(req.image, self.settings.max_image_bytes)
        if self.settings.demo:
            return assemble(demo_data(req), req, model=None, demo=True)
        data, model = await self._ask_claude(media_type, b64, req)
        return assemble(data, req, model=model)

    async def _ask_claude(self, media_type: str, b64: str, req: ScanRequest) -> tuple[dict, str]:
        try:
            response = await self.client.beta.messages.create(
                model=self.settings.model,
                max_tokens=8000,
                # Si le modèle refuse (filtre de sécurité trop zélé), l'API relance
                # automatiquement la requête sur un modèle de repli.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={
                    "effort": self.settings.effort,
                    "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
                },
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                            {"type": "text", "text": build_user_text(req)},
                        ],
                    }
                ],
            )
        except anthropic.AuthenticationError as exc:
            raise TutorError("Clé API Anthropic invalide côté serveur.", 500) from exc
        except anthropic.RateLimitError as exc:
            raise TutorError("Trop de demandes en même temps, réessaie dans quelques secondes.", 429) from exc
        except anthropic.BadRequestError as exc:
            log.warning("Requête refusée par l'API : %s", exc.message)
            raise TutorError("L'API a refusé la requête (image ?).", 400) from exc
        except anthropic.APIStatusError as exc:
            log.warning("Erreur API %s : %s", exc.status_code, exc.message)
            raise TutorError("Le service Claude est indisponible, réessaie.", 503) from exc
        except anthropic.APIConnectionError as exc:
            raise TutorError("Impossible de joindre le service Claude.", 503) from exc

        if response.stop_reason == "refusal":
            raise TutorError("Je ne peux pas analyser cette image. Vise plutôt des objets.", 422)
        if response.stop_reason == "max_tokens":
            raise TutorError("Réponse trop longue, réessaie.", 502)
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TutorError("Réponse du modèle illisible, réessaie.", 502) from exc
        return data, response.model


def demo_data(req: ScanRequest) -> dict:
    """Leçon fictive (mode démo, sans clé API) : une chaise et un bol."""
    data = {
        "scene": "Une chaise en bois à côté d'une table avec un bol dessus (mode démo).",
        "objects": [
            {
                "hanzi": "椅子",
                "pinyin": "yǐ zi",
                "fr": "chaise",
                "where": "à gauche",
                "hsk": 1,
                "measure": {"zh": "一把椅子", "pinyin": "yì bǎ yǐ zi", "fr": "une chaise"},
                "example": {"zh": "这是一把椅子。", "pinyin": "zhè shì yì bǎ yǐ zi.", "fr": "C'est une chaise."},
                "tip": "椅 contient la clé 木 (le bois) : une chaise, c'est souvent en bois.",
            },
            {
                "hanzi": "碗",
                "pinyin": "wǎn",
                "fr": "bol",
                "where": "au centre, sur la table",
                "hsk": 3,
                "measure": {"zh": "一个碗", "pinyin": "yí ge wǎn", "fr": "un bol"},
                "example": {"zh": "碗在桌子上。", "pinyin": "wǎn zài zhuō zi shang.", "fr": "Le bol est sur la table."},
                "tip": "碗 contient la clé 石 (la pierre) : les bols étaient en pierre ou en céramique.",
            },
            {
                "hanzi": "桌子",
                "pinyin": "zhuō zi",
                "fr": "table",
                "where": "au centre",
                "hsk": 1,
                "measure": {"zh": "一张桌子", "pinyin": "yì zhāng zhuō zi", "fr": "une table"},
                "example": {"zh": "桌子上有一个碗。", "pinyin": "zhuō zi shang yǒu yí ge wǎn.", "fr": "Il y a un bol sur la table."},
                "tip": "张 sert à compter les choses plates : tables, feuilles, lits.",
            },
        ],
        "teacher": {"zh": "桌子上有什么？", "pinyin": "zhuō zi shang yǒu shén me?", "fr": "Qu'y a-t-il sur la table ?"},
        "challenge": None,
    }
    if req.challenge:
        found = req.challenge in {"椅子", "碗", "桌子"}
        data["challenge"] = {
            "found": found,
            "feedback": f"Bravo, tu as trouvé : {req.challenge} !" if found else f"Je ne vois pas de {req.challenge} ici, cherche encore.",
        }
    return data
