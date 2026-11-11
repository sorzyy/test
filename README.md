# 老师 Lǎoshī : un prof de chinois dans tes lunettes

Tu regardes autour de toi avec tes lunettes Meta (Ray-Ban Meta, Oakley Meta, Meta Ray-Ban Display…).
Tu appuies sur le bouton photo. Le prof regarde ce que tu vois et te parle à l'oreille :

> « **椅子** » … *chaise* … « 一把椅子 » … « 这是一把椅子。» … *C'est une chaise.*
> « 桌子上有什么？» (*Qu'y a-t-il sur la table ?*)

Les mots rencontrés vont dans ton vocabulaire. Ils reviennent ensuite en révision, et en défis
(« Trouve un 杯子 autour de toi ! »).

## Comment ça marche

```
 Lunettes Meta ──Bluetooth/Wi-Fi──▶ App iPhone (ios/) ──HTTPS──▶ Serveur (server/) ──▶ Claude (vision)
   caméra, bouton photo,              SDK Meta « Device             prépare la leçon,
   haut-parleurs  ◀── voix ────────── Access Toolkit »              vérifie le pinyin
```

| Dossier | Rôle |
|---|---|
| `server/` | Le cerveau du prof : API `POST /api/scan` (photo → leçon) + une **appli web** pour tester tout de suite avec la caméra du téléphone, sans les lunettes. |
| `ios/` | L'app iPhone qui pilote les lunettes avec le [Meta Wearables Device Access Toolkit](https://github.com/facebook/meta-wearables-dat-ios) : flux caméra, bouton photo de la branche, voix dans les haut-parleurs des lunettes. |

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

## 1. Lancer le serveur (5 minutes)

Il faut une clé API Anthropic ([console.anthropic.com](https://console.anthropic.com)).

```bash
cd server
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Ouvre `http://localhost:8000` : c'est l'appli web. Sans clé API, le serveur passe en **mode démo**
(leçon fictive : une chaise, un bol) pour que tu puisses voir l'interface.

> La caméra du navigateur ne marche qu'en HTTPS (ou sur `localhost`). Pour tester sur ton
> téléphone, déploie sur Render (ci-dessous) ou utilise un tunnel HTTPS.

### Déployer en ligne (gratuit)

Sur [Render](https://render.com) : *New › Blueprint* › choisis ce dépôt (le fichier `render.yaml` est prêt).
Renseigne ensuite `ANTHROPIC_API_KEY`, et `LAOSHI_TOKEN` (un mot de passe de ton choix, à
saisir aussi dans les réglages de l'appli). Sans ce jeton, n'importe qui connaissant l'adresse pourrait
utiliser ta clé API.

| Variable | Défaut | Rôle |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Clé API (sans elle : mode démo) |
| `LAOSHI_TOKEN` | vide | Jeton exigé dans l'en-tête `X-Laoshi-Token` |
| `LAOSHI_MODEL` | `claude-opus-5-5` | Modèle Claude |
| `LAOSHI_EFFORT` | `low` | `low` = réponses rapides, `medium`/`high` = plus soigné mais plus lent |
| `LAOSHI_DEMO` | — | `1` pour forcer le mode démo |

### Appli web

- **Voir** : vise un objet, appuie sur « Qu'est-ce que je vois ? ». Le **mode balade** scanne toutes les 15 s.
- **Défi** : un mot de ton vocabulaire s'affiche, trouve l'objet et montre-le à la caméra.
- **Révision** : les cartes du jour (caractère → sens, avec audio).
- **Réglages** : niveau, nombre de mots nouveaux, vitesse de la voix, export/import du vocabulaire.

Astuce : sur le téléphone, connecte tes lunettes en Bluetooth (comme des écouteurs). La voix du prof sort
alors déjà dans les lunettes, même avec l'appli web.

## 2. L'app iPhone pour les lunettes

Prérequis : un Mac avec Xcode 26.4+, un iPhone (iOS 17.2+), l'app **Meta AI** avec tes lunettes appairées et le
**mode développeur** activé (Meta AI › Paramètres › tes lunettes › Mode développeur).

```bash
brew install xcodegen
cd ios
xcodegen generate        # crée Laoshi.xcodeproj et télécharge le SDK Meta
open Laoshi.xcodeproj
```

Dans Xcode : choisis ton équipe (*Signing & Capabilities*), branche ton iPhone, lance l'app (▶).
Ensuite, dans l'app :

1. ⚙︎ Réglages : renseigne l'adresse de ton serveur (et le jeton).
2. « Connecter mes lunettes » : l'app Meta AI s'ouvre pour autoriser Lǎoshī, puis revient.
3. « Démarrer la caméra des lunettes » : Meta AI demande l'accès à la caméra la première fois.
4. Appuie sur **le bouton photo de la branche des lunettes** (ou sur le bouton de l'app) : le prof te répond dans les lunettes.

Le bouton photo des lunettes utilise le module `MWDATInputs`. Il est **expérimental** : il faut l'activer
pour ton app dans le [Wearables Developer Center](https://wearables.developer.meta.com/). En attendant, le bouton
de l'app et le mode balade fonctionnent.

## Tests

```bash
cd server
pip install -r requirements-dev.txt
pytest -q
```

## Pistes pour la suite

- **Meta Ray-Ban Display** : afficher le caractère et le pinyin dans le verre (module `MWDATDisplay`).
- **Prononciation** : le micro des lunettes + `MWDATSpeech` pour que l'élève répète le mot et soit corrigé.
- **Synchroniser** le vocabulaire entre l'appli web et l'app iPhone (aujourd'hui chacune garde le sien).
- **Voix plus naturelle** : synthèse vocale neuronale côté serveur au lieu de la voix du système.
