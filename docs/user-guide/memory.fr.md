# La mémoire

Le système de mémoire offre un stockage de documents persistant et cherchable, pour la génération augmentée par récupération (RAG). Il accepte plusieurs moteurs de récupération, une chaîne de découpage configurable, l'ingestion de documents depuis des fichiers et des dossiers, et l'injection automatique de contexte dans les prompts.

## L'architecture

```
Documents   -->  Découpage              -->  Moteur de mémoire   -->  Injection de contexte     -->  Prompt
(fichiers)       (morceaux + recouvr.)       (stockage + index)       (récup. + mise en forme)       (vers le modèle)
```

---

## La classe abstraite `MemoryBackend`

Tous les moteurs de mémoire implémentent la classe de base abstraite `MemoryBackend`.

```python
class MemoryBackend(ABC):
    backend_id: str

    def store(self, content: str, *, source: str = "", metadata: dict | None = None) -> str:
        """Conserve le contenu et rend un identifiant de document unique."""

    def retrieve(self, query: str, *, top_k: int = 5, **kwargs) -> list[RetrievalResult]:
        """Cherche la question et rend les top_k meilleurs résultats."""

    def delete(self, doc_id: str) -> bool:
        """Supprime un document par son identifiant. Rend True s'il existait."""

    def clear(self) -> None:
        """Retire tous les documents stockés."""
```

### RetrievalResult

Chaque récupération rend une liste d'objets `RetrievalResult` :

