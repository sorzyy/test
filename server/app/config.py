"""Réglages lus dans les variables d'environnement."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Modèle Claude utilisé pour regarder l'image et préparer la leçon.
    model: str = os.getenv("LAOSHI_MODEL", "claude-opus-5-5")
    # low = réponses rapides (important dans des lunettes). medium/high = plus soigné.
    effort: str = os.getenv("LAOSHI_EFFORT", "low")
    # Jeton optionnel : si défini, chaque requête doit envoyer l'en-tête X-Laoshi-Token.
    # Évite qu'un inconnu utilise ton serveur public (et ta clé API).
    access_token: str = os.getenv("LAOSHI_TOKEN", "")
    # Mode démo : réponses fictives, sans appeler Claude (pratique pour tester l'interface).
    demo: bool = os.getenv("LAOSHI_DEMO", "").lower() in {"1", "true", "yes"} or not (
        os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
    )
    max_image_bytes: int = int(os.getenv("LAOSHI_MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))


def get_settings() -> Settings:
    return Settings()
