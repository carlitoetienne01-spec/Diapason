---
title: Une mémoire qui ne repart pas de zéro
description: Dis quelque chose une fois à Diapason. Il s'en souvient — trois mois plus tard, dans toutes les conversations
---

# 🧠 Une mémoire qui ne repart pas de zéro — Diapason me connaît vraiment

<figure markdown>
  ![Diapason se souvient d'une préférence trois mois plus tard](../assets/showcase/persistent-memory.png){ .showcase-screenshot loading=lazy }
  <figcaption>Trois mois après que j'ai mentionné l'allergie au détour d'une phrase, Diapason la remet sur la table — sans qu'on lui demande — pendant qu'il m'aide à choisir un restaurant pour un dîner d'anniversaire.</figcaption>
</figure>

J'ai dit une fois à Diapason, dans une phrase jetée en avril, que je suis allergique aux fruits de mer. En juillet, quand je lui ai demandé de m'aider à choisir un restaurant pour l'anniversaire de ma compagne, il a lancé de lui-même « tu voudras filtrer sur les cartes qui proposent autre chose que des fruits de mer » — sans rappel, dans une conversation totalement différente, sur un tout autre sujet.

Ce n'est pas de la magie. L'astuce, c'est que Diapason écrit dans trois simples fichiers markdown de mon dossier personnel chaque fois qu'il apprend quelque chose qui mérite d'être retenu :

- `SOUL.md` — comment je veux qu'il se comporte (ton, longueur, ce sur quoi il doit me contredire)
- `MEMORY.md` — des faits sur moi, mes projets, mes préférences
- `USER.md` — qui je suis : mon rôle, mon équipe, mon contexte

Chaque nouvelle conversation commence par la lecture de ces trois fichiers. Je peux les ouvrir dans n'importe quel éditeur de texte. Je peux supprimer une ligne, et le souvenir disparaît. Le tout fait `~6 KB` de markdown. Pas de base vectorielle, pas de cache d'embeddings, pas de « couche de personnalisation » opaque.

## Pourquoi c'est agréable

- **C'est vérifiable.** Je peux lire ce que Diapason « sait » de moi en 30 secondes. La plupart des produits d'IA personnelle en sont littéralement incapables.
- **C'est transportable.** Je garde mes trois fichiers dans iCloud Drive. Quand j'installe Diapason sur une nouvelle machine, ma mémoire me suit — sans tout reprendre depuis le début.
- **Ça s'accumule.** Au bout de deux semaines, Diapason a cessé de me redemander quel est mon style de code. Au bout de six semaines, il a cessé de redemander qui est dans mon équipe. Les conversations raccourcissent parce que le contexte est déjà là.
- **Ça ne peut pas dériver.** Une recherche vectorielle peut remonter avec aplomb le mauvais « souvenir » sans que tu n'en saches jamais rien. Du markdown ordinaire que je peux lire ne peut pas mentir sur ce qu'il contient.

## Comment j'ai mis ça en place

→ **[Guide de l'utilisateur : les agents](../user-guide/agents.md)** explique le motif de l'agent persistant, et notamment comment `SOUL.md` / `MEMORY.md` / `USER.md` sont chargés au début d'une conversation.

→ **[Tutoriel : assistant de recherche approfondie](../tutorials/deep-research.md)** repose sur la même primitive de mémoire persistante — un bon endroit pour la voir à l'œuvre, avec du code.
