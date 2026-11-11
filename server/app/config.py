"""Réglages lus dans les variables d'environnement."""

import os
from dataclasses import dataclass, field

DEFAULT_MODELS = {
    "gemini": "gemini-flash-latest",
    "claude": "claude-opus-5-5",
    "demo": "",
}


def _detect_provider() -> str:
    explicit = os.getenv("LAOSHI_PROVIDER", "").strip().lower()
    if os.getenv("LAOSHI_DEMO", "").lower() in {"1", "true", "yes"}:
        return "demo"
    if explicit in DEFAULT_MODELS:
        return explicit
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return "claude"
    return "demo"


@dataclass(frozen=True)
class Settings:
    # gemini (Gemini Flash, clé GEMINI_API_KEY), claude (clé ANTHROPIC_API_KEY) ou demo.
    # Choisi automatiquement selon la clé présente, ou forcé avec LAOSHI_PROVIDER.
    provider: str = field(default_factory=_detect_provider)
    # Vide = modèle par défaut du fournisseur.
    model: str = field(default_factory=lambda: os.getenv("LAOSHI_MODEL", ""))
    # low = réponses rapides (important dans des lunettes). medium/high = plus soigné.
    effort: str = field(default_factory=lambda: os.getenv("LAOSHI_EFFORT", "low"))
    # Jeton optionnel : si défini, chaque requête doit envoyer l'en-tête X-Laoshi-Token.
    # Évite qu'un inconnu utilise ton serveur public (et ta clé API).
    access_token: str = field(default_factory=lambda: os.getenv("LAOSHI_TOKEN", ""))
    max_image_bytes: int = field(default_factory=lambda: int(os.getenv("LAOSHI_MAX_IMAGE_BYTES", str(5 * 1024 * 1024))))

    @property
    def demo(self) -> bool:
        return self.provider == "demo"

    @property
    def model_name(self) -> str:
        return self.model or DEFAULT_MODELS.get(self.provider, "")


def get_settings() -> Settings:
    return Settings()
