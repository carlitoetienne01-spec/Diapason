---
title: Le flux de travail des compétences
description: Tutoriel de bout en bout — installer des compétences, s'en servir avec un agent, découvrir des motifs dans les traces et optimiser avec DSPy
---

# Tutoriel : le flux de travail des compétences

Ce tutoriel parcourt tout le cycle de vie d'une compétence : l'installer depuis une source publique, s'en servir avec un agent local, découvrir des motifs dans l'historique des traces, et optimiser les descriptions de compétences avec DSPy. À la fin, tu auras une installation de compétences qui marche et qui s'améliore avec le temps.

!!! note "Avant de commencer"
    Ce tutoriel suppose que Diapason est installé, qu'Ollama tourne et qu'un modèle est disponible (`qwen3.5:9b`, par exemple). Si tu n'as pas encore fait l'installation, commence par le [guide de démarrage rapide](../getting-started/quickstart.md).

## Étape 1 : installer des compétences depuis Hermes Agent

Diapason sait importer des compétences depuis la bibliothèque [Hermes Agent](https://github.com/NousResearch/hermes-agent), maintenue par NousResearch. Installons-en quelques-unes d'utiles.

```bash
# Installer des compétences une par une
diapason skill install hermes:arxiv
diapason skill install hermes:github-pr-workflow

# Ou installer toute une catégorie d'un coup
diapason skill sync hermes --category research
```

La première installation clone le dépôt Hermes dans `~/.diapason/skill-cache/hermes/` (une seule fois, environ 5 s). Les suivantes réutilisent le cache.

Vérifie ce qui est installé :

```bash
diapason skill list
```

Tu devrais voir un tableau avec, pour chaque compétence, son nom, sa description, sa version et ses étiquettes.

## Étape 2 : inspecter une compétence installée

Regardons ce que contient la compétence `arxiv` :

```bash
diapason skill info arxiv
```

S'affichent alors les métadonnées de la compétence — auteur, description, étiquettes, capacités, présence d'étapes structurées ou d'instructions markdown, et ses drapeaux d'invocation.

Tu peux aussi regarder le `SKILL.md` brut :

```bash
cat ~/.diapason/skills/hermes/arxiv/SKILL.md | head -40
```

Le fichier `.source` garde la provenance :

```bash
cat ~/.diapason/skills/hermes/arxiv/.source
```

On y lit la source (`hermes:arxiv`), le commit git dont elle a été importée, les noms d'outils qui ont été traduits (`Edit→file_edit`, par exemple) et la date d'installation.

## Étape 3 : se servir des compétences avec un agent

Posons maintenant à l'agent une question qui devrait déclencher l'usage d'une compétence :

```bash
diapason ask "Sers-toi de la compétence code-explainer pour expliquer ce code Python : for i in range(5): print(i*2)" \
  --engine ollama --model qwen3.5:9b
```

L'agent va :
1. Voir le catalogue de compétences dans son prompt système
2. Décider d'invoquer `skill_code-explainer`
3. Recevoir les instructions markdown de la compétence
4. Suivre le motif en cinq étapes pour expliquer le code

Essaie aussi une compétence à pipeline :

```bash
diapason ask "Sers-toi de la compétence math-solver pour calculer 17 * 23" \
  --engine ollama --model qwen3.5:9b
```

Cette fois, l'agent invoque `skill_math-solver`, qui exécute un pipeline déterministe (il appelle l'outil `calculator` en interne) et rend directement le résultat calculé.

## Étape 4 : créer ta propre compétence

Crée un dossier pour une nouvelle compétence :

```bash
mkdir -p ~/.diapason/skills/my-reviewer
```

Écris un `SKILL.md` :

```bash
cat > ~/.diapason/skills/my-reviewer/SKILL.md << 'EOF'
---
name: my-reviewer
description: Relit des changements de code, la sécurité d'abord
license: MIT
metadata:
  diapason:
    version: "0.1.0"
    author: me
    tags: [coding, review, security]
---

Quand on te demande de relire du code, procède ainsi :

1. **Balayage de sécurité d'abord** — cherche les failles d'injection, les secrets écrits en dur, les désérialisations dangereuses
2. **Correction** — vérifie la logique, les cas limites, la gestion des erreurs
3. **Style** — nommage, structure, cohérence avec le code alentour
4. **Résumé** — un paragraphe avec le verdict : approuver, demander des changements, ou bloquer

Commence toujours par la sécurité. Si tu trouves un problème de sécurité, signale-le comme BLOQUANT, quelles que soient les autres remarques.
EOF
```

Vérifie qu'elle est bien découverte :

```bash
diapason skill list
```

Tu devrais voir `my-reviewer` dans le tableau. Essaie-la :

```bash
diapason ask "Sers-toi de la compétence my-reviewer pour relire cette fonction : def login(user, pwd): return db.query(f'SELECT * FROM users WHERE name={user} AND pass={pwd}')" \
  --engine ollama --model qwen3.5:9b
```

