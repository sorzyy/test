#!/usr/bin/env sh
# Lancement local sans Docker (Linux / macOS). Prérequis : Python 3.10+, ffmpeg, et idéalement deno ou node.
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null 2>&1 || echo "⚠ ffmpeg introuvable : installe-le (brew install ffmpeg / apt install ffmpeg)."
command -v deno >/dev/null 2>&1 || command -v node >/dev/null 2>&1 || \
  echo "⚠ ni deno ni node : YouTube risque d'échouer (https://deno.com)."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "→ saphir sur http://localhost:${PORT:-9000}"
exec uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-9000}"
