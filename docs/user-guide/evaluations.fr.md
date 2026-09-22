# Évaluations

Le cadre d'évaluation de Diapason (`diapason.evals`) mesure la **justesse et l'exactitude** d'un modèle sur des jeux de données académiques. Il est livré dans le paquet principal `diapason` (sous `src/diapason/evals/`) et il est fait pour les travaux de recherche, là où il te faut des mesures de qualité reproductibles et pilotées par les données.

!!! info "Évaluations et benchmarks"
    Diapason mesure de deux façons distinctes, qui se complètent :

    | Système | Module | Ce qu'il mesure | Point d'entrée |
    |--------|--------|----------|-------------|
    | **Évaluations** | `diapason.evals` | La justesse sur des jeux de données académiques (exactitude, taux de réussite) | `diapason eval` |
    | **Benchmarks** | `diapason.bench` | La performance du moteur (latence, débit) | `diapason bench` |

    Les évaluations répondent à « ce modèle donne-t-il la bonne réponse ? » ; les benchmarks répondent à « en combien de temps répond-il ? ». Le système de mesure de performance est décrit dans le [guide des benchmarks](benchmarks.md).

---

> **Astuce :** la recherche de spécification guidée par LLM s'appuie sur cette même infrastructure d'évaluation pour filtrer les modifications contre ton banc de référence personnel. Voir [Recherche de spécification guidée par LLM](llm-guided-spec-search.md).

## Installation

Le cadre d'évaluation fait partie du paquet `diapason` — rien à installer à part, aucun extra à ajouter. L'installation de développement habituelle suffit :

```bash
uv sync --extra dev
```

Ses dépendances de base (`click`, `datasets`, `rich`) sont déjà des dépendances de `diapason`. Deux extras facultatifs activent le suivi d'expériences :

```bash
uv sync --extra dev --extra eval-wandb     # suivi des exécutions par Weights & Biases
uv sync --extra dev --extra eval-sheets    # export des résultats vers Google Sheets
```

!!! note "La version de Python compte"
    Python 3.10 a besoin du paquet `tomli` pour lire les configurations TOML. `diapason` le déclare comme dépendance conditionnelle : il s'installe tout seul.

## Points d'entrée

Deux points d'entrée équivalents exposent le cadre :

| Commande | Surface |
|---------|---------|
| `diapason eval {list,run,compare,report}` | La CLI canonique. `run` couvre les options courantes ; `compare` et `report` retraitent les fichiers de résultats. |
| `python -m diapason.evals {list,run,run-all,summarize,reparse-judge}` | La surface de recherche complète : configuration du juge, exécuteur agentique, mode épisode. |

Le script console `diapason-eval` est un alias de `python -m diapason.evals` — mêmes commandes, mêmes options. Ce guide utilise `diapason eval` partout où ses options suffisent, et la forme module pour les options réservées à la recherche.

---

## Jeux de données

Le cadre est livré avec **40 benchmarks enregistrés**, couvrant le raisonnement académique, les tâches agentiques, le code, la recherche documentaire, la qualité de conversation et des usages métier. Ils sont regroupés par catégorie ci-dessous ; `uv run python -m diapason.evals list` affiche le registre qui fait foi.

### Les benchmarks métier

Ceux-là évaluent les modèles sur des tâches concrètes, proches des usages réels de Diapason.

| Jeu de données | Clé | Description |
|---------|-----|-------------|
| **CodingAssistant** | `coding_assistant` | Assistant de code qui corrige des bugs (vérifié par des tests) |
| **SecurityScanner** | `security_scanner` | Détecteur de failles de sécurité |
| **DailyDigest** | `daily_digest` | Génération du point quotidien |
| **DocQA** | `doc_qa` | Questions-réponses ancrées dans un document, avec citations |
| **BrowserAssistant** | `browser_assistant` | Recherche web avec vérification des faits |
| **EmailTriage** | `email_triage` | Tri des courriels : classement et brouillon de réponse |
| **MorningBrief** | `morning_brief` | Génération du point du matin |
| **ResearchMining** | `research_mining` | Synthèse de recherche et exactitude |
| **KnowledgeBase** | `knowledge_base` | Questions-réponses par recherche dans des documents |
| **CodingTask** | `coding_task` | Génération de code à l'échelle d'une fonction |

### Les benchmarks académiques

Ceux-là mesurent le raisonnement et les connaissances sur des jeux de données académiques établis.

| Jeu de données | Clé | Catégorie | Description |
|---------|-----|----------|-------------|
| **SuperGPQA** | `supergpqa` | reasoning | Questions à choix multiples de niveau doctoral, toutes disciplines scientifiques |
| **GPQA** | `gpqa` | reasoning | QCM de niveau doctoral (variantes Diamond, Extended, Main) |
| **MMLU-Pro** | `mmlu-pro` | reasoning | QCM MMLU enrichi |
| **MATH-500** | `math500` | reasoning | Problèmes de mathématiques de niveau concours |
| **NaturalReasoning** | `natural-reasoning` | reasoning | Raisonnement en langue naturelle |
| **HLE** | `hle` | reasoning | Les épreuves difficiles de Humanity's Last Exam |
| **LiveResearchBench** | `liveresearchbench` | reasoning | Compréhension de travaux de recherche récents (Salesforce) |
| **SimpleQA** | `simpleqa` | chat | Questions factuelles à réponse courte |
| **IPW** | `ipw` | chat | Benchmark mixte « intelligence par watt » |

### Les benchmarks d'agents

Ceux-là éprouvent les capacités d'agent en plusieurs étapes : appel d'outils, génération de code, planification à long terme.

