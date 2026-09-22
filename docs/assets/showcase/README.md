# Captures d'écran de la Galerie

Ce dossier contient la capture d'écran principale de chaque entrée de la Galerie, dans `docs/showcase/`. La convention est d'un fichier par entrée, nommé d'après le *slug* de l'entrée :

| Entrée | Chemin de la capture |
|---|---|
| `docs/showcase/morning-brief.md` | `morning-brief.png` |
| `docs/showcase/persistent-memory.md` | `persistent-memory.png` |
| `docs/showcase/cost-savings.md` | `cost-savings.png` |
| `docs/showcase/discord-companion.md` | `discord-companion.png` |
| `docs/showcase/coding-assistant.md` | `coding-assistant.png` |

## Les conventions

| | |
|---|---|
| Format | PNG, sRGB, sans canal alpha |
| Dimensions | 1600 × 1000 (4:2.5 — plus large que le 16:9, pour que les captures ne se retrouvent pas encadrées de bandes noires dans la grille de la documentation) |
| Poids | Moins de 400 Ko après `pngquant --quality 70-90 --speed 1` |
| Chargement | Toutes les balises `<img>` et `<figure>` des pages de la Galerie utilisent `loading=lazy` — ces images sont sous la ligne de flottaison de la page galerie |

## Ce qu'il faut masquer

- Les vraies adresses courriel
- Les clés d'API, les jetons OAuth, tout ce qui commence par `sk-`, `ghp_`, `xox`, `eyJ`
- Les numéros de téléphone personnels
- Le visage ou le nom complet de tes interlocuteurs (à moins qu'ils n'aient donné leur accord)
- Les chemins de fichiers qui contiennent le dossier personnel de quelqu'un d'autre

## Ce qu'il faut garder

- Les noms de modèles (« llama3.1:8b », « qwen2.5:14b ») — ils sont informatifs
- Les horodatages — ils prouvent que la capture est récente
- Les montants en dollars sur le tableau de bord des économies — c'est tout l'intérêt
- Les réactions emoji, ton propre prénom, ton propre avatar

## Les PNG de remplacement

Ce dossier est livré sans aucune image dans la première PR. Les pages de la Galerie pointent vers des chemins d'images qui n'existent pas encore — MkDocs affichera un espace réservé d'image cassée, et la légende dit quand même ce qui devrait s'y trouver. Les vraies captures arrivent dans les PR suivantes, au fur et à mesure que les entrées de la Galerie se remplissent avec le montage réel de chaque contributeur.

Si tu proposes la première vraie entrée, dépose ton PNG dans `docs/assets/showcase/<ton-slug>.png`, dans la même PR que celle qui ajoute ta page markdown. Le nom du fichier image doit correspondre au *slug* utilisé dans la balise `<img>` de la page de la Galerie.

## Régénérer les captures en lot

Une amélioration à venir (suivie comme PR #3 dans la feuille de route du niveau Galerie) ajoutera `scripts/showcase/regen_screenshots.py` — une chaîne pilotée par Playwright qui démarre un `diapason serve` de démonstration sur une configuration scellée et capture des captures fraîches pour chaque entrée de la Galerie, à chaque tag de version. En attendant, les captures sont fournies à la main par chaque auteur de la Galerie.
