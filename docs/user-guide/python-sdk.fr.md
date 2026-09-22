---
title: SDK Python
description: Interface Python de haut niveau pour l'inférence locale, la mémoire et les flux d'agents
search:
  boost: 2
---

# SDK Python

Le SDK Python de Diapason offre une interface de haut niveau pour parler aux moteurs d'inférence locaux, gérer la mémoire et faire tourner des flux d'agents. Le point d'entrée principal est la classe `Diapason`.

## L'installation

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync
```

## Démarrage rapide

```python
from diapason import Diapason

j = Diapason()
response = j.ask("Quelle est la capitale de la France ?")
print(response)
j.close()
```

---

## La classe Diapason

### Le constructeur

```python
Diapason(
    *,
    config: DiapasonConfig | None = None,
    config_path: str | None = None,
    engine_key: str | None = None,
    model: str | None = None,
)
```

| Paramètre     | Type             | Défaut  | Description                                                    |
|---------------|------------------|---------|----------------------------------------------------------------|
| `config`      | `DiapasonConfig` | `None`  | Fournir un objet de configuration déjà construit               |
| `config_path` | `str`            | `None`  | Chemin vers un fichier de configuration TOML                   |
| `engine_key`  | `str`            | `None`  | Imposer le moteur d'inférence (`"ollama"`, `"vllm"`, etc.)     |
| `model`       | `str`            | `None`  | Imposer le modèle par défaut (`"qwen3:8b"`, par exemple)       |

Sans `config` ni `config_path`, le SDK lit la configuration à l'emplacement par défaut (`~/.diapason/config.toml`), et retombe sur les valeurs intégrées.

**Des exemples :**

```python
# La configuration par défaut — le moteur est détecté tout seul
j = Diapason()

# Imposer le modèle
j = Diapason(model="qwen3:8b")

# Imposer le moteur
j = Diapason(engine_key="ollama")

# Lire un fichier de configuration précis
j = Diapason(config_path="/path/to/config.toml")
```

### Les propriétés

| Propriété | Type             | Description                        |
|-----------|------------------|------------------------------------|
| `config`  | `DiapasonConfig` | L'objet de configuration actif     |
| `version` | `str`            | La chaîne de version de Diapason   |
| `memory`  | `MemoryHandle`   | Le relais des opérations de mémoire |

---

## La méthode `ask()`

Envoie une question et rend une réponse en texte simple.

```python
ask(
    query: str,
    *,
    model: str | None = None,
    agent: str | None = None,
    tools: list[str] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    context: bool = True,
) -> str
```

| Paramètre     | Type         | Défaut  | Description                                          |
|---------------|--------------|---------|------------------------------------------------------|
| `query`       | `str`        | --      | La question ou le prompt à envoyer                   |
| `model`       | `str`        | `None`  | Imposer le modèle pour cet appel                     |
| `agent`       | `str`        | `None`  | Faire passer par un agent (`"simple"`, `"orchestrator"`) |
| `tools`       | `list[str]`  | `None`  | Noms d'outils à activer (demande le mode agent)      |
| `temperature` | `float`      | `0.7`   | Température d'échantillonnage                        |
| `max_tokens`  | `int`        | `1024`  | Nombre maximum de jetons à générer                   |
| `context`     | `bool`       | `True`  | Injecter ou non le contexte mémoire                  |

**Rend :** une chaîne `str` qui porte le texte de la réponse du modèle.

**Des exemples :**

```python
# Une question simple
response = j.ask("Qu'est-ce que l'apprentissage automatique ?")

# Imposer le modèle pour cet appel
response = j.ask("Bonjour", model="llama3.2:3b")

# Couper l'injection du contexte mémoire
response = j.ask("Parle-moi de Python", context=False)

# Ajuster les paramètres de génération
response = j.ask("Écris un haïku", temperature=0.3, max_tokens=50)
```

---

## La méthode `ask_full()`

Envoie une question et rend un dictionnaire de résultat détaillé, avec ses métadonnées.

```python
ask_full(
    query: str,
    *,
    model: str | None = None,
    agent: str | None = None,
    tools: list[str] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    context: bool = True,
) -> dict[str, Any]
```

Les paramètres sont les mêmes que ceux d'`ask()`.

**Rend :** un dictionnaire dont les clés sont les suivantes.

=== "Mode direct"

    | Clé       | Type   | Description                              |
    |-----------|--------|------------------------------------------|
    | `content` | `str`  | Le texte de la réponse                   |
    | `usage`   | `dict` | La consommation de jetons (`prompt_tokens`, `completion_tokens`, `total_tokens`) |
    | `model`   | `str`  | Le modèle utilisé                        |
    | `engine`  | `str`  | Le moteur d'inférence utilisé            |

=== "Mode agent"

    | Clé            | Type         | Description                              |
    |----------------|--------------|------------------------------------------|
    | `content`      | `str`        | Le texte de la réponse                   |
    | `usage`        | `dict`       | La consommation de jetons (peut être vide en mode agent) |
    | `tool_results` | `list[dict]` | Les résultats d'exécution des outils     |
    | `turns`        | `int`        | Le nombre de tours faits par l'agent     |
    | `model`        | `str`        | Le modèle utilisé                        |
    | `engine`       | `str`        | Le moteur d'inférence utilisé            |

**Un exemple :**

```python
result = j.ask_full("Combien font 2+2 ?")
print(result["content"])       # "4"
print(result["model"])         # "qwen3:8b"
print(result["engine"])        # "ollama"
print(result["usage"])         # {"prompt_tokens": 10, ...}
```

---

## Le mode agent

Passe le paramètre `agent` pour faire passer les questions par un agent. Les agents savent mener des conversations sur plusieurs tours et utiliser des outils.

```python
# L'agent simple — un seul tour, pas d'outils
response = j.ask("Bonjour", agent="simple")