| Jeu de données | Clé | Catégorie | Description |
|---------|-----|----------|-------------|
| **GAIA** | `gaia` | agentic | Tâches en plusieurs étapes : lecture de fichiers, calculs, recherche web |
| **SWE-bench** | `swebench` | agentic | Vrais correctifs de code venus de GitHub |
| **SWEfficiency** | `swefficiency` | agentic | Tâches d'optimisation logicielle |
| **TerminalBench** | `terminalbench` | agentic | Tâches à accomplir dans un terminal |
| **TerminalBench Native** | `terminalbench-native` | agentic | TerminalBench, exécuté nativement dans Docker |
| **TerminalBench V2.1** | `terminalbench-v2.1` | agentic | Tâches Docker de style Harbor (TB v2.1) |
| **PinchBench** | `pinchbench` | agentic | Tâches d'agent tirées du réel |
| **TauBench** | `taubench` | agentic | Service client sur plusieurs tours |
| **DeepResearchBench** | `liveresearch` | agentic | Génération de rapports de recherche approfondie |
| **DeepResearchBench (alias)** | `deepresearch` | agentic | Le même benchmark que `liveresearch` |
| **ToolCall-15** | `toolcall15` | agentic | Benchmark d'appel d'outils |
| **LifelongAgent** | `lifelong-agent` | agentic | Apprentissage de tâches successives d'une session à l'autre |
| **PaperArena** | `paperarena` | agentic | Analyse d'articles scientifiques |
| **DeepPlanning** | `deepplanning` | agentic | Planification d'achats sous contraintes |
| **LogHub** | `loghub` | agentic | Détection d'anomalies dans les journaux |
| **AMA-Bench** | `ama-bench` | agentic | Évaluation de la mémoire d'un agent |
| **WebChoreArena** | `webchorearena` | agentic | Corvées web |
| **WorkArena** | `workarena` | agentic | Les workflows d'entreprise de WorkArena++ |

`liveresearch` et `deepresearch` sont deux clés enregistrées pour le même benchmark de génération de rapports, DeepResearchBench.

### Les benchmarks de code

| Jeu de données | Clé | Catégorie | Description |
|---------|-----|----------|-------------|
| **LiveCodeBench** | `livecodebench` | coding | Programmation compétitive |

### Les benchmarks de recherche documentaire

| Jeu de données | Clé | Catégorie | Description |
|---------|-----|----------|-------------|
| **FRAMES** | `frames` | rag | Recherche factuelle à plusieurs sauts, à travers des articles de Wikipédia |

### Les benchmarks de conversation

| Jeu de données | Clé | Catégorie | Description |
|---------|-----|----------|-------------|
| **WildChat** | `wildchat` | chat | Qualité des conversations d'utilisateurs réels (comparaison par paire, jugée par un LLM) |

---

### Le détail des jeux de données

**SuperGPQA** est un grand benchmark à choix multiples, couvrant des questions de niveau doctoral dans les disciplines scientifiques. Chaque échantillon porte une question, un jeu d'options désignées par des lettres, et la lettre de la réponse de référence.

**GAIA** est un benchmark agentique : le modèle doit mener à bien des tâches en plusieurs étapes, qui peuvent demander de lire un fichier, de calculer ou de chercher sur le web. Les questions viennent du jeu d'épreuves GAIA de 2023.

**FRAMES** éprouve la recherche factuelle à plusieurs sauts. Chaque question demande de recouper plusieurs articles de Wikipédia : c'est une bonne sonde de la génération augmentée par recherche.

**WildChat** part de vraies conversations d'utilisateurs, filtrées pour ne garder que les échanges en anglais à un seul tour. La réponse de référence est la réponse d'assistant d'origine du jeu de données ; le modèle évalué lui est comparé par un LLM juge.

!!! tip "Accéder au jeu de données GAIA"
    GAIA demande un compte HuggingFace et l'acceptation de ses conditions d'utilisation. Le chargeur télécharge l'instantané complet du jeu de données au premier usage et le met en cache dans `~/.cache/gaia_benchmark/`. Les exécutions suivantes se servent du cache local.

---

## Les configurations d'évaluation métier

Le cadre embarque deux configurations toutes faites pour évaluer des modèles sur les cinq benchmarks métier principaux (coding_assistant, security_scanner, daily_digest, doc_qa, browser_assistant).

### Les modèles distants

```bash
uv run diapason eval run --config src/diapason/evals/configs/use_case_v2_cloud.toml
```

Cette configuration évalue **6 modèles distants** (Claude Opus 4.6, Claude Haiku 4.5, Gemini 3.1 Pro, Gemini 3.1 Flash Lite, GPT-5.4, GPT-5 Mini) sur les 5 benchmarks métier, 30 échantillons chacun : une matrice de 6 × 5 = 30 exécutions. Les résultats sont écrits dans `results/use-cases-v2-cloud/`.

### Les modèles locaux

```bash
uv run diapason eval run --config src/diapason/evals/configs/use_case_v2_local.toml
```

Cette configuration évalue **5 modèles locaux** par Ollama (Qwen3.5 122B-A10B, GPT-OSS 120B, GLM4, Qwen3.5 35B-A3B, GLM-4.7-Flash) sur les mêmes 5 benchmarks : une matrice de 5 × 5 = 25 exécutions. Elle utilise 2 fils, ce qui convient à une machine à un seul GPU. Les résultats sont écrits dans `results/use-cases-v2-local/`.

!!! tip "Adapter les évaluations métier"
    Copie l'une des configurations `use_case_v2_*.toml` et modifie les blocs `[[models]]` pour évaluer tes propres modèles. Les cinq benchmarks métier utilisent des jeux de données synthétiques — rien à télécharger depuis HuggingFace — et vont vite avec 30 échantillons chacun.