| Champ      | Type             | Description                                |
|------------|------------------|--------------------------------------------|
| `content`  | `str`            | Le morceau de texte récupéré               |
| `score`    | `float`          | Score de pertinence (plus il est haut, mieux c'est) |
| `source`   | `str`            | Chemin du fichier d'origine, ou identifiant |
| `metadata` | `dict[str, Any]` | Métadonnées supplémentaires (numéro du morceau, etc.) |

---

## Les moteurs

### SQLite / FTS5 (par défaut)

**Clé de registre :** `sqlite`

Le moteur par défaut, qui se sert de l'extension de recherche plein texte FTS5 intégrée à SQLite. Aucune dépendance extérieure — il passe par le module `sqlite3` de la bibliothèque standard de Python.

- **Score :** classement BM25 par les requêtes `MATCH` de FTS5
- **Persistance :** un fichier de base SQLite (`~/.diapason/memory.db` par défaut)
- **Dépendances :** aucune (c'est dans Python)

```python
from diapason.core.registry import MemoryRegistry

backend = MemoryRegistry.create("sqlite", db_path="./memory.db")
doc_id = backend.store("Bonjour tout le monde", source="test.txt")
results = backend.retrieve("bonjour")
backend.close()
```

!!! tip "Quand prendre SQLite/FTS5"
    Prends ce moteur quand tu veux une installation sans configuration, que la recherche par mots-clés te suffit et qu'il te faut un stockage qui survit aux redémarrages. Il tient très bien sur des collections de documents petites à moyennes.

### FAISS

**Clé de registre :** `faiss`

Récupération neuronale dense, par Facebook AI Similarity Search. Les documents et les questions sont plongés en vecteurs denses, et la récupération se fait par similarité cosinus.

- **Score :** similarité cosinus, par recherche en produit scalaire sur des vecteurs normalisés en L2
- **Persistance :** en mémoire vive seulement (tout est perdu au redémarrage)
- **Dépendances :** `faiss-cpu` (ou `faiss-gpu`), `sentence-transformers`

```bash
uv sync --extra memory-faiss
```

```python
backend = MemoryRegistry.create("faiss")
doc_id = backend.store("Les réseaux de neurones sont des modèles de calcul")
results = backend.retrieve("architectures d'apprentissage profond")
```

!!! tip "Quand prendre FAISS"
    Prends ce moteur quand il te faut une recherche sémantique — trouver un contenu proche par le sens, même sans mot-clé en commun. Il convient surtout aux usages où tu peux réindexer à chaque lancement, puisque rien n'est conservé.

### ColBERTv2

**Clé de registre :** `colbert`

Récupération à interaction tardive, par les plongements au grain du jeton de ColBERT et le score MaxSim. C'est la meilleure qualité de récupération parmi les moteurs offerts.

- **Score :** MaxSim — pour chaque jeton de la question, on prend la similarité cosinus maximale sur tous les jetons du document, puis on somme
- **Persistance :** en mémoire vive seulement
- **Dépendances :** `colbert-ai`, `torch`

```bash
uv sync --extra memory-colbert
```

```python
backend = MemoryRegistry.create(
    "colbert",
    checkpoint="colbert-ir/colbertv2.0",
    device="cpu",
)
```

| Paramètre    | Défaut                     | Description                         |
|--------------|----------------------------|-------------------------------------|
| `checkpoint` | `"colbert-ir/colbertv2.0"` | Point de contrôle du modèle ColBERT |
| `device`     | `"cpu"`                    | Appareil de calcul (`cpu` ou `cuda`) |

!!! tip "Quand prendre ColBERTv2"
    Prends ce moteur quand la qualité de récupération passe avant tout et que tu as la puissance de calcul pour la payer. Le point de contrôle n'est chargé qu'au premier usage, pour éviter des imports lents. C'est le bon choix pour la recherche et l'évaluation.

### BM25

**Clé de registre :** `bm25`

Le classement probabiliste classique, par l'algorithme BM25 Okapi. Implémentation en mémoire vive, avec la bibliothèque `rank_bm25`.

- **Score :** BM25 Okapi, sur la fréquence des termes
- **Persistance :** en mémoire vive seulement
- **Dépendances :** `rank-bm25`

```bash
uv sync --extra memory-bm25
```

```python
backend = MemoryRegistry.create("bm25")
backend.store("Python est un langage de programmation", source="intro.txt")
results = backend.retrieve("langage de programmation")
```

!!! tip "Quand prendre BM25"
    Prends ce moteur quand tu veux la récupération classique par mots-clés, sans dépendre d'une base de données. Il sert bien de composante creuse dans une récupération hybride.

### Hybride (fusion RRF)

**Clé de registre :** `hybrid`

Combine un récupérateur creux et un récupérateur dense par la fusion de rangs réciproques (RRF). Les documents sont stockés dans les deux sous-moteurs, et les résultats de récupération sont fusionnés.

- **Score :** `RRF_score(d) = sum(weight_i / (k + rank_i(d)))`, sur les deux listes classées
- **Persistance :** celle des sous-moteurs
- **Dépendances :** celles des sous-moteurs

```python
from diapason.tools.storage.bm25 import BM25Memory
from diapason.tools.storage.faiss_backend import FAISSMemory

sparse = BM25Memory()
dense = FAISSMemory()

backend = MemoryRegistry.create(
    "hybrid",
    sparse=sparse,
    dense=dense,
    k=60,
    sparse_weight=1.0,
    dense_weight=1.0,
)
```

!!! note "Compatibilité ascendante"
    L'ancien `from diapason.memory.bm25 import BM25Memory` marche encore, par des cales de compatibilité, mais le code neuf passe par les imports canoniques `diapason.tools.storage.*`.

| Paramètre       | Défaut | Description                                    |
|-----------------|--------|------------------------------------------------|
| `sparse`        | —      | Moteur de récupération creux (BM25, par exemple) |
| `dense`         | —      | Moteur de récupération dense (FAISS, par exemple) |
| `k`             | `60`   | La constante RRF                               |
| `sparse_weight` | `1.0`  | Poids des résultats du récupérateur creux      |
| `dense_weight`  | `1.0`  | Poids des résultats du récupérateur dense      |

Le moteur hybride sur-récupère — 3 fois `top_k` — dans chaque sous-moteur avant d'appliquer la fusion, pour améliorer la qualité des résultats.

!!! tip "Quand prendre l'hybride"
    Prends ce moteur quand tu veux le meilleur des deux mondes : la correspondance de mots-clés et la similarité de sens. L'approche RRF est robuste et n'oblige pas à accorder entre elles des distributions de score venues de méthodes de récupération différentes.

---

## Comparer les moteurs

| Moteur      | Type de recherche  | Persistance | Dépendances          | Qualité    | Vitesse   |
|-------------|--------------------|-------------|----------------------|------------|-----------|
| SQLite/FTS5 | Mots-clés (BM25)   | Oui         | Aucune               | Bonne      | Rapide    |
| FAISS       | Dense (cosinus)    | Non         | faiss, transformers  | Meilleure  | Rapide    |
| ColBERTv2   | Interaction tardive | Non        | colbert-ai, torch    | La meilleure | Plus lent |
| BM25        | Mots-clés (Okapi)  | Non         | rank-bm25            | Bonne      | Rapide    |
| Hybride     | Fusion (RRF)       | Variable    | Celles des sous-moteurs | Meilleure | Moyenne  |

---

## La chaîne de découpage

Les documents sont découpés en morceaux avant d'être stockés, par une chaîne configurable. Le découpeur respecte les frontières de paragraphe quand il le peut.

### ChunkConfig

| Champ           | Type  | Défaut  | Description                              |
|-----------------|-------|---------|------------------------------------------|
| `chunk_size`    | `int` | `512`   | Taille visée d'un morceau, en jetons séparés par des espaces |
| `chunk_overlap` | `int` | `64`    | Recouvrement entre deux morceaux consécutifs |
| `min_chunk_size`| `int` | `50`    | Taille minimale d'un morceau (les plus petits sont jetés) |

### Comment le découpage se passe

1. Le document est découpé en paragraphes (séparés par deux sauts de ligne).
2. Les paragraphes sont accumulés jusqu'à ce que le nombre de jetons dépasse `chunk_size`.
3. Le contenu accumulé est émis comme un morceau.
4. Les `chunk_overlap` derniers jetons sont gardés comme contexte pour le morceau suivant.
5. Un paragraphe qui dépasse à lui seul `chunk_size` est découpé en fenêtres de taille fixe, avec recouvrement.

### Ce que produit le découpage

Chaque morceau est un objet `Chunk` qui porte :

| Champ      | Type             | Description                              |
|------------|------------------|------------------------------------------|
| `content`  | `str`            | Le texte du morceau                      |
| `source`   | `str`            | Chemin du fichier d'origine              |
| `offset`   | `int`            | Décalage en jetons dans le document      |
| `index`    | `int`            | Numéro d'ordre du morceau                |
| `metadata` | `dict[str, Any]` | Métadonnées supplémentaires              |

---

## L'ingestion des documents

La fonction `ingest_path()` lit un fichier ou parcourt récursivement un dossier, et produit des morceaux prêts à être stockés.

### Les types de fichiers acceptés

| Type     | Extensions                                                  |
|----------|-------------------------------------------------------------|
| Texte    | `.txt` et les autres fichiers en texte brut                 |
| Markdown | `.md`, `.markdown`, `.mdx`                                  |
| Code     | `.py`, `.js`, `.ts`, `.rs`, `.go`, `.java`, `.c`, `.cpp`, `.rb`, `.sh`, `.yaml`, `.json`, `.html`, `.css`, et d'autres |
| PDF      | `.pdf` (demande `pdfplumber` : `uv sync --extra memory-pdf`) |

### Ce qui est sauté automatiquement

La chaîne d'ingestion saute d'elle-même :

- Les fichiers et dossiers cachés (ceux qui commencent par `.`)
- Les dossiers courants sans contenu utile : `__pycache__`, `node_modules`, `.venv`, `.git`, etc.
- Les fichiers binaires : images, audio, vidéo, archives, fichiers compilés
- Les fichiers illisibles (droits refusés, problèmes d'encodage)

### Comment s'en servir

```python
from pathlib import Path
from diapason.tools.storage.chunking import ChunkConfig
from diapason.tools.storage.ingest import ingest_path

# Découpage par défaut
chunks = ingest_path(Path("./docs/"))

# Découpage sur mesure
config = ChunkConfig(chunk_size=256, chunk_overlap=32)
chunks = ingest_path(Path("./notes.md"), config=config)

print(f"{len(chunks)} morceaux produits")
for chunk in chunks[:3]:
    print(f"  [{chunk.index}] {chunk.source} : {chunk.content[:60]}...")
```

---

## L'injection de contexte

Quand l'injection de contexte mémoire est active — elle l'est par défaut —, les questions sont enrichies automatiquement des documents pertinents récupérés, avant d'être envoyées au modèle. Chaque passage récupéré porte la mention de sa source.

### ContextConfig

| Champ               | Type    | Défaut  | Description                                      |
|---------------------|---------|---------|--------------------------------------------------|
| `enabled`           | `bool`  | `True`  | Si l'injection de contexte est active            |
| `top_k`             | `int`   | `5`     | Nombre de résultats à récupérer                  |
| `min_score`         | `float` | `0.1`   | Seuil minimal de score de pertinence             |
| `max_context_tokens`| `int`   | `2048`  | Nombre maximum de jetons dans le contexte injecté |

### Comment ça marche

1. La question de l'utilisateur est cherchée dans le moteur de mémoire.
2. Les résultats sous `min_score` sont écartés.
3. Les résultats sont tronqués pour tenir dans `max_context_tokens`.
4. Un message système est mis en tête de la conversation, avec le contexte mis en forme :

```
The following context was retrieved from the knowledge base.
Use it to inform your response, citing sources where applicable:

[Source: docs/intro.md] Diapason is a modular AI framework...

[Source: docs/config.md] Configuration is stored in TOML format...
```

### Couper l'injection de contexte

=== "En ligne de commande"

    ```bash
    diapason ask --no-context "Parle-moi de Python"
    ```

=== "SDK Python"

    ```python
    response = j.ask("Parle-moi de Python", context=False)
    ```

---

## En ligne de commande

```bash
# Indexer un dossier
diapason memory index ./docs/

# Indexer avec un découpage sur mesure
diapason memory index ./notes/ --chunk-size 256 --chunk-overlap 32

# Chercher dans la mémoire
diapason memory search "apprentissage automatique"

# Chercher en demandant plus de résultats
diapason memory search -k 10 "réseaux de neurones"

# Afficher les statistiques de la mémoire
diapason memory stats
```

## Avec le SDK

```python
from diapason import Diapason

j = Diapason()

# Indexer des documents
result = j.memory.index("./docs/", chunk_size=512, chunk_overlap=64)
print(f"{result['chunks']} morceaux indexés")

# Chercher
results = j.memory.search("configuration", top_k=3)
for r in results:
    print(f"  [{r['score']:.4f}] {r['source']} : {r['content'][:80]}...")

# Les statistiques
stats = j.memory.stats()
print(f"Moteur : {stats['backend']}, Documents : {stats.get('count', 'N/A')}")

# Ranger derrière soi
j.close()
```
