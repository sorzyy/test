"""Vérification du pinyin : la « base sûre ».

Claude propose le pinyin de chaque mot. On le recoupe avec un dictionnaire local
(pypinyin, construit à partir de CC-CEDICT) avant de le montrer à l'élève :

- même nombre de syllabes que de caractères ;
- mêmes syllabes ;
- mêmes tons, sauf quand l'un des deux côtés met un ton neutre (le dictionnaire se
  trompe souvent sur les tons neutres : 东西 « dōngxi », 衣服 « yīfu »...).

Si ça ne colle pas, on garde la proposition de Claude mais on affiche la version du
dictionnaire à côté, avec un avertissement.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from pypinyin import Style, lazy_pinyin

_TONE_MARKS = {
    "̄": 1,  # ā  macron
    "́": 2,  # á  accent aigu
    "̌": 3,  # ǎ  caron
    "̀": 4,  # à  accent grave
}

_HANZI = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def is_hanzi(text: str) -> bool:
    """Vrai si le texte ne contient que des caractères chinois (au moins un)."""
    text = text.strip()
    return bool(text) and all(_HANZI.match(ch) for ch in text)


def contains_hanzi(text: str) -> bool:
    return bool(_HANZI.search(text))


def syllable_to_numbered(syllable: str) -> str:
    """« yǐ » -> « yi3 », « zi » -> « zi5 », « lǜ » -> « lv4 »."""
    tone = 5
    out = []
    for ch in unicodedata.normalize("NFD", syllable.lower()):
        if ch in _TONE_MARKS:
            tone = _TONE_MARKS[ch]
        elif ch == "̈":  # tréma de ü
            out.append(":")
        else:
            out.append(ch)
    base = "".join(out).replace("u:", "v")
    base = re.sub(r"[^a-zv]", "", base)
    if base and base[-1].isdigit():
        return base
    return f"{base}{tone}" if base else ""


def split_syllables(pinyin: str) -> list[str]:
    """Découpe « yǐ zi » / « yǐ-zi » en syllabes numérotées."""
    parts = re.split(r"[\s\-'’·]+", pinyin.strip())
    return [s for s in (syllable_to_numbered(p) for p in parts) if s]


def dictionary_pinyin(hanzi: str) -> list[str]:
    """Pinyin du dictionnaire, en syllabes numérotées (ton neutre = 5)."""
    return lazy_pinyin(hanzi, style=Style.TONE3, neutral_tone_with_five=True)


def dictionary_pinyin_marks(hanzi: str) -> str:
    return " ".join(lazy_pinyin(hanzi, style=Style.TONE))


@dataclass
class PinyinCheck:
    ok: bool
    dictionary: str
    reason: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "dictionary": self.dictionary, "reason": self.reason}


def _same_syllable(a: str, b: str) -> bool:
    base_a, tone_a = a[:-1], a[-1]
    base_b, tone_b = b[:-1], b[-1]
    if base_a != base_b:
        return False
    return tone_a == tone_b or "5" in (tone_a, tone_b)


def check(hanzi: str, pinyin: str) -> PinyinCheck:
    dico_marks = dictionary_pinyin_marks(hanzi)
    if not is_hanzi(hanzi):
        return PinyinCheck(False, dico_marks, "le mot contient autre chose que des caractères chinois")
    proposed = split_syllables(pinyin)
    expected = dictionary_pinyin(hanzi)
    if len(proposed) != len(hanzi):
        return PinyinCheck(False, dico_marks, f"{len(hanzi)} caractères mais {len(proposed)} syllabes")
    for got, ref in zip(proposed, expected):
        if not _same_syllable(got, ref):
            return PinyinCheck(False, dico_marks, f"« {got} » ne correspond pas au dictionnaire (« {ref} »)")
    return PinyinCheck(True, dico_marks)
