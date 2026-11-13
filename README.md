# The Follow-Through

*Europe decided. Did it deliver?* Un site d'actualité en anglais qui suit les décisions de l'UE : ce qui a été décidé, et si ça avance vraiment.

## Les pages
- **La une** (`#/`) : l'article principal, la « Scorecard » des objectifs, les dernières décisions (« Just in »), les grands titres et un bloc par rubrique.
- **Une rubrique** (`#/section/climate`, etc.) : toutes les décisions des 2 dernières années, de la plus récente à la plus ancienne, avec un filtre par type.
- **Le tableau des objectifs** (`#/goals`) : les 10 objectifs chiffrés de l'UE pour 2030, et s'ils sont en bonne voie.
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
- **Goal progress** : quand la décision sert un objectif chiffré (10 objectifs pour 2030 : émissions, renouvelables, consommation d'énergie, recyclage, emploi, pauvreté, sécurité routière, spécialistes du numérique, compétences numériques, agriculture bio), on affiche le chemin parcouru vers cet objectif, d'après Eurostat.
- **Rollout** : sinon, on affiche la part des étapes légales déjà franchies (entrée en vigueur, échéances).

## Ajouter un objectif chiffré
Tout se passe dans `config.json`, rubrique `targets`. Chaque objectif indique : sa rubrique, son titre, le texte qui l'a fixé (`basis`, et `law` si c'est une loi), le jeu de données Eurostat et ses filtres (`data`), l'année de départ (`start_year`), la cible (`goal`, ou `goal_change` en %, ou `goal_delta` en valeur), l'unité, et les mots-clés qui relient les décisions à cet objectif.

## Les mises à jour de politique étrangère
Les décisions du Conseil qui modifient une décision existante (listes de sanctions, missions, aides militaires) apparaissent avec le type « Foreign policy update ». Elles ne font jamais la une et sont limitées à 2 dans « Just in », pour que les nouvelles décisions restent visibles.

## Les photos des articles
Chaque décision reçoit une photo qui correspond à son sujet (guerre en Ukraine, Iran, quotas de pêche, douanes, inondations…). La liste des sujets et des mots-clés qui les reconnaissent est dans `config.json`, rubrique `photo_topics`. Les photos choisies pour chaque sujet (toutes libres de droits, vérifiées une par une, sans images violentes) sont dans `photos.json`, rubrique `topics`. Une nouvelle décision est rangée automatiquement dans le bon sujet ; si aucun sujet ne correspond, elle prend une photo générale de sa rubrique.

## Google et le partage des liens
Google ne lit pas les adresses en `#/…` du site interactif. `pages.py` (lancé à la fin de `update.py`) fabrique donc chaque matin des pages simples qu'il peut lire :
- `decision/<numéro CELEX>.html` : une page par décision, avec titre, photo, score, dates, titre officiel et décisions liées ; un bouton renvoie vers la version interactive ;
- `section/<rubrique>.html` et `goals.html` ;
- `sitemap.xml` (la liste de toutes les pages, à donner à Google Search Console) et `robots.txt`.
Ces pages ont aussi leur image et leur titre d'aperçu : un lien partagé sur WhatsApp ou LinkedIn s'affiche avec la photo de l'article. Le bouton « Share ↗ » de chaque article partage cette page.

## La une
- **La bannière** : la photo de l'hémicycle du jour passe derrière le titre et le menu, posés sur des bandeaux papier. Le sceau TFT est en haut à gauche (`seal.svg`).
- **L'article de une** change chaque jour : il tourne entre Security & Defence, Migration & Rights et Trade & World, parmi les décisions récentes les plus importantes. Son titre et son résumé « de journal » sont écrits par des modèles dans `update.py` (`LEAD_FIXED` pour les lois connues, et des modèles pour l'aide militaire, les sanctions, les missions, les envoyés spéciaux et les prêts). Pour ajouter un titre, ajoute une ligne à `LEAD_FIXED`.

## Légal et vie privée
- `about.html` : présentation, méthode, sources, signalement des erreurs (via les « issues » GitHub), vie privée, licence (textes sous CC BY-NC 4.0) et mentions légales (éditeur anonyme, hébergeur GitHub). Elle est fabriquée par `pages.py`.
- Les polices sont servies par le site lui-même (`fonts.css` et les fichiers `font-*.woff2`) : les visiteurs ne se connectent plus à Google.

## Recherche et flux RSS
- **Recherche** (`#/search`) : dans le menu. Elle cherche dans les titres, les titres officiels, les références (par ex. `2026/2332`), les rubriques et les sujets, sans tenir compte des accents. L'adresse de la recherche peut être partagée (par ex. `#/search/iran`).
- **Flux RSS** (`feed.xml`) : les 60 dernières décisions (sans les mises à jour de routine), refait chaque matin par `pages.py`. Lien en bas de page.
