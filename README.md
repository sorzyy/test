# 老师 Lǎoshī : un prof de chinois dans tes lunettes

Tu regardes autour de toi avec tes lunettes Meta (Ray-Ban Meta, Oakley Meta, Meta Ray-Ban Display…).
Tu appuies sur le bouton photo. Le prof regarde ce que tu vois et te parle à l'oreille :

> « **椅子** » … *chaise* … « 一把椅子 » … « 这是一把椅子。» … *C'est une chaise.*
> « 桌子上有什么？» (*Qu'y a-t-il sur la table ?*)

Tu peux aussi lui parler : « **Hey Meta, lance Lǎoshī** » → « Oui ? » → « Que veut dire *siège* en chinois ? »
→ « Siège, en chinois, se dit : 座位… 座位… 这个座位有人吗？ »

Les mots rencontrés vont dans ton vocabulaire. Ils reviennent ensuite en révision, et en défis
(« Trouve un 杯子 autour de toi ! »).

## Comment ça marche

```
 Lunettes Meta ──Bluetooth/Wi-Fi──▶ App iPhone (ios/) ──HTTPS──▶ Serveur (server/) ──▶ Gemini Flash
   caméra, micro, bouton photo,       SDK Meta « Device             prépare la leçon,      (ou Claude)
   « Hey Meta »,                      Access Toolkit »              répond aux questions,
   haut-parleurs  ◀── voix ──────────                               vérifie le pinyin
```

| Dossier | Rôle |
|---|---|
| `server/` | Le cerveau du prof : API `POST /api/scan` (photo → leçon) et `POST /api/ask` (question → réponse) + une **appli web** pour tester tout de suite avec la caméra du téléphone, sans les lunettes. |
| `ios/` | L'app iPhone qui pilote les lunettes avec le [Meta Wearables Device Access Toolkit](https://github.com/facebook/meta-wearables-dat-ios) : flux caméra, bouton photo de la branche, « Hey Meta, lance Lǎoshī », micro des lunettes, voix dans leurs haut-parleurs. |

## La méthode (pourquoi c'est efficace)

1. **Le monde réel comme manuel.** Un mot attaché à un objet que tu vois tous les jours se retient bien mieux qu'une liste.
2. **Peu de nouveautés à la fois.** Au maximum 1 à 3 mots nouveaux par photo (réglable). Les phrases d'exemple réutilisent tes mots connus. Tu n'as qu'un seul élément nouveau à comprendre à la fois.
3. **Rappel actif.** Pour un mot en cours d'apprentissage, le prof dit d'abord le chinois, puis la traduction après une pause : essaie de répondre avant lui.
4. **Répétition espacée.** Chaque mot revient au bon moment : 1, 3, 7, 16, 35 puis 80 jours (boîtes de Leitner). Un mot est « maîtrisé » à partir de 16 jours.
5. **Défis dans ton environnement.** Retrouver l'objet autour de toi, c'est de la révision active en contexte.
6. **Une base sûre :**
   - chinois standard (普通话), caractères simplifiés, pinyin avec tons ;
   - pinyin **recoupé avec un dictionnaire** (CC-CEDICT via `pypinyin`) : syllabes et tons, en tolérant les tons neutres où le dictionnaire se trompe. ⚠ s'affiche s'il y a un doute ;
   - classificateur (量词) appris avec chaque mot : 一**把**椅子, 一**张**桌子 ;
   - consignes au modèle : mots courants, objets clairement visibles uniquement, et pas d'étymologie inventée ;
   - pinyin coloré par ton (1 rouge, 2 vert, 3 bleu, 4 violet, neutre gris) pour bien mémoriser les tons.

## 0. Tester tout de suite (sans serveur ni clé)

`artifact/laoshi.html` est une version web autonome publiée sur claude.ai. Elle utilise Claude depuis le
compte de la personne qui l'ouvre : pas de serveur, pas de clé API. Elle comprend la photo depuis le
téléphone, les questions au clavier ou dictées, la lecture à voix haute, les défis et les révisions. Seule
différence avec le serveur : le pinyin n'y est pas recoupé avec le dictionnaire.

## 1. Lancer le serveur (5 minutes)

Il faut une clé API **Gemini** (gratuite sur [aistudio.google.com/apikey](https://aistudio.google.com/apikey)).
Gemini Flash est rapide et bon marché, c'est le choix par défaut. Claude marche aussi (clé `ANTHROPIC_API_KEY`).

```bash
cd server
pip install -r requirements.txt
export GEMINI_API_KEY=...        # ta clé, à ne jamais mettre dans le code ni dans Git
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Ouvre `http://localhost:8000` : c'est l'appli web. Sans clé API, le serveur passe en **mode démo**
(réponses fictives) pour que tu puisses voir l'interface.

> La caméra et le micro du navigateur ne marchent qu'en HTTPS (ou sur `localhost`). Pour tester sur ton
> téléphone, déploie sur Render (ci-dessous) ou utilise un tunnel HTTPS.

### Déployer en ligne (gratuit)

Sur [Render](https://render.com) : *New › Blueprint* › choisis ce dépôt (le fichier `render.yaml` est prêt).
Renseigne ensuite `GEMINI_API_KEY`, et `LAOSHI_TOKEN` (un mot de passe de ton choix, à
saisir aussi dans les réglages de l'appli). Sans ce jeton, n'importe qui connaissant l'adresse pourrait
utiliser ta clé API.

| Variable | Défaut | Rôle |
|---|---|---|
| `GEMINI_API_KEY` | — | Clé Gemini : active le fournisseur Gemini |
| `ANTHROPIC_API_KEY` | — | Clé Claude (utilisée seulement s'il n'y a pas de clé Gemini) |
| `LAOSHI_PROVIDER` | auto | `gemini`, `claude` ou `demo` pour forcer un fournisseur |
| `LAOSHI_MODEL` | `gemini-3.5-flash` / `claude-opus-5-5` | Modèle utilisé |
| `LAOSHI_EFFORT` | `low` | Profondeur de réflexion : `low` = rapide, `medium`/`high` = plus soigné mais plus lent |
| `LAOSHI_TOKEN` | vide | Jeton exigé dans l'en-tête `X-Laoshi-Token` |
| `LAOSHI_DEMO` | — | `1` pour forcer le mode démo |

### Appli web

- **Voir** : vise un objet, appuie sur « Qu'est-ce que je vois ? ». Le **mode balade** scanne toutes les 15 s.
  Sous la caméra, pose une question au prof, au clavier ou au micro 🎤 (« que veut dire siège en chinois ? »,
  « c'est quoi ça en chinois ? » : l'image de la caméra est jointe).
- **Défi** : un mot de ton vocabulaire s'affiche, trouve l'objet et montre-le à la caméra.
- **Révision** : les cartes du jour (caractère → sens, avec audio).
- **Réglages** : niveau, nombre de mots nouveaux, vitesse de la voix, export/import du vocabulaire.

Astuce : sur le téléphone, connecte tes lunettes en Bluetooth (comme des écouteurs). La voix du prof sort
alors déjà dans les lunettes, même avec l'appli web.

## 2. L'app iPhone pour les lunettes

👉 **Guide pas à pas : [`ios/INSTALLATION.md`](ios/INSTALLATION.md)** (Mac + Xcode, environ 30 minutes la première fois).

En résumé : `brew install xcodegen`, puis `cd ios && xcodegen generate && open Laoshi.xcodeproj`, puis signer avec
ton Apple ID et lancer sur l'iPhone. Dans l'app, colle ta clé Gemini dans ⚙︎ : c'est le **mode direct**, l'app
parle à Gemini elle-même, **sans serveur**. Le serveur reste possible (pinyin vérifié par dictionnaire).

L'app est compilée automatiquement sur un Mac GitHub à chaque modification (`.github/workflows/ios.yml`).

### Parler au prof : « Hey Meta, lance Lǎoshī »

Meta AI ne transmet pas les questions libres (« Hey Meta, que veut dire siège en chinois ? ») aux apps
tierces : il garde ces questions pour lui. Ce que le SDK permet, c'est **« Hey Meta, lance Lǎoshī »**.
Lǎoshī s'en sert comme mot d'éveil :

1. « Hey Meta, lance Lǎoshī » : l'app passe au premier plan et allume la caméra si besoin.
2. Les lunettes disent « Oui ? » et écoutent avec leur micro (reconnaissance vocale sur les lunettes).
3. Tu demandes : « Que veut dire siège en chinois ? », « Comment on dit fourchette ? », « C'est quoi ça ? ».
4. Le prof répond dans les lunettes. La dernière image de la caméra est jointe, ce qui lève les ambiguïtés
   (le siège d'une voiture n'est pas un siège social).

Le bouton « Poser une question » de l'app fait la même chose sans « Hey Meta ».

### Fonctions expérimentales du SDK

Le bouton photo (`MWDATInputs`), « Hey Meta, lance… » (Voice Invocations) et la reconnaissance vocale
(`MWDATSpeech`) sont **expérimentaux** chez Meta. Tu peux les utiliser en développement et en bêta, pas
encore dans une app publiée. Il faut les activer pour ton app dans le
[Wearables Developer Center](https://wearables.developer.meta.com/), y compris le nom prononcé de l'app
pour « Hey Meta, lance… ». La langue de la reconnaissance vocale dépend des lunettes : vérifie que le
français est bien reconnu.

Tant qu'elles ne sont pas activées, le bouton de l'app, le mode balade et l'appli web fonctionnent.

## Tests

```bash
cd server
pip install -r requirements-dev.txt
pytest -q
```

## Pistes pour la suite

- **Meta Ray-Ban Display** : afficher le caractère et le pinyin dans le verre (module `MWDATDisplay`).
- **Prononciation** : faire répéter le mot dans le micro des lunettes et corriger les tons.
- **Synchroniser** le vocabulaire entre l'appli web et l'app iPhone (aujourd'hui chacune garde le sien).
- **Voix plus naturelle** : synthèse vocale neuronale côté serveur au lieu de la voix du système.
