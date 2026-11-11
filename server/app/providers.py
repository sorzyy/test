"""Les modèles d'IA qui peuvent jouer le prof : Gemini (Flash) ou Claude.

Les deux reçoivent la même consigne, éventuellement une image, et doivent répondre en JSON
selon un schéma. Le reste de l'appli ne voit pas la différence.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

from .config import Settings

log = logging.getLogger("laoshi")


class TutorError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class Image:
    media_type: str
    data: bytes
    b64: str


class Provider(Protocol):
    name: str

    async def generate(self, system: str, text: str, schema: dict, image: Image | None) -> tuple[dict, str]:
        """Renvoie (réponse JSON décodée, nom du modèle)."""
        ...


def _parse_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise TutorError("Réponse du modèle illisible, réessaie.", 502) from exc
    if not isinstance(data, dict):
        raise TutorError("Réponse du modèle inattendue, réessaie.", 502)
    return data


# ---------------------------------------------------------------- Gemini

_GEMINI_THINKING = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "minimal": "MINIMAL"}


def gemini_schema(schema: dict) -> dict:
    """Gemini n'accepte pas « additionalProperties » partout : on le retire."""
    if isinstance(schema, dict):
        return {k: gemini_schema(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [gemini_schema(v) for v in schema]
    return schema


class GeminiProvider:
    name = "gemini"

    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client()  # lit GEMINI_API_KEY (ou GOOGLE_API_KEY)
        return self._client

    async def generate(self, system: str, text: str, schema: dict, image: Image | None) -> tuple[dict, str]:
        from google.genai import errors, types

        parts = []
        if image:
            parts.append(types.Part.from_bytes(data=image.data, mime_type=image.media_type))
        parts.append(types.Part.from_text(text=text))
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=gemini_schema(schema),
            max_output_tokens=8000,
        )
        level = _GEMINI_THINKING.get(self.settings.effort.lower())
        if level:
            config.thinking_config = types.ThinkingConfig(thinking_level=level)
        try:
            response = await self.client.aio.models.generate_content(
                model=self.settings.model_name,
                contents=[types.Content(role="user", parts=parts)],
                config=config,
            )
        except errors.ClientError as exc:
            log.warning("Gemini a refusé la requête (%s) : %s", exc.code, exc)
            if exc.code in (401, 403):
                raise TutorError("Clé API Gemini invalide côté serveur.", 500) from exc
            if exc.code == 429:
                raise TutorError("Quota Gemini atteint, réessaie dans un moment.", 429) from exc
            if exc.code == 404:
                raise TutorError(f"Modèle Gemini inconnu : {self.settings.model_name}.", 500) from exc
            raise TutorError("Gemini a refusé la requête.", 400) from exc
        except errors.ServerError as exc:
            log.warning("Erreur serveur Gemini : %s", exc)
            raise TutorError("Le service Gemini est indisponible, réessaie.", 503) from exc

        candidate = (response.candidates or [None])[0]
        finish = str(getattr(candidate, "finish_reason", "") or "")
        if candidate is None or any(k in finish for k in ("SAFETY", "PROHIBITED", "BLOCKLIST", "SPII")):
            raise TutorError("Je ne peux pas analyser ça. Vise plutôt des objets.", 422)
        if "MAX_TOKENS" in finish:
            raise TutorError("Réponse trop longue, réessaie.", 502)
        return _parse_json(response.text), response.model_version or self.settings.model_name


# ---------------------------------------------------------------- Claude

class ClaudeProvider:
    name = "claude"

    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic()
        return self._client

    async def generate(self, system: str, text: str, schema: dict, image: Image | None) -> tuple[dict, str]:
        import anthropic

        content = []
        if image:
            content.append({"type": "image", "source": {"type": "base64", "media_type": image.media_type, "data": image.b64}})
        content.append({"type": "text", "text": text})
        try:
            response = await self.client.beta.messages.create(
                model=self.settings.model_name,
                max_tokens=8000,
                # Si le modèle refuse à tort, l'API relance sur un modèle de repli.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": self.settings.effort, "format": {"type": "json_schema", "schema": schema}},
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.AuthenticationError as exc:
            raise TutorError("Clé API Anthropic invalide côté serveur.", 500) from exc
        except anthropic.RateLimitError as exc:
            raise TutorError("Trop de demandes en même temps, réessaie dans quelques secondes.", 429) from exc
        except anthropic.BadRequestError as exc:
            log.warning("Requête refusée par l'API : %s", exc.message)
            raise TutorError("L'API a refusé la requête.", 400) from exc
        except anthropic.APIStatusError as exc:
            log.warning("Erreur API %s : %s", exc.status_code, exc.message)
            raise TutorError("Le service Claude est indisponible, réessaie.", 503) from exc
        except anthropic.APIConnectionError as exc:
            raise TutorError("Impossible de joindre le service Claude.", 503) from exc

        if response.stop_reason == "refusal":
            raise TutorError("Je ne peux pas analyser ça. Vise plutôt des objets.", 422)
        if response.stop_reason == "max_tokens":
            raise TutorError("Réponse trop longue, réessaie.", 502)
        text_out = next((b.text for b in response.content if b.type == "text"), "")
        return _parse_json(text_out), response.model


def make_provider(settings: Settings) -> Provider | None:
    if settings.provider == "gemini":
        return GeminiProvider(settings)
    if settings.provider == "claude":
        return ClaudeProvider(settings)
    return None
