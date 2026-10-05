"""Erreurs applicatives et traduction des messages des extracteurs."""

from __future__ import annotations

import re

MESSAGES = {
    "link.empty": "Colle un lien pour commencer.",
    "link.invalid": "Ce lien n'est pas valide.",
    "link.private": "Les liens vers un réseau privé ne sont pas autorisés.",
    "link.unsupported": "Ce site ou ce type de lien n'est pas pris en charge.",
    "content.private": "Ce contenu est privé ou nécessite d'être connecté.",
    "content.login": "La plateforme demande une connexion pour ce contenu. "
                     "Ajoute un fichier cookies.txt (voir le README) pour débloquer.",
    "content.age": "Ce contenu est soumis à une restriction d'âge : un fichier cookies.txt d'un compte connecté est nécessaire.",
    "content.geo": "Ce contenu n'est pas disponible dans le pays du serveur.",
    "content.unavailable": "Ce contenu n'existe pas ou a été supprimé.",
    "content.live": "Les directs en cours ne peuvent pas être téléchargés.",
    "content.too_long": "Cette vidéo dépasse la durée maximale autorisée sur ce serveur.",
    "content.too_big": "Ce fichier dépasse la taille maximale autorisée sur ce serveur.",
    "content.empty": "Aucun média téléchargeable n'a été trouvé à ce lien.",
    "fetch.bot": "La plateforme bloque temporairement le serveur (détection anti-bot). "
                 "Réessaie plus tard, ou configure cookies / PO token (voir le README).",
    "fetch.rate": "Trop de requêtes vers la plateforme. Réessaie dans quelques minutes.",
    "fetch.fail": "Impossible de récupérer ce contenu. Réessaie dans un instant.",
    "fetch.timeout": "La plateforme a mis trop de temps à répondre.",
    "download.fail": "Le téléchargement a échoué.",
    "job.notfound": "Ce téléchargement a expiré. Relance-le.",
    "token.expired": "Cette analyse a expiré. Recolle le lien.",
    "rate.exceeded": "Doucement ! Trop de demandes, réessaie dans une minute.",
    "auth.required": "Clé d'API manquante ou invalide.",
}


class AppError(Exception):
    def __init__(self, code: str, detail: str | None = None, status: int = 400):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.status = status

    @property
    def message(self) -> str:
        return MESSAGES.get(self.code, MESSAGES["fetch.fail"])

    def to_dict(self) -> dict:
        data = {"code": self.code, "message": self.message}
        if self.detail:
            data["detail"] = self.detail
        return data


# Motifs ordonnés : le premier qui correspond gagne.
_PATTERNS: list[tuple[str, str]] = [
    (r"sign in to confirm you.?re not a bot|confirm you are not a robot|captcha", "fetch.bot"),
    (r"sign in to confirm your age|age.?restricted|inappropriate for some users|age.?gate", "content.age"),
    (r"private video|this account is private|protected tweet|private post|is private", "content.private"),
    (r"login required|requires? (?:a )?log[- ]?in|log in to|logged.?in|--cookies|authenticat|"
     r"empty media response|rate-limit reached or login", "content.login"),
    (r"not available in your country|geo.?restrict|blocked it in your country|not made this video available in your country", "content.geo"),
    (r"too many requests|http error 429|rate.?limit", "fetch.rate"),
    (r"is live|live event will begin|premieres in|this live event", "content.live"),
    (r"unsupported url|no suitable extractor|not a valid url|unsupported site", "link.unsupported"),
    (r"video unavailable|has been removed|does not exist|not found|404|no longer available|"
     r"deleted|status_deleted|this post is unavailable|item doesn't exist", "content.unavailable"),
    (r"there is no video in this post|no video could be found|no video formats found|"
     r"no media found|requested format is not available", "content.empty"),
    (r"timed? ?out", "fetch.timeout"),
]


def classify(stderr: str) -> str:
    """Transforme la sortie d'erreur de yt-dlp / gallery-dl en code d'erreur."""
    text = (stderr or "").lower()
    for pattern, code in _PATTERNS:
        if re.search(pattern, text):
            return code
    return "fetch.fail"


def last_error_line(stderr: str) -> str:
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    errors = [ln for ln in lines if "error" in ln.lower()]
    line = (errors or lines or [""])[-1]
    return line[:500]


# Plus le code est "spécifique", plus il est utile à l'utilisateur.
_PRIORITY = [
    "content.age", "content.private", "content.geo", "content.live", "content.unavailable",
    "content.login", "fetch.bot", "fetch.rate", "content.empty", "link.unsupported",
    "fetch.timeout", "fetch.fail",
]


def most_specific(codes: list[str]) -> str:
    for code in _PRIORITY:
        if code in codes:
            return code
    return codes[0] if codes else "fetch.fail"