---

## Les moteurs d'inférence

Toute évaluation achemine ses appels de modèle par l'un des quatre moteurs d'inférence :

| Moteur | Clé | Description |
|---------|-----|-------------|
| **diapason-direct** | `diapason-direct` | Inférence au niveau du moteur, via `SystemBuilder`. Fonctionne pour les modèles locaux (Ollama, vLLM, llama.cpp) comme distants. |
| **diapason-agent** | `diapason-agent` | Inférence au niveau de l'agent, avec appel d'outils. Passe par `DiapasonSystem.ask()` avec l'agent et les outils indiqués. |
| **hermes** | `hermes` | Le vrai Hermes Agent (Nous Research), lancé en sous-processus. Demande `--base-url` et `--api-key`. |
| **openclaw** | `openclaw` | Le vrai OpenClaw, lancé en sous-processus Node. Demande `--base-url` et `--api-key`. |

Prends `diapason-direct` pour la plupart des évaluations. Prends `diapason-agent` quand le benchmark exige des outils — par exemple les tâches GAIA qui renvoient à des fichiers qu'il faut lire avec `file_read`, ou les tâches de calcul qui gagnent à passer par `calculator`.

Les moteurs `hermes` et `openclaw` délèguent le travail à des cadres d'agents externes, et ceux-ci ont besoin d'un point d'accès compatible OpenAI pour leurs appels de modèle : passe `--base-url`/`--api-key`, pose les variables d'environnement `DIAPASON_BACKEND_BASE_URL`/`DIAPASON_BACKEND_API_KEY`, ou ajoute une section `[backend.external]` à ta configuration (voir la [référence de configuration](#backendexternal)).

!!! note "TerminalBench Native"
    `diapason eval run --backend` accepte en plus `terminalbench-native`, un moteur d'exécution fondé sur Docker, utilisé par le benchmark TerminalBench Native.

---

## L'usage en ligne de commande

### Lister les benchmarks et les moteurs disponibles

```bash
uv run python -m diapason.evals list
```

Sortie abrégée (40 benchmarks, 4 moteurs) :

```
                         Available Benchmarks
┌──────────────────────┬───────────┬───────────────────────────────────┐
│ Name                 │ Category  │ Description                       │
├──────────────────────┼───────────┼───────────────────────────────────┤
│ supergpqa            │ reasoning │ SuperGPQA multiple-choice         │
│ gpqa                 │ reasoning │ GPQA graduate-level MCQ           │
│ ...                  │ ...       │ ...                               │
│ livecodebench        │ coding    │ LiveCodeBench competitive progr.  │
│ toolcall15           │ agentic   │ ToolCall-15 tool calling benchmark│
└──────────────────────┴───────────┴───────────────────────────────────┘
                         Available Backends
┌───────────────┬──────────────────────────────────────────────────┐
│ diapason-direct │ Engine-level inference (local or cloud)          │
│ diapason-agent  │ Agent-level inference with tool calling          │
│ hermes        │ Real Hermes Agent (Nous Research) via subprocess │
│ openclaw      │ Real OpenClaw via Node subprocess                │
└───────────────┴──────────────────────────────────────────────────┘
```

`diapason eval list` affiche un tableau semblable, mais n'en montre pour l'instant qu'une sélection ; c'est la forme module ci-dessus qui fait foi.

### Lancer un seul benchmark

```bash
# Évaluer qwen3:8b sur SuperGPQA (au niveau du moteur, 10 échantillons)
uv run diapason eval run -b supergpqa -m qwen3:8b -n 10

# Évaluer GPT-5 Mini sur GAIA, avec le moteur agent et des outils
uv run diapason eval run -b gaia -m gpt-5-mini --backend diapason-agent \
    --agent orchestrator --tools calculator,file_read -n 50

# Lancer FRAMES avec le moteur vLLM, en écrivant la sortie dans un fichier
uv run diapason eval run -b frames -m llama3:70b -e vllm \
    -o results/frames_llama70b.jsonl

# Lancer WildChat à une température plus haute, pour la qualité de discussion
uv run diapason eval run -b wildchat -m qwen3:8b --temperature 0.7 -n 100
```

#### Les options de `diapason eval run`

| Option | Court | Type | Défaut | Description |
|--------|-------|------|---------|-------------|
| `--config` | `-c` | chemin | — | Fichier de configuration TOML ; quand il est fourni, `-b` et `-m` ne sont plus requis |
| `--benchmark` | `-b` | str | requis* | N'importe quelle clé de benchmark enregistrée (voir `... list`) |
| `--model` | `-m` | str | requis* | Identifiant du modèle (par ex. `qwen3:8b`, `gpt-5-mini`) |
| `--max-samples` | `-n` | int | tous | Limite le nombre d'échantillons évalués |
| `--backend` | | choix | `diapason-direct` | `diapason-direct`, `diapason-agent`, `hermes`, `openclaw` ou `terminalbench-native` |
| `--base-url` | | str | — | URL du point d'accès compatible OpenAI (variable : `DIAPASON_BACKEND_BASE_URL`) |
| `--api-key` | | str | — | Clé d'API du point d'accès (variable : `DIAPASON_BACKEND_API_KEY`) |
| `--agent` | | str | — | Nom de l'agent pour le moteur `diapason-agent` (par ex. `orchestrator`) |
| `--engine` | `-e` | str | auto | Clé du moteur (`ollama`, `vllm`, `cloud`, …) |
| `--tools` | | str | `""` | Noms d'outils séparés par des virgules (par ex. `calculator,file_read`) |
| `--telemetry/--no-telemetry` | | drapeau | désactivé | Active la collecte de télémétrie pendant l'évaluation |
| `--gpu-metrics/--no-gpu-metrics` | | drapeau | désactivé | Active le relevé des métriques GPU |
| `--seed` | | int | `42` | Graine aléatoire pour le brassage du jeu de données |
| `--temperature` | | float | `0.0` | Température de génération |
| `--max-tokens` | | int | `2048` | Nombre maximal de jetons en sortie |
| `--model-filter` | | str | — | Filtre les modèles sur un morceau de leur nom (configurations multi-modèles) |
| `--output` | `-o` | chemin | automatique | Chemin du fichier JSONL de sortie |
| `--wandb-project` / `--wandb-entity` / `--wandb-tags` / `--wandb-group` | | str | `""` | Suivi Weights & Biases (demande l'extra `eval-wandb`) |
| `--sheets-id` / `--sheets-worksheet` / `--sheets-creds` | | str | `""` | Export vers Google Sheets (demande l'extra `eval-sheets`) |
| `--verbose` | `-v` | drapeau | désactivé | Active les journaux de débogage |

*Requis quand `--config` n'est pas fourni.

#### Les options réservées à la recherche (`python -m diapason.evals run`)

La CLI module accepte tout ce qui précède, plus des options de recherche que `diapason eval run` n'expose pas :

| Option | Court | Type | Défaut | Description |
|--------|-------|------|---------|-------------|
| `--max-workers` | `-w` | int | `4` | Fils d'évaluation en parallèle |
| `--judge-model` | | str | `gpt-5-mini-2025-08-07` | LLM utilisé pour la notation par juge (le défaut courant est donné par `--help`) |
| `--judge-engine` | | str | `cloud` | Clé du moteur du LLM juge ; `vllm` pour juger en local |
| `--split` | | str | défaut du jeu de données | Remplace la tranche du jeu de données |
| `--compact` | | drapeau | désactivé | Sortie dense, en un seul tableau |
| `--trace-detail` | | drapeau | désactivé | Trace complète, étape par étape |
| `--agentic` | | drapeau | désactivé | Passe par `AgenticRunner` pour une exécution d'agent sur plusieurs tours |
| `--episode-mode` | | drapeau | désactivé | Traitement séquentiel par épisodes, avec apprentissage continu (requis pour `lifelong-agent` et les benchmarks du même genre) |
| `--concurrency` | | int | `1` | Exécution des requêtes en parallèle (`AgenticRunner` seulement) |
| `--query-timeout` | | float | — | Délai maximal par requête, en secondes de temps réel (`AgenticRunner` seulement) |

À noter : le `--backend` de la CLI module couvre `diapason-direct`, `diapason-agent`, `hermes` et `openclaw` ; `terminalbench-native` comme moteur n'est accessible que par `diapason eval run` et par les configurations TOML.

### Lancer tous les benchmarks d'un coup

La commande `run-all` (CLI module seulement) évalue un seul modèle contre **tous les benchmarks enregistrés**, l'un après l'autre, et écrit les résultats dans un dossier de sortie :

```bash
uv run python -m diapason.evals run-all -m qwen3:8b

# Avec des options
uv run python -m diapason.evals run-all -m gpt-5-mini -n 100 --output-dir results/gpt5mini/
```

Les fichiers sont écrits sous la forme `{output_dir}/{benchmark}_{model-slug}.jsonl`. Le « slug » du modèle remplace `/` et `:` par `-` : `qwen3:8b` devient donc `qwen3-8b`.

### Résumer les résultats

Après une exécution, inspecte un fichier de résultats JSONL :

```bash
uv run python -m diapason.evals summarize results/supergpqa_qwen3-8b.jsonl
```

Sortie :

```
File:      results/supergpqa_qwen3-8b.jsonl
Benchmark: supergpqa
Model:     qwen3:8b
Total:     200
Scored:    198
Correct:   143
Accuracy:  0.7222
Errors:    2
```

La CLI module fournit aussi `reparse-judge` : elle relit les sorties de juge stockées dans un fichier de résultats et récupère les enregistrements dont le verdict n'avait pas pu être analysé — utile après avoir amélioré l'analyseur, sans relancer l'inférence.

### Comparer et rapporter

`diapason eval` ajoute deux commandes de retraitement des fichiers de résultats :

```bash
# Comparaison des métriques côte à côte, entre plusieurs exécutions
uv run diapason eval compare results/supergpqa_qwen3-8b.jsonl results/supergpqa_gpt-5-mini.jsonl

# Rapport détaillé (exactitude, latence, coût, répartition par sujet) pour une exécution
uv run diapason eval report results/supergpqa_qwen3-8b.jsonl
```

---

## Évaluer un point d'accès déjà en marche

Si un serveur compatible OpenAI tourne déjà — `diapason serve`, vLLM, SGLang, le serveur de llama.cpp, ou un point d'accès hébergé —, pointe l'évaluation dessus avec `--base-url` et `--api-key` :

```bash
# Un serveur vLLM sert déjà Qwen/Qwen3-8B sur un nœud GPU :
#   vllm serve Qwen/Qwen3-8B --port 8000
uv run diapason eval run -b supergpqa -m Qwen/Qwen3-8B \
    --base-url http://gpu-node:8000/v1 \
    --api-key local-key \
    -n 50
```

La valeur de `-m` doit correspondre à un identifiant de modèle annoncé par le serveur sur `GET /v1/models`. Les deux options retombent sur les variables d'environnement `DIAPASON_BACKEND_BASE_URL` et `DIAPASON_BACKEND_API_KEY` : un job de CI peut donc les poser une fois pour toutes :

```bash
export DIAPASON_BACKEND_BASE_URL=http://gpu-node:8000/v1
export DIAPASON_BACKEND_API_KEY=local-key
uv run diapason eval run -b gaia -m Qwen/Qwen3-8B --backend diapason-agent -n 25
```

Pour les moteurs externes `hermes` et `openclaw`, ces valeurs sont **obligatoires** : ces cadres étrangers ont besoin d'un point d'accès où envoyer leurs appels de modèle.

!!! tip "Autre voie pour vLLM, au niveau du moteur"
    Le moteur vLLM respecte aussi la variable d'environnement `VLLM_HOST` (par défaut `http://localhost:8000`) :

    ```bash
    VLLM_HOST=http://gpu-node:8000 uv run python -m diapason.evals run \
        -b supergpqa -m Qwen/Qwen3-8B -e vllm -n 50
    ```

    `VLLM_HOST` vaut pour tout le processus : si le modèle candidat et le juge passent tous deux par le moteur `vllm`, ils partagent le même point d'accès. Quand il te les faut séparés, passe par `--base-url`.

---

## Le système de configuration TOML

Pour comparer plusieurs modèles sur plusieurs benchmarks, décris l'évaluation dans un fichier TOML, comme une **matrice modèles × benchmarks**. C'est la voie recommandée pour une évaluation systématique.

### Lancer depuis une configuration

```bash
uv run diapason eval run --config src/diapason/evals/configs/full-suite.toml
```

Quand `--config` est fourni, `-b`/`--benchmark` et `-m`/`--model` ne sont plus requis : tous les réglages viennent du fichier. La CLI déploie la matrice, affiche un tableau d'avancement et écrit les résultats dans l'`output_dir` configuré.

### Le format du fichier de configuration

Un fichier de configuration a six sections : `[meta]`, `[defaults]`, `[judge]`, `[run]`, `[[models]]` et `[[benchmarks]]`. Seules `[[models]]` et `[[benchmarks]]` sont obligatoires — les autres sont facultatives et retombent sur les défauts internes.

```toml title="src/diapason/evals/configs/full-suite.toml"
# Métadonnées de la suite (facultatif)
[meta]
name = "full-suite-v1"
description = "Évaluer tous les benchmarks contre les modèles de production"

# Paramètres de génération par défaut (facultatif)
[defaults]
temperature = 0.0
max_tokens = 2048

# Configuration du LLM juge (facultatif)
[judge]
model = "gpt-4o"
temperature = 0.0
max_tokens = 1024

# Réglages d'exécution (facultatif)
[run]
max_workers = 4
output_dir = "results/"
seed = 42

# --- Les modèles (un bloc [[models]] par modèle) ---

[[models]]
name = "qwen3:8b"
engine = "ollama"
temperature = 0.3    # remplace [defaults] pour ce modèle
max_tokens = 4096

[[models]]
name = "gpt-4o"
provider = "openai"  # passe par le moteur cloud

[[models]]
name = "llama3:70b"
engine = "vllm"
temperature = 0.1

# --- Les benchmarks (un bloc [[benchmarks]] par benchmark) ---

[[benchmarks]]
name = "supergpqa"
backend = "diapason-direct"
max_samples = 200
split = "train"

[[benchmarks]]
name = "gaia"
backend = "diapason-agent"
agent = "orchestrator"
tools = ["file_read", "calculator"]
max_samples = 50
judge_model = "claude-sonnet-4-20250514"  # un autre juge pour ce benchmark

[[benchmarks]]
name = "frames"
backend = "diapason-direct"
max_samples = 100

[[benchmarks]]
name = "wildchat"
backend = "diapason-direct"
max_samples = 150
temperature = 0.7   # température propre à ce benchmark
```

Cette configuration produit 3 modèles × 4 benchmarks = **12 exécutions d'évaluation**.

### L'ordre de préséance

Les réglages sont résolus dans cet ordre, du plus fort au plus faible :

```
niveau benchmark  >  niveau modèle  >  [defaults]  >  défauts internes
```

Par exemple, `temperature` se résout ainsi : partir de `[defaults].temperature` (0.0), puis appliquer `[[models]].temperature` s'il est posé (0.3 pour qwen3:8b), puis le remplacer par `[[benchmarks]].temperature` s'il est posé (0.7 pour wildchat). L'exécution de WildChat avec qwen3:8b tourne donc à `temperature = 0.7`.

### La configuration minimale

Une configuration n'exige qu'une entrée `[[models]]` et une entrée `[[benchmarks]]` :

```toml title="src/diapason/evals/configs/minimal.toml"
[[models]]
name = "qwen3:8b"

[[benchmarks]]
name = "supergpqa"
```

Elle lance SuperGPQA contre qwen3:8b avec tous les réglages par défaut. C'est le point de départ quand tu itères sur un seul modèle ou un seul jeu de données.

### Une exécution unique, avec toutes les options

```toml title="src/diapason/evals/configs/single-run.toml"
[meta]
name = "single-run-example"
description = "Évaluer SuperGPQA avec un seul modèle et une configuration complète"

[defaults]
temperature = 0.0
max_tokens = 2048

[judge]
model = "gpt-4o"
temperature = 0.0
max_tokens = 1024

[run]
max_workers = 4
output_dir = "results/"
seed = 42

[[models]]
name = "qwen3:8b"
engine = "ollama"
temperature = 0.3
max_tokens = 4096

[[benchmarks]]
name = "supergpqa"
backend = "diapason-direct"
max_samples = 100
split = "train"
```

---

## Référence de configuration

### `[meta]`

Les métadonnées de la suite. Aucun des deux champs ne change le comportement de l'évaluation ; ils servent à l'affichage de la CLI et aux fichiers de résumé.

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `name` | str | `""` | Nom de la suite, affiché par la CLI |
| `description` | str | `""` | Description en clair |

### `[defaults]`

Les paramètres de génération appliqués à toute exécution, sauf s'ils sont remplacés au niveau du modèle ou du benchmark.

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `temperature` | float | `0.0` | Température d'échantillonnage |
| `max_tokens` | int | `2048` | Nombre maximal de jetons en sortie |

### `[judge]`

La configuration du LLM qui sert de juge pour la notation de GAIA, FRAMES et WildChat.

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `model` | str | `"gpt-5-mini-2025-08-07"` | Identifiant du modèle juge |
| `engine` | str | `None` | Clé du moteur du juge (par ex. `"vllm"` pour juger en local ; par défaut, le cloud) |
| `provider` | str | `None` | Fournisseur imposé (par ex. `"openai"`) |
| `temperature` | float | `0.0` | Température d'échantillonnage du juge |
| `max_tokens` | int | `1024` | Nombre maximal de jetons produits par le juge |

!!! warning "Ce que coûte le modèle juge"
    Chaque échantillon noté par un LLM déclenche un appel distinct au modèle juge. Sur de grosses exécutions, à plusieurs centaines d'échantillons, le juge peut coûter plus cher que l'évaluation elle-même. GAIA, FRAMES et WildChat demandent tous un juge ; SuperGPQA, lui, se sert d'un LLM pour extraire la lettre de la réponse, puis la compare à la référence sans appel de juge supplémentaire.

### `[run]`

Les réglages d'exécution qui valent pour toute la suite.

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `max_workers` | int | `4` | Nombre de fils d'évaluation en parallèle |
| `output_dir` | str | `"results/"` | Dossier où sont écrits les fichiers JSONL et les résumés |
| `seed` | int | `42` | Graine aléatoire pour le brassage du jeu de données |
| `telemetry` | bool | `false` | Active la capture de télémétrie GPU (énergie, puissance, utilisation, débit) |
| `gpu_metrics` | bool | `false` | Active le relevé des métriques GPU par `pynvml` (demande `pynvml` ou `nvidia-ml-py`) |
| `warmup_samples` | int | `0` | Échantillons de chauffe, non chronométrés, avant la mesure |
| `energy_vendor` | str | `""` | Fournisseur d'énergie GPU imposé |
| `max_turns` | int | `None` | Nombre maximal de tours d'agent par requête |
| `wandb_project` / `wandb_entity` / `wandb_tags` / `wandb_group` | str | `""` | Suivi Weights & Biases |
| `sheets_spreadsheet_id` / `sheets_worksheet` / `sheets_credentials_path` | str | `""` / `"Results"` / `""` | Export vers Google Sheets |

### `[backend.external]`

Les réglages de point d'accès des moteurs `hermes` et `openclaw`. Les variables d'environnement l'emportent sur les valeurs du TOML.

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `base_url` | str | `None` | URL du point d'accès compatible OpenAI (variable : `DIAPASON_BACKEND_BASE_URL`) |
| `api_key` | str | `None` | Clé d'API du point d'accès (variable : `DIAPASON_BACKEND_API_KEY`) |

### `[[models]]`

Un bloc par modèle. Le champ `name` est obligatoire.

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `name` | str | requis | Identifiant du modèle (par ex. `"qwen3:8b"`, `"gpt-5-mini"`) |
| `engine` | str | `None` | Clé du moteur à utiliser (`"ollama"`, `"vllm"`, `"cloud"`, …) |
| `provider` | str | `None` | Fournisseur imposé pour les modèles distants (par ex. `"openai"`) |
| `temperature` | float | `None` | Remplace `[defaults].temperature` pour ce modèle |
| `max_tokens` | int | `None` | Remplace `[defaults].max_tokens` pour ce modèle |
| `param_count_b` | float | `0.0` | Nombre total de paramètres du modèle, en milliards (pour le calcul du MFU et du MBU) |
| `active_params_b` | float | `None` | Paramètres actifs par jeton, en milliards (modèles MoE ; vaut `param_count_b` par défaut) |
| `gpu_peak_tflops` | float | `0.0` | TFLOPS FP16 crête du GPU (par ex. 312.0 pour une A100 SXM) |
| `gpu_peak_bandwidth_gb_s` | float | `0.0` | Bande passante mémoire crête du GPU, en Go/s (par ex. 2039.0 pour une A100 SXM) |
| `num_gpus` | int | `1` | Nombre de GPU utilisés (inférence en parallélisme de tenseurs) |

### `[[benchmarks]]`

Un bloc par benchmark. Le champ `name` est obligatoire.

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `name` | str | requis | N'importe quelle clé de benchmark enregistrée (voir `uv run python -m diapason.evals list`) |
| `backend` | str | `"diapason-direct"` | `diapason-direct`, `diapason-agent`, `hermes`, `openclaw` ou `terminalbench-native` |
| `max_samples` | int | `None` | Limite le nombre d'échantillons ; `None` évalue tout le jeu de données |
| `split` | str | `None` | Remplace la tranche par défaut du jeu de données |
| `subset` | str | `None` | Sous-ensemble ou variante du jeu de données (propre à chaque benchmark) |
| `record_ids` | list[str] | `None` | N'évaluer que ces identifiants d'enregistrement |
| `agent` | str | `None` | Nom de l'agent pour le moteur `diapason-agent` (par ex. `"orchestrator"`) |
| `tools` | list[str] | `[]` | Noms des outils pour le moteur `diapason-agent` |
| `judge_model` | str | `None` | Remplace `[judge].model` pour ce seul benchmark |
| `temperature` | float | `None` | Remplace la température pour ce benchmark (préséance maximale) |
| `max_tokens` | int | `None` | Remplace le nombre maximal de jetons pour ce benchmark (préséance maximale) |

---

## Le format de sortie

### Le fichier de résultats JSONL

Chaque échantillon terminé est ajouté au fichier JSONL de sortie dès qu'il est noté. Le chemin du fichier est soit donné par `-o`/`--output`, soit généré automatiquement sous la forme `{output_dir}/{benchmark}_{model-slug}.jsonl`.

Chaque ligne est un objet JSON, avec les champs suivants :

```json title="results/supergpqa_qwen3-8b.jsonl (une ligne par échantillon)"
{
  "record_id": "supergpqa-42",
  "benchmark": "supergpqa",
  "model": "qwen3:8b",
  "backend": "diapason-direct",
  "model_answer": "La réponse est C, parce que…",
  "is_correct": true,
  "score": 1.0,
  "latency_seconds": 1.34,
  "prompt_tokens": 187,
  "completion_tokens": 12,
  "cost_usd": 0.0,
  "error": null,
  "scoring_metadata": {"reference_letter": "C", "candidate_letter": "C"},
  "ttft": 0.0,
  "energy_joules": 140792.95,
  "power_watts": 893.0,
  "gpu_utilization_pct": 47.4,
  "throughput_tok_per_sec": 36.6,
  "mfu_pct": 0.0176,
  "mbu_pct": 26.89,
  "ipw": 0.00112,
  "ipj": 0.000007
}
```

| Champ | Type | Description |
|-------|------|-------------|
| `record_id` | str | Identifiant unique de l'échantillon |
| `benchmark` | str | Nom du benchmark |
| `model` | str | Identifiant du modèle |
| `backend` | str | Moteur utilisé |
| `model_answer` | str | La sortie brute du modèle |
| `is_correct` | bool ou null | Résultat de la notation (`null` si non noté) |
| `score` | float ou null | Note chiffrée (1.0 juste, 0.0 faux, `null` non noté) |
| `latency_seconds` | float | Latence de l'inférence |
| `prompt_tokens` | int | Jetons consommés en entrée |
| `completion_tokens` | int | Jetons produits en sortie |
| `cost_usd` | float | Coût estimé, en dollars américains |
| `error` | str ou null | Message d'erreur si l'échantillon a échoué |
| `scoring_metadata` | dict | Détails propres au correcteur (lettres extraites, sortie du juge, etc.) |
| `ttft` | float | Temps jusqu'au premier jeton, en secondes (0.0 si indisponible) |
| `energy_joules` | float | Énergie GPU consommée par cet échantillon (joules) |
| `power_watts` | float | Puissance GPU moyenne pendant l'inférence (watts) |
| `gpu_utilization_pct` | float | Pourcentage moyen d'utilisation du GPU |
| `throughput_tok_per_sec` | float | Débit de jetons en sortie (jetons par seconde) |
| `mfu_pct` | float | Taux d'utilisation des FLOPs du modèle, en pourcentage (demande les paramètres matériels du modèle) |
| `mbu_pct` | float | Taux d'utilisation de la bande passante mémoire, en pourcentage (demande les paramètres matériels du modèle) |
| `ipw` | float | Intelligence par watt : `accuracy / power_watts` (0 si la réponse est fausse ou si la puissance n'est pas mesurée) |
| `ipj` | float | Intelligence par joule : `accuracy / energy_joules` (0 si la réponse est fausse ou si l'énergie n'est pas mesurée) |

### Le fichier de résumé JSON

Une fois tous les échantillons traités, un fichier de résumé est écrit à côté du JSONL, en `{output_path}.summary.json` :

```json title="results/supergpqa_qwen3-8b.jsonl.summary.json"
{
  "benchmark": "supergpqa",
  "category": "reasoning",
  "backend": "diapason-direct",
  "model": "qwen3:8b",
  "total_samples": 200,
  "scored_samples": 198,
  "correct": 143,
  "accuracy": 0.7222,
  "errors": 2,
  "mean_latency_seconds": 1.4821,
  "total_cost_usd": 0.0,
  "per_subject": {
    "chemistry": {"accuracy": 0.74, "total": 50.0, "scored": 50.0, "correct": 37.0},
    "mathematics": {"accuracy": 0.68, "total": 50.0, "scored": 49.0, "correct": 33.0}
  },
  "started_at": 1708789200.0,
  "ended_at": 1708789496.3,
  "accuracy_stats": {"mean": 0.72, "median": 1.0, "min": 0.0, "max": 1.0, "std": 0.45},
  "energy_stats": {"mean": 140792.95, "median": 135112.79, "min": 3926.17, "max": 1806568.12, "std": 156038.54},
  "power_stats": {"mean": 892.98, "median": 898.19, "min": 811.50, "max": 1104.90, "std": 42.65},
  "gpu_utilization_stats": {"mean": 47.41, "median": 47.45, "min": 42.38, "max": 56.23, "std": 2.72},
  "throughput_stats": {"mean": 36.55, "median": 37.22, "min": 26.22, "max": 45.03, "std": 5.00},
  "mfu_stats": {"mean": 0.0176, "median": 0.0179, "min": 0.0126, "max": 0.0216, "std": 0.0024},
  "mbu_stats": {"mean": 26.89, "median": 27.38, "min": 19.29, "max": 33.13, "std": 3.68},
  "ipw_stats": {"mean": 0.00113, "median": 0.00112, "min": 0.00100, "max": 0.00123, "std": 0.00005},
  "ipj_stats": {"mean": 0.00003, "median": 0.00001, "min": 0.000002, "max": 0.00021, "std": 0.00004},
  "total_energy_joules": 28158590.26
}
```

Quand `telemetry = true` et `gpu_metrics = true` sont posés dans `[run]`, le résumé contient un `MetricStats` (moyenne, médiane, min, max, écart-type) pour chaque métrique de télémétrie, plus `total_energy_joules`. Ces statistiques valent `null` quand la métrique n'a aucune valeur.

La répartition `per_subject` groupe les résultats par le champ de sujet ou de catégorie du jeu de données, qui change d'un benchmark à l'autre :

- **SuperGPQA** : `subfield`, `field` ou `discipline`
- **GAIA** : le niveau de difficulté (`level_1`, `level_2`, `level_3`)
- **FRAMES** : le ou les types de raisonnement (par ex. `temporal`, `intersection`)
- **WildChat** : toujours `"conversation"`

---

## Les méthodes de notation

Chaque benchmark a un correcteur accordé à son format de réponse.

### SuperGPQA : extraction de QCM assistée par LLM

Les réponses de SuperGPQA sont du texte libre, qui doit contenir l'une des lettres d'option valides (A, B, C, D, …). Le correcteur demande au LLM juge d'extraire la lettre de la réponse finale, puis la compare à la lettre de référence, caractère pour caractère.

Le juge reçoit l'énoncé d'origine et la réponse du modèle, et on lui demande de ne rendre qu'une seule lettre. Cela couvre le cas du modèle qui raisonne longuement avant d'énoncer sa réponse finale.

```
is_correct = extracted_letter == reference_letter
```

Les métadonnées de notation contiennent `reference_letter`, `candidate_letter` et `valid_letters`.

### GAIA : correspondance exacte normalisée, avec repli sur le LLM

Les réponses de GAIA sont le plus souvent des nombres, des expressions courtes ou des listes séparées par des virgules. Le correcteur normalise avant de comparer :

- **Les nombres** : retrait de `$`, `%` et `,`, puis conversion en flottant pour la comparaison
- **Les listes** : découpage sur `,`/`;` et comparaison élément par élément (avec détection du type de chaque élément)
- **Les chaînes** : passage en minuscules, retrait des espaces et de la ponctuation

Si la correspondance exacte échoue après normalisation, le correcteur se replie sur le LLM juge, qui rend une réponse structurée avec `extracted_final_answer`, `reasoning` et `correct: yes/no`. Ce repli rattrape les différences d'unités, les formulations autres, et les réponses équivalentes mais écrites autrement.

### FRAMES : le LLM en juge (justesse factuelle)

FRAMES passe par un LLM juge, qui évalue l'équivalence de sens entre la réponse du modèle et la vérité de référence. Le juge reçoit la question, la vérité de référence et la réponse prédite, puis rend un verdict structuré :

```
extracted_final_answer: <extracted answer>
reasoning: <brief explanation>
correct: yes / no
```

Le correcteur lit la ligne `correct:` et, si le format structuré manque, se rabat sur la présence des jetons `TRUE`/`FALSE`.

### WildChat : comparaison par paire, jugée par un LLM

WildChat n'a pas de réponse « juste » unique : il mesure la qualité d'une réponse de discussion. Le correcteur lance une **double comparaison par paire** :

1. Le juge évalue le couple (réponse du modèle en A, référence en B) et rend un jeton de verdict : `[[A>>B]]`, `[[A>B]]`, `[[A=B]]`, `[[B>A]]` ou `[[B>>A]]`.
2. Le juge évalue ensuite le couple inverse (référence en A, réponse du modèle en B) et rend un second verdict.

Le modèle est réputé avoir réussi (`is_correct = True`) s'il gagne ou fait match nul dans l'une ou l'autre des comparaisons. La double comparaison réduit le biais de position du juge.

Le juge suit une grille en plusieurs étapes, qui sépare les demandes subjectives — notées sur la justesse, l'utilité, la pertinence, la concision et la créativité — des demandes objectives ou techniques, notées sur la seule justesse.

!!! tip "Lire une exactitude WildChat"
    Une exactitude WildChat de 0,50 veut dire que le modèle a égalé ou battu la réponse de référence dans la moitié des comparaisons. Comme la réponse de référence vient du jeu de données d'origine — qui peut contenir des réponses de modèles très capables —, un score au-dessus de 0,50 signale une bonne qualité de discussion sur cet échantillonnage.

---

## L'exécution en parallèle

`EvalRunner` traite les échantillons en concurrence, par un `ThreadPoolExecutor`. Les résultats sont écrits au fil de l'eau dans le fichier JSONL, à mesure que chaque échantillon se termine : tu peux donc regarder les résultats partiels pendant une longue exécution.

```bash
# Plus de fils, évaluation plus rapide (si le moteur encaisse les requêtes en parallèle)
uv run python -m diapason.evals run -b supergpqa -m qwen3:8b -w 8 -n 500
```

!!! warning "Nombre de fils et charge du moteur"
    Augmenter le nombre de fils n'augmente le débit que si le moteur d'inférence encaisse des requêtes concurrentes. Une instance Ollama locale en tient 1 à 2. Les API distantes (OpenAI, Anthropic) en tiennent bien plus. Règle `-w` sur le parallélisme réel de ton moteur.

---

## Voir aussi

- [Benchmarks](benchmarks.md) — Mesurer la latence et le débit du moteur d'inférence
- [Télémétrie et traces](telemetry.md) — Enregistrer et analyser les métriques d'inférence venues de l'usage réel
- [Agents](agents.md) — Configurer l'`OrchestratorAgent` utilisé par le moteur `diapason-agent`
- [Outils](tools.md) — Les outils disponibles pour les évaluations avec agent
- [SDK Python](python-sdk.md) — Accès par programme à l'inférence et aux agents de Diapason
