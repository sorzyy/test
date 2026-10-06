# saphir

Télécharge vidéos, photos et audio depuis **YouTube, Instagram, X/Twitter, TikTok** et plus de 1800 autres sites. Colle un lien, récupère le fichier. Sans pub, sans pistage.

C'est une réécriture complète inspirée de [Cobalt](https://github.com/imputnet/cobalt), faite pour régler son principal problème : quand une plateforme change son API, Cobalt casse jusqu'à ce que quelqu'un corrige son extracteur à la main. saphir s'appuie sur des moteurs maintenus en continu ([yt-dlp](https://github.com/yt-dlp/yt-dlp) et [gallery-dl](https://github.com/mikf/gallery-dl), corrigés en général quelques heures après une casse) et **se met à jour tout seul**. Il garde aussi des extracteurs natifs en secours, portés de Cobalt et améliorés.

## Ce que ça fait

| Plateforme | Vidéo | Photo | Notes |
|---|---|---|---|
| YouTube | ✅ vidéos, shorts, music | — | qualité jusqu'à 8K, h264 / av1 / vp9, PO token intégré |
| Instagram | ✅ reels, posts | ✅ photos, carrousels mixtes | liens `/share/` acceptés ; cookies conseillés |
| X / Twitter | ✅ vidéos, gifs | ✅ jusqu'à 4 photos en qualité originale | sans compte (API syndication + fxtwitter) |
| TikTok | ✅ sans filigrane | ✅ diaporamas + leur musique | liens courts `vm.` / `vt.` acceptés |
| +1800 sites | ✅ Reddit, Facebook, Vimeo, Twitch, SoundCloud, Bluesky, Dailymotion… | ✅ Pinterest, Imgur, Tumblr, Reddit… | via yt-dlp / gallery-dl |

- **3 modes**, comme Cobalt : *auto* (vidéo + son), *audio* (mp3 / m4a / opus / ogg / wav / original), *muet*
- **qualité et codec au choix** : 144p à 4K+, h264 (lisible partout), av1, vp9
- **sélecteur** pour les carrousels et les tweets à plusieurs médias, plus un bouton **tout télécharger (.zip)**
- conversion des gifs X/Twitter en vrai `.gif`
- **barre de progression** en direct
- **appli installable** (PWA) : sur Android, "Partager → saphir" depuis Instagram ou TikTok
- **API compatible Cobalt** : les raccourcis iOS et extensions faits pour Cobalt marchent en pointant sur ton serveur
- **mise à jour automatique** de yt-dlp et gallery-dl toutes les 12 h (canal nightly par défaut), sans redémarrage

## Démarrage rapide

### Avec Docker (recommandé)

```bash
git clone https://github.com/sorzyy/test.git saphir && cd saphir
docker compose up -d --build
```

Ouvre http://localhost:9000. Le `docker-compose.yml` lance aussi `bgutil`, qui fournit à YouTube les "PO tokens" nécessaires pour éviter le blocage *"Sign in to confirm you're not a bot"*.

### Sans Docker

Prérequis : Python 3.10+, [ffmpeg](https://ffmpeg.org/download.html) et [deno](https://deno.com) (ou Node.js), YouTube exigeant un runtime JavaScript depuis fin 2025.

- **Windows** : `winget install Gyan.FFmpeg DenoLand.Deno`, puis double-clic sur `start.bat`
- **macOS / Linux** : `brew install ffmpeg deno` (ou `apt install ffmpeg`), puis `./start.sh`

## Mettre en ligne (URL publique)

GitHub Pages n'héberge que des pages statiques : il affiche l'interface, mais le travail (yt-dlp, ffmpeg) doit tourner sur un vrai serveur. Il y a donc deux étapes :

**1. Le serveur, sur Render (gratuit)**
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/sorzyy/test)

Clique le bouton, connecte-toi avec GitHub, puis valide. Render construit l'image Docker (~5 min) et te donne une adresse du type `https://saphir-xxxx.onrender.com`, qui affiche déjà l'interface complète. L'offre gratuite met le serveur en veille après 15 min sans visite : le premier lien suivant prend environ 30 s.

**2. L'interface sur GitHub Pages** (optionnel, pour l'adresse `https://sorzyy.github.io/test/`)
- mets l'adresse Render dans `deploy/api-url.txt` et pousse : le workflow *GitHub Pages* publie la page
- s'il échoue à la première publication : *Settings → Pages → Build and deployment → Source : GitHub Actions*, puis relance le workflow

**Instagram sur Render** : Instagram bloque les visiteurs non connectés sur beaucoup de reels récents quand la demande vient d'un serveur. Ajoute les cookies d'un compte (un compte secondaire de préférence) : exporte `cookies.txt` (voir plus bas), ouvre-le dans un éditeur de texte, copie tout, et colle-le dans la variable `COOKIES_TXT` (Render → ton service → *Environment*). Le service redémarre et les reels passent.

À savoir : sur un hébergeur (Render ou autre), YouTube bloque la plupart des IP de datacenter. Pour YouTube, ajoute des cookies (variable `COOKIES_FILE` via un *Secret File* Render) ou garde une instance chez toi. Instagram, X et TikTok marchent sans réglage, mais un `cookies.txt` Instagram reste conseillé pour un usage régulier.

## Débloquer Instagram (et le contenu réservé aux membres) : les cookies

Instagram bride fortement les visiteurs non connectés, surtout depuis des IP de serveurs. Avec les cookies d'un compte, tout passe : posts, reels, carrousels, stories, contenus +18.

1. Installe l'extension **"Get cookies.txt LOCALLY"** ([Chrome](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) / [Firefox](https://addons.mozilla.org/firefox/addon/get-cookies-txt-locally/))
2. Connecte-toi à instagram.com (un compte secondaire est conseillé), clique sur l'extension, puis **Export**
3. Place le fichier ainsi :
   - Docker : `cookies/cookies.txt` (à côté du `docker-compose.yml`)
   - sans Docker : `cookies.txt` à la racine du projet
4. Redémarre (`docker compose restart`)

**Sans Docker, plus simple** : lance saphir avec `COOKIES_FROM_BROWSER=firefox` (ou `chrome`, `edge`, `brave`…) et il utilise directement les cookies du navigateur où tu es connecté. Firefox est le plus fiable : sous Windows, Chrome chiffre ses cookies d'une façon que yt-dlp ne sait pas toujours lire.

Le même fichier peut contenir les cookies de plusieurs sites (Instagram, YouTube, X, TikTok…) : exporte-les les uns après les autres et colle-les dans le même fichier. Pour YouTube, des cookies ne servent qu'aux vidéos avec restriction d'âge ou réservées aux membres, le PO token suffit pour le reste.

## Configuration

Tout se règle par variables d'environnement (dans `docker-compose.yml`) :

| Variable | Défaut | Rôle |
|---|---|---|
| `PORT` | `9000` | port HTTP |
| `COOKIES_FILE` | `cookies.txt` s'il existe | fichier cookies au format Netscape |
| `COOKIES_TXT` | — | le **contenu** du cookies.txt, collé dans une variable (pratique sur Render) |
| `COOKIES_FROM_BROWSER` | — | sans Docker : lit les cookies d'un navigateur installé (`firefox`, `chrome`, `edge`, `brave`…) |
| `POT_PROVIDER_URL` | — | serveur bgutil pour les PO tokens YouTube (`http://bgutil:4416` dans le compose) |
| `AUTO_UPDATE` | `1` | met à jour yt-dlp / gallery-dl tout seul |
| `UPDATE_CHANNEL` | `nightly` | `nightly` (correctifs plus rapides) ou `stable` |
| `UPDATE_INTERVAL_HOURS` | `12` | fréquence des mises à jour |
| `API_KEY` | — | protège l'instance : clé à saisir dans les réglages de l'interface |
| `RATE_LIMIT_PER_MINUTE` | `30` | analyses par minute et par IP (`0` = illimité) |
| `MAX_CONCURRENT_JOBS` | `4` | téléchargements simultanés |
| `EXTRACT_WORKERS` | `2` | processus yt-dlp gardés en mémoire pour des analyses rapides (`0` = désactivé) |
| `MAX_DURATION` | `0` | durée max d'une vidéo en secondes (`0` = illimité) |
| `MAX_FILESIZE_MB` | `0` | taille max d'un fichier (`0` = illimité) |
| `MAX_ITEMS` | `50` | éléments max d'un carrousel / d'une playlist |
| `PROXY` | — | proxy sortant (`http://…`, `socks5://…`), utile si l'IP du serveur est bloquée |
| `TRUST_PROXY` | `0` | lit l'IP client dans `X-Forwarded-For` (derrière Caddy / Nginx) |
| `PUBLIC_URL` | — | URL publique, utilisée dans les liens de l'API Cobalt |
| `CORS_ORIGINS` | `*` | sites autorisés à appeler l'API depuis un navigateur (ex. `https://sorzyy.github.io`) |
| `JOB_TTL` | `900` | secondes avant suppression d'un fichier préparé |
| `ALLOW_PRIVATE_URLS` | `0` | autorise les liens vers le réseau local (désactivé par sécurité) |
| `YTDLP_EXTRA_ARGS` | — | options yt-dlp supplémentaires, ex. `--extractor-args "youtube:player-client=mweb,tv"` |

## API

Documentation interactive : `http://localhost:9000/api/docs`.

```bash
# 1. analyser un lien
curl -X POST localhost:9000/api/resolve -H 'content-type: application/json' \
     -d '{"url": "https://x.com/perrypumas/status/894001459754180609"}'
# -> {"token": "…", "items": [{"index": 0, "type": "photo", …}, …], "audio": null}

# 2. lancer un téléchargement (index, "audio" ou "all" pour un zip)
curl -X POST localhost:9000/api/jobs -H 'content-type: application/json' \
     -d '{"token": "…", "index": 0, "options": {"mode": "auto", "quality": "1080", "codec": "h264"}}'

# 3. suivre la progression, puis récupérer le fichier
curl localhost:9000/api/jobs/<id>          # {"status": "downloading", "progress": 42.0, …}
curl -OJ localhost:9000/api/jobs/<id>/file
```

Options : `mode` (`auto` | `audio` | `mute`), `quality` (`max`, `2160`, `1440`, `1080`, `720`, `480`, `360`, `240`, `144`), `codec` (`h264` | `av1` | `vp9` | `best`), `audio_format` (`mp3` | `best` | `m4a` | `opus` | `ogg` | `wav`), `audio_bitrate` (`320` … `64`), `convert_gif`.

### Compatibilité Cobalt

`POST /` accepte le format de requête de Cobalt v10 (`url`, `downloadMode`, `videoQuality`, `audioFormat`, `audioBitrate`, `youtubeVideoCodec`, `convertGif`) et répond pareil (`tunnel`, `picker`, `error`). Dans un client Cobalt, il suffit de remplacer l'adresse de l'instance par celle de ton serveur.

## Comment ça marche

Pour chaque lien, saphir détecte la plateforme et essaie plusieurs moteurs, du plus fiable au secours :

- **YouTube** et autres sites : yt-dlp, puis gallery-dl
- **Instagram** : yt-dlp (photos de carrousel incluses), puis l'extracteur natif (API mobile, page embed, GraphQL, comme Cobalt), puis gallery-dl
- **X / Twitter** : yt-dlp et l'API syndication en parallèle, puis fxtwitter, puis gallery-dl. Les photos gardent leur ordre et les vidéos passent par yt-dlp pour le choix de qualité.
- **TikTok** : yt-dlp et l'extracteur natif en parallèle (vidéos sans filigrane, diaporamas avec musique), puis gallery-dl

Pour aller vite :
- **yt-dlp reste chargé en mémoire** (processus permanents, recyclés après chaque mise à jour) : une analyse économise ~1,3 s de démarrage ;
- **le fichier part en flux direct**, comme avec Cobalt : le serveur relaie les octets au navigateur dès qu'ils arrivent, en fusionnant vidéo + audio ou en convertissant en mp3 à la volée avec ffmpeg, sans fichier temporaire ni attente ;
- pour YouTube et les archives zip, le fichier est préparé sur le serveur, puis envoyé et supprimé au bout de 15 minutes.

```
app/
├── main.py           serveur web, API, API compatible Cobalt
├── resolver.py       choix des moteurs par plateforme et fusion des résultats
├── jobs.py           téléchargements, progression, ffmpeg, zip
├── formats.py        qualité / codec / audio -> options yt-dlp et ffmpeg
├── services.py       détection et normalisation des liens
├── updater.py        mise à jour automatique de yt-dlp et gallery-dl
├── extractors/       yt-dlp, gallery-dl, et extracteurs natifs instagram / twitter / tiktok
└── static/           interface web
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest                      # tests unitaires et de bout en bout hors ligne (yt-dlp, gallery-dl, ffmpeg réels)
RUN_LIVE=1 pytest -m live -v -s   # vrais liens YouTube / Instagram / X / TikTok
```

La CI GitHub lance aussi les tests live une fois par jour, pour repérer une plateforme qui casse.

## Dépannage

- **YouTube : "Sign in to confirm you're not a bot"** : YouTube bloque presque toutes les IP de datacenter (VPS, cloud, CI), quel que soit l'outil, Cobalt compris. Chez toi (connexion perso), ça marche normalement. Sur un serveur : ajoute des cookies YouTube (compte secondaire) ou un `PROXY` résidentiel, et vérifie que le service `bgutil` tourne (`docker compose ps`).
- **Instagram : "connexion requise"** : ajoute un `cookies.txt` (voir plus haut).
- **Un site qui marchait ne marche plus** : la mise à jour auto récupère le correctif en général sous 24 h. Pour forcer : `curl -X POST localhost:9000/api/update` (depuis le serveur, ou avec `Authorization: Api-Key …`).
- **Infos et versions** : `http://localhost:9000/api/status`.

## Avertissement

Outil destiné à un usage personnel. Ne télécharge que du contenu que tu as le droit de télécharger, et respecte les droits d'auteur et les conditions d'utilisation des plateformes.
