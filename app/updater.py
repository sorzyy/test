"""Mise à jour automatique de yt-dlp et gallery-dl.

Les plateformes changent souvent leurs API : yt-dlp et gallery-dl publient des
correctifs en quelques heures. Le serveur les installe tout seul, sans
redémarrage (ils tournent en sous-processus).
"""

from __future__ import annotations

import asyncio
import logging
import time

from .config import settings
from .tools import PYTHON, package_version, run

log = logging.getLogger("saphir.updater")

PACKAGES = ["yt-dlp[default]", "gallery-dl", "bgutil-ytdlp-pot-provider"]

state = {
    "last_check": None,
    "last_result": None,
    "running": False,
}


def versions() -> dict:
    return {
        "yt-dlp": package_version("yt-dlp"),
        "yt-dlp-ejs": package_version("yt-dlp-ejs"),
        "gallery-dl": package_version("gallery-dl"),
        "bgutil-pot-provider": package_version("bgutil-ytdlp-pot-provider"),
    }


async def update_now() -> dict:
    from .jobs import gate

    if state["running"]:
        return {"ok": False, "message": "mise à jour déjà en cours"}
    state["running"] = True
    before = versions()
    try:
        cmd = [PYTHON, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
               "--no-input", "--quiet"]
        if settings.update_channel == "nightly":
            cmd.append("--pre")
        cmd += PACKAGES
        # on attend la fin des téléchargements en cours pour ne pas remplacer
        # les fichiers de yt-dlp sous leurs pieds
        try:
            await asyncio.wait_for(gate.exclusive(), timeout=600)
        except asyncio.TimeoutError:
            gate.reopen()
            raise
        try:
            res = await run(cmd, timeout=600)
        finally:
            gate.reopen()
        after = versions()
        changed = {k: [before[k], after[k]] for k in after if before.get(k) != after.get(k)}
        result = {"ok": res.ok, "changed": changed, "versions": after,
                  "error": None if res.ok else res.stderr[-1000:]}
        if res.ok:
            log.info("update ok, changed: %s", changed or "rien")
        else:
            log.warning("update failed: %s", res.stderr[-500:])
    except asyncio.TimeoutError:
        result = {"ok": False, "changed": {}, "versions": before, "error": "téléchargements trop longs"}
    finally:
        state["running"] = False
    state["last_check"] = time.time()
    state["last_result"] = result
    return result


async def update_loop():
    await asyncio.sleep(5)
    while True:
        try:
            await update_now()
        except Exception:
            log.exception("auto-update crashed")
        await asyncio.sleep(settings.update_interval_hours * 3600)
