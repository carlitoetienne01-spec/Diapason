# Les mesures de performance

Le cadre de mesure évalue les performances d'un moteur d'inférence par des tests reproductibles et normalisés. Il embarque des mesures de latence et de débit, un lanceur de suite pour les enchaîner, et de quoi ajouter tes propres mesures.

## Vue d'ensemble

Diapason est livré avec deux mesures :

| Mesure        | Clé de registre | Ce qu'elle mesure                             |
|---------------|----------------|-----------------------------------------------|
| **Latence**   | `latency`      | La latence d'inférence par appel (moyenne, p50, p95, min, max) |
| **Débit**     | `throughput`    | Le débit, en jetons par seconde               |

---

## La classe abstraite BaseBenchmark

Toutes les mesures implémentent la classe de base abstraite `BaseBenchmark`.

```python
from abc import ABC, abstractmethod
from diapason.bench._stubs import BenchmarkResult
from diapason.engine._stubs import InferenceEngine

class BaseBenchmark(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifiant court de cette mesure."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Description lisible de ce que cette mesure évalue."""

    @abstractmethod
    def run(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        num_samples: int = 10,
    ) -> BenchmarkResult:
        """Exécute la mesure et rend les résultats."""
```

### BenchmarkResult

Chaque passage produit un `BenchmarkResult` :

| Champ            | Type             | Description                              |
|------------------|------------------|------------------------------------------|
| `benchmark_name` | `str`            | Le nom de la mesure                      |
| `model`          | `str`            | Le modèle utilisé                        |
| `engine`         | `str`            | Le moteur utilisé                        |
| `metrics`        | `dict[str, float]` | Les métriques mesurées, par couples clé-valeur |
| `metadata`       | `dict[str, Any]` | Des métadonnées supplémentaires          |
| `samples`        | `int`            | Le nombre d'échantillons lancés          |
| `errors`         | `int`            | Le nombre d'erreurs rencontrées          |

---

## Les mesures fournies

### La mesure de latence

Mesure la latence d'inférence appel par appel, avec des prompts courts et fixes. Chaque échantillon envoie un prompt simple au moteur et chronomètre le temps réel écoulé.

**Les prompts utilisés :** la mesure fait tourner un petit jeu de prompts courts et figés (« Hello », « What is 2+2? », « Explain gravity in one sentence ») pour que la variation de l'entrée reste la même d'un passage à l'autre.

**Les métriques produites :**

| Métrique        | Description                                         |
|-----------------|-----------------------------------------------------|
| `mean_latency`  | La latence moyenne sur tous les échantillons réussis |
| `p50_latency`   | La latence médiane (50ᵉ centile)                    |
| `p95_latency`   | La latence au 95ᵉ centile (le comportement de queue) |
| `min_latency`   | L'appel le plus rapide                              |
| `max_latency`   | L'appel le plus lent                                |

**Exemple de sortie :**

```
latency (10 samples, 0 errors)
  mean_latency: 0.2345
  p50_latency:  0.2100
  p95_latency:  0.3800
  min_latency:  0.1500
  max_latency:  0.4200
```

### La mesure de débit

Mesure le débit d'inférence en jetons par seconde. Chaque échantillon envoie un prompt plus long (« Write a short paragraph about artificial intelligence ») et mesure à la fois le temps pris et le nombre de jetons de complétion générés.

**Les métriques produites :**

| Métrique              | Description                                    |
|-----------------------|------------------------------------------------|
| `tokens_per_second`   | Total des jetons de complétion / temps total   |
| `total_tokens`        | Total des jetons de complétion, tous échantillons confondus |
| `total_time_seconds`  | Temps réel total, tous échantillons confondus  |

**Exemple de sortie :**

```
throughput (10 samples, 0 errors)
  tokens_per_second:  45.6789
  total_tokens:       1250.0000
  total_time_seconds: 27.3600
```

---

## Lire les résultats

### Les métriques de latence