L'agent devrait suivre l'approche « sécurité d'abord » et signaler la faille d'injection SQL.

## Étape 5 : produire des traces

Pour que la boucle d'apprentissage fonctionne, il faut des traces. Lance plusieurs requêtes qui se servent des compétences :

```bash
# Produire quelques traces
diapason ask "Sers-toi de math-solver pour calculer 100 / 7"
diapason ask "Sers-toi de code-explainer pour expliquer : lambda x: x**2"
diapason ask "Sers-toi de my-reviewer pour relire : def add(a,b): return a+b"
diapason ask "Sers-toi de math-solver pour calculer 2**10"
diapason ask "Sers-toi de code-explainer pour expliquer : [x for x in range(10) if x % 2 == 0]"
```

Chaque requête produit une trace dans `~/.diapason/traces.db`, avec les étiquettes de métadonnées de la compétence (`skill`, `skill_source`, `skill_kind`).

## Étape 6 : découvrir des motifs dans les traces

Fouille le stock de traces pour y repérer des suites d'outils récurrentes :

```bash
# Aperçu, sans rien écrire
diapason skill discover --dry-run --min-frequency 2

# Écrire les motifs découverts en manifestes de compétence
diapason skill discover --min-frequency 2
```

Les compétences découvertes atterrissent dans `~/.diapason/skills/discovered/` et apparaissent d'elles-mêmes dans `diapason skill list` à la session suivante.

## Étape 7 : optimiser les compétences avec DSPy

Une fois que tu as assez de traces (au moins 3 à 5 par compétence), lance l'optimiseur :

```bash
# Aperçu de ce qui serait optimisé
diapason optimize skills --dry-run

# Lancer l'optimisation DSPy
diapason optimize skills --policy dspy --min-traces 3
```

Cela produit des fichiers overlay à `~/.diapason/learning/skills/<skill-name>/optimized.toml`, avec des descriptions améliorées et des exemples few-shot tirés de tes meilleures traces.

Inspecte ce qui a été produit :

```bash
diapason skill show-overlay math-solver
diapason skill show-overlay code-explainer
```

À la requête suivante, l'agent voit les descriptions optimisées et les exemples few-shot dans son prompt système.

## Étape 8 : mesurer l'impact

Lance une mesure rapide pour voir si les compétences et leur optimisation aident vraiment :

```bash
# Test de fumée : 4 conditions × 1 graine × 5 tâches
diapason bench skills --max-samples 5 --seeds 42
```

Cela lance la mesure PinchBench dans quatre conditions (sans compétences, compétences activées, optimisées par DSPy, optimisées par GEPA) et produit un rapport markdown dans `docs/superpowers/results/`.

## Étape 9 : configurer l'import et l'optimisation automatiques

Pour que tout se fasse sans toi, ajoute ceci à `~/.diapason/config.toml` :

```toml
[skills]
enabled = true
auto_sync = true

[[skills.sources]]
source = "hermes"
filter = { category = ["research", "coding"] }
auto_update = true

[learning.skills]
auto_optimize = true
optimizer = "dspy"
min_traces_per_skill = 20
```

Désormais, les compétences se synchronisent d'elles-mêmes depuis Hermes au démarrage de la session, et l'optimiseur tourne après chaque cycle d'apprentissage dès qu'assez de traces se sont accumulées.

## Ce que tu as appris

| Notion | Ce que tu as fait |
|---------|-------------|
| **Installer des compétences** | `diapason skill install hermes:arxiv` — importées depuis des sources publiques |
| **S'en servir** | `diapason ask "Sers-toi de la compétence code-explainer..."` — l'agent invoque les compétences comme des outils |
| **En créer** | Écrire un `SKILL.md` avec du front-matter YAML et des instructions markdown |
| **Produire des traces** | Lancer des requêtes qui se servent des compétences, pour remplir le stock de traces |
| **Découvrir des motifs** | `diapason skill discover` — fouiller les traces pour y repérer des suites d'outils récurrentes |
| **Optimiser les compétences** | `diapason optimize skills --policy dspy` — descriptions améliorées et exemples few-shot |
| **Mesurer** | `diapason bench skills` — mesurer l'impact sur 4 conditions |
| **Configurer l'automatique** | Ajouter les sections `[skills]` et `[learning.skills]` à la configuration |

## Pour aller plus loin

- Parcours le [guide complet des compétences](../user-guide/skills.md) pour toutes les commandes CLI et les options de configuration
- Lis l'[architecture des compétences](../architecture/skills.md) pour le détail technique
- Explore la [bibliothèque de compétences Hermes Agent](https://github.com/NousResearch/hermes-agent/tree/main/skills) pour en installer d'autres
- Essaie les [compétences OpenClaw](https://github.com/openclaw/skills), contribuées par la communauté
