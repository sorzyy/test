"""Le « prof » : prépare les mini-leçons (photo) et répond aux questions (voix)."""

from __future__ import annotations

import base64
import binascii
import re

from . import pinyin as py
from .config import Settings
from .providers import Image, Provider, TutorError, make_provider
from .schemas import (
    AskRequest,
    AskResult,
    ChallengeResult,
    ScanRequest,
    ScanResult,
    Sentence,
    SpeechSegment,
    Word,
)

__all__ = ["Tutor", "TutorError"]

# ---------------------------------------------------------------- consignes

TEACHING_RULES = """\
Tu es Lǎoshī (老师), un professeur de chinois mandarin bienveillant qui vit dans les \
lunettes connectées d'un élève francophone. Tu lui parles à l'oreille.

Ce que tu enseignes doit être fiable : l'élève apprend sur cette base.
- Chinois standard de Chine continentale (普通话), caractères simplifiés.
- Pinyin avec accents de ton, syllabes séparées par une espace (« yǐ zi »), ton neutre \
sans accent. Pour le mot seul, pinyin du dictionnaire sans sandhi. Dans les phrases \
(classificateur, exemple), applique le sandhi de 一 et 不 (« yí ge », « yì bǎ », « bú shì »).
- Choisis le mot le plus courant (杯子 plutôt que 玻璃杯, sauf si la précision est \
utile). Pas de mots rares ou littéraires.
- « tip » : une phrase en français pour retenir le mot. Décomposition du caractère \
(clé et sens) seulement si tu en es sûr (ex. 椅 contient la clé 木, le bois). \
N'invente jamais d'étymologie : si tu n'es pas sûr, donne plutôt une astuce d'usage.
- « measure » : le classificateur le plus courant, sous la forme « 一 + classificateur + \
mot » (一把椅子), avec pinyin et traduction.
- « example » : une phrase courte et naturelle. Elle réutilise surtout des mots que \
l'élève connaît déjà, plus le mot cible (un seul élément nouveau à la fois).
- « hsk » : niveau HSK (1 à 6) du mot, 7 s'il est hors liste HSK.

Niveau de l'élève :
- debutant : phrases de 4 à 8 caractères, structures 这是…、…在…上、有…, vocabulaire HSK 1-2.
- intermediaire : phrases jusqu'à 15 caractères, vocabulaire HSK 3-4.
- avance : phrases naturelles et idiomatiques, vocabulaire libre.

Confidentialité : ne décris pas et n'identifie pas les personnes, ne recopie pas le \
contenu des écrans ni des documents.
"""

SCAN_TASK = """\
TÂCHE : MINI-LEÇON SUR CE QUE VOIT L'ÉLÈVE.
Tu reçois une photo de ce qu'il regarde.
- Ne nomme que des objets clairement visibles. Dans le doute, ignore l'objet.
- « where » : position de l'objet sur la photo en quelques mots de français.
- « example » parle de la scène photographiée.
- « objects » (du plus visible au moins visible) : d'abord les mots « en cours \
d'apprentissage » visibles (les revoir en contexte les ancre), puis au plus le nombre \
demandé de mots nouveaux, éventuellement un ou deux mots connus. Maximum 6.
- « teacher » : une seule phrase que tu dis à voix haute, en chinois, à son niveau, à \
propos de la scène. De préférence une petite question qui le fait réutiliser un mot \
(« 桌子上有什么？»).
- « scene » : la scène en une courte phrase de français.
- « challenge » : null s'il n'y a pas de défi. Sinon l'élève devait trouver l'objet \
cible : « found » dit s'il est visible sur la photo, « feedback » le félicite (une \
phrase en français, avec le mot chinois) ou l'aide à chercher.
"""

