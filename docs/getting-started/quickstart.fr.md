---
title: Démarrage rapide
description: Mettre Diapason en marche en quelques minutes
search:
  boost: 3
---

# Démarrage rapide

!!! tip "Lancer les commandes `diapason`"
    Chaque exemple `diapason ...` ci-dessous suppose que tu as activé le venv du projet
    (`source .venv/bin/activate`) ou que tu préfixes chaque commande par `uv run`. Un
    `diapason init --preset ...` tout nu, depuis un clone frais, échoue sur un
    `command not found`.

## Ce que tu peux construire

Diapason est un cadriciel modulaire d'assistant IA. Voici ce que les développeurs en font :

=== "Discuter avec n'importe quel modèle"

    ```bash
    diapason ask "Explique l'intrication quantique" -m qwen3.5:4b   # prends qwen3.5:9b ou plus gros sur GPU
    ```

=== "Agent + outils"

    ```bash
    diapason ask --agent orchestrator --tools calculator,web_search "Quel est le PIB de la France en dollars américains ?"
    ```

=== "Indexer des documents et poser une question"

    ```bash
    diapason memory index ./docs/
    diapason ask "Comment configurer le moteur ?"
    ```

    !!! warning "L'extension Rust est nécessaire"
        `diapason memory index` et `diapason memory search` importent `diapason_rust`. Si tu
        as sauté l'étape `uv run maturin develop -m rust/crates/diapason-python/Cargo.toml`
        de l'[installation](installation.md), ces commandes échouent sur un
        `ModuleNotFoundError: No module named 'diapason_rust'`. Construis l'extension
        une fois, et n'importe quel préréglage (`deep-research` compris) marchera.

=== "Le SDK Python en 5 lignes"

    ```python
    from diapason import Diapason
    with Diapason() as j:
        print(j.ask("Bonjour !"))
    ```

=== "Serveur d'API"

    ```bash
    diapason serve --port 8000
    # Sers-toi ensuite de n'importe quel client compatible OpenAI
    ```

=== "Le point du matin"

    ```bash
    cp configs/diapason/examples/morning-digest-mac.toml ~/.diapason/config.toml
    diapason connect gdrive       # un seul passage OAuth pour Gmail, Agenda et Tâches
    CARTESIA_API_KEY="..." diapason digest --fresh
    # Lit à voix haute le point du jour : courriels, agenda, santé et actualités
    ```

=== "Recherche approfondie"

    ```bash
    diapason init --preset deep-research
    diapason memory index ~/Documents/papers/
    diapason ask "Résume tous les documents sur les architectures transformeur"
    # Recherche à sauts multiples dans tes documents indexés, avec les sources
    ```

=== "Assistant de code"

    ```bash
    diapason init --preset code-assistant
    diapason ask "Écris un script Python qui analyse des fichiers CSV"
    # L'agent orchestrator, avec exécution de code, lecture et écriture de fichiers, et accès au shell
    ```

=== "Surveillance programmée"

    ```bash
    diapason init --preset scheduled-monitor
    diapason memory index ~/Documents/
    diapason scheduler start
    diapason scheduler create \
      --prompt "Cherche les nouveaux courriels au sujet du Projet X" \
      --schedule "0 9 * * 1-5" --agent operative
    # Un agent persistant, lancé selon une programmation cron
    ```

Pour des motifs complets à copier-coller, voir [Extraits de code](snippets.md).

## Les configurations de départ

Copie l'une d'elles dans `~/.diapason/config.toml` pour obtenir un montage déjà réglé :

