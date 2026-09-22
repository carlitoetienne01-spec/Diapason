---
title: Tutoriels
description: Des guides pas à pas pour construire avec Diapason
---

# Tutoriels

Des guides pratiques qui construisent de vraies applications avec Diapason. Chaque tutoriel fournit un script autonome que tu peux lancer tout de suite, une recette TOML pour la configuration, et une explication détaillée des notions en jeu.

!!! note "Avant de commencer"
    Tous les tutoriels supposent que Diapason est installé et qu'un moteur d'inférence tourne. Si tu n'as pas encore fait l'installation, commence par le [guide de démarrage rapide](../getting-started/quickstart.md).

<div class="grid cards" markdown>

- :material-magnify:{ .lg .middle } **Assistant de recherche approfondie**

    ---

    De la recherche multi-sources avec un agent orchestrateur doté de mémoire. Il fouille le web, garde ses trouvailles d'un tour à l'autre, recoupe ses sources et produit un rapport sourcé.

    [:octicons-arrow-right-24: Commencer](deep-research.md)

- :material-clock-outline:{ .lg .middle } **Opérations personnelles programmées**

    ---

    Des agents autonomes sur des horaires cron pour les tâches personnelles qui reviennent — revue de presse du matin, relecture de code hebdomadaire, vérification des horaires de la salle de sport.

    [:octicons-arrow-right-24: Commencer](scheduled-ops.md)

- :material-message-outline:{ .lg .middle } **Centre de messagerie**

    ---

    Un assistant de boîte de réception qui trie les messages par priorité, rédige des réponses qui tiennent compte du contexte et produit un résumé de fin de journée, sur Slack, WhatsApp et les autres canaux.

    [:octicons-arrow-right-24: Commencer](messaging-hub.md)

- :material-code-braces:{ .lg .middle } **Compagnon de code**

    ---

    Relecture de code, débogage et génération de tests avec un agent ReAct qui lit les fichiers source, lance des commandes et raisonne étape par étape avant de produire une sortie structurée.

    [:octicons-arrow-right-24: Commencer](code-companion.md)

- :material-puzzle:{ .lg .middle } **Le flux de travail des compétences**

    ---

    Installer des compétences depuis Hermes Agent, s'en servir avec un agent local, découvrir des motifs dans les traces, optimiser avec DSPy et mesurer le gain — tout le cycle de vie d'une compétence.

    [:octicons-arrow-right-24: Commencer](skills-workflow.md)

</div>

## Ce que tu vas apprendre

Chaque tutoriel met en scène une combinaison différente des primitives de Diapason :

| Tutoriel | Agent | Primitives principales |
|---|---|---|
| Recherche approfondie | `orchestrator` | Moteur, Agents, Outils (web + mémoire), Recettes |
| Opérations programmées | `orchestrator`, `native_react` | Agents, Outils, Programmateur |
| Centre de messagerie | `orchestrator` | Agents, Outils (mémoire), Canaux |
| Compagnon de code | `native_react` | Agents, Outils (git + fichiers + shell) |

## Temps estimé

Compte 15 à 30 minutes par tutoriel de bout en bout, installation et exécution des scripts comprises. Les sections sur la configuration TOML et les conseils de personnalisation sont à lire plus tard, quand tu adapteras le motif à ton propre usage.
