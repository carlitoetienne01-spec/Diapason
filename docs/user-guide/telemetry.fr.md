# Télémétrie et traces

Diapason a deux systèmes d'observation complémentaires : la **télémétrie**, pour les mesures prises à chaque inférence, et les **traces**, qui enregistrent une interaction entière. Ensemble, ils donnent une vue complète du comportement du système et alimentent les mises à jour de la politique d'aiguillage du système d'apprentissage.

---

## La télémétrie

Le système de télémétrie enregistre des mesures pour chaque appel d'inférence — latence, nombre de jetons, coût et consommation d'énergie. Les données sont rangées dans SQLite ; tu peux les interroger, les exporter et les agréger.

### TelemetryRecord

Chaque appel d'inférence produit un `TelemetryRecord` avec les champs suivants :

| Champ                | Type             | Description                              |
|----------------------|------------------|------------------------------------------|
| `timestamp`          | `float`          | Horodatage Unix de l'appel               |
| `model_id`           | `str`            | Identifiant du modèle                    |
| `engine`             | `str`            | Moteur d'inférence utilisé               |
| `agent`              | `str`            | Agent utilisé (s'il y en a un)           |
| `prompt_tokens`      | `int`            | Jetons consommés en entrée               |
| `completion_tokens`  | `int`            | Jetons générés en sortie                 |
| `total_tokens`       | `int`            | Jetons au total (prompt + complétion)    |
| `latency_seconds`    | `float`          | Temps d'inférence à l'horloge            |
| `ttft`               | `float`          | Délai jusqu'au premier jeton             |
| `cost_usd`           | `float`          | Coût estimé, en dollars US               |
| `energy_joules`      | `float`          | Consommation d'énergie estimée           |
| `power_watts`        | `float`          | Puissance appelée pendant l'inférence    |
| `metadata`           | `dict[str, Any]` | Métadonnées supplémentaires              |

### TelemetryStore

Le `TelemetryStore` est une base SQLite en ajout seul qui conserve les enregistrements de télémétrie. Il se branche sur le bus d'événements pour les capturer tout seul.

```python
from diapason.telemetry.store import TelemetryStore
from diapason.core.events import EventBus

bus = EventBus()
store = TelemetryStore(db_path="~/.diapason/telemetry.db")
store.subscribe_to_bus(bus)

# Les enregistrements sont capturés tout seuls dès qu'un TELEMETRY_RECORD part.
# Rien à enregistrer à la main — instrumented_generate() s'en charge.

store.close()
```

Le magasin s'abonne aux événements `TELEMETRY_RECORD` du bus. Dès que l'enveloppe `instrumented_generate()` est utilisée (ce qui arrive tout seul, aussi bien en ligne de commande que dans le SDK), les enregistrements de télémétrie sont publiés et rangés sans que tu aies à intervenir.

### `instrumented_generate()`

Cette fonction d'enveloppe appelle `engine.generate()` et publie automatiquement les événements de télémétrie :

1. Elle publie `INFERENCE_START`, avec le modèle et le moteur.
2. Elle appelle le moteur et mesure la latence à l'horloge.
3. Elle extrait la consommation de jetons de la réponse du moteur.
4. Elle construit un `TelemetryRecord` à partir des mesures.
5. Elle publie les événements `INFERENCE_END` et `TELEMETRY_RECORD`.

Toutes les commandes de la CLI et toutes les méthodes du SDK passent par cette enveloppe : la télémétrie s'enregistre sans que rien ne le montre.

### TelemetryAggregator

Le `TelemetryAggregator` offre des méthodes de lecture seule pour interroger et agréger les données de télémétrie déjà rangées.

```python
from diapason.telemetry.aggregator import TelemetryAggregator

agg = TelemetryAggregator(db_path="~/.diapason/telemetry.db")

# Le résumé global
summary = agg.summary()
print(f"Appels au total : {summary.total_calls}")
print(f"Jetons au total : {summary.total_tokens}")
print(f"Coût total : {summary.total_cost:.6f} $")

# Le détail par modèle
for ms in agg.per_model_stats():
    print(f"  {ms.model_id} : {ms.call_count} appels, {ms.avg_latency:.3f} s en moyenne")

# Le détail par moteur
for es in agg.per_engine_stats():
    print(f"  {es.engine} : {es.call_count} appels, {es.total_tokens} jetons")

# Les modèles les plus utilisés
top = agg.top_models(n=5)

# Exporter les enregistrements bruts
records = agg.export_records()

# Filtrer sur une plage de temps (horodatages Unix)
recent = agg.summary(since=1700000000.0)

# Effacer tous les enregistrements
count = agg.clear()
print(f"{count} enregistrements supprimés")

agg.close()
```

#### Les méthodes d'agrégation

| Méthode             | Rend               | Description                                |
|---------------------|--------------------|--------------------------------------------|
| `summary()`         | `AggregatedStats`  | Appels, jetons, coût et latence au total, plus le détail par modèle et par moteur |
| `per_model_stats()` | `list[ModelStats]`  | Nombre d'appels, jetons, latence et coût, groupés par modèle |
| `per_engine_stats()`| `list[EngineStats]` | Nombre d'appels, jetons, latence et coût, groupés par moteur |
| `top_models(n)`     | `list[ModelStats]`  | Les N modèles les plus appelés             |
| `export_records()`  | `list[dict]`        | Tous les enregistrements, en dictionnaires simples |
| `record_count()`    | `int`               | Nombre total d'enregistrements rangés      |
| `clear()`           | `int`               | Efface tous les enregistrements et rend leur nombre |

Toutes les méthodes d'interrogation acceptent les paramètres facultatifs `since` et `until` (des horodatages Unix) pour filtrer sur une plage de temps.

#### Les classes de données

**ModelStats :**

| Champ              | Type    | Description                    |
|--------------------|---------|--------------------------------|
| `model_id`         | `str`   | Identifiant du modèle          |
| `call_count`       | `int`   | Appels d'inférence au total    |
| `total_tokens`     | `int`   | Jetons traités au total        |
| `prompt_tokens`    | `int`   | Jetons d'entrée au total       |
| `completion_tokens`| `int`   | Jetons de sortie au total      |
| `total_latency`    | `float` | Somme de toutes les latences   |
| `avg_latency`      | `float` | Latence moyenne par appel      |
| `total_cost`       | `float` | Coût total, en dollars US      |

**EngineStats :**

| Champ           | Type    | Description                    |
|-----------------|---------|--------------------------------|
| `engine`        | `str`   | Identifiant du moteur          |
| `call_count`    | `int`   | Appels d'inférence au total    |
| `total_tokens`  | `int`   | Jetons traités au total        |
| `total_latency` | `float` | Somme de toutes les latences   |
| `avg_latency`   | `float` | Latence moyenne par appel      |
| `total_cost`    | `float` | Coût total, en dollars US      |

**AggregatedStats :**

| Champ           | Type               | Description                          |
|-----------------|--------------------|--------------------------------------|
| `total_calls`   | `int`              | Appels d'inférence au total          |
| `total_tokens`  | `int`              | Jetons au total, tous modèles confondus |
| `total_cost`    | `float`            | Coût total, en dollars US            |
| `total_latency` | `float`            | Latence totale, en secondes          |
| `per_model`     | `list[ModelStats]`  | Le détail par modèle                 |
| `per_engine`    | `list[EngineStats]` | Le détail par moteur                 |

### Les commandes de la CLI

```bash
# Afficher les statistiques agrégées
diapason telemetry stats
diapason telemetry stats -n 5          # Les 5 premiers modèles seulement

# Exporter les enregistrements
diapason telemetry export              # JSON sur la sortie standard
diapason telemetry export -f csv       # CSV sur la sortie standard
diapason telemetry export -o data.json # JSON dans un fichier
diapason telemetry export -f csv -o metrics.csv

# Effacer tous les enregistrements
diapason telemetry clear               # Avec demande de confirmation
diapason telemetry clear --yes         # Sans confirmation
```

---

## Les traces

Là où la télémétrie prend des mesures à chaque inférence, le système de traces enregistre des **séquences d'interaction entières** — toute la chaîne d'étapes qu'un agent suit pour traiter une question. Les traces sont la matière première du système d'apprentissage.

### Qu'est-ce qu'une trace ?

Une `Trace` capture tout le cycle de vie du traitement d'une question :

| Champ                    | Type               | Description                                    |
|--------------------------|--------------------|------------------------------------------------|
| `trace_id`               | `str`              | Identifiant unique (généré tout seul)          |
| `query`                  | `str`              | La question d'origine                          |
| `agent`                  | `str`              | L'agent qui a traité la question               |
| `model`                  | `str`              | Le modèle utilisé pour l'inférence             |
| `engine`                 | `str`              | Le moteur d'inférence utilisé                  |
| `steps`                  | `list[TraceStep]`  | La liste ordonnée des étapes de traitement     |
| `result`                 | `str`              | Le contenu de la réponse finale                |
| `outcome`                | `str` ou `None`    | `"success"`, `"failure"`, ou `None` (inconnu)  |
| `feedback`               | `float` ou `None`  | Note de qualité donnée par l'utilisateur, entre 0 et 1 |
| `started_at`             | `float`            | Horodatage Unix du début du traitement         |
| `ended_at`               | `float`            | Horodatage Unix de la fin du traitement        |
| `total_tokens`           | `int`              | Jetons au total, toutes étapes confondues      |
| `total_latency_seconds`  | `float`            | Latence totale, toutes étapes confondues       |
| `metadata`               | `dict[str, Any]`   | Métadonnées supplémentaires                    |

### Trace et télémétrie : la différence

| Aspect          | Télémétrie                               | Traces                                        |
|-----------------|------------------------------------------|-----------------------------------------------|
| **Portée**      | Un seul appel d'inférence                | L'interaction entière (plusieurs étapes)      |
| **Granularité** | Des mesures par appel                    | Une séquence, étape par étape                 |
| **Rôle**        | Surveiller les performances, suivre le coût | Apprendre, optimiser l'aiguillage, déboguer |
| **Données**     | Latence, jetons, coût, énergie           | Route, récupération, génération, appel d'outil, réponse |
| **Rangement**   | Une table plate d'enregistrements        | Une table de traces + une table d'étapes      |

### TraceStep

Chaque étape d'une trace enregistre une action que l'agent a menée.

| Champ              | Type             | Description                              |
|--------------------|------------------|------------------------------------------|
| `step_type`        | `StepType`       | Le type d'étape (voir ci-dessous)        |
| `timestamp`        | `float`          | Le moment où l'étape a eu lieu           |
| `duration_seconds` | `float`          | Le temps qu'elle a pris                  |
| `input`            | `dict[str, Any]` | Les données d'entrée de l'étape          |
| `output`           | `dict[str, Any]` | Les données de sortie de l'étape         |
| `metadata`         | `dict[str, Any]` | Métadonnées supplémentaires              |

### StepType

| Type         | Description                                      | Exemple d'entrée             | Exemple de sortie                  |
|--------------|--------------------------------------------------|------------------------------|------------------------------------|
| `route`      | Décision de choix du modèle ou de l'agent        | `{"query_type": "math"}`     | `{"model": "qwen3:8b"}`           |
| `retrieve`   | Recherche en mémoire pour du contexte            | `{"query": "topic"}`         | `{"num_results": 3}`               |
| `generate`   | Appel d'inférence au modèle                      | `{"model": "qwen3:8b"}`     | `{"tokens": 128}`                  |
| `tool_call`  | Exécution d'un outil                             | `{"tool": "calculator"}`     | `{"success": true}`                |
| `respond`    | Réponse finale rendue à l'utilisateur            | `{}`                         | `{"content": "...", "turns": 2}`   |

### TraceCollector

Le `TraceCollector` enveloppe n'importe quel `BaseAgent` pour enregistrer tout seul une `Trace` à chaque appel de `run()`. Il s'abonne aux événements du bus pendant l'exécution et les convertit en objets `TraceStep`.

```python
from diapason.agents.orchestrator import OrchestratorAgent
from diapason.traces.collector import TraceCollector
from diapason.traces.store import TraceStore
from diapason.core.events import EventBus

bus = EventBus()
store = TraceStore(db_path="./traces.db")

agent = OrchestratorAgent(engine, model, tools=tools, bus=bus)
collector = TraceCollector(agent, store=store, bus=bus)

# La trace s'enregistre toute seule
result = collector.run("Combien font 2+2 ?")
print(result.content)
# La trace est maintenant dans le magasin, et publiée sur le bus
```

**Comment le collecteur travaille :**

1. Il s'abonne aux événements `INFERENCE_START`, `INFERENCE_END`, `TOOL_CALL_START`, `TOOL_CALL_END` et `MEMORY_RETRIEVE`.
2. Il exécute la méthode `run()` de l'agent qu'il enveloppe.
3. Il convertit les événements capturés en objets `TraceStep`, avec leurs temps.
4. Il ajoute une dernière étape `RESPOND` portant le résultat.
5. Il construit un objet `Trace` complet et l'enregistre dans le `TraceStore`.
6. Il publie un événement `TRACE_COMPLETE` sur le bus.
7. Il se désabonne des événements une fois l'exécution terminée.

### TraceStore

Le `TraceStore` est une base adossée à SQLite qui conserve les traces entières, avec leurs étapes.

```python
from diapason.traces.store import TraceStore

store = TraceStore(db_path="./traces.db")

# Enregistrer une trace
store.save(trace)

# Récupérer une trace précise
trace = store.get("abc123def456")

# Lister les traces avec des filtres
traces = store.list_traces(
    agent="orchestrator",
    model="qwen3:8b",
    outcome="success",
    since=1700000000.0,
    limit=50,
)

# Compter les traces
count = store.count()

# S'abonner au bus d'événements pour un enregistrement automatique
store.subscribe_to_bus(bus)

store.close()
```

#### Les options de filtrage

| Paramètre | Type    | Description                                     |
|-----------|---------|-------------------------------------------------|
| `agent`   | `str`   | Filtrer par identifiant d'agent                 |
| `model`   | `str`   | Filtrer par identifiant de modèle               |
| `outcome` | `str`   | Filtrer par issue (`"success"`, `"failure"`)    |
| `since`   | `float` | Début de la plage de temps (horodatage Unix)    |
| `until`   | `float` | Fin de la plage de temps (horodatage Unix)      |
| `limit`   | `int`   | Nombre maximum de traces à rendre (100 par défaut) |

### TraceAnalyzer

Le `TraceAnalyzer` offre des statistiques agrégées, en lecture seule, sur les traces rangées. Ce sont elles que le système d'apprentissage utilise pour mettre à jour les politiques d'aiguillage.

```python
from diapason.traces.analyzer import TraceAnalyzer

analyzer = TraceAnalyzer(store=trace_store)

# Le résumé global
summary = analyzer.summary()
print(f"Traces au total : {summary.total_traces}")
print(f"Étapes au total : {summary.total_steps}")
print(f"Étapes par trace en moyenne : {summary.avg_steps_per_trace:.1f}")
print(f"Latence moyenne : {summary.avg_latency:.3f} s")
print(f"Taux de réussite : {summary.success_rate:.1%}")
print(f"Répartition des étapes : {summary.step_type_distribution}")

# Les statistiques par route (les couples modèle + agent)
for rs in analyzer.per_route_stats():
    print(f"  {rs.model}/{rs.agent} : {rs.count} traces, "
          f"{rs.avg_latency:.3f} s en moyenne, {rs.success_rate:.1%} de réussite")

# Les statistiques par outil
for ts in analyzer.per_tool_stats():
    print(f"  {ts.tool_name} : {ts.call_count} appels, "
          f"{ts.avg_latency:.3f} s en moyenne, {ts.success_rate:.1%} de réussite")

# Retrouver les traces selon les caractéristiques de la question
code_traces = analyzer.traces_for_query_type(has_code=True)
short_traces = analyzer.traces_for_query_type(max_length=100)

# Exporter les traces en dictionnaires simples
exported = analyzer.export_traces(limit=500)
```

#### Les méthodes d'analyse

| Méthode                   | Rend               | Description                                          |
|---------------------------|--------------------|------------------------------------------------------|
| `summary()`               | `TraceSummary`     | Les statistiques d'ensemble : comptes, moyennes, répartitions |
| `per_route_stats()`       | `list[RouteStats]` | Les statistiques groupées par couple (modèle, agent) |
| `per_tool_stats()`        | `list[ToolStats]`  | Les statistiques groupées par nom d'outil            |
| `traces_for_query_type()` | `list[Trace]`      | Filtrer les traces selon les caractéristiques de la question |
| `export_traces()`         | `list[dict]`       | Exporter les traces en dictionnaires sérialisables   |

Toutes les méthodes d'analyse acceptent les paramètres facultatifs `since` et `until` pour filtrer sur une plage de temps.

#### Les classes de données

**TraceSummary :**

| Champ                    | Type            | Description                                  |
|--------------------------|-----------------|----------------------------------------------|
| `total_traces`           | `int`           | Nombre total de traces                       |
| `total_steps`            | `int`           | Étapes au total, toutes traces confondues    |
| `avg_steps_per_trace`    | `float`         | Nombre moyen d'étapes par trace              |
| `avg_latency`            | `float`         | Latence totale moyenne par trace             |
| `avg_tokens`             | `float`         | Jetons moyens par trace                      |
| `success_rate`           | `float`         | Part des traces évaluées qui ont réussi      |
| `step_type_distribution` | `dict[str, int]`| Le compte de chaque type d'étape             |

**RouteStats :**

| Champ          | Type              | Description                                    |
|----------------|-------------------|------------------------------------------------|
| `model`        | `str`             | Identifiant du modèle                          |
| `agent`        | `str`             | Identifiant de l'agent                         |
| `count`        | `int`             | Nombre de traces pour cette route              |
| `avg_latency`  | `float`           | Latence moyenne pour cette route               |
| `avg_tokens`   | `float`           | Jetons moyens pour cette route                 |
| `success_rate` | `float`           | Taux de réussite de cette route                |
| `avg_feedback` | `float` ou `None` | Retour moyen de l'utilisateur (s'il y en a un) |

