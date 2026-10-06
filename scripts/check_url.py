"""Diagnostic d'un lien : chaque moteur séparément, puis le parcours complet (analyse + téléchargement).

Usage : python scripts/check_url.py URL [mode]
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.config import settings  # noqa: E402
from app.extractors import gallerydl, instagram, tiktok, twitter, ytdlp  # noqa: E402
from app.netutil import normalize_input_url  # noqa: E402
from app.services import detect  # noqa: E402


async def engines(url: str) -> None:
    match = detect(normalize_input_url(url))
    print(f"service={match.service} kind={match.kind} id={match.post_id} url={match.url}")
    native = {"instagram": instagram.extract, "twitter": twitter.extract, "tiktok": tiktok.extract}.get(match.service)
    tests = [("yt-dlp", ytdlp.extract(match)), ("gallery-dl", gallerydl.extract(match.url))]
    if native:
        tests.append(("natif", native(match)))
    for name, coro in tests:
        t = time.time()
        res = await coro
        print(f"  [{name}] {time.time() - t:.1f}s ok={res.ok} items={[i.type for i in res.items]} "
              f"audio={bool(res.audio)} error={res.error} detail={(res.detail or '')[:400]!r}")


def full(url: str, mode: str) -> None:
    settings.auto_update = False
    settings.rate_limit_per_minute = 0
    with TestClient(main.app) as client:
        t = time.time()
        res = client.post("/api/resolve", json={"url": url}).json()
        print(f"analyse : {time.time() - t:.1f}s -> {json.dumps(res, ensure_ascii=False)[:600]}")
        if "error" in res:
            return
        t = time.time()
        job = client.post("/api/jobs", json={"token": res["token"], "index": 0, "options": {"mode": mode}}).json()
        while job["status"] not in ("done", "error"):
            time.sleep(0.2)
            job = client.get(f"/api/jobs/{job['id']}").json()
        print(f"téléchargement : {time.time() - t:.1f}s -> {json.dumps(job, ensure_ascii=False)[:600]}")
        if job["status"] == "done":
            r = client.get(job["url"])
            print(f"fichier : {job['filename']} ({len(r.content)} octets)")


if __name__ == "__main__":
    target = sys.argv[1]
    asyncio.run(engines(target))
    full(target, sys.argv[2] if len(sys.argv) > 2 else "auto")
