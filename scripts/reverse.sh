#!/usr/bin/env bash
# Analyse passive de https://brandsearch.co avec REA (https://github.com/morluto/rea).
# Lance Chromium avec un port CDP local, ouvre la page, puis capture avec REA :
# structure DOM, scripts, requêtes réseau, forme des réponses JSON, bundle JS, capture d'écran.
set -euo pipefail

URL="${1:-https://brandsearch.co/}"
ORIGIN="$(printf '%s' "$URL" | sed -E 's#^(https?://[^/]+).*#\1#')"
PORT="${CDP_PORT:-9222}"
ENDPOINT="http://127.0.0.1:${PORT}"
SLUG="$(printf '%s' "$URL" | sed -E 's|^https?://||; s|[/?]+$||; s|[^a-zA-Z0-9.]+|_|g')"
OUT="${OUT:-$(cd "$(dirname "$0")/.." && pwd)/analysis/$SLUG}"
WAIT_MS="${WAIT_MS:-8000}"
REA="npx -y rea-agents@6.4.0"

CHROME="${CHROME:-$(command -v chromium || command -v chromium-browser || command -v google-chrome || echo /opt/pw-browsers/chromium-1194/chrome-linux/chrome)}"
PROFILE="$(mktemp -d)"

mkdir -p "$OUT"
"$CHROME" --headless=new --no-sandbox --password-store=basic \
  --remote-debugging-port="$PORT" --user-data-dir="$PROFILE" \
  --window-size=1440,900 "$URL" >/dev/null 2>&1 &
CHROME_PID=$!
trap 'kill $CHROME_PID 2>/dev/null; wait $CHROME_PID 2>/dev/null; rm -rf "$PROFILE"' EXIT

for _ in $(seq 1 60); do curl -sf "$ENDPOINT/json/version" >/dev/null && break; sleep 0.5; done
sleep "$((WAIT_MS / 1000))"

$REA list-browser-targets "$ENDPOINT" --format json > "$OUT/targets.json"
TARGET="$(node -e '
  const r = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"));
  const list = JSON.stringify(r).match(/"target_id":"([^"]+)"/g) || [];
  if (!list.length) process.exit(1);
  console.log(list[0].split(":")[1].replace(/"/g, ""));
' "$OUT/targets.json")"
echo "Cible CDP : $TARGET"

$REA inspect-web-page "$ENDPOINT" "$TARGET" --allowed-origins "$ORIGIN" \
  --observation-ms 5000 --include-accessibility-text --include-console-text \
  --include-json-body-shapes --include-websocket-shapes --include-script-sources \
  --include-storage-keys --format json > "$OUT/inspect.json"

$REA analyze-web-bundle "$ENDPOINT" "$TARGET" --allowed-origins "$ORIGIN" \
  --observation-ms 3000 --fetch-source-maps --format json > "$OUT/bundle.json"

$REA capture-web-screenshot "$ENDPOINT" "$TARGET" --allowed-origins "$ORIGIN" \
  --format json > "$OUT/screenshot.json"

rm -rf "$OUT/scripts"
$REA export-web-scripts "$OUT/inspect.json" "$OUT/scripts" --format json > "$OUT/export.json" || true

echo "Résultats dans $OUT"
