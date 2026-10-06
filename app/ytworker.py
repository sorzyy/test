"""Processus yt-dlp permanent : garde yt-dlp chargé en mémoire.

Lancer yt-dlp coûte ~1,3 s (import de 1800 extracteurs) avant tout travail ;
un processus déjà chaud répond en quelques millisecondes de surcoût.

Protocole : une requête JSON par ligne sur stdin ({"id", "args"}), une réponse
JSON par ligne ({"id", "ok", "info", "stderr"}). `args` sont les mêmes options
que la ligne de commande de yt-dlp, URL comprise.
"""

from __future__ import annotations

import json
import os
import sys


class _Collector:
    """Logger yt-dlp qui garde avertissements et erreurs (équivalent de stderr)."""

    def __init__(self):
        self.lines: list[str] = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        self.lines.append(msg if msg.startswith("WARNING") else f"WARNING: {msg}")

    def error(self, msg):
        self.lines.append(msg if msg.startswith("ERROR") else f"ERROR: {msg}")

    def text(self) -> str:
        return "\n".join(self.lines)


_FORMAT_KEYS = ("format_id", "url", "protocol", "ext", "vcodec", "acodec", "http_headers", "cookies",
                "width", "height", "filesize", "filesize_approx", "tbr")


def select(yt_dlp, info: dict, args: list[str]) -> dict:
    """Choisit les formats (mêmes options -f / -S que la ligne de commande) sans télécharger."""
    log = _Collector()
    try:
        opts = dict(yt_dlp.parse_options(args).ydl_opts)
        opts.update(logger=log, quiet=True, noprogress=True, simulate=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.process_ie_result(dict(info), download=False)
            chosen = result.get("requested_formats") or [result]
            formats = [{k: f.get(k) for k in _FORMAT_KEYS} for f in chosen]
            return {"ok": True, "formats": formats, "ext": result.get("ext"), "stderr": log.text()}
    except BaseException as exc:
        log.error(str(exc))
        return {"ok": False, "stderr": log.text()}


def handle(yt_dlp, args: list[str]) -> dict:
    log = _Collector()
    try:
        parsed = yt_dlp.parse_options(args)
        if not parsed.urls:
            return {"ok": False, "stderr": "ERROR: no URL"}
        opts = dict(parsed.ydl_opts)
        opts.update(logger=log, quiet=True, noprogress=True, simulate=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(parsed.urls[0], download=False)
            if not info:
                return {"ok": False, "stderr": log.text() or "ERROR: no info"}
            return {"ok": True, "info": ydl.sanitize_info(info), "stderr": log.text()}
    except BaseException as exc:  # DownloadError, SystemExit d'un argparse…
        message = str(exc)
        if message and message not in log.text():
            log.error(message)
        return {"ok": False, "stderr": log.text()}


def main() -> None:
    # stdout est réservé au protocole : tout print() parasite part sur stderr
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    import yt_dlp

    proto.write(json.dumps({"ready": True, "version": yt_dlp.version.__version__}) + "\n")
    proto.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if req.get("op") == "select":
            res = select(yt_dlp, req.get("info") or {}, req.get("args") or [])
        else:
            res = handle(yt_dlp, req.get("args") or [])
        res["id"] = req.get("id")
        proto.write(json.dumps(res, ensure_ascii=False) + "\n")
        proto.flush()


if __name__ == "__main__":
    main()