# L'agent orchestrator — plusieurs tours, avec appels d'outils
response = j.ask(
    "Combien font sqrt(144) + 3^2 ?",
    agent="orchestrator",
    tools=["calculator", "think"],
)
```

En mode agent avec `ask_full()`, le résultat porte `tool_results`, qui montre chaque appel d'outil :

```python
result = j.ask_full(
    "Calcule 15 % de 340",
    agent="orchestrator",
    tools=["calculator"],
)

print(result["content"])       # "15 % de 340 font 51.0"
print(result["turns"])         # 2
print(result["tool_results"])
# [{"tool_name": "calculator", "content": "51.0", "success": True}]
```

Les agents offerts : `simple`, `orchestrator`, `operative`, `monitor_operative`

Les outils offerts : `calculator`, `think`, `retrieval`, `llm`, `file_read`

---

## MemoryHandle

L'attribut `Diapason.memory` donne un `MemoryHandle` pour indexer des documents, les chercher et en tirer des statistiques. Le moteur de mémoire ne s'initialise qu'à la première utilisation.

### `index()`

Indexe un fichier ou un dossier dans la mémoire.

```python
index(
    path: str,
    *,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> dict[str, Any]
```

| Paramètre       | Type  | Défaut  | Description                              |
|-----------------|-------|---------|------------------------------------------|
| `path`          | `str` | --      | Chemin du fichier ou du dossier à indexer |
| `chunk_size`    | `int` | `512`   | Taille des fragments, en jetons          |
| `chunk_overlap` | `int` | `64`    | Recouvrement entre fragments, en jetons  |

**Rend :** un dictionnaire avec `chunks` (le nombre), `doc_ids` (la liste) et `path`.

```python
result = j.memory.index("./docs/")
print(f"{result['chunks']} fragments indexés")
# 42 fragments indexés

# Des paramètres de fragmentation sur mesure
result = j.memory.index("./notes/", chunk_size=256, chunk_overlap=32)
```

### `search()`

Cherche dans la mémoire les fragments pertinents.

```python
search(
    query: str,
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]
```

| Paramètre | Type  | Défaut  | Description                     |
|-----------|-------|---------|---------------------------------|
| `query`   | `str` | --      | La requête de recherche         |
| `top_k`   | `int` | `5`     | Le nombre de résultats à rendre |

**Rend :** une liste de dictionnaires, chacun portant `content`, `score`, `source` et `metadata`.

```python
results = j.memory.search("réseaux de neurones")
for r in results:
    print(f"[{r['score']:.4f}] {r['source']} : {r['content'][:80]}...")
```

### `stats()`

Rend les statistiques du moteur de mémoire.

```python
stats() -> dict[str, Any]
```

**Rend :** un dictionnaire avec `backend` (le nom) et `count` (le nombre de documents, s'il est connu).

```python
info = j.memory.stats()
print(f"Moteur : {info['backend']}, Documents : {info.get('count', 'N/D')}")
```

### `close()`

Libère le moteur de mémoire et ses ressources.

```python
j.memory.close()
```

---

## Découvrir les modèles et les moteurs

### `list_models()`

Rend la liste des identifiants de modèles offerts par le moteur actif.

```python
models = j.list_models()
print(models)  # ["qwen3:8b", "llama3.2:3b", ...]
```

### `list_engines()`

Rend la liste des clés de moteurs enregistrées.

```python
engines = j.list_engines()
print(engines)  # ["ollama", "vllm", "llamacpp", ...]
```

---

## La gestion des ressources

### `close()`

Libère toutes les ressources tenues par l'instance `Diapason` : le moteur de mémoire, le magasin de télémétrie et la connexion au moteur d'inférence.

```python
j.close()
```

!!! tip "Le motif du gestionnaire de contexte"
    `Diapason` n'implémente pas `__enter__`/`__exit__` directement : appelle toujours `close()` quand tu as fini, pour libérer les connexions aux bases et le reste des ressources.

    ```python
    j = Diapason()
    try:
        response = j.ask("Bonjour")
        print(response)
    finally:
        j.close()
    ```

---

## Un exemple complet

```python
from diapason import Diapason

# Démarrer avec le moteur détecté tout seul
j = Diapason(model="qwen3:8b")

# Indexer des documents pour enrichir les réponses de contexte
result = j.memory.index("./docs/")
print(f"{result['chunks']} fragments indexés depuis {result['path']}")

# Une question simple, avec le contexte mémoire
response = j.ask("Quelles sont les principales fonctionnalités ?")
print(response)

# Une question détaillée, avec agent et outils
full_result = j.ask_full(
    "Calcule la racine carrée de 256 et ajoute 10",
    agent="orchestrator",
    tools=["calculator"],
)
print(f"Réponse : {full_result['content']}")
print(f"Tours : {full_result['turns']}")
print(f"Outils utilisés : {[t['tool_name'] for t in full_result['tool_results']]}")

# Chercher directement dans la mémoire
results = j.memory.search("configuration")
for r in results:
    print(f"  [{r['score']:.3f}] {r['source']}")

# Lister les modèles offerts
print("Modèles :", j.list_models())

# Faire le ménage
j.close()
```
