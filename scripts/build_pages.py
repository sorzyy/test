"""Construit la version GitHub Pages de l'interface (fichiers statiques) dans _site/.

L'interface appelle le serveur saphir dont l'adresse est dans deploy/api-url.txt
(ou dans la variable d'environnement SAPHIR_API_URL).
"""

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
OUT = ROOT / "_site"


def main() -> None:
    api = (os.environ.get("SAPHIR_API_URL") or (ROOT / "deploy" / "api-url.txt").read_text()).strip().rstrip("/")
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(STATIC, OUT)

    # chemins relatifs : la page est servie sous /<dépôt>/ sur github.io
    index = (OUT / "index.html").read_text(encoding="utf-8")
    index = index.replace('"/static/', '"./').replace('"/manifest.webmanifest"', '"./manifest.webmanifest"')
    (OUT / "index.html").write_text(index, encoding="utf-8")

    manifest = json.loads((OUT / "manifest.webmanifest").read_text(encoding="utf-8"))
    manifest["start_url"] = "./"
    manifest["share_target"]["action"] = "./"
    for icon in manifest["icons"]:
        icon["src"] = "./" + icon["src"].rsplit("/", 1)[-1]
    (OUT / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    config = {"api": api} if api else {"api": "", "missing": True}
    (OUT / "config.js").write_text(f"window.SAPHIR_CONFIG = {json.dumps(config)};\n", encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    print(f"site construit dans {OUT} (serveur : {api or 'non configuré'})")


if __name__ == "__main__":
    main()
