---
title: Contribuer une entrée à la Galerie
description: Comment ajouter ton montage à la Galerie de Diapason
---

# Contribuer une entrée à la Galerie

La Galerie existe pour une seule raison : aider un lecteur perdu, curieux et *non technique* à décider si Diapason mérite son week-end. Ce but commande tous les choix éditoriaux de cette page.

## Le format

```markdown
---
title: <Ton titre — court, avec une majuscule>
description: <Une phrase. L'accroche qu'un inconnu voit dans les résultats de recherche.>
---

# <emoji> <Une phrase d'accroche — ce que ça fait POUR toi, en français simple>

<figure markdown>
  ![<texte alternatif>](../assets/showcase/<ton-image>.png){ .showcase-screenshot loading=lazy }
  <figcaption>Une légende d'une phrase, qui ajoute le contexte que l'image ne peut pas montrer toute seule.</figcaption>
</figure>

<2 ou 3 paragraphes courts de contexte : quand est-ce que tu t'en sers, ce qui a
changé pour toi, l'effet que ça fait à l'usage. Concret > abstrait. « Je le lis
sur mon téléphone avant le café » > « améliore la productivité matinale ».

Une liste à puces de deux ou trois RÉSULTATS CONCRETS marche bien — ton agenda,
ta boîte de réception, ton code. Des verbes précis et des noms propres.>

## Pourquoi c'est agréable

- **<un bénéfice en une ligne>.** <une ou deux phrases de preuve>
- **<un bénéfice en une ligne>.** <une ou deux phrases de preuve>
- **<un bénéfice en une ligne>.** <une ou deux phrases de preuve>

## Comment je l'ai mis en place

→ **[Tutoriel : <nom>](../tutorials/<fichier>.md)** est ce qui s'en rapproche le plus.

→ **[Recette : <nom>](https://github.com/carlitoetienne01-spec/Diapason/tree/main/src/diapason/recipes/data)** si tu veux la configuration exacte.

→ **[<un document lié de plus>](../<chemin>.md)** si le lecteur veut aller plus loin.
```

## Les conventions éditoriales

Ce sont des garde-fous, pas des règles. Enfreins-les si tu as une raison.

### Commence par le résultat, pas par la technique

❌ « Routage multicanal avec mémoire adossée à MCP et agent orchestrateur. »<br>
✅ « Diapason répond à mes messages Discord pendant que je dors. »

Le lecteur ne sait pas encore ce qu'est un « agent orchestrateur ». Il sait ce qu'est un message Discord.

### Montre une seule capture. Fais-en le titre.

Une capture unique, grande et *intéressante*, vaut mieux que cinq petites. Recadre-la sur le résultat, pas sur l'habillage de l'interface. Si une image peut le dire, n'écris pas le paragraphe.

**Le cahier des charges de la capture :**

- PNG 1600 × 1000, sRGB, sans canal alpha
- Chemin du fichier : `docs/assets/showcase/<ton-slug>.png`
- À masquer : les vraies adresses de courriel, les clés d'API, les numéros de téléphone personnels, les visages et les noms complets de tes interlocuteurs (sauf s'ils ont donné leur accord)
- À garder : les noms de modèles, les horodatages, les montants, les réactions emoji, ton propre prénom

### Précis plutôt qu'impressionnant

❌ « Fait gagner un temps considérable chaque matin. »<br>
✅ « Mon rattrapage du matin est passé de 25 minutes à 2. »

Les nombres, les durées, les montants et les outils nommés inspirent confiance. Les adjectifs, non.

### Trois paragraphes, c'est bien assez

Le lecteur qui en veut plus clique sur le lien « Comment je l'ai mis en place → » en bas de page. Les pages de la Galerie sont un entonnoir vers la documentation, pas un substitut. Si tu te retrouves à expliquer une configuration dans ton entrée, cette matière appartient au tutoriel lié.

### « Pourquoi c'est agréable » parle de l'expérience, pas de l'architecture

Les puces sous **Pourquoi c'est agréable** doivent répondre à « qu'est-ce qui change *pour toi* ? » — pas à « qu'est-ce qui change dans le fonctionnement du cadre ? ». Garde le discours d'architecture pour les documents liés.

❌ « Utilise SQLite en local pour l'état, en mode WAL pour les lectures concurrentes. »<br>
✅ « Je peux lire mon propre fichier de mémoire dans un éditeur de texte. Je peux en supprimer une ligne, et le souvenir a disparu. »

### Toute entrée doit finir par au moins un lien « Comment je l'ai mis en place → »

S'il n'existe pas encore de tutoriel pertinent, pointe vers le [guide d'utilisation](../user-guide/cli.md) le plus proche et ouvre un ticket disant que le tutoriel manque. On l'écrira.

## Proposer ton entrée

1. **Duplique** le dépôt (fork) et crée une branche : `docs/showcase-<ton-slug>`.
2. **Ajoute** ton fichier markdown dans `docs/showcase/<ton-slug>.md` et ta capture dans `docs/assets/showcase/<ton-slug>.png`.
3. **Ajoute une tuile** à la grille de `docs/showcase/index.md` (sur le modèle des tuiles existantes — emoji + titre + résumé d'une phrase + `[:octicons-arrow-right-24: See it](<ton-slug>.md)`).
4. **Ouvre une pull request** intitulée `docs(showcase): <ton titre>`. Mentionne un mainteneur si tu veux un retour éditorial avant la fusion.

## Où ça va une fois fusionné

Hannah et l'équipe documentation publient les entrées fusionnées dans **`#config-showcase`**, sur [le Discord de Diapason](https://discord.gg/diapason). Tu seras mentionné dans le message — tu n'as pas à le faire toi-même.

## Questions, brouillons, idées à moitié faites

Dépose-les dans **`#config-showcase`** sur Discord *avant* d'ouvrir une pull request. Le retour éditorial va plus vite en discussion qu'en revue de pull request, et tu t'épargneras un tour de corrections.
