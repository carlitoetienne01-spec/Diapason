---
title: Un relecteur de code hors ligne
description: Relis une pull request en plein vol transatlantique, sans la moindre connexion
---

# 🛠️ Un relecteur de code hors ligne — la revue de code en avion

<figure markdown>
  ![Diapason relit un diff sans aucune connexion internet](../assets/showcase/coding-assistant.png){ .showcase-screenshot loading=lazy }
  <figcaption>Le mode avion dans la barre de menus. Diapason lit un `git diff`, les fichiers autour, et rend une revue de code avec le Wi-Fi d'une salle d'embarquement (c'est-à-dire aucun).</figcaption>
</figure>

Ce mois-ci, j'étais dans un vol SFO–FRA : onze heures, pas de Wi-Fi utilisable. J'avais la pull request d'un collègue ouverte dans VS Code. J'ai demandé à Diapason de la relire. Il a lu le diff, lu les trois fichiers que le diff touchait, lu le `CLAUDE.md` du projet pour en connaître les conventions, et rendu une revue en cinq commentaires — dont deux qui attrapaient de vrais bugs.

La revue a pris une quarantaine de secondes sur la carte graphique intégrée du portable. Aucun appel d'API. Aucune erreur « tu es hors ligne ». À l'atterrissage, j'avais déposé les commentaires sur GitHub et la PR partait en fusion.

Le même montage se charge aussi :

- **De la revue de code** — le diff, les fichiers de contexte, les conventions, et des commentaires structurés.
- **Du débogage** — colle une trace d'appels : Diapason lit la pile, ouvre les fichiers concernés, propose des correctifs.
- **De la génération de tests** — pointe une fonction, récupère un fichier `pytest` avec les cas limites.
- **De la documentation** — des docstrings qui collent vraiment au code, parce que Diapason a le fichier sous les yeux.

## Pourquoi c'est agréable

- **Ça marche en avion.** Ou en train, ou dans un hôtel au Wi-Fi poussif, ou sur ton canapé le jour où ton fournisseur d'accès fait des siennes. La même vitesse à chaque fois.
- **Il voit ton dépôt, pas un extrait assaini.** Les assistants de code dans le nuage te font téléverser une fenêtre de contexte. Celui d'ici lit simplement `git status` et les fichiers sur lesquels tu travailles.
- **Plus de question du genre « on s'est entraînés sur ton code ».** Ton code ne quitte jamais ton portable. Point.

## Comment j'ai mis ça en place

→ **[Tutoriel : Compagnon de code](../tutorials/code-companion.md)** déroule de bout en bout la pile utilisée ici : un agent ReAct, plus les outils git, fichiers et shell.

→ **[Guide de l'utilisateur : l'assistant de code](../user-guide/code-assistant.md)** est la recette ciblée, celle de la revue de code au quotidien.

→ **[Serveur compatible OpenAI](../getting-started/quickstart.md)** — pointe l'intégration IA que ton éditeur a déjà (Cursor, Continue, Cody, Aider) vers `localhost:8000`. La plupart ne voient même pas qu'elles ne parlent pas à OpenAI.
