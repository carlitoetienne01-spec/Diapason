# La recherche de spec guidée par un LLM

La recherche de spec guidée par un LLM (*LLM-guided spec search*, Saad-Falcon
et al., 2026) est une collaboration entre le local et le distant : un modèle
de pointe distant — le *professeur* — lit les traces d'un agent local déjà
déployé et propose des modifications typées sur toute la configuration de cet
agent ; le matériel local fait ensuite tourner la configuration obtenue sans
le moindre coût d'API marginal au moment de l'inférence. Un *portier*, qui
note sur des données réservées, n'accepte que les modifications améliorant un
groupe d'échecs visé sans régression inacceptable ailleurs.

Cette page est un tutoriel à copier-coller. À la fin, tu auras :

- un vrai `SpecSearchOrchestrator` qui tourne sur ta machine,
- une boucle multi-sessions avec la règle de stagnation de l'article (algorithme 1),
- une idée claire des réglages à toucher pour un déploiement en production.

## En bref — lance-le

```bash
python examples/diapason/spec_search_quickstart.py
```

Le script se suffit à lui-même (pas de clé d'API, pas d'Ollama) : il câble le
vrai orchestrateur, la vraie boucle multi-sessions et les vrais modules de
récompense composite avec des bouchons de professeur, d'élève et de juge, pour
que tu voies une session complète et une boucle de stagnation aller jusqu'à
leur terme. Les points à remplacer en production sont commentés sur place ;
voir [Passer en production](#going-to-production) plus bas.

## Comment ça marche

Une session de recherche répète quatre phases (§3.3 de l'article) :

| Phase | Ce qui se passe |
|---|---|
| **Diagnostiquer** | Le professeur lit les traces éligibles et regroupe les échecs en groupes, chacun annoté de `(student_failure_rate, teacher_success_rate, skill_gap)`. |
| **Planifier** | Le professeur propose des modifications typées sur les quatre primitives modifiables (Intelligence, Moteur, Agents, Outils et Mémoire). Une même proposition peut modifier plusieurs emplacements à la fois. |
| **Exécuter** | Chaque modification candidate est appliquée ; le portier note la spec obtenue sur un sous-échantillon réservé. Acceptée si et seulement si `GateOK` est vraie (voir plus bas). |
| **Consigner** | Les modifications acceptées sont validées dans le magasin de points de contrôle ; celles qui sont refusées sont annulées. La session est persistée dans `SessionStore`. |

`SpecSearchOrchestrator.run(trigger)` mène **une seule** session de bout en
bout. `SpecSearchLoop` (algorithme 1 de l'article) enveloppe l'orchestrateur et
répète les sessions jusqu'à la stagnation du score du portier (*k* = 5 sessions
par défaut) ou l'épuisement du budget.

### `GateOK` — le prédicat d'acceptation

Soit `G_c(S)` le score du portier, sur données réservées, de la spec `S`
restreinte au groupe d'échecs `c`. Pour une modification `e` visant le groupe
`c`, avec `S' = apply(S, e)` :

```
GateOK(S', S, c, eps) ⟺
    G_c(S')  >  G_c(S)            # le groupe visé s'améliore, ET
    G_c'(S') >= G_c'(S) − eps     # tout autre groupe régresse de ≤ eps
```

Par défaut `eps = 0.01` (1 %), comme dans l'article. La classe `BenchmarkGate`
l'implémente ; le réglage `max_regression`, c'est `eps`.

### La récompense composite (seulement pour l'entraînement des modifications d'Intelligence)

Quand une modification d'Intelligence déclenche un entraînement LoRA / GRPO
pendant la phase d'exécution, les réponses candidates `y` à la question `q`
sont notées par (éq. 1 de l'article) :

```
R(q, y) = α · R_acc(q, y)
       − β · Ê(q, y)        # énergie
       − γ · L̂(q, y)        # latence
       − δ · Ĉ(q, y)        # coût
```

Par défaut `(α, β, γ, δ) = (0.5, 0.1, 0.1, 0.3)`. Les grandeurs d'efficacité
(E, L, C) sont centrées-réduites *à l'intérieur du lot* avant d'être pondérées :
la récompense arbitre donc entre des écarts sans dimension, et non entre des
joules, des secondes et des dollars bruts (annexe C.6 de l'article).
Implémentation : `diapason.learning.spec_search.composite_reward.score_batch`.

Le portier, lui, évalue la spec obtenue de bout en bout sur ses données
réservées ; ces poids ne l'affectent pas.

## La configuration

La config toute prête vit dans
`configs/diapason/examples/spec-search-quickstart.toml`. Copie-la vers
`~/.diapason/config.toml` (ou pointe `DIAPASON_CONFIG` dessus) et le chargeur
habituel la prend :

```python
from diapason.core.config import load_config
cfg = load_config().learning.spec_search   # SpecSearchLearningConfig
```

La table `[learning.spec_search]` correspond terme à terme à la dataclass
`SpecSearchLearningConfig`, et elle est lue à la fois par
`SpecSearchOrchestrator.from_config` et par `SpecSearchLoop` :

```toml
[learning.spec_search]
enabled = true
teacher_model = "claude-opus-4-6"
teacher_engine = "cloud"
autonomy_mode  = "tiered"             # auto | tiered | manual

# Bornes par session
min_traces                   = 20
max_cost_per_session_usd     = 5.0
max_tool_calls_per_diagnosis = 30

# Boucle multi-sessions (algorithme 1 de l'article)
stagnation_k        = 5               # défaut de l'article
stagnation_eps      = 0.001
max_total_cost_usd  = 50.0

# Portier (GateOK)
max_regression           = 0.01       # défaut de l'article : epsilon = 1 %
min_improvement          = 0.0
benchmark_subsample_size = 50
benchmark_version        = "personal_v1"

[learning.spec_search.composite_reward]
alpha = 0.5    # exactitude
beta  = 0.1    # énergie
gamma = 0.1    # latence
delta = 0.3    # coût
```

## Passer en production

Le démarrage rapide utilise des doublures pour le moteur du professeur, le
lanceur d'élève et le juge, afin de tourner sans aucun service extérieur. Pour
mener une vraie session, remplace chaque doublure par le composant de
production correspondant :

| Emplacement | Démarrage rapide | Production |
|---|---|---|
| `teacher_engine` | `FakeTeacherEngine` | `EngineRegistry.get(cfg.teacher_engine)(model=cfg.teacher_model)` — pose `ANTHROPIC_API_KEY` et les autres. |
| `trace_store` | `MagicMock` | `diapason.traces.store.TraceStore(home / "traces.db")` |
| `student_runner` | `MagicMock` | `diapason.learning.spec_search.student_runner.VLLMStudentRunner(host=..., model=...)` |
| `judge` | `MagicMock` | `diapason.evals.core.scorer.LLMJudgeScorer(...)` (ou un noteur déterministe si ton banc d'essai en fournit un) |
| `session_store` | `MagicMock` | `diapason.learning.spec_search.storage.session_store.SessionStore(home / "learning" / "sessions.db")` |
| `checkpoint_store` | `MagicMock` | `diapason.learning.spec_search.checkpoint.store.CheckpointStore(home / "learning" / "checkpoints")` |
| `scorer` | une doublure qui grimpe puis plafonne | un vrai appelable `Scorer` (en général un adaptateur autour de `BenchmarkGate.score`) |

L'orchestrateur ne dépend que de l'*interface* de chaque emplacement, jamais de
la classe concrète — tout ce qui implémente le protocole correspondant fait
l'affaire.

## Ajouter un nouveau corpus externe

La phase de diagnostic sait avaler des enregistrements venus d'un corpus
externe adossé à HuggingFace. Trois fournisseurs sont livrés dans l'arbre
(`adp`, `toolorchestra`, `generalthoughts`) ; pour en ajouter un :

1. Crée `src/diapason/evals/datasets/<corpus>.py` en implémentant
   `DatasetProvider` (`adp.py` est une petite référence). Le
   `load(max_samples, seed, split)` du fournisseur doit respecter `split` par
   `apply_split`, de `diapason.evals.core.splits`.
2. Déclare-le : `@DatasetRegistry.register("<corpus>")`.
3. Donne-le au proposeur par le magasin de traces :

```python
from diapason.evals.datasets.adp import ADPDataset
from diapason.learning.spec_search.external_adapter import (
    write_external_records_as_traces,
)
from diapason.traces.store import TraceStore

records = list(ADPDataset().load(max_samples=200, seed=42, split="all"))
store = TraceStore("~/.diapason/traces.db")
n = write_external_records_as_traces(store, records, source_name="adp")
# le proposeur peut maintenant filtrer sur metadata["source"] == "adp"
```

## Ce qui tourne où

Au moment de l'inférence, la spec obtenue tourne entièrement sur l'appareil —
inférence du modèle, exécution de l'agent, appel d'outil. Les appels d'API vers
le professeur n'ont lieu qu'au moment de la recherche (diagnostiquer +
planifier), et seules les **traces éligibles et expurgées** sont transmises
(selon les règles d'éligibilité des traces posées dans ta config).

Si tu exiges un fonctionnement strictement local, mets un plus gros modèle
local à la place du professeur : tu y perds en qualité de recherche, tu
n'exposes plus rien au dehors.

## Le défaut corrigé dans cette version

`src/diapason/evals/backends/diapason_agent.py` écrivait en dur
`builder.telemetry(telemetry).traces(True).build()`, sans tenir compte du
paramètre `telemetry`. Toute évaluation passant par le backend agent écrivait
donc dans `~/.diapason/traces.db`, en silence, quoi qu'ait demandé l'appelant.
Une `traces.db` corrompue transformait ensuite chaque évaluation d'agent en
erreurs « database disk image is malformed », que le noteur d'évaluation
laissait tomber : il en sortait de fausses exactitudes élevées, tirées d'une
poignée d'échantillons réussis.

Le correctif tient en une ligne :

```python
self._system = builder.telemetry(telemetry).traces(telemetry).build()
```

Les appelants qui comptaient jusqu'ici sur une écriture systématique des traces
doivent désormais passer `telemetry=True` explicitement.

## Voir aussi

- `examples/diapason/spec_search_quickstart.py` — la démo exécutable de bout en bout.
- `configs/diapason/examples/spec-search-quickstart.toml` — la config toute prête.
- `src/diapason/learning/spec_search/orchestrator.py` — `SpecSearchOrchestrator` (une seule session).
- `src/diapason/learning/spec_search/multi_session.py` — `SpecSearchLoop` (algorithme 1).
- `src/diapason/learning/spec_search/composite_reward.py` — l'éq. 1 de l'article.
- `src/diapason/learning/spec_search/gate/benchmark_gate.py` — le prédicat `GateOK`.
- `src/diapason/learning/spec_search/external_adapter.py` — l'adaptateur corpus → trace.
- `tests/learning/spec_search/test_multi_session.py`, `test_composite_reward.py` — les tests unitaires.
- `tests/learning/spec_search/test_orchestrator.py` — le test de session complète, avec des mocks.
