---
title: Déploiement
description: Déployer Diapason en production
---

# Déploiement

Diapason se déploie de plusieurs façons, selon l'environnement et l'échelle.

## Docker

La façon recommandée de déployer Diapason en production. Construction
multi-étapes, avec des variantes processeur et carte graphique (NVIDIA CUDA,
AMD ROCm).

[:octicons-arrow-right-24: Déploiement Docker](docker.md)

## systemd (Linux)

Faire tourner Diapason comme service système géré sur un serveur Linux.

[:octicons-arrow-right-24: Mise en place de systemd](systemd.md)

## launchd (macOS)

Déclarer Diapason comme agent de lancement sur macOS.

[:octicons-arrow-right-24: Mise en place de launchd](launchd.md)

## Le serveur d'API

Faire tourner Diapason comme serveur HTTP compatible OpenAI, avec
`diapason serve`.

[:octicons-arrow-right-24: Guide du serveur d'API](api-server.md)
