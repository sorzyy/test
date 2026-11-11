"""Formats des requêtes / réponses de l'API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["debutant", "intermediaire", "avance"]
Status = Literal["new", "review", "known"]


class ScanRequest(BaseModel):
    # Photo de ce que voient les lunettes (ou le téléphone), en base64.
    # Accepte aussi un data URL : « data:image/jpeg;base64,... ».
    image: str
    level: Level = "debutant"
    # Mots (en caractères) que l'élève maîtrise déjà / est en train d'apprendre.
    known: list[str] = Field(default_factory=list, max_length=500)
    learning: list[str] = Field(default_factory=list, max_length=500)
    # Mode défi : le mot que l'élève doit retrouver autour de lui.
    challenge: str | None = Field(default=None, max_length=12)
    # Combien de mots nouveaux au maximum par photo (charge cognitive).
    max_new: int = Field(default=2, ge=0, le=5)


class Sentence(BaseModel):
    zh: str
    pinyin: str
    fr: str


class Word(BaseModel):
    hanzi: str
    pinyin: str
    fr: str
    where: str
    hsk: int
    measure: Sentence  # ex. 一把椅子 — yì bǎ yǐzi — une chaise
    example: Sentence
    tip: str
    status: Status
    pinyin_check: dict


class ChallengeResult(BaseModel):
    target: str
    found: bool
    feedback: str


class SpeechSegment(BaseModel):
    lang: Literal["zh-CN", "fr-FR"]
    text: str


class ScanResult(BaseModel):
    scene: str
    words: list[Word]
    teacher: Sentence
    challenge: ChallengeResult | None = None
    speech: list[SpeechSegment]
    demo: bool = False
    model: str | None = None