| Configuration | Pour | Ce qu'elle fait |
|--------|-----|-------------|
| [`chat-simple.toml`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/configs/diapason/examples/chat-simple.toml) | N'importe quelle machine | Discussion légère, sans outils — le montage le plus simple |
| [`code-assistant.toml`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/configs/diapason/examples/code-assistant.toml) | N'importe quelle machine | L'agent orchestrator, avec exécution de code, fichiers et shell |
| [`deep-research.toml`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/configs/diapason/examples/deep-research.toml) | N'importe quelle machine | Recherche à sauts multiples dans les documents indexés, avec les sources |
| [`scheduled-monitor.toml`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/configs/diapason/examples/scheduled-monitor.toml) | N'importe quelle machine | L'agent operative, persistant, sur une programmation cron |
| [`morning-digest-mac.toml`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/configs/diapason/examples/morning-digest-mac.toml) | Mac (Apple Silicon) | Le point du jour à voix haute : courriels, agenda, santé, actualités |
| [`morning-digest-linux.toml`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/configs/diapason/examples/morning-digest-linux.toml) | Linux / serveur GPU | Le même, avec la prise en charge de vLLM |
| [`morning-digest-minimal.toml`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/configs/diapason/examples/morning-digest-minimal.toml) | N'importe quelle machine | Gmail et Agenda, rien de plus |

Ou génère une configuration qui inclut déjà le point du matin :

```bash
diapason init --digest
```

Ce guide parcourt les usages de fond de Diapason : l'app navigateur, la CLI, le SDK Python, les agents avec outils, la mémoire, les mesures de performance et le serveur d'API.

!!! info "Ce qu'il te faut d'abord"
    Assure-toi d'avoir [installé Diapason](installation.md) et d'avoir au moins un moteur d'inférence en marche (`ollama serve`, par exemple).

## L'app navigateur

Le chemin le plus rapide pour découvrir Diapason, c'est l'interface de discussion complète dans ton navigateur :

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
./scripts/quickstart.sh
```

Cela démarre le serveur d'API et une interface React sur [http://localhost:5173](http://localhost:5173).
Tu obtiens une interface façon ChatGPT, avec des réponses au fil de l'eau, l'usage des outils, le suivi de consommation et un tableau de bord de télémétrie — le tout sur ta machine.

La recherche web fonctionne par le repli DuckDuckGo intégré. Pour utiliser
Tavily, ajoute `TAVILY_API_KEY` sous **Réglages → Outils → Recherche web** une fois
l'app démarrée, ou exporte-la avant de lancer quickstart :

```bash
export TAVILY_API_KEY="tvly-..."
./scripts/quickstart.sh
```

Le script ne source pas les fichiers `.env` tout seul. Lance `source .env`
d'abord si c'est là que tu gardes la clé. Arrête tout serveur Diapason déjà en
marche avant de relancer, pour qu'il hérite de l'environnement à jour.

Pour arrêter tous les services, presse ++ctrl+c++ dans le terminal.

!!! tip "Variable d'environnement"
    Pose `DIAPASON_MODEL` pour changer le modèle par défaut : `DIAPASON_MODEL=deepseek-r1:14b ./scripts/quickstart.sh`

## Initialiser la configuration

Commence par détecter ton matériel et générer un fichier de configuration :

```bash
diapason init
```

Cela lance la détection automatique du matériel (fabricant de la carte graphique, VRAM, processeur, mémoire vive) et écrit un fichier de configuration dans `~/.diapason/config.toml`, avec des valeurs raisonnables pour ton système. La commande choisit aussi le moteur d'inférence recommandé.

```
Detecting hardware...
  Platform : linux
  CPU      : AMD EPYC 7763 (128 cores)
  RAM      : 512.0 GB
  GPU      : NVIDIA A100 (80.0 GB VRAM, x8)

