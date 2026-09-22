# Recherche approfondie

Un agent de recherche multi-sauts qui cherche dans tes documents indexés, recoupe l'information et rend des réponses avec leurs citations. Il raisonne pas à pas sur les questions complexes, en tirant du contexte de plusieurs sources de ta base de connaissances locale.

Dans l'app de bureau (la bascule **Recherche approfondie**, à côté du champ de saisie), l'agent dispose aussi de `web_search` : les questions sur le monde public — sites web, liens, actualité, « sur internet » — partent vers le web, et une recherche dans le corpus qui ne rend rien de pertinent est suivie d'une recherche web, pas d'une réponse tirée de la mémoire du modèle. Les résultats web sont cités comme les trouvailles du corpus, avec leur URL. Les tours précédents de la conversation voyagent avec chaque requête de recherche, si bien qu'une relance comme « donne-moi les liens de ces sites » renvoie à ce qui vient d'être dit (22 septembre 2026 : elle partait seule, et revenait avec des liens tirés des courriels).

## Démarrage rapide (5 minutes)

### 1. Installer et initialiser

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync --extra dev
diapason init --preset deep-research
```

Cela écrit un `~/.diapason/config.toml` préconfiguré pour l'agent de recherche approfondie.

### 2. Indexer tes documents

```bash
# Installer Ollama : https://ollama.com
ollama pull qwen3.5:9b

# Indexer un dossier de fichiers
diapason memory index ./docs/
diapason memory index ~/Documents/papers/
```

Diapason découpe le contenu en morceaux et les range dans une base SQLite/FTS5 locale. Parmi les formats pris en charge : `.txt`, `.md`, `.pdf`, `.py`, `.json`, `.csv`, et d'autres.

### 3. Poser une question de recherche

```bash
diapason ask "Résume tous les documents traitant des architectures transformeur"
```

L'agent de recherche approfondie va :

1. Chercher les morceaux pertinents dans tes documents indexés
2. Raisonner sur plusieurs sources (jusqu'à 8 sauts)
3. Synthétiser une réponse cohérente, avec les références aux documents sources

## Les commandes de la CLI

```bash
# Poser une question (avec cette config, l'agent deep_research est celui par défaut)
diapason ask "Quelles réunions ai-je eues avec Alice le mois dernier ?"

# Nommer l'agent explicitement
diapason ask --agent deep_research "Compare les approches décrites dans paper-a.pdf et paper-b.pdf"

# Indexer d'autres documents
diapason memory index ~/Downloads/reports/
diapason memory index ./notes.md

# Chercher directement dans la mémoire
diapason memory search "calendrier du projet"
diapason memory search -k 20 "estimations budgétaires"

# Voir ce qui est indexé
diapason memory stats
```

## La configuration en référence

Le préréglage écrit ceci dans `~/.diapason/config.toml` :

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:9b"
temperature = 0.3               # Température basse, pour une recherche factuelle

[agent]
default_agent = "deep_research"
max_turns = 8                   # Étapes de raisonnement multi-sauts

[tools]
enabled = ["knowledge_search", "knowledge_sql", "scan_chunks", "think", "web_search"]

[tools.storage]
default_backend = "sqlite"
```

### Les réglages qui comptent

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `intelligence.default_model` | `qwen3.5:9b` | Le modèle qui raisonne. Les modèles plus gros (`qwen3.5:35b`, par exemple) donnent de meilleurs résultats sur les questions complexes. |
| `intelligence.temperature` | `0.3` | Une température basse garde les réponses factuelles. Augmente-la pour une synthèse plus créative. |
| `agent.max_turns` | `8` | Nombre maximum de sauts de raisonnement. Augmente-le pour les recherches profondément imbriquées. |
| `tools.enabled` | 5 outils | `knowledge_search` (sémantique), `knowledge_sql` (structuré), `scan_chunks` (parcours), `think` (brouillon de raisonnement), `web_search` (repli en ligne). |
| `tools.storage.default_backend` | `sqlite` | Recherche plein texte adossée à FTS5. Accepte aussi `faiss`, `colbert`, `bm25` et `hybrid`. |

## Des exemples de questions

```bash
# Résumer plusieurs documents à la fois
diapason ask "Résume tous les courriels sur la revue du budget du T3"

# Recouper les sources
diapason ask "Sur quoi les articles A et B s'accordent-ils à propos des mécanismes d'attention ?"

# Trouver une information précise
diapason ask "Quelles réunions ai-je eues avec Alice le mois dernier ?"

# Extraire des données structurées
diapason ask "Liste toutes les actions à mener dans les notes de réunion de ~/Documents/meetings/"

# Chercher avec repli sur le web
diapason ask "Compare nos relevés de performance internes aux derniers résultats publiés"
```

## Indexer différentes sources de données

### Les fichiers et dossiers locaux

```bash
# Indexer un dossier, récursivement
diapason memory index ~/Documents/

# Un seul fichier
diapason memory index ./report.pdf

# Une taille de morceau sur mesure, pour les longs documents
diapason memory index ./paper.pdf --chunk-size 1024 --chunk-overlap 128
```

### Les PDF

Les PDF sont extraits et découpés automatiquement. Pour de bons résultats avec des PDF numérisés, assure-toi qu'ils sont passés par l'OCR.

```bash
diapason memory index ~/Papers/*.pdf
```

### Les pages web

Utilise l'outil `web_search` (activé par défaut dans cette config) pour tirer des sources en ligne au moment de la question. Pour indexer durablement du contenu web, télécharge d'abord les pages :

```bash
curl -s https://example.com/article | diapason memory index --stdin --source "example.com"
```

### Les dépôts de code

```bash
diapason memory index ./src/ --chunk-size 256
```

Les petites tailles de morceau conviennent mieux au code, où chaque fonction ou classe forme une unité naturelle.

## Dépannage

**« No results found »** — Assure-toi d'avoir d'abord indexé des documents avec `diapason memory index`. Vérifie ce qui est indexé avec `diapason memory stats`.

**Les réponses sont trop vagues** — Augmente `max_turns` dans la config (`12` ou `15`, par exemple) pour donner plus d'étapes de raisonnement à l'agent. Tu peux aussi essayer un modèle plus gros, comme `qwen3.5:35b`.

**Les réponses sont lentes** — L'agent fait plusieurs passes de recherche, et chaque tour est un appel au modèle. Réduis `max_turns`, ou prends un modèle plus petit (`qwen3.5:4b`) pour des résultats plus rapides mais moins fouillés.

**La recherche web ne marche pas** — L'outil `web_search` a besoin de l'API Tavily. Installe-la avec `uv sync --extra tools-search` et pose `TAVILY_API_KEY`.

**Les mauvais morceaux remontent** — Réindexe avec d'autres tailles de morceau. Pour les documents techniques, des morceaux plus petits (`256`) retrouvent souvent plus précisément. Pour du texte narratif, des morceaux plus grands (`1024`) gardent plus de contexte.
