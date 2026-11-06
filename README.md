# The Follow-Through

*Europe decided. Did it deliver?* Un site d'actualité en anglais qui suit les décisions de l'UE : ce qui a été décidé, et si ça avance vraiment.

## Les pages
- **La une** (`#/`) : l'article principal, la « Scorecard » des objectifs, les dernières décisions (« Just in »), les grands titres et un bloc par rubrique.
- **Une rubrique** (`#/section/climate`, etc.) : toutes les décisions des 2 dernières années, de la plus récente à la plus ancienne, avec un filtre par type.
- **Une décision** (`#/decision/<numéro CELEX>`) : le score de progression, puis les boutons *Progress chart*, *Decision map*, *Timeline* et *Official text*.

## Les fichiers
| Fichier | Rôle |
|---|---|
| `index.html`, `style.css`, `app.js` | Le site |
| `config.json` | Le nom, les rubriques (et leurs mots-clés) et les objectifs suivis |
| `update.py` | Récupère les décisions (EUR-Lex) et les chiffres (Eurostat), puis écrit `data.json` |
| `photos.py` | Choisit les photos libres de droits sur Wikimedia Commons et écrit `photos.json` |
| `.github/workflows/update.yml` | Lance `update.py` chaque matin, une fois le site sur GitHub |
| `prototype-v1/` | L'ancien prototype en français, archivé |

## Mettre à jour à la main
```
python3 update.py
```

## Voir le site en local
```
python3 -m http.server 8765
```
puis ouvrir http://localhost:8765

## Titres accrocheurs et résumés par l'IA (facultatif)
Sans clé API, les titres sont générés automatiquement à partir du titre officiel. Avec une clé API Claude, chaque nouvelle décision reçoit un vrai titre de journal, un résumé en anglais simple, et un classement plus fiable dans sa rubrique :
```
ANTHROPIC_API_KEY=sk-... python3 update.py
```
Le résultat est mis en cache dans `ai_cache.json` : chaque décision n'est payée qu'une seule fois.

## Comment le score est calculé
- **Goal progress** : quand la décision sert un objectif chiffré (pour l'instant : −55 % d'émissions et 42,5 % de renouvelables en 2030), on affiche le chemin parcouru vers cet objectif, d'après Eurostat.
- **Rollout** : sinon, on affiche la part des étapes légales déjà franchies (entrée en vigueur, échéances).