Config written successfully.
```

Pour écraser une configuration existante :

```bash
diapason init --force
```

Voir [Configuration](configuration.md) pour la référence complète.

## Ta première question

### Depuis la CLI

Le plus simple, pour parler à Diapason, c'est la commande `ask` :

```bash
diapason ask "Quelle est la capitale de la France ?"
```

Diapason détecte tout seul un moteur en marche, choisit un modèle selon la politique de routage configurée et rend la réponse.

#### Les options de la CLI

| Option | Description | Exemple |
|--------|-------------|---------|
| `-m`, `--model` | Remplace le choix du modèle | `diapason ask -m qwen3:8b "Bonjour"` |
| `-e`, `--engine` | Force un moteur précis | `diapason ask -e ollama "Bonjour"` |
| `-t`, `--temperature` | Température d'échantillonnage (défaut : 0.7) | `diapason ask -t 0.2 "Bonjour"` |
| `--max-tokens` | Nombre maximum de jetons à générer (défaut : 1024) | `diapason ask --max-tokens 2048 "Bonjour"` |
| `--json` | Rend le résultat JSON brut | `diapason ask --json "Bonjour"` |
| `--no-stream` | Coupe le fil de l'eau | `diapason ask --no-stream "Bonjour"` |
| `--no-context` | Coupe l'injection du contexte mémoire | `diapason ask --no-context "Bonjour"` |
| `-a`, `--agent` | Utilise un agent | `diapason ask -a orchestrator "Bonjour"` |
| `--tools` | Outils séparés par des virgules | `diapason ask --tools calculator,think "2+2"` |
| `--router` | Politique de routage pour le choix du modèle | `diapason ask --router heuristic "Bonjour"` |

### Depuis le SDK Python

La classe `Diapason` offre une interface Python de haut niveau :

```python
from diapason import Diapason

j = Diapason()
response = j.ask("Quelle est la capitale de la France ?")
print(response)
j.close()
```

Pour un résultat détaillé, avec la consommation de jetons et les informations de modèle :

```python
result = j.ask_full("Quelle est la capitale de la France ?")
print(result["content"])  # Le texte de la réponse
print(result["model"])    # Le modèle qui a traité la question
print(result["engine"])   # Le moteur qui a fait l'inférence
print(result["usage"])    # Les statistiques de consommation de jetons
```

#### Les options du constructeur du SDK

```python
# Utiliser la configuration par défaut (matériel détecté, ~/.diapason/config.toml)
j = Diapason()

# Imposer le modèle
j = Diapason(model="qwen3:8b")

# Imposer le moteur
j = Diapason(engine_key="ollama")

# Utiliser un fichier de configuration à soi
j = Diapason(config_path="/path/to/config.toml")
```

!!! warning "Appelle toujours `close()`"
    L'instance `Diapason` garde des références vers les dépôts de télémétrie et les backends de mémoire. Appelle `j.close()` quand tu as fini, pour libérer les ressources.

## Se servir des agents et de leurs outils

Les agents ajoutent le raisonnement sur plusieurs tours et l'appel d'outils. L'agent `orchestrator` fait tourner une boucle d'appel d'outils, et invoque ce qu'il faut pour répondre à la question.

### Les agents disponibles

| Agent | Description |
|-------|-------------|
| `simple` | Un seul tour, sans outils. Envoie la question droit au modèle. |
| `orchestrator` | Boucle d'appel d'outils sur plusieurs tours. Invoque les outils l'un après l'autre jusqu'à tenir une réponse. |
| `custom` | Un gabarit pour ta propre logique d'agent. |
| `operative` | Agent orienté tâches, avec planification et exécution structurées. |

### Les outils intégrés

| Outil | Description |
|------|-------------|
| `calculator` | Évaluation sûre d'expressions mathématiques (fondée sur l'AST). |
| `think` | Brouillon de raisonnement, pour la chaîne de pensée. |
| `retrieval` | Cherche dans la mémoire le contexte pertinent. |
| `llm` | Pose des sous-questions à un autre modèle. |
| `file_read` | Lit des fichiers, avec validation du chemin. |
| `web_search` | Recherche web par l'API Tavily (réclame l'extra `tools-search`). |

### Exemple en CLI

```bash
diapason ask --agent orchestrator --tools calculator,think "Combien font 137 * 42 ?"
```

### Exemple avec le SDK

```python
from diapason import Diapason

