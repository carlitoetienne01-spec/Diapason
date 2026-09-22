# Le planificateur de tâches

Le planificateur de tâches lance des questions d'agent automatiquement, selon un calendrier — une seule fois à une date à venir, à intervalle régulier, ou par une expression cron. Les tâches planifiées sont conservées en SQLite : elles survivent au redémarrage du processus. L'exécution revient à un fil démon d'arrière-plan, qui va voir toutes les 60 secondes quelles tâches sont dues.

!!! note "Un composant optionnel"
    Le planificateur est un module autonome (`diapason.scheduler`). Il n'est pas branché au démarrage par défaut de `Diapason` / `DiapasonSystem`. Tu l'actives explicitement par `SystemBuilder`, ou en démarrant le démon en ligne de commande avec `diapason scheduler start`.

---

## Les types de planification

| `schedule_type` | Format de `schedule_value`          | Exemple                     | Ce que ça veut dire                 |
|-----------------|------------------------------------|-----------------------------|-------------------------------------|
| `once`          | Date-heure ISO 8601 en UTC         | `"2026-03-01T09:00:00Z"`    | Lance une seule fois à cet instant  |
| `interval`      | Des secondes, en chaîne            | `"3600"`                    | Lance toutes les heures, à partir de maintenant |
| `cron`          | Expression cron standard à 5 champs | `"0 9 * * 1-5"`            | 09:00 UTC, du lundi au vendredi     |

!!! tip "Le support de cron"
    Les expressions cron complètes réclament `croniter` (`uv pip install croniter`). Sans lui, le planificateur se rabat sur un parseur interne minimal, qui ne sait lire que les motifs simples `minute hour * * *`.

---

## Les commandes en ligne de commande

Le groupe de sous-commandes `diapason scheduler` gère les tâches et le démon depuis le terminal.

### Démarrer le démon

```bash
diapason scheduler start
```

Démarre le démon de scrutation en arrière-plan. Le démon occupe le premier plan jusqu'à ce qu'on l'interrompe (++ctrl+c++). En production, fais-le tourner sous systemd ou launchd (voir [Déploiement](../deployment/systemd.md)).

### Créer une tâche

```bash
# Lancer une seule fois, à une date précise
diapason scheduler create \
  --prompt "Génère le rapport de synthèse hebdomadaire" \
  --type once \
  --value "2026-03-01T09:00:00Z"

# Lancer toutes les heures
diapason scheduler create \
  --prompt "Vérifie les nouveaux courriels et résume-les" \
  --type interval \
  --value "3600" \
  --agent orchestrator \
  --tools retrieval,think

# Lancer selon un calendrier cron
diapason scheduler create \
  --prompt "Résume les journaux de la nuit" \
  --type cron \
  --value "0 8 * * 1-5"
```

### Lister les tâches

```bash
# Toutes les tâches
diapason scheduler list

# Les tâches actives seulement
diapason scheduler list --status active

# Les tâches en pause
diapason scheduler list --status paused
```

Exemple de sortie :

```
ID               AGENT     TYPE       VALUE          STATUS   NEXT RUN
a3f9b12c4d8e    simple    cron       0 8 * * 1-5    active   2026-02-26T08:00:00+00:00
b7c2e56f1a3d    orchestr  interval   3600           active   2026-02-25T14:05:00+00:00
```

### Mettre en pause et reprendre

```bash
# Mettre en pause une tâche en marche
diapason scheduler pause a3f9b12c4d8e

# Reprendre -- next_run est recalculé à partir de l'heure courante
diapason scheduler resume a3f9b12c4d8e
```

### Annuler une tâche

```bash
# Annulation définitive (status -> "cancelled", next_run effacé)
diapason scheduler cancel a3f9b12c4d8e
```

### Voir le journal des exécutions

```bash
# Les 10 dernières exécutions d'une tâche
diapason scheduler logs a3f9b12c4d8e
```

Exemple de sortie :

```
Run 1: started=2026-02-25T08:00:01Z finished=2026-02-25T08:00:04Z success=True
  Result: Overnight logs contain 3 warnings and no errors.
Run 2: started=2026-02-24T08:00:00Z finished=2026-02-24T08:00:05Z success=True
  Result: Logs are clean.
```

---

## L'API Python

