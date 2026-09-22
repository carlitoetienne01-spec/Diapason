---
title: Les compétences
description: Des compositions réutilisables d'outils et d'instructions d'agent — les découvrir, les importer, les optimiser et les partager
search.boost: 2.0
---

# Les compétences

Les compétences apprennent aux agents **à mieux se servir des outils et à mieux raisonner**. Ce sont des compositions réutilisables d'outils, de sous-compétences et d'instructions d'agent, qui se partagent par des registres publics.

Toute compétence est un outil. Les compétences apparaissent dans un catalogue léger, au sein du prompt système de l'agent ; quand l'agent en invoque une, son contenu (résultats de pipeline, instructions markdown, ou les deux) est injecté dans le contexte de la conversation.

## Vue d'ensemble

| Notion | Description |
|---------|-------------|
| **Compétence** | Un dossier contenant `skill.toml` (pipeline structuré), `SKILL.md` (instructions markdown), ou les deux |
| **SkillManager** | Le coordinateur central : découverte, résolution, génération du catalogue et habillage en outil |
| **SkillTool** | L'adaptateur qui habille n'importe quelle compétence en `BaseTool`, pour que les agents puissent l'invoquer |
| **Overlay** | Un fichier annexe dans `~/.diapason/learning/skills/`, qui garde les descriptions optimisées et les exemples few-shot |
| **Source** | Un résolveur pour importer des compétences depuis Hermes Agent, OpenClaw ou n'importe quel dépôt GitHub |

## Pour démarrer

```bash
# Lister les compétences installées
diapason skill list

# Installer une compétence depuis Hermes Agent
diapason skill install hermes:apple-notes

# Installer toute une catégorie d'un coup
diapason skill sync hermes --category research

# Lancer une compétence directement
diapason skill run math-solver -a expression="41 + 82"

# Voir le détail d'une compétence
diapason skill info research-and-summarize
```

## Le format de définition d'une compétence

Une compétence est un dossier contenant un `skill.toml`, un `SKILL.md`, ou les deux.

### La structure du dossier

```
research-and-summarize/
├── SKILL.md              # Instructions markdown (chargées à l'invocation)
├── skill.toml            # Étapes du pipeline structuré
├── templates/            # Gabarits Jinja2, facultatifs
├── scripts/              # Aides exécutables, facultatives
├── references/           # Documentation détaillée, facultative
├── assets/               # Ressources statiques, facultatives
└── examples/             # Exemples d'usage, facultatifs
```

### `skill.toml` (le pipeline structuré)

Les compétences à pipeline définissent une suite d'appels d'outils qui s'exécutent de façon déterministe :

```toml
[skill]
name = "research-and-summarize"
version = "0.1.0"
description = "Cherche sur le web et produit un résumé structuré"
author = "diapason"
tags = ["research", "summarization"]
required_capabilities = ["network:fetch"]
depends = ["summarize"]

[[skill.steps]]
tool_name = "web_search"
arguments_template = '{"query": "{query}"}'
output_key = "search_results"

[[skill.steps]]
skill_name = "summarize"
arguments_template = '{"text": "{search_results}"}'
output_key = "summary"
```

Une étape peut appeler un outil (`tool_name`) ou une autre compétence (`skill_name`). Les emplacements de gabarit comme `{query}` deviennent les paramètres d'entrée de la compétence. Les clés de sortie s'enchaînent d'une étape à la suivante.

### `SKILL.md` (le contenu instructionnel)

Les compétences instructionnelles fournissent une consigne en markdown, que les agents suivent avec leurs autres outils :

```markdown
---
name: code-explainer
description: Explique du code en langage clair, avec des exemples
license: MIT
metadata:
  diapason:
    version: "0.1.0"
    author: diapason
    tags: [coding, explanation]
---

Quand on te demande d'expliquer du code, procède ainsi :

1. Identifie le langage de programmation
2. Découpe le code en sections logiques
3. Explique chaque section en langage clair
4. Signale les motifs, les idiomes et les problèmes éventuels
5. Termine par un résumé d'une phrase
```

