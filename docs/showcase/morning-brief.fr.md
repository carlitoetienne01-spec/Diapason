---
title: Le brief du matin
description: Slack, courriels, GitHub et agenda — résumés en cinq points sur ton téléphone avant 7 h
---

# ☕ Le brief du matin — Diapason lit tout pendant la nuit pour que je n'aie pas à le faire

<figure markdown>
  ![Le brief du matin dans Discord](../assets/showcase/morning-brief.png){ .showcase-screenshot loading=lazy }
  <figcaption>Le brief de 7 h qui arrive dans mon Discord privé — cinq points, deux minutes de lecture, écrits par un agent qui a tourné sur mon bureau pendant que je dormais.</figcaption>
</figure>

Chaque matin à 7 h, avant mon premier café, un message apparaît dans mon Discord privé avec cinq points :

- ce qui est sorti au travail pendant la nuit (les versions GitHub et les PR fusionnées)
- les deux courriels sur lesquels j'ai vraiment besoin d'agir (résumés en une ligne)
- tout ce qui s'est dit dans le canal Slack `#general` de mon équipe
- l'agenda du jour, avec les rendez-vous des vingt-quatre prochaines heures
- une chose que j'ai demandé à Diapason de suivre pour moi (« le déploiement de mardi est-il passé proprement ? »)

C'est la première chose que je lis sur mon téléphone, encore au lit. Avant, le brief me prenait vingt-cinq minutes — ouvrir quatre applications, faire défiler, décider de ce qui comptait. Maintenant, c'est deux minutes de lecture et j'ai fini.

## Pourquoi c'est agréable

- **Ça ne me coûte rien par mois.** Ça tourne sur un Mac mini dans mon placard. Le même volume de prompts sur l'API d'OpenAI reviendrait à `~18 $/mois`, d'après les estimations d'économies en local.
- **Rien ne sort de chez moi.** Ma boîte de réception, mes messages privés Slack, mon agenda — Diapason les lit en local et écrit le résumé en local. Le seul appel réseau, c'est le webhook Discord vers mon propre serveur privé.
- **Il apprend mes goûts.** En quelques semaines, Diapason a compris que les PR dont le titre commence par `chore:` ne valent pas d'être remontées, et que je ne veux pas voir les créneaux d'agenda que j'ai bloqués moi-même. Le résumeur tient un `MEMORY.md` qu'il met à jour quand je réagis à un point par 👎.

## Ce qu'il te faut

Un portable ou un mini-PC qui reste allumé la nuit, un moteur d'inférence (Ollama est le choix facile par défaut), des comptes sur les services que tu veux voir résumés (Slack, Gmail, GitHub, Google Agenda) et une destination Discord (ou Slack, ou Telegram, ou courriel) où publier le brief.

## Comment j'ai monté ça

→ **[Tutoriel : opérations personnelles programmées](../tutorials/scheduled-ops.md)** déroule le motif d'agent programmé par cron qui sert ici. La variante « brief du matin », c'est l'agent `orchestrator` + les adaptateurs de canaux + la primitive d'ordonnancement — trois primitives, une recette TOML.

→ **[Guide : le point du matin](../user-guide/morning-digest.md)** est le déroulé ciblé de la recette, si tu ne veux que ce flux-là.

→ **[Guide : les canaux](../user-guide/cli.md)** pour brancher Discord, Slack ou Telegram comme destination.