- **mean_latency :** le temps de réponse moyen. Sers-t'en pour comparer les performances d'ensemble.
- **p50_latency (la médiane) :** le temps de réponse habituel. Moins sensible aux valeurs extrêmes que la moyenne.
- **p95_latency :** le pire temps de réponse pour 95 % des requêtes. Décisif pour l'expérience — s'il est trop haut, une partie des utilisateurs subira des délais visibles.
- **min/max_latency :** le meilleur et le pire appel isolé. Un grand écart entre les deux signale des performances irrégulières.

!!! tip "Ce qu'il faut regarder"
    Une installation en bonne santé a `p95 / p50 < 2`. Si le p95 dépasse largement la médiane, cherche du côté de la contention du moteur, du bridage thermique ou de la pression mémoire.

### Les métriques de débit

- **tokens_per_second :** l'indicateur principal de débit. Plus c'est haut, mieux c'est. Les ordres de grandeur habituels :
    - Processeur seul : 5 à 20 jetons par seconde
    - Carte graphique grand public (RTX 3060-4090) : 30 à 100 jetons par seconde
    - Carte graphique de centre de données (A100, H100) : 100 à plus de 500 jetons par seconde
- **total_tokens / total_time :** les données brutes derrière le calcul du débit. Utiles pour vérifier que le moteur génère vraiment quelque chose (et ne rend pas des réponses vides).

---

## BenchmarkSuite

La classe `BenchmarkSuite` lance un ensemble de mesures et offre de quoi les agréger et les sérialiser.

```python
from diapason.bench._stubs import BenchmarkSuite
from diapason.bench.latency import LatencyBenchmark
from diapason.bench.throughput import ThroughputBenchmark

suite = BenchmarkSuite([LatencyBenchmark(), ThroughputBenchmark()])

# Lancer toutes les mesures
results = suite.run_all(engine, model, num_samples=20)

# Sérialiser en JSONL (un objet JSON par ligne)
jsonl = suite.to_jsonl(results)

# Obtenir un dictionnaire de résumé
summary = suite.summary(results)
```

### Les méthodes

| Méthode                 | Rend               | Description                              |
|-------------------------|--------------------|--------------------------------------------|
| `run_all(engine, model, num_samples=10)` | `list[BenchmarkResult]` | Lance toutes les mesures l'une après l'autre |
| `to_jsonl(results)`     | `str`              | Sérialise les résultats au format JSONL  |
| `summary(results)`      | `dict[str, Any]`   | Construit un dictionnaire de résumé      |

### Le format JSONL

Chaque ligne de la sortie JSONL est un objet JSON :

```json
{"benchmark_name": "latency", "model": "qwen3:8b", "engine": "ollama", "metrics": {"mean_latency": 0.234, "p50_latency": 0.21, "p95_latency": 0.38, "min_latency": 0.15, "max_latency": 0.42}, "metadata": {}, "samples": 10, "errors": 0}
{"benchmark_name": "throughput", "model": "qwen3:8b", "engine": "ollama", "metrics": {"tokens_per_second": 45.67, "total_tokens": 1250.0, "total_time_seconds": 27.36}, "metadata": {}, "samples": 10, "errors": 0}
```

### Le format du résumé

```json
{
  "benchmark_count": 2,
  "benchmarks": [
    {
      "name": "latency",
      "model": "qwen3:8b",
      "engine": "ollama",
      "metrics": {"mean_latency": 0.234, ...},
      "samples": 10,
      "errors": 0
    },
    {
      "name": "throughput",
      "model": "qwen3:8b",
      "engine": "ollama",
      "metrics": {"tokens_per_second": 45.67, ...},
      "samples": 10,
      "errors": 0
    }
  ]
}
```

---

## En ligne de commande