**ToolStats :**

| Champ          | Type    | Description                              |
|----------------|---------|------------------------------------------|
| `tool_name`    | `str`   | Identifiant de l'outil                   |
| `call_count`   | `int`   | Nombre de fois où l'outil a été appelé   |
| `avg_latency`  | `float` | Latence d'exécution moyenne              |
| `success_rate` | `float` | Part des exécutions réussies             |

---

## Le cheminement des données

Le schéma suivant montre par où passent les données de télémétrie et de trace :

```
Question de l'utilisateur
    |
    v
Agent.run()  -->  EventBus  -->  TraceCollector (capture les étapes)
    |                   |
    v                   v
Engine.generate()  TelemetryStore (capture les mesures par appel)
    |
    v
instrumented_generate()
    |
    +---> événement INFERENCE_START
    +---> événement INFERENCE_END
    +---> événement TELEMETRY_RECORD
    |
    v
TraceCollector
    |
    +---> Construit la Trace et ses TraceStep
    +---> Enregistre dans le TraceStore
    +---> Publie l'événement TRACE_COMPLETE
    |
    v
TraceAnalyzer / TelemetryAggregator  -->  Système d'apprentissage
```

Les deux systèmes travaillent sans rien demander : tu n'as aucune instrumentation à poser à la main quand tu passes par la CLI ou le SDK, puisqu'ils mettent en place le bus d'événements et le magasin de télémétrie tout seuls.