```python title="scheduler_example.py"
from diapason.scheduler.store import SchedulerStore
from diapason.scheduler.scheduler import TaskScheduler

# Mettre en place le stockage
store = SchedulerStore(db_path="~/.diapason/scheduler.db")  # (1)!

# Brancher un DiapasonSystem pour exécuter les tâches
from diapason import Diapason
diapason = Diapason()

scheduler = TaskScheduler(
    store=store,
    system=diapason,         # (2)!
    poll_interval=60,      # (3)!
)

# Créer des tâches
daily_summary = scheduler.create_task(
    prompt="Résume les gros titres de l'actualité",
    schedule_type="cron",
    schedule_value="0 8 * * *",
    agent="simple",
)
print(f"Tâche {daily_summary.id} créée, prochaine exécution : {daily_summary.next_run}")

# Lister les tâches actives
for task in scheduler.list_tasks(status="active"):
    print(f"  {task.id}: {task.prompt} @ {task.next_run}")

# Gérer l'état d'une tâche
scheduler.pause_task(daily_summary.id)
scheduler.resume_task(daily_summary.id)   # next_run recalculé à partir de maintenant
scheduler.cancel_task(daily_summary.id)  # définitif

# Démarrer le fil d'arrière-plan
scheduler.start()   # (4)!

# ... l'application tourne ...

scheduler.stop()
diapason.close()
```

1. La base SQLite qui garde l'état de toutes les tâches et le journal des exécutions.
2. Le planificateur appelle `system.ask(task.prompt, agent=task.agent, tools=...)` quand une tâche est due. Passe `system=None` pour un mode à blanc, qui journalise ce qu'il aurait exécuté sans jamais appeler l'agent.
3. Le nombre de secondes entre deux tours de scrutation. Plus c'est bas, plus la réaction est vive — au prix de lectures SQLite plus nombreuses.
4. Démarre un fil démon nommé `"diapason-scheduler"`. Un fil démon se termine tout seul quand le processus principal se termine.

---

## Les champs de `ScheduledTask`

Chaque tâche est représentée par une dataclass `ScheduledTask`.

| Champ            | Type              | Défaut        | Description                                       |
|------------------|-------------------|---------------|---------------------------------------------------|
| `id`             | `str`             | auto (16 hex) | Identifiant unique de la tâche                    |
| `prompt`         | `str`             | —             | La question envoyée à l'agent à l'exécution       |
| `schedule_type`  | `str`             | —             | `"cron"`, `"interval"` ou `"once"`                |
| `schedule_value` | `str`             | —             | Expression cron, secondes d'intervalle, ou date-heure ISO |
| `context_mode`   | `str`             | `"isolated"`  | Le mode du contexte d'exécution                   |
| `status`         | `str`             | `"active"`    | `"active"`, `"paused"`, `"completed"`, `"cancelled"` |
| `next_run`       | `str` ou `None`   | calculé       | Date-heure ISO 8601 UTC de la prochaine exécution |
| `last_run`       | `str` ou `None`   | `None`        | Date-heure ISO 8601 UTC de la dernière exécution  |
| `agent`          | `str`             | `"simple"`    | La clé du registre d'agents à employer pour l'exécution |
| `tools`          | `str`             | `""`          | Les noms d'outils pour l'agent, séparés par des virgules |
| `metadata`       | `dict`            | `{}`          | Métadonnées libres attachées à la tâche           |

---

## Donner les outils du planificateur à un agent

Les cinq outils MCP du planificateur (`schedule_task`, `list_scheduled_tasks`, `pause_scheduled_task`, `resume_scheduled_task`, `cancel_scheduled_task`) se passent à n'importe quel `ToolUsingAgent` : un agent peut alors planifier ses propres suites tout seul.

```bash
# Laisser l'orchestrator planifier lui-même la suite
diapason ask --agent orchestrator \
  --tools schedule_task,list_scheduled_tasks \
  "Documente-toi sur les architectures de transformeurs et planifie un résumé quotidien à 8 h"
```

```python
from diapason import Diapason

j = Diapason()
response = j.ask(
    "Planifie un condensé hebdomadaire des articles de recherche, chaque lundi à 9 h",
    agent="orchestrator",
    tools=["schedule_task"],
)
print(response)
```

Voir [Les outils du planificateur](tools.md#scheduler-tools) pour la référence complète des paramètres.

---

## La configuration

Les réglages du planificateur vivent dans la section `[scheduler]` de `~/.diapason/config.toml`.

```toml title="~/.diapason/config.toml"
[scheduler]
enabled = false
db_path = "~/.diapason/scheduler.db"
poll_interval = 60
default_agent = "simple"
```

| Clé              | Type   | Défaut                           | Description                                |
|------------------|--------|----------------------------------|--------------------------------------------|
| `enabled`        | `bool` | `false`                          | Démarre le démon du planificateur automatiquement |
| `db_path`        | `str`  | `~/.diapason/scheduler.db`     | Chemin de la base SQLite                   |
| `poll_interval`  | `int`  | `60`                             | Secondes entre deux tours de scrutation    |
| `default_agent`  | `str`  | `"simple"`                       | Agent par défaut pour les tâches qui n'en nomment pas |

---

## Voir aussi

- [Référence des outils du planificateur](tools.md#scheduler-tools) — le détail des paramètres des outils MCP
- [Architecture : la logique agentique](../architecture/agents.md) — comment le planificateur s'intègre aux agents
- [Déploiement : systemd](../deployment/systemd.md) — faire tourner le planificateur comme service système
