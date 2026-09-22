# La primitive Mémoire

La primitive Memory fournit un **stockage persistant et interrogeable** pour les documents et la connaissance. C'est elle qui rend possible l'injection de contexte : retrouver l'information pertinente dans les documents indexés et la placer en tête du prompt, pour que le modèle réponde en s'appuyant sur un contenu précis.

---

## La classe abstraite MemoryBackend

Tous les backends de mémoire implémentent la classe de base abstraite `MemoryBackend` :

```python
class MemoryBackend(ABC):
    backend_id: str

    @abstractmethod
    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persiste *content* et renvoie un identifiant de document unique."""

    @abstractmethod
    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Cherche *query* et renvoie les top-k meilleurs résultats."""

    @abstractmethod
    def delete(self, doc_id: str) -> bool:
        """Supprime un document par son identifiant. Renvoie True s'il existait."""

    @abstractmethod
    def clear(self) -> None:
        """Retire tous les documents stockés."""
```

### RetrievalResult

Les résultats de recherche sont renvoyés sous forme d'objets `RetrievalResult` :

```python
@dataclass(slots=True)
class RetrievalResult:
    content: str                  # Le texte du document
    score: float = 0.0            # Score de pertinence (plus il est haut, mieux c'est)
    source: str = ""              # Chemin du fichier d'origine, ou identifiant
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

## Comparer les backends

| Backend | Clé du registre | Type d'index | Dépendances supplémentaires | GPU requis | Qualité | Vitesse | Persistance |
|---------|-------------|-----------|-------------------|-------------|---------|-------|-------------|
| **SQLite/FTS5** | `sqlite` | Plein texte (BM25) | aucune | non | bonne | rapide | Disque (SQLite) |
| **FAISS** | `faiss` | Vecteurs denses | `faiss-cpu`, `sentence-transformers` | facultatif | très bonne | rapide | En mémoire |
| **ColBERTv2** | `colbert` | Interaction tardive | `colbert-ai`, `torch` | facultatif | excellente | plus lente | En mémoire |
| **BM25** | `bm25` | Fréquence des termes | `rank-bm25` | non | bonne | rapide | En mémoire |
| **Hybride** | `hybrid` | Fusion RRF | selon les sous-backends | variable | la meilleure | moyenne | variable |

### SQLite/FTS5 (le défaut)

Le backend par défaut, celui qui n'exige aucune dépendance. Il se sert de l'extension FTS5 intégrée à SQLite pour faire de la recherche plein texte avec un classement BM25.

- **Stockage :** les documents sont rangés dans une table `documents`, indexée automatiquement par FTS5 au moyen de déclencheurs
- **Recherche :** des requêtes `MATCH` FTS5 avec classement BM25 (plus le rang est négatif, meilleure est la correspondance ; il est converti en score positif)
- **Échappement des requêtes :** chaque mot est mis entre guillemets pour éviter les erreurs de syntaxe FTS5
- **Persistance :** les données survivent aux redémarrages, dans `~/.diapason/memory.db`

### FAISS

Recherche dense au moyen de Facebook AI Similarity Search. Les documents sont plongés dans un espace vectoriel et retrouvés par similarité cosinus.

- **Type d'index :** `IndexFlatIP` (produit scalaire, équivalent à la similarité cosinus quand les vecteurs sont normalisés en L2)
- **Modèle de plongement :** `all-MiniLM-L6-v2` par défaut (384 dimensions, ~22 Mo)
- **Suppression :** suppression douce (les documents sont marqués comme supprimés mais restent dans l'index)
- **Persistance :** en mémoire seulement — les données sont perdues au redémarrage

### ColBERTv2

Recherche à interaction tardive, fondée sur des plongements au niveau du jeton et un score MaxSim. C'est la meilleure qualité de recherche, au prix d'une latence plus élevée.

- **Score :** pour chaque jeton de la requête, on retient la similarité cosinus maximale parmi tous les jetons du document, puis on somme sur les jetons de la requête
- **Point de contrôle :** `colbert-ir/colbertv2.0` (chargé paresseusement au premier usage)
- **Persistance :** en mémoire seulement

!!! warning "Des dépendances lourdes"
    ColBERTv2 réclame `colbert-ai` et `torch`, qui sont de gros paquets. Installe-les ainsi :
    `uv sync --extra memory-colbert`

### BM25

La fonction de classement probabiliste Okapi BM25, dans sa forme classique, via la bibliothèque `rank_bm25`.

- **Découpage en jetons :** passage en minuscules et séparation sur les espaces
- **Index :** reconstruit à chaque opération `store()` et `delete()`
- **Filtrage :** les résultats sont filtrés pour exiger au moins un jeton commun avec la requête (cela couvre les cas limites où BM25 attribue IDF=0)
- **Persistance :** en mémoire seulement

### Hybride (fusion RRF)

Combine un chercheur creux et un chercheur dense au moyen de la fusion de rangs réciproques :

$$\text{RRF}(d) = \sum_{i} \frac{w_i}{k + \text{rank}_i(d)}$$

- **Sous-backends :** deux implémentations quelconques de `MemoryBackend` (SQLite + FAISS, par exemple)
- **Sur-extraction :** `top_k * 3` résultats sont demandés à chaque sous-backend, pour une meilleure fusion
- **Configurable :** la constante RRF `k` (60 par défaut) et le poids de chaque backend

```python
from diapason.tools.storage.sqlite import SQLiteMemory
from diapason.tools.storage.faiss_backend import FAISSMemory
from diapason.tools.storage.hybrid import HybridMemory

