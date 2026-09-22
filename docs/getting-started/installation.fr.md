---
title: Installation
description: Mettre Diapason en marche — app navigateur, app de bureau, CLI ou SDK Python
search:
  boost: 3
---

# Installation

Diapason tourne entièrement sur ta machine. Choisis l'interface qui te convient.

---

## L'app navigateur

Lance l'interface de discussion complète dans ton navigateur. Tout reste local — le
serveur tourne sur ta machine et l'interface s'y connecte par `localhost`.

### Installation en une commande

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
./scripts/quickstart.sh
```

Le script s'occupe de tout :

1. Vérifie que Python 3.10+ et Node.js 18+ sont présents
2. Installe Ollama s'il manque et télécharge un premier modèle
3. Installe les dépendances Python et celles de l'interface
4. Démarre le serveur d'API et le serveur de développement de l'interface
5. Ouvre `http://localhost:5173` dans ton navigateur

### Installation pas à pas

Si tu préfères faire chaque étape toi-même :

=== "Étape 1 : cloner et installer"

    ```bash
    git clone https://github.com/carlitoetienne01-spec/Diapason.git
    cd Diapason
    uv sync --extra desktop
    uv run maturin develop -m rust/crates/diapason-python/Cargo.toml
    cd frontend && npm install && cd ..
    ```

    !!! note "Ce qu'il te faut d'abord"
        [Rust](https://rustup.rs/) est nécessaire (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`).
        Sur Python 3.14+, pose `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` avant la commande `maturin`.

=== "Étape 2 : démarrer Ollama"

    ```bash
    # À installer depuis https://ollama.com si ce n'est pas déjà fait
    ollama serve &
    ollama pull qwen3:0.6b
    ```

=== "Étape 3 : démarrer le serveur"

    ```bash
    uv run diapason serve --port 8000
    ```

=== "Étape 4 : démarrer l'interface"

    ```bash
    cd frontend
    npm run dev
    ```

Ouvre ensuite [http://localhost:5173](http://localhost:5173).

---

## L'app de bureau

L'app de bureau est une fenêtre native pour l'interface de discussion de Diapason.
L'inférence et tout le traitement se font sur ta machine — l'app se connecte au
serveur que tu démarres chez toi.

### Mise en place

**Étape 1.** Démarre le serveur (comme pour l'app navigateur) :

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
./scripts/quickstart.sh
```

**Étape 2.** Construis et ouvre l'app de bureau depuis le clone authentifié.

Il n'y a pour l'instant aucun installateur publié : la liste des releases GitHub
est vide, et les anciens liens `desktop-v1.0.2` n'existaient pas. Sur macOS,
sers-toi de l'installateur local, celui qui est vérifié :

```bash
./scripts/install-desktop.sh
```

Sur Windows, lance d'abord `deploy/windows/install.ps1`. Il prépare le serveur
dans `%LOCALAPPDATA%\Diapason\src` ; l'application Tauri détecte désormais cet
emplacement exact. Un `.msi` distribuable ne sera annoncé qu'après une
construction et un essai de bout en bout sur le vrai PC Windows.

L'app se connecte à un serveur `http://localhost:8000` déjà en marche, ou démarre
celui du projet installé.

!!! warning "macOS : « l'app est endommagée »"
    Si macOS dit que l'app est endommagée, lève le drapeau de quarantaine de Gatekeeper :
    ```bash
    xattr -cr /Applications/Diapason.app
    ```
    C'est le cas courant des apps open-source distribuées hors de l'App Store.

### Construire depuis les sources

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason/frontend
npm install
npm run tauri:build
```

L'installateur construit se trouvera dans `frontend/src-tauri/target/release/bundle/`.

---

## La ligne de commande

La ligne de commande est le chemin le plus direct pour se servir de Diapason par
programme. Tout est accessible depuis le terminal.

### Installer

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync
uv run maturin develop -m rust/crates/diapason-python/Cargo.toml
```

[Rust](https://rustup.rs/) est nécessaire. Sur Python 3.14+, pose `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` avant la commande `maturin`.

### Vérifier

```bash
diapason --version
# diapason, version 0.1.0
```

### Premières commandes

```bash
diapason ask "Quelle est la capitale de la France ?"

diapason ask --agent orchestrator --tools calculator "Combien font 137 * 42 ?"

diapason serve --port 8000

diapason doctor

diapason model list

diapason chat
```

!!! info "Un moteur d'inférence est nécessaire"
    La CLI a besoin d'un moteur d'inférence en marche (Ollama, par exemple). Voir
    [Mettre en place un moteur d'inférence](#setting-up-an-inference-backend) plus bas.

---

## Le SDK Python

Pour un accès par programme, la classe `Diapason` offre une API synchrone de haut niveau.

### Installer

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync
uv run maturin develop -m rust/crates/diapason-python/Cargo.toml
```

[Rust](https://rustup.rs/) est nécessaire. Sur Python 3.14+, pose `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` avant la commande `maturin`.

### Exemple minimal

```python
from diapason import Diapason

j = Diapason()
print(j.ask("Explique le tri rapide en deux phrases."))
j.close()
```

### Avec des agents et des outils

```python
result = j.ask_full(
    "Quelle est la racine carrée de 144 ?",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(result["content"])       # « 12 »
print(result["tool_results"])  # les appels d'outils
print(result["turns"])         # le nombre de tours d'agent
```

### La couche de composition

Pour tout contrôler, passe par `SystemBuilder` :

```python
from diapason import SystemBuilder

system = (
    SystemBuilder()
    .engine("ollama")
    .model("qwen3:8b")
    .agent("orchestrator")
    .tools(["calculator", "web_search", "file_read"])
    .enable_telemetry()
    .enable_traces()
    .build()
)

result = system.ask("Résume l'actualité de l'IA.")
system.close()
```

Voir le [guide du SDK Python](../user-guide/python-sdk.md) pour la référence complète de l'API.

---

## Ce qu'il te faut

| Il te faut | Version | Installation | Remarques |
|-------------|---------|---------|-------|
| Python | 3.10–3.13 | [python.org](https://www.python.org/downloads/) | Obligatoire. 3.14+ pas encore pris en charge (une dépendance centrale n'a pas de wheels 3.14). |
| uv | la dernière | `curl -LsSf https://astral.sh/uv/install.sh \| sh` ou `brew install uv` (macOS) | Gestionnaire de paquets et de projets Python |
| Git | n'importe laquelle | [git-scm.com](https://git-scm.com/) ou `brew install git` (macOS) | Obligatoire |
| Rust | stable | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` | Obligatoire pour l'extension Rust |
| Moteur d'inférence | n'importe lequel | Voir [plus bas](#setting-up-an-inference-backend) | Au moins l'un parmi Ollama, vLLM, llama.cpp, SGLang, ou une API distante |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) ou `brew install node` (macOS) | Obligatoire pour l'interface navigateur ; 22+ pour la passerelle du canal WhatsApp Baileys |

!!! tip "Sous macOS"
    Voir le [guide d'installation macOS](macos.md) pour une marche à suivre complète,
    pas à pas : Homebrew, uv, Rust, llama.cpp et les pièges courants.

## Les extras facultatifs

Diapason se sert d'extras facultatifs pour garder l'installation de base légère.

### Les moteurs d'inférence

| Extra | Commande d'installation | Description |
|-------|----------------|-------------|
| `inference-cloud` | `uv sync --extra inference-cloud` | Les API d'OpenAI et d'Anthropic |
| `inference-google` | `uv sync --extra inference-google` | L'API Google Gemini |

!!! note "Ollama, vLLM et llama.cpp passent par HTTP"
    Ces moteurs n'ajoutent aucune dépendance Python — Diapason leur parle en HTTP. Il te faut quand même le logiciel du moteur en marche sur ta machine.

### Les moteurs de mémoire

| Extra | Commande d'installation | Description |
|-------|----------------|-------------|
| `memory-faiss` | `uv sync --extra memory-faiss` | Base vectorielle FAISS |
| `memory-colbert` | `uv sync --extra memory-colbert` | Recherche à interaction tardive ColBERTv2 |
| `memory-bm25` | `uv sync --extra memory-bm25` | Recherche creuse BM25 |

!!! tip "La mémoire SQLite est toujours là"
    Le moteur de mémoire SQLite/FTS5 par défaut n'a besoin d'aucune dépendance supplémentaire.

### Le serveur, et le reste

| Extra | Commande d'installation | Description |
|-------|----------------|-------------|
| `desktop` | `uv sync --extra desktop` | Le serveur de bureau et d'API, avec l'entrée vocale locale |
| `server` | `uv sync --extra server` | Le serveur d'API compatible OpenAI (`diapason serve`) |
| `dev` | `uv sync --extra dev` | Les outils de développement et de test |
| `docs` | `uv sync --extra docs` | Les outils de construction de la documentation |

On peut les combiner :

```bash
uv sync --extra desktop --extra memory-faiss --extra inference-cloud
```

## Mettre en place un moteur d'inférence {#setting-up-an-inference-backend}

Diapason a besoin d'au moins un moteur d'inférence. Choisis celui qui va avec ta machine.

### Ollama (recommandé)

Le plus simple pour commencer. Il télécharge les modèles et les sert tout seul.

1. Installe-le depuis [ollama.com](https://ollama.com)
2. Démarre le serveur et télécharge un modèle :

    ```bash
    ollama serve
    ollama pull qwen3:0.6b
    ```

3. Vérifie : `diapason model list`

!!! tip "Le meilleur choix pour : les Mac Apple Silicon, les cartes NVIDIA grand public, les machines sans carte graphique"

### vLLM

Un service à haut débit, optimisé pour les cartes graphiques de centre de données.

1. Installe-le en suivant le [guide officiel](https://docs.vllm.ai)
2. Démarre-le : `vllm serve Qwen/Qwen2.5-7B-Instruct`
3. Détecté tout seul sur `http://localhost:8000`

!!! tip "Le meilleur choix pour : les cartes NVIDIA de centre de données (A100, H100), les cartes AMD"

### llama.cpp

Une inférence efficace sur processeur comme sur carte graphique, avec des modèles quantifiés GGUF.

1. Construis-le depuis [github.com/ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp)
2. Démarre-le : `llama-server -m /path/to/model.gguf --port 8080`
3. Détecté tout seul sur `http://localhost:8080`

### Les API distantes

```bash
uv sync --extra inference-cloud --extra inference-google
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Pour aller plus loin

- [Démarrage rapide](quickstart.md) — lance ta première question
- [Configuration](configuration.md) — règle les hôtes des moteurs, l'aiguillage des modèles, la mémoire et le reste
