# Reverse de brandsearch.co avec REA

Analyse passive du site public https://brandsearch.co avec
[REA](https://github.com/morluto/rea) (Reverse Engineer Anything) : structure de
la page, scripts JS, appels réseau et forme des réponses JSON, routes et
endpoints trouvés dans le bundle, capture d'écran.

On n'analyse que ce qui est servi publiquement, sans contourner la connexion
ni le paywall.

## Lancer

Il faut Node.js ≥ 22.19 et Chromium (ou Chrome).

```bash
./scripts/reverse.sh                 # https://brandsearch.co/ par défaut
./scripts/reverse.sh https://brandsearch.co/pricing
```

Variables : `CHROME` (chemin du navigateur), `CDP_PORT` (9222), `WAIT_MS`
(temps de chargement avant capture, 8000).

## Résultats (`analysis/`)

| Fichier           | Contenu                                                         |
| ----------------- | --------------------------------------------------------------- |
| `inspect.json`    | DOM, accessibilité, scripts, requêtes réseau, formes JSON       |
| `bundle.json`     | Chunks, routes et endpoints candidats, librairies détectées     |
| `screenshot.json` | Capture PNG de la page                                          |
| `scripts/`        | Scripts JS exportés pour l'analyse statique                     |