j = Diapason()
result = j.ask_full(
    "Quelle est la racine carrée de 144 ?",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(result["content"])
print(result["tool_results"])  # La liste des appels d'outils et de leurs résultats
print(result["turns"])         # Le nombre de tours d'agent
j.close()
```

## La mémoire : indexer et chercher

Le système de mémoire te laisse indexer des documents, puis injecte automatiquement le contexte pertinent dans tes questions.

### Indexer des documents

Indexe un fichier ou un dossier. Diapason découpe le contenu en morceaux et les range dans le backend de mémoire configuré (SQLite/FTS5 par défaut).

=== "CLI"

    ```bash
    # Indexer un dossier
    diapason memory index ./docs/

    # Indexer un seul fichier, avec une taille de morceau à soi
    diapason memory index ./paper.txt --chunk-size 256 --chunk-overlap 32
    ```

=== "SDK Python"

    ```python
    from diapason import Diapason

    j = Diapason()
    result = j.memory.index("./docs/", chunk_size=512, chunk_overlap=64)
    print(f"{result['chunks']} morceaux indexés")
    j.close()
    ```

### Chercher dans la mémoire

Interroge la mémoire pour trouver les morceaux pertinents :

=== "CLI"

    ```bash
    diapason memory search "options de configuration"
    diapason memory search -k 10 "comment déployer"
    ```

=== "SDK Python"

    ```python
    results = j.memory.search("options de configuration", top_k=5)
    for r in results:
        print(f"[{r['score']:.4f}] {r['source']}: {r['content'][:100]}")
    ```

### Consulter les statistiques de la mémoire

=== "CLI"

    ```bash
    diapason memory stats
    ```

=== "SDK Python"

    ```python
    stats = j.memory.stats()
    print(f"Backend : {stats['backend']}, documents : {stats.get('count', 'N/A')}")
    ```

### L'injection automatique de contexte

Quand tu as indexé des documents, Diapason injecte tout seul le contexte pertinent dans tes questions. Le système de mémoire cherche les morceaux qui correspondent à la question et les place en tête, comme contexte système, avant l'envoi au modèle.

Pour couper ce comportement :

=== "CLI"

    ```bash
    diapason ask --no-context "Bonjour"
    ```

=== "SDK Python"

    ```python
    response = j.ask("Bonjour", context=False)
    ```

L'injection de contexte est pilotée par `agent.context_from_memory` dans `config.toml`. Les paramètres de récupération (`context_top_k`, `context_min_score`, `context_max_tokens`) vivent sous `[tools.storage]`. Voir [Configuration](configuration.md) pour le détail.

## La gestion des modèles

### Lister les modèles disponibles

Voir tous les modèles offerts par les moteurs en marche :

```bash
diapason model list
```

Cela produit une table qui montre chaque modèle, son moteur, son nombre de paramètres, sa longueur de contexte et la VRAM nécessaire.

### Obtenir le détail d'un modèle

```bash
diapason model info qwen3:8b
```

### Télécharger un modèle (Ollama)

```bash
diapason model pull qwen3:8b
```

### Lister les modèles depuis le SDK

```python
from diapason import Diapason

j = Diapason()
models = j.list_models()
engines = j.list_engines()
print(f"Modèles : {models}")
print(f"Moteurs : {engines}")
j.close()
```

## Mesurer les performances

Le cadriciel de mesure évalue la latence et le débit de l'inférence sur ton moteur.

=== "Toutes les mesures"

    ```bash
    diapason bench run
    ```

=== "Une mesure précise"

    ```bash
    diapason bench run -b latency
    diapason bench run -b throughput
    ```

=== "Des options à soi"

    ```bash
    # 20 échantillons, sortie JSON
    diapason bench run -n 20 --json

    # Un modèle et un moteur précis, écriture dans un fichier
    diapason bench run -m qwen3:8b -e ollama -o results.jsonl
    ```

Exemple de sortie :

```
Running 2 benchmark(s) on ollama/qwen3:8b (10 samples)...

latency (10 samples, 0 errors)
  mean_ms: 245.3200
  p50_ms: 238.1000
  p95_ms: 312.4500
  min_ms: 201.2000
  max_ms: 345.6000

throughput (10 samples, 0 errors)
  tokens_per_second: 42.1500
  total_tokens: 4215
  total_seconds: 100.0000
```

## Démarrer le serveur d'API

Diapason offre un serveur d'API compatible OpenAI, pour s'intégrer aux outils et aux interfaces qui existent déjà.

!!! note "L'extra `server` est nécessaire"
    ```bash
    uv sync --extra server
    ```

### Démarrer le serveur

```bash
diapason serve --port 8000
```

Avec des options à soi :

```bash
diapason serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b --agent orchestrator
```

### Les routes de l'API

| Route | Méthode | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | `POST` | Complétions de discussion (au fil de l'eau ou non) |
| `/v1/models` | `GET` | Liste les modèles disponibles |
| `/health` | `GET` | Contrôle de santé |

### Se servir de n'importe quel client compatible OpenAI

Une fois le serveur en marche, pointe n'importe quel client compatible OpenAI dessus :

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")
response = client.chat.completions.create(
    model="qwen3:8b",
    messages=[{"role": "user", "content": "Bonjour !"}],
)
print(response.choices[0].message.content)
```

Ou avec `curl` :

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:8b",
    "messages": [{"role": "user", "content": "Bonjour !"}]
  }'