ASK_TASK = """\
TÂCHE : RÉPONDRE À UNE QUESTION ORALE.
L'élève te pose une question à voix haute (transcrite automatiquement, donc parfois mal \
orthographiée : « que veut dire siège en chinois », « comment on dit fourchette », \
« c'est quoi yizi », « c'est quoi ça en chinois »). Une photo de ce qu'il regarde peut \
être jointe : utilise-la si la question parle de « ça », ou pour choisir le bon sens d'un \
mot ambigu (le siège d'une voiture n'est pas un siège social).
- « words » : le ou les mots chinois qui répondent (1 en général, 2 au maximum si le mot \
français a deux sens courants). Mêmes règles que plus haut ; « where » vide.
- « intro » : la réponse parlée, en français, une phrase courte qui sera lue par une \
voix française juste AVANT le mot chinois. Elle ne contient NI caractères chinois NI \
pinyin (la voix française les prononcerait mal). Ex. : « Siège, en chinois, se dit : ».
- « followup » : une phrase en français dite après le mot, pour une nuance utile \
(« Le deuxième mot désigne plutôt une chaise. »). Ni caractères chinois ni pinyin non \
plus. Vide s'il n'y a rien d'utile à ajouter.
- Si la question n'a rien à voir avec le chinois : « words » vide, « intro » rappelle \
gentiment que tu es son prof de chinois, « followup » vide.
"""

# ---------------------------------------------------------------- schémas JSON

_SENTENCE = {
    "type": "object",
    "properties": {"zh": {"type": "string"}, "pinyin": {"type": "string"}, "fr": {"type": "string"}},
    "required": ["zh", "pinyin", "fr"],
    "additionalProperties": False,
}

_WORD = {
    "type": "object",
    "properties": {
        "hanzi": {"type": "string"},
        "pinyin": {"type": "string"},
        "fr": {"type": "string"},
        "where": {"type": "string"},
        "hsk": {"type": "integer"},
        "measure": _SENTENCE,
        "example": _SENTENCE,
        "tip": {"type": "string"},
    },
    "required": ["hanzi", "pinyin", "fr", "where", "hsk", "measure", "example", "tip"],
    "additionalProperties": False,
}

SCAN_SCHEMA = {
    "type": "object",
    "properties": {
        "scene": {"type": "string"},
        "objects": {"type": "array", "items": _WORD},
        "teacher": _SENTENCE,
        "challenge": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {"found": {"type": "boolean"}, "feedback": {"type": "string"}},
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

ASK_SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {"type": "string"},
        "words": {"type": "array", "items": _WORD},
        "followup": {"type": "string"},
    },
    "required": ["intro", "words", "followup"],
    "additionalProperties": False,
}

# Compatibilité : ancien nom.
OUTPUT_SCHEMA = SCAN_SCHEMA

# ---------------------------------------------------------------- images

_DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp|gif));base64,", re.I)
_MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
    b"RIFF": "image/webp",
    b"GIF8": "image/gif",
}


def decode_image(data: str, max_bytes: int) -> Image:
    """Décode une image base64 (ou data URL). Lève TutorError si elle est invalide."""
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
    return Image(media_type=media_type, data=raw, b64=base64.b64encode(raw).decode("ascii"))


# ---------------------------------------------------------------- messages

def _learner_lines(level: str, known: list[str], learning: list[str]) -> list[str]:
    return [
        f"Niveau : {level}",
        f"Mots déjà connus : {'、'.join(known[:300]) or '(aucun)'}",
        f"Mots en cours d'apprentissage : {'、'.join(learning[:300]) or '(aucun)'}",
    ]


def build_user_text(req: ScanRequest) -> str:
    lines = _learner_lines(req.level, req.known, req.learning) + [
        f"Mots nouveaux maximum : {req.max_new}",
        f"Défi : trouver « {req.challenge} »" if req.challenge else "Défi : aucun",
        "Fais la mini-leçon pour cette photo.",
    ]
    return "\n".join(lines)