```bash
# Lancer toutes les mesures avec les réglages par défaut (10 échantillons)
diapason bench run

# Lancer avec plus d'échantillons, pour une meilleure précision statistique
diapason bench run -n 50

# Lancer seulement la mesure de latence
diapason bench run -b latency

# Lancer seulement la mesure de débit, sur 20 échantillons
diapason bench run -b throughput -n 20

# Choisir le modèle et le moteur
diapason bench run -m qwen3:8b -e ollama

# Afficher le résumé JSON sur la sortie standard
diapason bench run --json

# Écrire les résultats JSONL dans un fichier
diapason bench run -o results.jsonl

# Combiner les options
diapason bench run -b latency -n 100 -m qwen3:8b --json -o latency.jsonl
```

| Option                     | Type    | Défaut    | Description                              |
|----------------------------|---------|-----------|------------------------------------------|
| `-m`, `--model MODEL`      | chaîne  | auto      | Modèle à mesurer                         |
| `-e`, `--engine ENGINE`    | chaîne  | auto      | Moteur d'inférence                       |
| `-n`, `--samples N`        | entier  | `10`      | Nombre d'échantillons par mesure         |
| `-b`, `--benchmark NAME`   | chaîne  | toutes    | Mesure précise à lancer (`latency` ou `throughput`) |
| `-o`, `--output PATH`      | chemin  | aucun     | Écrit les résultats JSONL dans un fichier |
| `--json`                   | drapeau | désactivé | Affiche le résumé JSON sur la sortie standard |

---

## Ajouter tes propres mesures

Pour créer une mesure à toi, dérive `BaseBenchmark` et enregistre-la auprès du `BenchmarkRegistry`.

### Étape 1 : écrire la mesure

```python
import time
from diapason.bench._stubs import BaseBenchmark, BenchmarkResult
from diapason.core.registry import BenchmarkRegistry
from diapason.core.types import Message, Role
from diapason.engine._stubs import InferenceEngine


class ContextLengthBenchmark(BaseBenchmark):
    """Mesure comment la latence évolue avec la longueur de l'entrée."""

    @property
    def name(self) -> str:
        return "context_length"

    @property
    def description(self) -> str:
        return "Mesure l'évolution de la latence quand l'entrée s'allonge"

    def run(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        num_samples: int = 10,
    ) -> BenchmarkResult:
        latencies = {}
        errors = 0

        for length in [100, 500, 1000, 2000]:
            prompt = "x " * length
            messages = [Message(role=Role.USER, content=prompt)]

            t0 = time.time()
            try:
                engine.generate(messages, model=model)
                latencies[f"latency_{length}_tokens"] = time.time() - t0
            except Exception:
                errors += 1

        return BenchmarkResult(
            benchmark_name=self.name,
            model=model,
            engine=engine.engine_id,
            metrics=latencies,
            samples=len(latencies),
            errors=errors,
        )
```

### Étape 2 : enregistrer la mesure

Passe par le motif `ensure_registered()`, qui survit au vidage du registre dans les tests :

```python
def ensure_registered() -> None:
    """Enregistre la mesure si elle n'y est pas déjà."""
    if not BenchmarkRegistry.contains("context_length"):
        BenchmarkRegistry.register_value("context_length", ContextLengthBenchmark)
```

Tu peux sinon utiliser le décorateur à la définition de la classe :

```python
@BenchmarkRegistry.register("context_length")
class ContextLengthBenchmark(BaseBenchmark):
    ...
```

!!! info "Le motif `ensure_registered()`"
    La fonction `ensure_registered()` est préférée au décorateur dans les modules de mesure, parce qu'elle survit au vidage du registre pendant les tests. Les mesures fournies `latency` et `throughput` l'emploient toutes les deux. La commande de mesure appelle `ensure_registered()` avant d'aller chercher les mesures.

### Étape 3 : te servir de ta mesure

Une fois enregistrée, ta mesure est accessible en ligne de commande :

```bash
diapason bench run -b context_length
```

Et par le `BenchmarkSuite` :

```python
from diapason.core.registry import BenchmarkRegistry

bench_cls = BenchmarkRegistry.get("context_length")
bench = bench_cls()
result = bench.run(engine, model, num_samples=5)
```
