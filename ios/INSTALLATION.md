# Installer Lǎoshī sur ton iPhone (pour tes lunettes Meta)

Compte environ 30 minutes la première fois. Ensuite, l'app reste sur ton iPhone.

## Ce qu'il te faut

- Un **Mac** avec **Xcode 26.4 ou plus récent** (gratuit sur l'App Store).
- Ton **iPhone** (iOS 17.2 ou plus) et son câble.
- Tes **lunettes Meta** déjà appairées dans l'app **Meta AI**.
- Un **Apple ID** (ton compte habituel suffit).
- Une **clé Gemini** : sur [aistudio.google.com/apikey](https://aistudio.google.com/apikey), crée une **nouvelle** clé
  (l'ancienne a circulé dans une conversation, supprime-la).

> Avec un Apple ID gratuit, l'app installée expire au bout de **7 jours** : il suffit de rebrancher l'iPhone
> et de relancer depuis Xcode (étape 5). Avec un compte Apple Developer payant, elle tient un an.

## Raccourci : installer l'IPA toute faite (sans Xcode)

Une IPA est fabriquée automatiquement à chaque modification :
**https://github.com/sorzyy/test/releases/tag/ipa-latest** (fichier `Laoshi.ipa`).

- Installe-la avec **SideStore**, **AltStore** ou **Sideloadly** : ils la signent avec ton Apple ID et
  l'installent comme une vraie app. ✅ Les lunettes fonctionnent.
- **Pas dans LiveContainer** : l'app tourne, mais iOS ne voit pas ses déclarations (retour depuis Meta AI,
  protocole Bluetooth des lunettes). La connexion aux lunettes échoue. ❌

Ensuite, fais l'étape 1 (mode développeur dans Meta AI) puis l'étape 6 (premier lancement).

## 1. Activer le mode développeur

- **Dans l'app Meta AI** : Paramètres › **Infos sur l'app** (App Info) › touche **5 fois le numéro de version**,
  puis active **Mode développeur** et confirme. Ça autorise une app maison à utiliser les lunettes.
  Si rien n'apparaît : force-quitte Meta AI, rouvre-le et recommence. Mets aussi Meta AI à jour.
  Une fois Lǎoshī autorisé, il apparaît dans Meta AI › Paramètres › **Connexions d'apps** ›
  Apps en mode développeur.
- **Sur l'iPhone** : Réglages › Confidentialité et sécurité › **Mode développeur** → activé (l'iPhone redémarre).
  Si l'option n'apparaît pas, branche d'abord l'iPhone au Mac avec Xcode ouvert, elle apparaîtra.

## 2. Récupérer le projet

Dans l'app **Terminal** du Mac :

```bash
git clone -b claude/youthful-curie-5bi3u8 https://github.com/sorzyy/test.git laoshi
cd laoshi/ios
```

## 3. Générer le projet Xcode

```bash
# Si Homebrew n'est pas installé : voir https://brew.sh (une ligne à copier-coller)
brew install xcodegen
xcodegen generate
open Laoshi.xcodeproj
```

Xcode s'ouvre et télécharge tout seul le SDK des lunettes Meta (une minute la première fois).

## 4. Signer l'app avec ton compte

Dans Xcode :

1. Menu **Xcode › Settings › Accounts** : ajoute ton Apple ID si ce n'est pas déjà fait.
2. Dans la colonne de gauche, clique sur **Laoshi** (l'icône bleue tout en haut), puis la cible **Laoshi**,
   onglet **Signing & Capabilities**.
3. **Team** : choisis ton nom (« Personal Team »).
4. **Bundle Identifier** : remplace `com.example.laoshi` par quelque chose d'unique, par exemple
   `com.tonprenom.laoshi`.

> Ces réglages sont écrasés si tu relances `xcodegen generate`. Pour les garder, mets-les aussi dans
> `ios/project.yml` (`PRODUCT_BUNDLE_IDENTIFIER` et `DEVELOPMENT_TEAM`).

## 5. Installer sur l'iPhone

1. Branche l'iPhone, déverrouille-le, et accepte « Faire confiance à cet ordinateur ».
2. En haut d'Xcode, choisis ton iPhone comme destination, puis clique sur **▶**.
3. Au premier lancement, l'iPhone refuse d'ouvrir l'app : va dans Réglages › Général ›
   **VPN et gestion de l'appareil**, touche ton Apple ID, puis **Faire confiance**. Relance l'app.

## 6. Premier lancement

1. ⚙︎ en haut à droite : colle ta **clé Gemini** dans « Mode direct ». Elle est rangée dans le trousseau
   chiffré de l'iPhone, pas dans le code.
2. **Connecter mes lunettes** : l'app Meta AI s'ouvre, autorise Lǎoshī, tu reviens dans l'app.
3. Mets tes lunettes. **Démarrer la caméra des lunettes** : Meta AI demande l'accès à la caméra la première fois.
4. **Qu'est-ce que je vois ?** : le prof regarde par tes lunettes et te répond dans les haut-parleurs des lunettes.
5. **Poser une question** : les lunettes disent « Oui ? », tu demandes « Que veut dire siège en chinois ? ».
   Meta AI demande l'accès au micro la première fois.

## 7. Le mode mains libres

Trois fonctions du SDK de Meta sont encore **expérimentales** et doivent être activées pour ton app :

| Fonction | Ce que tu fais |
|---|---|
| Bouton photo des lunettes | Appuie sur le bouton de la branche : leçon sur ce que tu regardes |
| « Hey Meta, lance Lǎoshī » | Les lunettes disent « Oui ? » et écoutent ta question |
| Micro des lunettes | Ta question est comprise par les lunettes elles-mêmes |

Pour les activer :

1. Crée un compte sur le [Wearables Developer Center](https://wearables.developer.meta.com/).
2. Crée une organisation puis un projet pour ton app, avec le même Bundle Identifier qu'à l'étape 4.
3. Dans le projet, active **Inputs**, **Speech** et **Voice Invocations**. Pour Voice Invocations,
   indique le nom à prononcer : « Lǎoshī » (ou « Laoshi »).

Les intitulés exacts du site peuvent différer un peu, car ces fonctions sont récentes. Tant qu'elles ne sont
pas activées, les boutons de l'app fonctionnent, et la voix du prof sort quand même dans les lunettes.

## En cas de souci

- **Rien ne se passe après « Connecter mes lunettes »** : vérifie le mode développeur dans Meta AI (étape 1)
  et que l'app Meta AI est à jour.
- **« Clé Gemini refusée »** : recopie la clé dans ⚙︎, sans espace avant ni après.
- **Pas de voix chinoise** : iPhone › Réglages › Accessibilité › Contenu énoncé › Voix › **Chinois** :
  télécharge une voix (par exemple « Tingting » ou une voix « Améliorée »).
- **La reconnaissance vocale ne comprend pas le français** : elle suit la langue des lunettes. Vérifie-la dans
  Meta AI.
- **L'app a disparu ou ne s'ouvre plus après une semaine** : c'est la limite des 7 jours du compte gratuit.
  Rebranche l'iPhone et refais l'étape 5.