def build_ask_text(req: AskRequest, has_image: bool) -> str:
    lines = _learner_lines(req.level, req.known, req.learning) + [
        "Photo jointe : oui" if has_image else "Photo jointe : non",
        f"Question de l'élève : « {req.question.strip()} »",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- mise en forme

def _status(hanzi: str, known: list[str], learning: list[str]) -> str:
    if hanzi in known:
        return "known"
    if hanzi in learning:
        return "review"
    return "new"


def build_words(
    objects: list[dict],
    known: list[str],
    learning: list[str],
    max_new: int | None = None,
    limit: int = 6,
) -> list[Word]:
    """Statut calculé ici (pas par le modèle), limite de mots nouveaux, vérif du pinyin."""
    words: list[Word] = []
    seen: set[str] = set()
    new_count = 0
    for obj in objects:
        hanzi = str(obj.get("hanzi", "")).strip()
        if not hanzi or hanzi in seen or not py.is_hanzi(hanzi):
            continue
        status = _status(hanzi, known, learning)
        if status == "new" and max_new is not None:
            if new_count >= max_new:
                continue
            new_count += 1
        seen.add(hanzi)
        try:
            hsk = max(1, min(7, int(obj.get("hsk", 7))))
        except (TypeError, ValueError):
            hsk = 7
        words.append(
            Word(
                hanzi=hanzi,
                pinyin=obj["pinyin"].strip(),
                fr=obj["fr"].strip(),
                where=str(obj.get("where", "")).strip(),
                hsk=hsk,
                measure=Sentence(**obj["measure"]),
                example=Sentence(**obj["example"]),
                tip=obj["tip"].strip(),
                status=status,
                pinyin_check=py.check(hanzi, obj["pinyin"]).as_dict(),
            )
        )
        if len(words) >= limit:
            break
    return words


def build_speech(words: list[Word], teacher: Sentence, challenge: ChallengeResult | None) -> list[SpeechSegment]:
    """Ce que les lunettes disent après une photo, dans l'ordre.

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


def build_ask_speech(intro: str, words: list[Word], followup: str) -> list[SpeechSegment]:
    """Réponse orale : « Siège, en chinois, se dit : » 座位 … 座位 … exemple … traduction."""
    if py.contains_hanzi(intro):  # la voix française ne sait pas lire les caractères
        intro = "Voici la réponse :" if words else ""
    segs = [SpeechSegment(lang="fr-FR", text=intro)] if intro.strip() else []
    for i, w in enumerate(words):
        if i > 0:
            segs.append(SpeechSegment(lang="fr-FR", text=f"Et aussi, pour « {w.fr} » :"))
        segs += [
            SpeechSegment(lang="zh-CN", text=w.hanzi),
            SpeechSegment(lang="zh-CN", text=w.hanzi),  # deux fois : le temps de répéter
            SpeechSegment(lang="zh-CN", text=w.example.zh),
            SpeechSegment(lang="fr-FR", text=w.example.fr),
        ]
    if followup.strip() and not py.contains_hanzi(followup):
        segs.append(SpeechSegment(lang="fr-FR", text=followup))
    return segs


def assemble(data: dict, req: ScanRequest, *, model: str | None, demo: bool = False) -> ScanResult:
    words = build_words(data.get("objects") or [], req.known, req.learning, max_new=req.max_new)
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


def assemble_ask(data: dict, req: AskRequest, *, model: str | None, demo: bool = False) -> AskResult:
    words = build_words(data.get("words") or [], req.known, req.learning, limit=2)
    intro = str(data.get("intro", "")).strip()
    followup = str(data.get("followup", "")).strip()
    if not words and not intro:
        intro = "Je n'ai pas compris la question, tu peux répéter ?"
    return AskResult(
        question=req.question.strip(),
        intro=intro,
        words=words,
        followup=followup,
        speech=build_ask_speech(intro, words, followup),
        demo=demo,
        model=model,
    )


# ---------------------------------------------------------------- le prof

class Tutor:
    def __init__(self, settings: Settings, provider: Provider | None = None):
        self.settings = settings
        self.provider = provider if provider is not None else make_provider(settings)

    async def scan(self, req: ScanRequest) -> ScanResult:
        image = decode_image(req.image, self.settings.max_image_bytes)
        if self.provider is None:
            return assemble(demo_scan(req), req, model=None, demo=True)
        data, model = await self.provider.generate(TEACHING_RULES + "\n" + SCAN_TASK, build_user_text(req), SCAN_SCHEMA, image)
        return assemble(data, req, model=model)

    async def ask(self, req: AskRequest) -> AskResult:
        image = decode_image(req.image, self.settings.max_image_bytes) if req.image else None
        if self.provider is None:
            return assemble_ask(demo_ask(req), req, model=None, demo=True)
        data, model = await self.provider.generate(
            TEACHING_RULES + "\n" + ASK_TASK, build_ask_text(req, image is not None), ASK_SCHEMA, image
        )
        return assemble_ask(data, req, model=model)


# ---------------------------------------------------------------- mode démo

_DEMO_WORDS = {
    "椅子": {
        "hanzi": "椅子",
        "pinyin": "yǐ zi",
        "fr": "chaise",
        "where": "à gauche",
        "hsk": 1,
        "measure": {"zh": "一把椅子", "pinyin": "yì bǎ yǐ zi", "fr": "une chaise"},
        "example": {"zh": "这是一把椅子。", "pinyin": "zhè shì yì bǎ yǐ zi.", "fr": "C'est une chaise."},
        "tip": "椅 contient la clé 木 (le bois) : une chaise, c'est souvent en bois.",
    },
    "碗": {
        "hanzi": "碗",
        "pinyin": "wǎn",
        "fr": "bol",
        "where": "au centre, sur la table",
        "hsk": 3,
        "measure": {"zh": "一个碗", "pinyin": "yí ge wǎn", "fr": "un bol"},
        "example": {"zh": "碗在桌子上。", "pinyin": "wǎn zài zhuō zi shang.", "fr": "Le bol est sur la table."},
        "tip": "碗 contient la clé 石 (la pierre) : les bols étaient en pierre ou en céramique.",
    },
    "桌子": {
        "hanzi": "桌子",
        "pinyin": "zhuō zi",
        "fr": "table",
        "where": "au centre",
        "hsk": 1,
        "measure": {"zh": "一张桌子", "pinyin": "yì zhāng zhuō zi", "fr": "une table"},
        "example": {"zh": "桌子上有一个碗。", "pinyin": "zhuō zi shang yǒu yí ge wǎn.", "fr": "Il y a un bol sur la table."},
        "tip": "张 sert à compter les choses plates : tables, feuilles, lits.",
    },
    "座位": {
        "hanzi": "座位",
        "pinyin": "zuò wèi",
        "fr": "siège, place assise",
        "where": "",
        "hsk": 4,
        "measure": {"zh": "一个座位", "pinyin": "yí ge zuò wèi", "fr": "une place assise"},
        "example": {"zh": "这个座位有人吗？", "pinyin": "zhè ge zuò wèi yǒu rén ma?", "fr": "Cette place est-elle prise ?"},
        "tip": "座 contient 坐 (s'asseoir) sous un toit : l'endroit où l'on s'assoit.",
    },
}


def demo_scan(req: ScanRequest) -> dict:
    """Leçon fictive (mode démo, sans clé API) : une chaise, un bol, une table."""
    data = {
        "scene": "Une chaise en bois à côté d'une table avec un bol dessus (mode démo).",
        "objects": [dict(_DEMO_WORDS[k]) for k in ("椅子", "碗", "桌子")],
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


# Compatibilité : ancien nom.
demo_data = demo_scan


def demo_ask(req: AskRequest) -> dict:
    q = req.question.lower()
    if "siège" in q or "siege" in q:
        return {
            "intro": "Siège, en chinois, se dit :",
            "words": [dict(_DEMO_WORDS["座位"]), dict(_DEMO_WORDS["椅子"])],
            "followup": "Le premier, c'est une place assise ; le second, une chaise. (Mode démo.)",
        }
    return {
        "intro": "Mode démo : je réponds toujours avec le mot chaise.",
        "words": [dict(_DEMO_WORDS["椅子"])],
        "followup": "",
    }
