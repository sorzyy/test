# Reverse de brandsearch.co

Analyse faite le 13/10/2026 avec [REA](https://github.com/morluto/rea) 6.4.0
(`inspect-web-page`, `analyze-web-bundle`, `capture-web-screenshot`,
`export-web-scripts`) sur trois pages publiques : `/`, `/pricing` et `/mcp`.
On n'a regardé que ce que le site sert sans compte. Tout ce qui concerne le
back-end (comment les données sont collectées) vient de ce que Brandsearch
en dit publiquement, pas d'une observation directe.

Captures d'écran : `analysis/*/screenshot.png`. Analyse du bundle :
`analysis/*/bundle.json`.

## 1. Ce que c'est

Un outil de veille e-commerce : une base de **14M+ boutiques** reliées à
**400M+ pubs et posts** (120M+ Meta, 100M+ TikTok, 90M+ Instagram, plus le
TikTok organique). Pas de Google Ads. Ce qui le distingue d'un simple « ad spy » :
chaque pub est rattachée à la boutique qui la paie, avec son CA estimé, son
trafic, ses produits, ses landing pages et ses emails.

Société : SPECTRE PRYSM S.à r.l.-S (Wemperhardt, Luxembourg).

## 2. Les modules (app.brandsearch.co)

| Module          | Route app                  | Rôle                                                                 |
| --------------- | -------------------------- | -------------------------------------------------------------------- |
| Brand Library   | `/brand-library`           | Filtrer les marques : CA, dépense pub, marchés, stack technique, presets (« Biggest EU spenders ») |
| Fiche marque    | `/search`                  | CA/jour estimé, pubs Meta actives/total, top landing pages, emails, bestsellers, followers |
| Discovery       | `/discovery`               | Recherche de pubs (Meta, TikTok, Instagram, Emails) avec filtres marque + « AI profile » (type de hook, angle…) |
| Fiche pub       | –                          | Onglets Overview / AI analysis / Transcription / Adspend ; « Winning signals » : Ad Rank, jours actifs, duplicats, dépense UE/UK |
| Spectre         | `/spectre`                 | Suivi de concurrents : flux des nouvelles pubs et landing pages, alertes |
| Swipe Files     | –                          | Dossiers partagés (pubs, marques, LP) ; ajout depuis Instagram en envoyant la pub en DM à `brandsearch_co` |
| Trends          | –                          | Demande par niche |
| Ad Generator / Supergen | –                  | Recrée une pub gagnante (hook, claim, offer, proof) autour de ton produit |
| API REST + MCP  | –                          | 46 à 60+ outils, webhooks, clés API |

Outils MCP visibles sur `/mcp` : `discover_brands`, `discover_meta_ads`,
`discover_tiktok_ads`, `get_brand_summary`, `get_brand_ads_aggregates`,
`get_products`, `get_ad_by_url`, `analyze_ad`, `add_to_folder`,
`get_system_freshness` (catégories : Discover, Brands, Ads, Keep, Account).

## 3. Comment les chiffres sont calculés (d'après leur FAQ)

- **CA estimé** = trafic mensuel × taux de conversion de **1 % à 5 %** × panier
  → une fourchette (plancher/plafond), pas un chiffre exact.
- **Dépense pub UE/UK** : le seul chiffre « dur ». Il vient de la Meta Ad
  Library, qui doit publier la portée et les données des pubs diffusées
  dans l'UE (DSA). Ce n'est pas une estimation de Brandsearch.
- **Ad Rank** : une pub est classée **par rapport aux autres pubs de la même
  marque** (top 1 % = meilleure créa de la marque), pas contre tout l'index.
  Indices visibles : durée de diffusion, nombre de duplicats/versions, dépense UE.
- **Analyse IA** : chaque pub est lue par un modèle → étape du funnel, niveau
  de conscience, désir, type de hook, angle, audience.
- **Spectre** : instantané quotidien par marque (CA/jour, pubs actives,
  tendance 7 jours, nouvelles créas/LP) + diff → alertes.

## 4. Stack technique observée

- **Front** : Next.js (App Router, React Server Components : requêtes
  `?_rsc=`), bundlé avec **Turbopack**, hébergé sur **Vercel** (`_next/static`,
  `dpl_…`, `_vercel/insights`). Animations : Motion (`motion.dev`).
- **Deux domaines** : site marketing `brandsearch.co` (SEO + ~30 outils
  gratuits : calculateurs, générateurs de faux commentaires, pixel detector,
  « what is my CMS »…) et app `app.brandsearch.co` (login, dashboard).
- **Médias** : `media.brandsearch.co`, images en WebP.
- **Analytics / tracking** : Vercel Analytics, Google Tag Manager + gtag
  (`_gcl_ls`), Plausible auto-hébergé (`plausible.brandsearch.co`),
  DataFast (`datafa.st`), pixels TikTok (`tt_*`) et Reddit (`_rdt_cfg`).
- **Affiliation** : Tolt (`cdn.tolt.io`), suivi `ref` et `utm_source` en
  localStorage (`lastExternalReferrer`).
- **Paiement** : Stripe (référencé dans le bundle).
- **Divers** : Calendly (démo), Trustpilot, taux de change via
  `open.er-api.com` (prix affichés dans ta devise), extension Chrome.
- **Aucun appel API métier sur les pages publiques** : tout est rendu côté
  serveur. Les données de l'app sont derrière la connexion, donc hors du
  périmètre de cette analyse.

## 5. Modèle économique

| Plan       | Mensuel | Annuel  | Lookups     | Marques Spectre | Sièges | Crédits IA            | Appels API/MCP |
| ---------- | ------- | ------- | ----------- | --------------- | ------ | --------------------- | -------------- |
| Starter    | 63 $    | 568 $   | 15 000/mois | 5               | 1      | 250/mois (≈ 3 $)      | 5 000/mois     |
| Outscaler  | 79 $    | 712 $   | illimité    | 50              | 2      | 1 400/mois (≈ 20 $)   | 10 000/mois    |
| Agency     | 149 $   | 1 432 $ | illimité    | 100             | 5      | 2 800/mois (≈ 40 $)   | 10 000/mois    |

Les plans sont codés en dur dans le bundle JS (`id: starter / unlimited /
enterprise`, « illimité » = 200 000 lookups). Les prix sont en USD. Le
navigateur devine le pays à partir du fuseau horaire, récupère le taux du jour
sur `open.er-api.com` et affiche le prix en € ou en CHF **majoré de 4 %**.

Swipe Files illimités partout ; recharge IA : 29 $ les 2 000
crédits. Argument de vente : « 459 $ inclus », soit le prix du plan Agency de
Foreplay, qu'ils prétendent remplacer (avec Atria). Tous les plans ouvrent tout l'index : seuls les quotas changent.
Acquisition : SEO (pages marques, niches, marchés, apps Shopify, alternatives),
outils gratuits, affiliation, Discord.

## 6. Pour construire un équivalent

1. **Index de boutiques** : crawler les domaines Shopify (`/products.json`,
   `/collections/*/products.json` sont publics), détecter la stack via les
   scripts/pixels de la page.
2. **Pubs** : Meta Ad Library API (officielle, avec données UE détaillées) et
   TikTok Commercial Content API ; rattacher chaque pub à son domaine via
   l'URL de destination.
3. **Trafic** : fournisseur tiers (Similarweb, etc.), puis CA = trafic ×
   1–5 % × panier moyen tiré du catalogue.
4. **Analyse IA** : un appel LLM par pub (hook, angle, awareness, desire),
   stocké en champs filtrables.
5. **Ad Rank** : percentile de la pub dans les pubs de sa marque selon
   la durée de diffusion, les duplicats et la dépense UE.
6. **Suivi** : instantané quotidien des marques suivies + diff → alertes.
7. **Distribution** : API REST + serveur MCP (c'est un argument de vente fort).

## Limites

- On n'a vu que le site public : l'app et l'API demandent un compte.
- Pas de source maps publiées : le code JS est minifié.
- Le fonctionnement interne (crawlers, fournisseur de trafic) n'est pas
  observable de l'extérieur. La section 6 est une proposition, pas une
  observation.