hybrid = HybridMemory(
    sparse=SQLiteMemory(db_path="memory.db"),
    dense=FAISSMemory(),
    sparse_weight=1.0,
    dense_weight=1.5,  # Donner plus de poids à la recherche dense
)
```

!!! note "Compatibilité ascendante"
    Les anciens imports (`from diapason.memory.sqlite import SQLiteMemory`, par exemple) fonctionnent toujours, grâce à des cales de compatibilité dans le paquet `memory/` — mais l'emplacement canonique est désormais `diapason.tools.storage.*`.

---

## La chaîne de découpage en fragments

Les gros documents sont découpés en fragments maniables avant d'être stockés. Cette chaîne est définie dans `tools/storage/chunking.py` (autrefois `memory/chunking.py`).

### ChunkConfig

```python
@dataclass(slots=True)
class ChunkConfig:
    chunk_size: int = 512      # Nombre maximum de jetons par fragment (séparés par les espaces)
    chunk_overlap: int = 64    # Jetons à faire recouvrir entre deux fragments voisins
    min_chunk_size: int = 50   # Nombre minimum de jetons pour qu'un fragment soit gardé
```

### Chunk

```python
@dataclass(slots=True)
class Chunk:
    content: str               # Le texte du fragment
    source: str = ""           # Chemin du fichier d'origine
    offset: int = 0            # Décalage en jetons dans le document d'origine
    index: int = 0             # Numéro du fragment (0, 1, 2, ...)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### L'algorithme de découpage

La fonction `chunk_text()` découpe le texte en s'appuyant sur les frontières de paragraphe :

1. Découper le document sur les doubles sauts de ligne (`\n\n`), en paragraphes
2. Accumuler les paragraphes dans le fragment courant jusqu'à dépasser `chunk_size`
3. Quand un fragment est plein, le vider et garder les derniers `chunk_overlap` jetons comme recouvrement pour le fragment suivant
4. Si un seul paragraphe dépasse `chunk_size`, le découper en fenêtres de taille fixe avec recouvrement
5. Jeter les fragments plus petits que `min_chunk_size`

```python
from diapason.tools.storage.chunking import chunk_text, ChunkConfig

config = ChunkConfig(chunk_size=256, chunk_overlap=32)
chunks = chunk_text(document_text, source="docs/guide.md", config=config)
```

---

## L'ingestion des documents

Le module `tools/storage/ingest.py` (autrefois `memory/ingest.py`) se charge de lire les fichiers et les dossiers pour en faire des fragments.

### La détection du type de fichier

| Extension | Type détecté |
|-----------|--------------|
| `.md`, `.markdown`, `.mdx` | `markdown` |
| `.pdf` | `pdf` |
| `.py`, `.js`, `.ts`, `.rs`, `.go`, `.java`, `.c`, `.cpp`, `.yaml`, `.json`, `.html`, `.css`, … | `code` |
| Tout le reste | `text` |

### `ingest_path(path, config=None)`

Ingère un fichier ou un dossier sous forme de fragments :

- **Un seul fichier :** le fichier est lu, son type détecté, et son contenu découpé
- **Un dossier :** l'arborescence est parcourue récursivement, en sautant :
    - Les dossiers cachés (ceux qui commencent par `.`)
    - Les dossiers sans contenu utile (`__pycache__`, `node_modules`, `.git`, `.venv`, etc.)
    - Les fichiers binaires (images, audio, vidéo, archives, fichiers compilés)
    - Les fichiers cachés (ceux qui commencent par `.`)

```python
from pathlib import Path
from diapason.tools.storage.ingest import ingest_path

# Ingérer un seul fichier
chunks = ingest_path(Path("docs/guide.md"))

# Ingérer un dossier entier
chunks = ingest_path(Path("./docs/"))
```

### La prise en charge des PDF