```

## La télémétrie

Diapason enregistre la télémétrie de chaque appel d'inférence (durées, jetons, coût). Pour voir les statistiques agrégées :

```bash
diapason telemetry stats
```

Exporter les données de télémétrie :

```bash
diapason telemetry export --format json
diapason telemetry export --format csv -o telemetry.csv
```

Effacer tous les enregistrements de télémétrie :

```bash
diapason telemetry clear --yes
```

## Un exemple complet, de bout en bout

Voici une séance complète, qui combine plusieurs fonctions :

```python
from diapason import Diapason

# Initialiser avec les valeurs par défaut (matériel et moteur détectés tout seuls)
j = Diapason()

# 1. Indexer de la documentation
index_result = j.memory.index("./docs/", chunk_size=512)
print(f"{index_result['chunks']} morceaux indexés depuis {index_result['path']}")

# 2. Chercher dans la mémoire
results = j.memory.search("comment configurer les moteurs")
for r in results:
    print(f"  [{r['score']:.3f}] {r['source']}")

# 3. Poser une question (le contexte mémoire est injecté tout seul)
answer = j.ask("Comment configurer l'hôte du moteur Ollama ?")
print(f"\nRéponse : {answer}")

# 4. Utiliser un agent avec des outils
calc_result = j.ask_full(
    "Calcule les intérêts composés sur 10 000 $ à 5 % pendant 10 ans",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(f"\nCalcul : {calc_result['content']}")
print(f"Outils utilisés : {[t['tool_name'] for t in calc_result['tool_results']]}")
print(f"Tours d'agent : {calc_result['turns']}")

# 5. Lister les modèles disponibles
models = j.list_models()
print(f"\nModèles disponibles : {models}")

# 6. Faire le ménage
j.close()
```

## Pour aller plus loin

- [Configuration](configuration.md) — Régler finement les hôtes de moteur, le routage des modèles, la mémoire, et le reste
- [Référence de la ligne de commande](../user-guide/cli.md) — La référence complète des commandes et de leurs options
- [SDK Python](../user-guide/python-sdk.md) — La documentation détaillée du SDK
- [Vue d'ensemble de l'architecture](../architecture/overview.md) — Comprendre la conception à cinq primitives
