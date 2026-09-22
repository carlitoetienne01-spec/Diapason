---
title: Compagnon Discord
description: Diapason répond à tes questions dans ton Discord privé pendant que tu dors — il lit tes notes, consulte ton agenda, planifie des rendez-vous
---

# 💬 Compagnon Discord — un assistant personnel qui vit dans mon Discord

<figure markdown>
  ![Diapason répond à un message privé Discord au sujet de l'agenda et des notes de l'utilisateur](../assets/showcase/discord-companion.png){ .showcase-screenshot loading=lazy }
  <figcaption>Je lui ai écrit en privé depuis mon téléphone, à minuit. Il a consulté mon Google Calendar, l'a recoupé avec une note de la semaine dernière, et il a répondu — en tournant sur le Mac mini au fond de mon placard.</figcaption>
</figure>

J'ai un serveur Discord privé, avec deux salons et un seul utilisateur (moi). Diapason y habite. Je peux lui écrire en privé depuis mon téléphone, mon portable ou ma montre — partout où Discord tourne. Quelques exemples de ce que je lui ai demandé cette semaine :

- « Quelle est l'adresse de l'endroit où j'avais cette réunion mardi dernier ? » → Diapason cherche dans mon agenda et mes notes de réunion, répond en 4 secondes.
- « Réponds au message de maman de tout à l'heure : dis-lui que je l'appelle demain à 7 h. » → il rédige une réponse, me demande de confirmer, envoie.
- « Ajoute “l'anniversaire de Sam est le 12 mars” à ma mémoire de longue durée. » → il met à jour `MEMORY.md`, confirme.
- « Résume la dernière heure de conversation dans `#deploys-prod`. » → il lit le salon Slack via MCP, résume.

Avant, je me servais de l'assistant vocal de mon téléphone pour ça. Les deux différences qui comptent : **Diapason répond en trois phrases, pas en une**, et **il a vraiment mon contexte** — mes notes, mon agenda, mes projets, mon historique.

## Pourquoi c'est agréable

- **La latence est celle d'une conversation avec quelqu'un.** L'inférence locale sur une carte graphique modeste est 5 à 10 fois plus rapide qu'un aller-retour vers une API distante. De la question à la réponse : 3 secondes.
- **L'interface Discord est multi-appareils sans rien faire.** Le même fil de conversation sur mon téléphone, mon portable, ma montre — aucune app particulière à installer.
- **C'est déjà privé.** Un serveur Discord que je tiens moi-même, qui parle à un modèle sur une machine qui m'appartient. La trace des données passe par deux points, et les deux sont à moi.

## Comment je l'ai mis en place

→ **[Tutoriel : Centre de messagerie](../tutorials/messaging-hub.md)** est ce qui s'en rapproche le plus — même schéma adaptateur de canal + agent orchestrateur, avec Discord à la place de Slack.

→ **[La documentation des canaux](../user-guide/cli.md)** détaille la mise en place de Discord, Slack, Telegram et WhatsApp. Pour Discord, c'est deux variables d'environnement et un jeton de bot.

→ **[Le guide d'intégration MCP](../user-guide/cli.md)** si tu veux que Diapason aille chercher dans Notion, Linear, Gmail, etc.
