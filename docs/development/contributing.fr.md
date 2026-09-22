# Guide de contribution

Ce guide explique comment mettre en place un environnement de développement,
lancer les tests et contribuer du code à Diapason.

---

## Mettre en place l'environnement de développement

### Les prérequis

| Prérequis | Version | Notes |
|---|---|---|
| Python | 3.10+ | Obligatoire |
| [uv](https://docs.astral.sh/uv/) | La dernière | Gestionnaire de paquets |
| Node.js | 22+ | Nécessaire seulement pour ClaudeCodeAgent et le canal WhatsApp |

### Cloner et installer

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync --extra dev
```

Le paquet s'installe en mode éditable, avec toutes les dépendances de
développement (pytest, ruff, respx, pytest-asyncio, pytest-cov).

!!! tip "Les extras optionnels"
    Installe les extras des composants sur lesquels tu veux travailler :

    ```bash
    # Les mémoires
    uv sync --extra dev --extra memory-faiss --extra memory-colbert --extra memory-bm25

    # L'inférence cloud
    uv sync --extra dev --extra inference-cloud --extra inference-google

    # Le serveur d'API
    uv sync --extra dev --extra server

    # La documentation
    uv sync --extra dev --extra docs
    ```

### Vérifier l'installation

```bash
uv run diapason --version   # Doit afficher 0.1.0
uv run diapason --help      # Affiche toutes les sous-commandes
```

---

## Lancer les tests

Diapason utilise [pytest](https://docs.pytest.org/), avec plus d'un millier de
tests organisés par module.

### La suite complète

```bash
uv run pytest tests/ -v
```

### Lancer un fichier de tests précis

```bash
uv run pytest tests/core/test_registry.py -v
uv run pytest tests/engine/test_ollama.py -v
uv run pytest tests/memory/test_sqlite.py -v
```

### Lancer un test précis

```bash
uv run pytest tests/core/test_registry.py::test_register_and_get -v
```

### Lancer les tests d'un module

```bash
uv run pytest tests/agents/ -v       # Tous les tests d'agents
uv run pytest tests/tools/ -v        # Tous les tests d'outils
uv run pytest tests/learning/ -v     # Tous les tests d'apprentissage
```

### La couverture

```bash
uv run pytest tests/ --cov=diapason --cov-report=html
```

### Les marqueurs de tests

Les tests qui demandent du matériel particulier ou un service en marche sont
derrière des marqueurs pytest. Par défaut ils sont collectés, mais ils se
sautent proprement si ce qu'ils demandent manque.

| Marqueur | Description | Exemple |
|---|---|---|
| `live` | Demande un moteur d'inférence en marche (Ollama, vLLM, etc.) | `@pytest.mark.live` |
| `cloud` | Demande des clés d'API cloud (`OPENAI_API_KEY`, etc.) | `@pytest.mark.cloud` |
| `nvidia` | Demande une carte graphique NVIDIA | `@pytest.mark.nvidia` |
| `amd` | Demande une carte graphique AMD avec ROCm | `@pytest.mark.amd` |
| `apple` | Demande une puce Apple Silicon | `@pytest.mark.apple` |
| `slow` | Test long | `@pytest.mark.slow` |

Pour ne lancer que les tests d'un marqueur :

```bash
uv run pytest tests/ -m live -v          # Seulement les tests sur moteur en marche
uv run pytest tests/ -m "not slow" -v    # Saute les tests lents
uv run pytest tests/ -m "not cloud" -v   # Saute les tests cloud
```

!!! info "L'isolation des registres dans les tests"
    Le `conftest.py` des tests contient une fixture `autouse` qui vide tous
    les registres et remet le bus d'événements à zéro avant chaque test.
    L'isolation entre les tests est donc totale. Les modules dont les
    enregistrements doivent survivre à ce vidage emploient le motif
    `ensure_registered()` décrit plus bas.

---

## Le lint

Diapason passe par [Ruff](https://docs.astral.sh/ruff/) pour le lint, configuré
dans `pyproject.toml` :

```bash
uv run ruff check src/ tests/
```

La configuration Ruff vise Python 3.10 et active les jeux de règles suivants :

- **E** -- les erreurs pycodestyle
- **F** -- Pyflakes
- **I** -- isort (l'ordre des imports)
- **W** -- les avertissements pycodestyle

Corriger ce qui peut l'être automatiquement :

```bash
uv run ruff check src/ tests/ --fix
```

---

## Construire la documentation

Le site de documentation est bâti avec [MkDocs Material](https://squidfunnel.com/mkdocs-material/).

```bash
# Installer les dépendances de la documentation
uv sync --extra docs

# Servir en local, avec rechargement à chaud
uv run mkdocs serve --dev-addr 127.0.0.1:8001

# Construire le site statique
uv run mkdocs build
```

La configuration du site vit dans `mkdocs.yml`. Les pages de référence d'API
sont générées automatiquement à partir des docstrings par
[mkdocstrings](https://mkdocstrings.github.io/), au style NumPy.

---

## La structure du projet

Le code source est organisé sous `src/diapason/` :

```
src/diapason/
    __init__.py                 # Racine du paquet, __version__
    sdk.py                      # la classe Diapason — le SDK Python de haut niveau

    core/                       # Infrastructure partagée
        config.py               # DiapasonConfig, détection du matériel, chargeur TOML
        events.py               # le système publication/abonnement EventBus
        registry.py             # RegistryBase[T] et tous les registres typés
        types.py                # Message, ModelSpec, ToolResult, Trace, etc.

    intelligence/               # Gestion des modèles et aiguillage des requêtes
        model_catalog.py        # BUILTIN_MODELS, fonctions d'enregistrement et de fusion
        router.py               # HeuristicRouter, build_routing_context

    engine/                     # Les moteurs d'inférence
        _stubs.py               # la classe abstraite InferenceEngine
        _base.py                # EngineConnectionError, messages_to_dicts
        _discovery.py           # discover_engines, discover_models, get_engine
        _openai_compat.py       # l'enveloppe compatible OpenAI
        ollama.py               # OllamaEngine
        openai_compat_engines.py   # enregistrement piloté par les données (vLLM, SGLang, llama.cpp, MLX, LM Studio)
        cloud.py                # CloudEngine (OpenAI/Anthropic/Google)

    agents/                     # Les implémentations d'agents
        _stubs.py               # la classe abstraite BaseAgent, ToolUsingAgent, AgentContext, AgentResult
        simple.py               # SimpleAgent — un seul tour, sans outils
        orchestrator.py         # OrchestratorAgent — appels d'outils sur plusieurs tours (function_calling + structured)
        native_react.py         # NativeReActAgent — boucle Pensée-Action-Observation
        native_openhands.py     # NativeOpenHandsAgent — exécution de code façon CodeAct
        rlm.py                  # RLMAgent — modèle de langage récursif avec REPL persistante
        openhands.py            # OpenHandsAgent — enveloppe le vrai openhands-sdk
        react.py                # cale de compatibilité (ré-exporte NativeReActAgent)
        claude_code.py          # ClaudeCodeAgent — le SDK Claude Agent par un sous-processus Node.js
        claude_code_runner/     # le lanceur Node.js embarqué du SDK Claude Agent

    memory/                     # Les mémoires et la recherche
        _stubs.py               # la classe abstraite MemoryBackend, RetrievalResult
        sqlite.py               # SQLiteMemory — la mémoire par défaut, en FTS5
        faiss_backend.py        # la mémoire vectorielle FAISS
        colbert_backend.py      # la mémoire ColBERTv2
        bm25.py                 # la mémoire BM25
        hybrid.py               # la mémoire hybride (fusion RRF)
        chunking.py             # ChunkConfig, chunk_text
        context.py              # ContextConfig, inject_context
        ingest.py               # ingest_path, read_document

    tools/                      # Le système d'outils
        _stubs.py               # la classe abstraite BaseTool, ToolSpec, ToolExecutor
        calculator.py           # CalculatorTool — calcul sûr, par AST
        think.py                # ThinkTool — brouillon de raisonnement
        retrieval.py            # RetrievalTool — recherche en mémoire
        llm_tool.py             # LLMTool — appels à un sous-modèle
        file_read.py            # FileReadTool — lecture de fichier sûre
        web_search.py           # WebSearchTool
        code_interpreter.py     # CodeInterpreterTool

    learning/                   # Les politiques d'aiguillage et les fonctions de récompense
        _stubs.py               # les classes abstraites RouterPolicy et RewardFunction
        heuristic_policy.py     # branche HeuristicRouter sur le registre
        trace_policy.py         # TraceDrivenPolicy — apprend des traces
        grpo_policy.py          # GRPORouterPolicy — ébauche d'entraînement par renforcement
        heuristic_reward.py     # HeuristicRewardFunction

    traces/                     # L'enregistrement complet des interactions
        store.py                # TraceStore — persistance SQLite
        collector.py            # TraceCollector — enveloppe les agents
        analyzer.py             # TraceAnalyzer — requêtes agrégées

    telemetry/                  # La télémétrie de l'inférence
        store.py                # TelemetryStore — persistance SQLite
        aggregator.py           # TelemetryAggregator — statistiques par modèle et par moteur
        wrapper.py              # l'enveloppe instrumented_generate()

    bench/                      # Le banc de mesure
        _stubs.py               # la classe abstraite BaseBenchmark, BenchmarkSuite
        latency.py              # LatencyBenchmark
        throughput.py           # ThroughputBenchmark

    server/                     # Le serveur d'API compatible OpenAI
        app.py                  # la fabrique d'application FastAPI
        routes.py               # /v1/chat/completions, /v1/models, /health

    mcp/                        # La couche MCP (Model Context Protocol)

    cli/                        # Les commandes CLI, en Click
        __init__.py             # le groupe principal
        ask.py                  # diapason ask
        init_cmd.py             # diapason init
        model.py                # diapason model list/info
        memory_cmd.py           # diapason memory index/search/stats
        telemetry_cmd.py        # diapason telemetry stats/export/clear
        bench_cmd.py            # diapason bench run
        serve.py                # diapason serve
```

---

## Les conventions de code

### Le nom des fichiers

| Motif | Rôle | Exemples |
|---|---|---|
| `_stubs.py` | Définitions de classes abstraites et dataclasses | `engine/_stubs.py`, `agents/_stubs.py`, `tools/_stubs.py` |
| `_discovery.py` | Détection automatique et sondage | `engine/_discovery.py` |
| `_base.py` | Utilitaires partagés et ré-exports | `engine/_base.py` |
| `*_cmd.py` | Modules de commande CLI | `init_cmd.py`, `memory_cmd.py`, `bench_cmd.py` |

### Le motif de registre

Tous les composants extensibles passent par le motif de registre à décorateur.
On ajoute une implémentation en décorant une classe -- aucune fabrique à
modifier :

```python
from diapason.core.registry import EngineRegistry

@EngineRegistry.register("my_engine")
class MyEngine(InferenceEngine):
    ...
```

Les registres disponibles :

| Registre | Contient | Exemples de clés |
|---|---|---|
| `ModelRegistry` | des objets `ModelSpec` | `"qwen3:8b"`, `"llama3.1:70b"` |
| `EngineRegistry` | des classes `InferenceEngine` | `"ollama"`, `"vllm"`, `"llamacpp"` |
| `MemoryRegistry` | des classes `MemoryBackend` | `"sqlite"`, `"faiss"`, `"bm25"` |
| `AgentRegistry` | des classes `BaseAgent` | `"simple"`, `"orchestrator"` |
| `ToolRegistry` | des classes `BaseTool` | `"calculator"`, `"think"`, `"retrieval"` |
| `RouterPolicyRegistry` | des classes `RouterPolicy` | `"heuristic"`, `"learned"` |
| `BenchmarkRegistry` | des classes `BaseBenchmark` | `"latency"`, `"throughput"` |

### Les dépendances optionnelles

Les composants qui dépendent de paquets optionnels emploient le motif
`try/except ImportError`, pour échouer proprement quand la dépendance n'est
pas installée :

```python
# Dans __init__.py — l'import déclenche l'enregistrement
try:
    import diapason.memory.faiss_backend  # noqa: F401
except ImportError:
    pass
```

Le paquet se charge donc toujours, même si `faiss-cpu` ou une autre dépendance
optionnelle manque.

### Le motif `ensure_registered()`

Les modules du banc de mesure et de l'apprentissage s'enregistrent
paresseusement, pour que leurs entrées survivent au vidage des registres dans
les tests :

```python
def ensure_registered() -> None:
    """Enregistre le banc de latence s'il n'y est pas déjà."""
    if not BenchmarkRegistry.contains("latency"):
        BenchmarkRegistry.register_value("latency", LatencyBenchmark)
```

Le motif vérifie `contains()` avant d'enregistrer : on peut donc l'appeler
plusieurs fois sans lever d'erreur de clé en double.

### Les conventions de dataclass

- Mets `slots=True` sur toutes les dataclasses, pour économiser la mémoire :

```python
@dataclass(slots=True)
class BenchmarkResult:
    benchmark_name: str
    model: str
    ...
```

### Les annotations de type

- Toute signature de fonction porte des annotations de type
- Mets `from __future__ import annotations` en tête de chaque module
- Utilise `Optional[X]` pour ce qui peut être nul
- Utilise `Sequence` pour les collections en lecture seule, `List` pour celles qui changent

### Le style des imports

- Des imports absolus seulement (`from diapason.core.registry import ...`)
- Trie les imports avec `ruff` (les règles isort sont actives)
- Place `from __future__ import annotations` en tout premier import

---

## Les règles pour une PR

### Avant de soumettre

1. **Lance la suite de tests complète** et vérifie qu'il n'y a pas de régression :
    ```bash
    uv run pytest tests/ -v
    ```

2. **Lance le linter** et corrige tout ce qu'il signale :
    ```bash
    uv run ruff check src/ tests/
    ```

3. **Ajoute des tests** pour toute nouveauté. Mets-les dans le sous-dossier
   `tests/` correspondant (les tests d'un nouveau moteur vont dans
   `tests/engine/`, par exemple).

4. **Suis le motif de registre** pour tout nouveau composant extensible.

### Les messages de commit

- Emploie l'impératif (« Add FAISS memory backend », par exemple)
- Garde la première ligne sous 72 caractères
- Renvoie aux tickets ou aux PR concernés

### Ce qui fait une bonne PR

- **Ciblée** : une fonctionnalité, un correctif ou un remaniement par PR
- **Testée** : des tests unitaires qui couvrent les nouveaux chemins de code
- **Documentée** : mets à jour les docstrings et les pages de documentation si
  tu ajoutes de l'API publique
- **Rétrocompatible** : ne casse pas une interface existante sans en avoir
  discuté

### Ajouter un nouveau composant primitif

Pour ajouter un moteur, une mémoire, un agent, un outil, un banc de mesure ou
une politique d'aiguillage :

1. Implémente la classe abstraite correspondante
2. Enregistre-le avec le décorateur `@XRegistry.register("key")` qui convient
3. Ajoute un import dans le `__init__.py` du module (avec `try/except ImportError`
   si le composant a des dépendances optionnelles)
4. Ajoute des tests dans le sous-dossier `tests/` correspondant
5. Ajoute une entrée dans `pyproject.toml` sous `[project.optional-dependencies]`
   si le composant demande de nouveaux paquets

Voir la section [motif de registre](#registry-pattern) plus haut pour des
exemples complets.