Le front-matter YAML suit le standard ouvert [agentskills.io](https://agentskills.io/specification). Champs obligatoires : `name`, `description`. Facultatifs : `license`, `compatibility`, `metadata`, `allowed-tools`.

### Ce qui se passe à l'invocation

| La compétence a | À l'invocation |
|-----------|---------------|
| seulement des étapes `skill.toml` | Le pipeline s'exécute et rend ses résultats |
| seulement un `SKILL.md` | Les instructions markdown sont rendues — l'agent les suit aux tours suivants |
| les deux | Les étapes du pipeline s'exécutent ET la consigne markdown est rendue à côté des résultats |

## Installer des compétences

### Depuis Hermes Agent

```bash
# Une seule compétence
diapason skill install hermes:apple-notes

# Installation en masse, par catégorie
diapason skill sync hermes --category research
diapason skill sync hermes --category coding
diapason skill sync hermes  # tout (~150 compétences)
```

### Depuis OpenClaw

```bash
# Une seule compétence (format propriétaire/slug)
diapason skill install openclaw:0xv4l3nt1n3/etherscan

# Installation en masse, avec un filtre de recherche
diapason skill sync openclaw --search "web3|crypto"
```

### Depuis n'importe quel dépôt GitHub

```bash
diapason skill install github:user/repo/path/to/skill --url https://github.com/user/repo
```

Par exemple, installe la compétence Hermes Tweet quand tu veux qu'un agent cherche
sur Twitter/X, lise les réponses à un tweet, surveille des tweets, exporte des
abonnés et mène des workflows de publication, de réponse ou de message privé sous
condition :

```bash
diapason skill install github:Xquik-dev/hermes-tweet/skills/hermes-tweet --url https://github.com/Xquik-dev/hermes-tweet
```

### L'import automatique par la configuration

Ajoute des sources dans `~/.diapason/config.toml` pour une synchronisation automatique :

```toml
[skills]
enabled = true
auto_sync = true

[[skills.sources]]
source = "hermes"
filter = { category = ["research", "coding", "productivity"] }
auto_update = true

[[skills.sources]]
source = "openclaw"
filter = { search = "web3|crypto" }
```

Quand `auto_sync = true`, le SkillManager vérifie la fraîcheur des sources au démarrage de chaque session et récupère les mises à jour en arrière-plan.

### Gérer les sources

```bash
# Lister les sources configurées
diapason skill sources

# Mettre à jour toutes les sources configurées
diapason skill update
```

## Comment les agents se servent des compétences

### Le catalogue de compétences dans le prompt système

Toutes les compétences disponibles apparaissent sous forme d'un catalogue XML léger, dans le prompt système de l'agent :

```xml
<available_skills>
  <skill name="research-and-summarize" description="Cherche sur le web et produit un résumé structuré" />
  <skill name="code-explainer" description="Explique du code en langage clair, avec des exemples" />
  <skill name="math-solver" description="Résout un problème de mathématiques pas à pas, avec la calculatrice" />
</available_skills>
```

L'agent lit ce catalogue et décide quand invoquer une compétence, selon ce que demande l'utilisateur.

### Contrôler l'invocation

Des drapeaux, compétence par compétence, en contrôlent la visibilité :

```toml
[skill]
user_invocable = true              # exposée comme commande CLI (défaut : true)
disable_model_invocation = false   # cachée du catalogue de l'agent (défaut : false)
```

| `user_invocable` | `disable_model_invocation` | Commande CLI ? | L'agent la découvre ? |
|---|---|---|---|
| true (défaut) | false (défaut) | Oui | Oui |
| true | true | Oui | Non |
| false | false | Non | Oui |
| false | true | Non | Non (dormante) |

### Compétences à pipeline et compétences instructionnelles

Les agents gèrent correctement les deux types :

- **Les compétences à pipeline** (avec des étapes `skill.toml`) s'exécutent de façon déterministe et rendent des résultats calculés. L'agent se sert du résultat directement dans sa réponse.
- **Les compétences instructionnelles** (avec seulement un `SKILL.md`) rendent un texte markdown qui décrit COMMENT accomplir une tâche. L'agent lit les instructions et les suit avec ses autres outils (web_search, shell_exec, calculator, etc.).

## Découvrir des compétences dans les traces

Diapason sait fouiller tout seul ton historique de traces pour y repérer des suites d'outils récurrentes, et te les proposer comme compétences candidates :

```bash
# Aperçu des motifs découverts, sans rien écrire
diapason skill discover --dry-run --min-frequency 3

# Écrire les compétences découvertes dans ~/.diapason/skills/discovered/
diapason skill discover
```

Les compétences découvertes atterrissent dans `~/.diapason/skills/discovered/` et apparaissent d'elles-mêmes dans `diapason skill list` à la session suivante.

## Optimiser les compétences

### Optimiser avec DSPy ou GEPA

La boucle d'apprentissage des compétences se sert de ton historique de traces pour optimiser leurs descriptions et en extraire des exemples few-shot :

```bash
# Aperçu de ce qui serait optimisé
diapason optimize skills --dry-run

# Lancer l'optimisation DSPy
diapason optimize skills --policy dspy --min-traces 3

# Lancer l'optimisation évolutionnaire GEPA
diapason optimize skills --policy gepa --min-traces 3

# Inspecter ce que l'optimisation a produit
diapason skill show-overlay research-and-summarize
```

Les résultats de l'optimisation sont rangés dans des overlays annexes, à `~/.diapason/learning/skills/<skill-name>/optimized.toml`. Ils remplacent la description de la compétence et ajoutent des exemples few-shot au prompt système de l'agent. Les fichiers d'origine de la compétence ne sont jamais modifiés.

### L'optimisation automatique

Active l'optimisation automatique dans la configuration :

```toml
[learning.skills]
auto_optimize = false       # passe à true pour l'activer
optimizer = "dspy"          # "dspy" ou "gepa"
min_traces_per_skill = 20
```

Une fois activée, le `LearningOrchestrator` lance l'optimisation des compétences après chaque cycle d'apprentissage.

## Mesurer les compétences

Pour savoir si les compétences améliorent vraiment les performances de l'agent :

```bash
# Balayage complet : 4 conditions × 3 graines
diapason bench skills

# Test de fumée : 4 conditions × 1 graine × 5 tâches
diapason bench skills --max-samples 5 --seeds 42

# Une seule condition
diapason bench skills --condition skills_optimized_dspy
```

Les quatre conditions de mesure sont :

| Condition | Ce qu'elle teste |
|---|---|
| `no_skills` | Compétences désactivées (le témoin) |
| `skills_on` | Compétences activées, sans optimisation |
| `skills_optimized_dspy` | Overlays optimisés par DSPy |
| `skills_optimized_gepa` | Overlays optimisés par GEPA |

Les résultats sont écrits dans `docs/superpowers/results/pinchbench-skills-eval-{date}.md`, avec un tableau de synthèse, le détail par tâche, les écarts et le nombre d'invocations de chaque compétence.

## Sécurité et confiance

### Les niveaux de confiance

| Niveau | Source | Vérification | À l'exécution |
|------|--------|-------------|---------|
| **Livrée** | Fournie avec Diapason | Confiance implicite | Accès complet, dans les limites des capacités déclarées |
| **Indexée** | Dans l'index officiel des compétences, signée | SHA256 + Ed25519 | Sous contrôle de capacités |
| **Non revue** | URL GitHub quelconque | SHA256 seulement | Sous contrôle de capacités + avertissement de bac à sable |
| **Espace de travail** | Dossier local `./skills/` | Aucune (code de l'utilisateur) | De confiance |

### Le contrôle des capacités

Les compétences déclarent les capacités dont elles ont besoin. À l'exécution, le SkillExecutor vérifie que chaque appel d'outil reste dans les capacités déclarées par la compétence :

- `network:fetch` — requêtes HTTP sortantes
- `filesystem:read` / `filesystem:write` — accès aux fichiers
- `shell:execute` — lancer des commandes shell (dangereux)
- `memory:read` / `memory:write` — accès au stockage de la mémoire
- `engine:inference` — appels au modèle

Une compétence qui déclare des capacités dangereuses (`shell:execute`, `network:listen`, `filesystem:write`) déclenche des avertissements au moment de l'installation et une recommandation de bac à sable.

### Les scripts

Une compétence importée peut contenir un dossier `scripts/` avec du code exécutable. Il est **ignoré par défaut**, par sécurité. Passe `--with-scripts` pour l'accepter :

```bash
diapason skill install hermes:arxiv --with-scripts
```

## Composer des compétences

Une compétence peut en invoquer une autre comme sous-étape :

```toml
[[skill.steps]]
skill_name = "summarize"
arguments_template = '{"text": "{search_results}"}'
output_key = "summary"
```

Le SkillManager construit un graphe de dépendances au moment de la découverte, et vérifie :

1. **Aucun cycle** — `A → B → C → A` est rejeté avec une erreur claire
2. **La profondeur maximale** — 5 niveaux par défaut (configurable)
3. **L'union des capacités** — le parent doit déclarer toutes les capacités dont ses enfants ont besoin

## Référence de configuration

### La section `[skills]`

```toml
[skills]
enabled = true                    # active ou coupe le système de compétences
skills_dir = "~/.diapason/skills/"  # où les compétences sont installées
active = "*"                      # les compétences à activer ("*" = toutes)
auto_discover = true              # balaye skills_dir au démarrage
auto_sync = false                 # récupère depuis les sources configurées au démarrage
max_depth = 5                     # profondeur maximale d'imbrication des sous-compétences
sandbox_dangerous = true          # avertit sur les capacités dangereuses
```

### La section `[[skills.sources]]`

```toml
[[skills.sources]]
source = "hermes"                 # "hermes", "openclaw" ou "github"
url = ""                          # obligatoire quand source = "github"
filter = { category = ["research", "coding"] }
auto_update = true                # récupère la dernière version à la synchronisation
```

### La section `[learning.skills]`

```toml
[learning.skills]
auto_optimize = false             # optimisation automatique, sur demande explicite
optimizer = "dspy"                # "dspy" ou "gepa"
min_traces_per_skill = 20         # nombre minimal de traces avant d'optimiser
optimization_interval_seconds = 86400  # au plus une fois par jour
overlay_dir = "~/.diapason/learning/skills/"
```

## La priorité des noms

Quand le même nom de compétence existe à plusieurs endroits, la portée la plus proche l'emporte :

1. **L'espace de travail** `./skills/` (priorité la plus haute)
2. **L'utilisateur** `~/.diapason/skills/`
3. **Les compétences livrées** (fournies avec Diapason)

## Référence de la ligne de commande

| Commande | Description |
|---------|-------------|
| `diapason skill list` | Liste les compétences installées |
| `diapason skill info <name>` | Affiche le détail d'une compétence |
| `diapason skill run <name> [-a key=value]` | Lance une compétence directement |
| `diapason skill install <source>:<name>` | Installe depuis Hermes, OpenClaw ou GitHub |
| `diapason skill sync [<source>] [--category C]` | Installe en masse et met à jour depuis les sources |
| `diapason skill sources` | Liste les sources de compétences configurées |
| `diapason skill update` | Récupère la dernière version depuis les sources configurées |
| `diapason skill remove <name>` | Retire une compétence installée |
| `diapason skill search <query>` | Cherche dans l'index des compétences |
| `diapason skill discover [--dry-run]` | Fouille les traces pour y trouver des motifs d'outils récurrents |
| `diapason skill show-overlay <name>` | Inspecte ce que l'optimisation a produit pour une compétence |
| `diapason optimize skills [--policy dspy\|gepa]` | Optimise les descriptions de compétences et les exemples few-shot |
| `diapason bench skills [--condition C]` | Lance le banc de mesure PinchBench des compétences |
