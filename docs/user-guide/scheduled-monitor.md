# La veille programmée

Un agent `operative` persistant, qui tourne sur un horaire cron, garde son état d'une exécution à l'autre et se sert de la mémoire pour suivre ce qui change au fil du temps. Parfait pour surveiller ta boîte de réception chaque jour, pour les vérifications d'état qui reviennent et pour les projets de recherche au long cours.

## Démarrage rapide (5 minutes)

### 1. Installer et initialiser

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync --extra dev
diapason init --preset scheduled-monitor
```

Cela écrit un `~/.diapason/config.toml` préconfiguré pour l'agent `operative`, avec la programmation activée.

### 2. Lancer un modèle local avec Ollama

```bash
# Installe Ollama : https://ollama.com
ollama pull qwen3.5:9b
```

### 3. Indexer tes données

```bash
diapason memory index ~/Documents/
```

L'agent `operative` se sert de la mémoire pour garder son état d'une exécution à l'autre : indexer tes données lui donne du contexte dès la première.

### 4. Créer une tâche programmée

```bash
diapason scheduler start

diapason scheduler create \
  --prompt "Vérifie s'il y a de nouveaux courriels au sujet du Projet X et mets tes notes à jour" \
  --schedule "0 9 * * 1-5" \
  --agent operative \
  --tools "knowledge_search,knowledge_sql,memory_store,think"
```

Cela crée une tâche qui tourne à 9 h tous les jours de semaine. L'agent `operative` cherchera dans tes données indexées, traitera ce qui est nouveau et rangera ses notes en mémoire pour l'exécution suivante.

## Comment fonctionne la programmation

Le programmateur se sert d'expressions cron pour déclencher les exécutions de l'agent aux intervalles indiqués. Chaque exécution est une session d'agent indépendante, mais l'agent `operative`, lui, garde son état d'une session à l'autre.

### Mémento des expressions cron

```
 .------------ minute (0-59)
 | .---------- heure (0-23)
 | | .-------- jour du mois (1-31)
 | | | .------ mois (1-12)
 | | | | .---- jour de la semaine (0-6, 0 = dimanche)
 | | | | |
 * * * * *
```

Des exemples courants :

| Expression | Ce qu'elle veut dire |
|------------|---------|
| `0 9 * * 1-5` | 9 h, du lundi au vendredi |
| `0 6 * * *` | 6 h tous les jours |
| `*/30 * * * *` | Toutes les 30 minutes |
| `0 9,17 * * *` | 9 h et 17 h tous les jours |
| `0 8 1 * *` | 8 h le 1er de chaque mois |

### Les commandes de la CLI

```bash
# Démarrer le démon programmateur
diapason scheduler start

# Créer une tâche programmée
diapason scheduler create \
  --prompt "Résume les nouveaux articles de recherche de ma bibliothèque" \
  --schedule "0 8 * * *" \
  --agent operative

# Lister toutes les tâches programmées
diapason scheduler list

# Voir le détail d'une tâche et l'historique de ses exécutions
diapason scheduler status <task-id>

# Mettre en pause / reprendre / supprimer une tâche
diapason scheduler pause <task-id>
diapason scheduler resume <task-id>
diapason scheduler delete <task-id>

# Lancer une tâche tout de suite (hors de son horaire)
diapason scheduler run <task-id>

# Arrêter le démon programmateur
diapason scheduler stop
```

## Référence de la configuration

Le préréglage écrit ceci dans `~/.diapason/config.toml` :

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:9b"
temperature = 0.3

[agent]
default_agent = "operative"
max_turns = 20
context_from_memory = true          # Injecte la mémoire pertinente dans le contexte

[tools]
enabled = ["knowledge_search", "knowledge_sql", "scan_chunks", "memory_store", "memory_search", "think", "web_search"]

[tools.storage]
default_backend = "sqlite"
```