Les fichiers PDF sont lus avec `pdfplumber` : le texte est extrait page par page, puis raccordé par des doubles sauts de ligne. Cela réclame la dépendance facultative `pdfplumber` :

```bash
uv sync --extra memory-pdf
```

---

## Les plongements

Les backends de recherche dense (FAISS, ColBERT) ont besoin de plongements de texte. Le module `tools/storage/embeddings.py` (autrefois `memory/embeddings.py`) fournit la classe abstraite `Embedder` et une implémentation par défaut.

### La classe abstraite Embedder

```python
class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> Any:
        """Plonge les textes et renvoie un tableau numpy de forme (n, dim)."""

    @abstractmethod
    def dim(self) -> int:
        """Renvoie la dimension des vecteurs de plongement."""
```

### SentenceTransformerEmbedder

Le plongeur par défaut enveloppe la bibliothèque `sentence-transformers` :

- **Modèle par défaut :** `all-MiniLM-L6-v2` (384 dimensions, ~22 Mo)
- **Sortie :** des tableaux NumPy de forme `(n, dim)`

```python
from diapason.tools.storage.embeddings import SentenceTransformerEmbedder

embedder = SentenceTransformerEmbedder(model_name="all-MiniLM-L6-v2")
vectors = embedder.embed(["Bonjour tout le monde", "Comment ça va ?"])
# Forme : (2, 384)
```

---

## L'injection de contexte

La chaîne d'injection de contexte retrouve les documents pertinents et les place en tête du prompt, en indiquant leur source. Elle est définie dans `tools/storage/context.py` (autrefois `memory/context.py`).

### ContextConfig

```python
@dataclass(slots=True)
class ContextConfig:
    enabled: bool = True           # L'injection de contexte est-elle active
    top_k: int = 5                 # Nombre maximum de résultats à retrouver
    min_score: float = 0.1         # Seuil minimum de score de pertinence
    max_context_tokens: int = 2048 # Nombre maximum de jetons de contexte à injecter
```

### `inject_context()`

La fonction principale de l'injection de contexte :

```python
def inject_context(
    query: str,
    messages: List[Message],
    backend: MemoryBackend,
    *,
    config: Optional[ContextConfig] = None,
) -> List[Message]:
```

Comment ça marche :

1. Les résultats sont retrouvés dans le backend de mémoire à partir de la requête
2. Les résultats sous `min_score` sont écartés
3. Le tout est tronqué à `max_context_tokens` (le compte de jetons est approché par une séparation sur les espaces)
4. Les résultats sont mis en forme avec une étiquette d'attribution de source : `[Source: docs/guide.md] Le contenu...`
5. Un message système est créé avec le contexte ainsi mis en forme
6. Une **nouvelle** liste de messages est renvoyée, le message de contexte en tête

```python
from diapason.tools.storage.context import inject_context, ContextConfig

config = ContextConfig(top_k=3, min_score=0.2)
messages = inject_context("Qu'est-ce que l'API ?", messages, backend, config=config)
```

### L'attribution des sources

Le contexte est injecté sous forme de message système, avec des étiquettes de source explicites :

```
Le contexte suivant a été retrouvé dans la base de connaissances. Sers-t'en
pour nourrir ta réponse, en citant les sources quand c'est pertinent :

[Source: docs/api.md] L'API expose un point d'entrée /v1/chat/completions...

[Source: docs/setup.md] Pour configurer le serveur d'API, modifie config.toml...
```

---

## L'enregistrement des backends

Les backends de mémoire s'enregistrent au moyen du décorateur `@MemoryRegistry.register("nom")` :

```python
from diapason.core.registry import MemoryRegistry
from diapason.tools.storage._stubs import MemoryBackend

@MemoryRegistry.register("my-backend")
class MyMemoryBackend(MemoryBackend):
    backend_id = "my-backend"

    def store(self, content, *, source="", metadata=None) -> str: ...
    def retrieve(self, query, *, top_k=5, **kwargs) -> list: ...
    def delete(self, doc_id) -> bool: ...
    def clear(self) -> None: ...
```

Le backend par défaut se configure dans `~/.diapason/config.toml`. Les réglages de stockage vivent sous `[tools.storage]`, et l'injection de contexte est commandée par `agent.context_from_memory` :

```toml
[agent]
context_from_memory = true

[tools.storage]
default_backend = "sqlite"
db_path = "~/.diapason/memory.db"
context_top_k = 5
context_min_score = 0.1
context_max_tokens = 2048
chunk_size = 512
chunk_overlap = 64
```

!!! note "Compatibilité ascendante"
    La section TOML `[memory]` est toujours acceptée : elle vaut alias de `[tools.storage]`, par compatibilité ascendante. L'ancien champ `context_injection` est migré automatiquement vers `agent.context_from_memory` au chargement.