### Les réglages qui comptent

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `intelligence.default_model` | `qwen3.5:9b` | Le modèle qui raisonne. |
| `intelligence.temperature` | `0.3` | Une température basse, pour des sorties constantes et factuelles d'une exécution à l'autre. |
| `agent.default_agent` | `operative` | L'agent persistant, qui garde son état d'une session à l'autre. |
| `agent.max_turns` | `20` | Une limite de tours élevée, pour traiter à fond les données accumulées. |
| `agent.context_from_memory` | `true` | Injecte automatiquement les morceaux de mémoire pertinents dans le contexte de l'agent. |
| `tools.enabled` | 7 outils | De quoi chercher, ranger, parcourir et raisonner — lire et écrire dans la base de connaissances. |

### Ce que font les outils

| Outil | Ce qu'il fait |
|------|-------------|
| `knowledge_search` | Recherche sémantique dans les documents indexés. |
| `knowledge_sql` | Requêtes structurées sur le magasin de documents. |
| `scan_chunks` | Parcourt les morceaux de documents un à un. |
| `memory_store` | Écrit de nouveaux faits et de nouvelles notes dans la base de connaissances. |
| `memory_search` | Cherche dans les notes déjà rangées par l'agent. |
| `think` | Brouillon de raisonnement interne, pour planifier. |
| `web_search` | Cherche sur le web ce qui manque. |

## Des exemples d'usage

### La veille quotidienne de la boîte de réception

```bash
diapason scheduler create \
  --prompt "Relis mes courriels récents. Signale ce qui est urgent et résume le reste. Range un résumé quotidien." \
  --schedule "0 9 * * 1-5" \
  --agent operative \
  --tools "knowledge_search,memory_store,think"
```

### Le suivi de la recherche

```bash
diapason scheduler create \
  --prompt "Cherche les nouveaux articles autour de 'efficient transformers'. Compare-les à ceux que j'ai déjà indexés et note ce qui est nouveau." \
  --schedule "0 8 * * 1" \
  --agent operative \
  --tools "knowledge_search,web_search,memory_store,think"
```

### Le rapport d'avancement

```bash
diapason scheduler create \
  --prompt "Regarde les documents d'état du projet et produis un résumé hebdomadaire de l'avancement. Note ce qui bloque." \
  --schedule "0 17 * * 5" \
  --agent operative \
  --tools "knowledge_search,knowledge_sql,memory_store,think"
```

## Comment l'état survit d'une exécution à l'autre

L'agent `operative` se distingue des autres agents en ceci : il garde son état d'une exécution à l'autre.

- **Le rangement en mémoire** : l'agent se sert de l'outil `memory_store` pour garder ses notes, ses résumés et ses observations. Tout cela persiste dans la base SQLite locale et reste disponible aux exécutions suivantes.
- **L'injection du contexte** : avec `context_from_memory = true`, l'agent reçoit automatiquement le contexte pertinent des exécutions précédentes quand il ouvre une nouvelle session.
- **Le savoir accumulé** : au fil du temps, l'agent se construit une compréhension de plus en plus riche de tes données. Une exécution du lundi peut se référer aux notes du vendredi précédent.
- **Tout reste chez toi** : l'état est rangé dans `~/.diapason/`, par le moteur de mémoire configuré. Rien ne quitte ta machine.

## Quand ça coince

**« Scheduler not running »** — démarre le démon programmateur avec `diapason scheduler start`. Il doit tourner pour que les tâches programmées s'exécutent.

**La tâche ne part pas à l'heure** — vérifie qu'Ollama tourne (`ollama serve`). Le programmateur déclenche l'agent, mais l'agent a besoin d'un moteur d'inférence. Contrôle l'horaire avec `diapason scheduler status <task-id>`.

**L'agent rend des résultats qui varient** — garde `temperature` à `0.3` ou plus bas pour les tâches programmées. Une température plus haute introduit un hasard qui s'accumule d'une exécution à l'autre.

**La mémoire grossit trop** — passe-la en revue de temps en temps avec `diapason memory stats`. Efface les vieilles entrées avec `diapason memory clear --before 2026-01-01` si besoin.

**L'agent tourne trop longtemps** — baisse `max_turns` ou simplifie le prompt. L'agent `operative` est minutieux et peut consommer tous les tours qu'on lui laisse.
