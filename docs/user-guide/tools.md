# Les outils

Le système d'outils permet aux agents d'agir au-delà de la génération de texte — calculs, consultations de mémoire, lecture de fichiers, appels à un sous-modèle. Les outils suivent une conception pilotée par la spécification, avec un moteur de répartition central et la prise en charge du format d'appel de fonctions d'OpenAI.

## L'architecture

```
Agent  -->  Engine (with tool defs)  -->  tool_calls response  -->  ToolExecutor  -->  Tool.execute()
  ^                                                                                          |
  |                                                                                          v
  +-------------------------------  ToolResult  <--------------------------------------------+
```

---

## La classe abstraite BaseTool

Tous les outils implémentent la classe de base abstraite `BaseTool`.

```python
from abc import ABC, abstractmethod
from diapason.tools._stubs import ToolSpec
from diapason.core.types import ToolResult

class BaseTool(ABC):
    tool_id: str

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """Rend la spécification de l'outil."""

    @abstractmethod
    def execute(self, **params) -> ToolResult:
        """Exécute l'outil avec les paramètres donnés."""

    def to_openai_function(self) -> dict:
        """Convertit au format d'appel de fonctions d'OpenAI."""
```

La méthode `to_openai_function()` est fournie par la classe de base : elle convertit la spécification de l'outil dans le format qu'attendent les API compatibles OpenAI.

```json
{
  "type": "function",
  "function": {
    "name": "calculator",
    "description": "Evaluate a mathematical expression safely.",
    "parameters": {
      "type": "object",
      "properties": {
        "expression": {
          "type": "string",
          "description": "Math expression to evaluate"
        }
      },
      "required": ["expression"]
    }
  }
}
```

---

## ToolSpec

La dataclasse `ToolSpec` décrit l'interface et les caractéristiques d'un outil.

| Champ                  | Type             | Défaut  | Description                                        |
|------------------------|------------------|---------|----------------------------------------------------|
| `name`                 | `str`            | --      | Identifiant unique de l'outil                      |
| `description`          | `str`            | --      | Description lisible par un humain (envoyée au modèle) |
| `parameters`           | `dict[str, Any]` | `{}`    | Le JSON Schema des paramètres de l'outil           |
| `category`             | `str`            | `""`    | Catégorie de l'outil (`math`, `memory`, `reasoning`, par exemple) |
| `cost_estimate`        | `float`          | `0.0`   | Coût estimé par appel                              |
| `latency_estimate`     | `float`          | `0.0`   | Latence estimée par appel                          |
| `requires_confirmation`| `bool`           | `False` | Si l'outil exige une confirmation de l'utilisateur |
| `metadata`             | `dict[str, Any]` | `{}`    | Métadonnées supplémentaires                        |

---

## ToolResult

La dataclasse `ToolResult` porte le résultat de l'exécution d'un outil.

| Champ             | Type             | Défaut  | Description                              |
|-------------------|------------------|---------|------------------------------------------|
| `tool_name`       | `str`            | --      | Nom de l'outil appelé                    |
| `content`         | `str`            | --      | La sortie de l'outil (du texte)          |
| `success`         | `bool`           | `True`  | Si l'exécution a réussi                  |
| `usage`           | `dict[str, Any]` | `{}`    | Consommation de jetons (pour l'outil LLM) |
| `cost_usd`        | `float`          | `0.0`   | Coût réel de l'appel                     |
| `latency_seconds` | `float`          | `0.0`   | Latence d'exécution mesurée              |
| `metadata`        | `dict[str, Any]` | `{}`    | Métadonnées supplémentaires              |

---

## ToolExecutor

`ToolExecutor` est le moteur de répartition central des appels d'outils. Il tient un jeu d'instances d'outils, analyse les arguments JSON, mesure la latence d'exécution et publie des événements sur le bus d'événements.

```python
from diapason.tools._stubs import ToolExecutor

executor = ToolExecutor(tools=[calculator, think_tool], bus=event_bus)

# Récupérer les définitions d'outils au format OpenAI
openai_tools = executor.get_openai_tools()

# Exécuter un appel d'outil
from diapason.core.types import ToolCall
tc = ToolCall(id="call_1", name="calculator", arguments='{"expression": "2+2"}')
result = executor.execute(tc)
print(result.content)  # "4"
```

### Le déroulé d'une exécution

1. **Analyse des arguments :** la chaîne JSON `arguments` du `ToolCall` est désérialisée.
2. **Publication de l'événement de départ :** `TOOL_CALL_START` est émis sur le bus d'événements, avec le nom de l'outil et ses arguments.
3. **Exécution :** la méthode `execute()` de l'outil est appelée avec les paramètres analysés.
4. **Mesure de la latence :** le temps d'exécution est consigné dans `result.latency_seconds`.
5. **Publication de l'événement de fin :** `TOOL_CALL_END` est émis, avec le succès et la latence.
6. **Retour du résultat :** le `ToolResult` est rendu à l'appelant.

Si le nom de l'outil est inconnu, un `ToolResult` avec `success=False` est rendu. Si l'analyse JSON échoue ou si l'outil lève une exception, l'erreur est capturée et rendue sous forme de `ToolResult` en échec.

### Les méthodes

| Méthode             | Rend                   | Description                                |
|---------------------|------------------------|--------------------------------------------|
| `execute(tool_call)`| `ToolResult`           | Analyse les arguments, répartit, mesure, émet les événements |
| `available_tools()` | `list[ToolSpec]`       | Rend les spécifications de tous les outils enregistrés |
| `get_openai_tools()`| `list[dict]`           | Rend les outils au format de fonctions d'OpenAI |

---

## build_tool_descriptions()

La fonction `build_tool_descriptions()` est la **source unique de vérité** pour produire les descriptions enrichies d'outils qu'on trouve dans les prompts système des agents. Tous les agents textuels (`NativeReActAgent`, `NativeOpenHandsAgent`, `RLMAgent`, `OrchestratorAgent` en mode structuré) passent par elle pour produire leurs sections d'outils en Markdown.

### Les paramètres

| Paramètre          | Type             | Défaut  | Description                                          |
|--------------------|------------------|---------|------------------------------------------------------|
| `tools`            | `list[BaseTool]` | --      | La liste des instances d'outils à décrire            |
| `include_category` | `bool`           | `True`  | Si la ligne `Category:` est incluse                  |
| `include_cost`     | `bool`           | `False` | Si les lignes d'estimation de coût et de latence sont incluses |

### L'usage

```python
from diapason.tools._stubs import build_tool_descriptions
from diapason.tools.calculator import CalculatorTool
from diapason.tools.think import ThinkTool

tools = [CalculatorTool(), ThinkTool()]
desc = build_tool_descriptions(tools)
print(desc)
# ### calculator
# Evaluate a mathematical expression safely.
# Category: math
# Parameters:
#   - expression (string, required): Math expression to evaluate
#
# ### think
# Reasoning scratchpad ...
```

### Les agents qui utilisent ce constructeur

- **NativeReActAgent** — il injecte les descriptions dans le prompt système ReAct
- **NativeOpenHandsAgent** — il les injecte dans le prompt système CodeAct
- **RLMAgent** — il ajoute une section `## Available Tools` au prompt système du REPL
- **OrchestratorAgent** (en mode structuré) — il passe `tools=` à `build_system_prompt()`, qui délègue à ce constructeur

---

## Les outils intégrés, en résumé

Tous les outils intégrés sont enregistrés par `@ToolRegistry.register()` et sont accessibles par leur nom depuis les agents et depuis la ligne de commande.

| Catégorie | Clé de registre | Description |
|----------|-------------|-------------|
| **Raisonnement** | `think` | Bloc-notes de raisonnement sans coût, pour la chaîne de pensée |
| **Mathématiques** | `calculator` | Évaluateur d'expressions mathématiques sûr (fondé sur `ast`) |
| **Code** | `code_interpreter` | Exécute du Python dans un sous-processus isolé |
| **Code** | `code_interpreter_docker` | Exécute du Python dans un conteneur Docker jetable |
| **Code** | `repl` | REPL Python persistant, qui garde son état d'un appel à l'autre |
| **Recherche** | `web_search` | Recherche web rendant des résultats numérotés et datés `[N]` |
| **Recherche** | `web_read` | Lit une page : texte principal, titre, date de publication |
| **Fichiers** | `file_read` | Lit le contenu d'un fichier, avec des contrôles de sûreté |
| **HTTP** | `http_request` | Émet des requêtes HTTP, avec protection contre le SSRF |
| **Mémoire** | `retrieval` | Cherche dans le moteur de mémoire le contexte pertinent |
| **Mémoire** | `memory_store` | Range du contenu dans le moteur de mémoire |
| **Mémoire** | `memory_retrieve` | Récupère du contenu pertinent depuis le moteur de mémoire |
| **Mémoire** | `memory_search` | Recherche plein texte dans toute la mémoire stockée |
| **Mémoire** | `memory_index` | Indexe un fichier ou un dossier dans le moteur de mémoire |
| **Inférence** | `llm` | Délègue une sous-question à un moteur d'inférence |
| **Canal** | `channel_send` | Envoie un message par un canal (Telegram, Discord, etc.) |
| **Canal** | `channel_list` | Liste les canaux de messagerie disponibles |
| **Canal** | `channel_status` | Vérifie l'état de connexion d'un canal de messagerie |
| **Planification** | `schedule_task` | Planifie une tâche, ponctuelle ou récurrente |
| **Planification** | `list_scheduled_tasks` | Liste toutes les tâches planifiées |
| **Planification** | `pause_scheduled_task` | Met en pause une tâche planifiée active |
| **Planification** | `resume_scheduled_task` | Reprend une tâche mise en pause |
| **Planification** | `cancel_scheduled_task` | Annule définitivement une tâche planifiée |
| **Intégration** | `mcp_adapter` | Pont vers des serveurs d'outils MCP externes (voir [Les serveurs MCP externes](mcp-external-servers.md)) |

---

## Les outils intégrés en détail

### Calculator

**Clé de registre :** `calculator` | **Catégorie :** `math`

Évalue des expressions mathématiques sans risque, avec le module `ast` de Python. Aucune exécution de code arbitraire — seules les opérations de la liste blanche sont permises.

**Paramètres :**

| Paramètre    | Type   | Obligatoire | Description                              |
|--------------|--------|----------|------------------------------------------|
| `expression` | string | Oui      | Expression mathématique (`"2+3*4"`, `"sqrt(16)"`, par exemple) |

**Les opérations prises en charge :**

| Catégorie    | Opérations                                                    |
|--------------|---------------------------------------------------------------|
| Arithmétique | `+`, `-`, `*`, `/`, `//` (division entière), `%` (modulo), `**` (puissance) |
| Fonctions    | `abs`, `round`, `min`, `max`, `sqrt`, `log`, `log10`, `log2` |
| Trigonométrie | `sin`, `cos`, `tan`                                          |
| Arrondis     | `ceil`, `floor`                                               |
| Constantes   | `pi`, `e`                                                     |

**Exemple :**

```python
from diapason.tools.calculator import CalculatorTool

calc = CalculatorTool()
result = calc.execute(expression="sqrt(144) + 3**2")
print(result.content)   # "21.0"
print(result.success)   # True
```

### Think

**Clé de registre :** `think` | **Catégorie :** `reasoning`

Un bloc-notes de raisonnement sans coût. L'entrée est renvoyée telle quelle en sortie, ce qui laisse le modèle « penser à voix haute » pendant une boucle d'appel d'outils. C'est ce qui rend possible le raisonnement en chaîne de pensée à l'intérieur du flux de l'agent.

**Paramètres :**

| Paramètre | Type   | Obligatoire | Description                           |
|-----------|--------|----------|------------------------------------------|
| `thought` | string | Oui      | Le raisonnement, ou le cheminement de pensée |

**Exemple :**

```python
from diapason.tools.think import ThinkTool

think = ThinkTool()
result = think.execute(thought="Décomposons ce problème en étapes...")
print(result.content)   # "Décomposons ce problème en étapes..."
print(result.success)   # True
```

!!! info "Coût et latence"
    L'outil Think ne coûte rien et sa latence est quasi nulle : il est idéal pour structurer un raisonnement sans consommer de ressources supplémentaires.

### Retrieval

**Clé de registre :** `retrieval` | **Catégorie :** `memory`

Cherche dans le moteur de mémoire le contexte pertinent et rend des résultats mis en forme, avec l'attribution de leur source.

**Paramètres :**

| Paramètre | Type    | Obligatoire | Description                            |
|-----------|---------|----------|------------------------------------------|
| `query`   | string  | Oui      | La requête de recherche                  |
| `top_k`   | integer | Non      | Nombre de résultats (5 par défaut)       |

**Paramètres du constructeur :**

| Paramètre | Type            | Défaut  | Description                    |
|-----------|-----------------|---------|--------------------------------|
| `backend` | `MemoryBackend` | `None`  | Le moteur de mémoire à interroger |
| `top_k`   | `int`           | `5`     | Nombre de résultats par défaut |

**Exemple :**

```python
from diapason.tools.retrieval import RetrievalTool
from diapason.memory.sqlite import SQLiteMemory

backend = SQLiteMemory(db_path="./memory.db")
retrieval = RetrievalTool(backend=backend)
result = retrieval.execute(query="apprentissage automatique")
print(result.content)   # Le contexte mis en forme, avec les étiquettes de source
```

### LLM

**Clé de registre :** `llm` | **Catégorie :** `inference`

Délègue une sous-question à un moteur d'inférence. Utile pour résumer, pour poser une question intermédiaire ou pour produire une sortie structurée à l'intérieur du flux d'un agent.

**Paramètres :**

| Paramètre | Type   | Obligatoire | Description                             |
|-----------|--------|----------|------------------------------------------|
| `prompt`  | string | Oui      | Le prompt à envoyer au modèle            |
| `system`  | string | Non      | Un message système facultatif, pour le contexte |

**Paramètres du constructeur :**

| Paramètre | Type              | Défaut  | Description                    |
|-----------|-------------------|---------|--------------------------------|
| `engine`  | `InferenceEngine` | `None`  | Le moteur d'inférence à utiliser |
| `model`   | `str`             | `""`    | L'identifiant du modèle        |

**Exemple :**

```python
from diapason.tools.llm_tool import LLMTool

llm = LLMTool(engine=my_engine, model="qwen3:8b")
result = llm.execute(
    prompt="Résume : l'IA transforme des industries entières...",
    system="Tu résumes de façon concise.",
)
print(result.content)
```

### FileRead

**Clé de registre :** `file_read` | **Catégorie :** `filesystem`

Lit le contenu d'un fichier, avec des contrôles de sûreté. Il accepte une restriction facultative à certains dossiers, une limite de taille de fichier (1 Mo au maximum) et une limite sur le nombre de lignes.

**Paramètres :**

| Paramètre   | Type    | Obligatoire | Description                          |
|-------------|---------|----------|------------------------------------------|
| `path`      | string  | Oui      | Le chemin du fichier à lire              |
| `max_lines` | integer | Non      | Nombre maximum de lignes rendues (tout, par défaut) |

**Paramètres du constructeur :**

| Paramètre      | Type         | Défaut  | Description                                   |
|----------------|--------------|---------|-----------------------------------------------|
| `allowed_dirs` | `list[str]`  | `None`  | Restreint l'accès aux fichiers à ces dossiers |

**Les garde-fous :**

- Validation du chemin contre les dossiers autorisés (quand ils sont configurés)
- Taille maximale du fichier : 1 Mo
- Encodage UTF-8 exigé (les fichiers binaires sont refusés)
- Contrôles d'existence et de type de fichier

**Exemple :**

```python
from diapason.tools.file_read import FileReadTool

reader = FileReadTool(allowed_dirs=["/home/user/projects"])
result = reader.execute(path="/home/user/projects/README.md", max_lines=50)
print(result.content)
print(result.metadata)  # {"path": "/home/user/projects/README.md", "size_bytes": 1234}
```

### WebSearch

**Clé de registre :** `web_search` | **Catégorie :** `search`

Cherche sur le web et rend un résumé des résultats. Utile pour les questions qui demandent une information à jour.

**Paramètres :**

| Paramètre     | Type    | Obligatoire | Description                                    |
|---------------|---------|----------|----------------------------------------------------|
| `query`       | string  | Oui      | La requête de recherche                            |
| `max_results` | integer | Non      | Nombre maximum de résultats (5 par défaut)         |
| `recency`     | string  | Non      | `day`, `week`, `month` ou `year`                   |
| `news`        | boolean | Non      | Cherche d'abord dans les médias d'information (articles datés) |

Les résultats sont numérotés `[N]`, avec le domaine de la source et la date ;
le chat les cite par leur numéro et les affiche en pastilles cliquables. La
région suit `DIAPASON_SEARCH_REGION` (`ca-fr` par défaut).

### WebRead

**Clé de registre :** `web_read` | **Catégorie :** `search`

Lit une page web et rend son texte principal (navigation, pieds de page et
bandeaux de cookies retirés ; les tableaux gardés en lignes `a | b | c`), son
titre et ses dates de publication et de modification (JSON-LD, `<meta>`,
`<time>`, puis l'en-tête HTTP `Last-Modified` — une date ambiguë est rendue
comme absente, jamais devinée). Utilise-le après `web_search` quand les
extraits ne disent pas le fait demandé. Pour une question sur le titulaire
d'une fonction, le chat lit de lui-même la page de la fonction après la
première recherche (affiché `web_read · auto`).

**Paramètres :**

| Paramètre | Type   | Obligatoire | Description                                       |
|-----------|--------|----------|------------------------------------------------------|
| `url`     | string | Oui      | L'URL de la page (http/https ; les adresses privées sont refusées) |
| `focus`   | string | Non      | Les mots à chercher ; les passages qui les entourent viennent en premier |

La sortie est bornée à 3 600 caractères ; la page compte comme une source
`[N]`, exactement comme un résultat de recherche.

### CodeInterpreter

**Clé de registre :** `code_interpreter` | **Catégorie :** `code`

Exécute des bouts de code Python dans un environnement isolé et en rend la sortie. C'est ce dont se sert `NativeOpenHandsAgent` pour l'exécution façon CodeAct.

**Paramètres :**

| Paramètre | Type   | Obligatoire | Description                              |
|-----------|--------|----------|------------------------------------------|
| `code`    | string | Oui      | Le code Python à exécuter                |

---

## Les outils de planification

Les outils de planification exposent les opérations de `TaskScheduler` comme des outils découvrables par MCP. Ils laissent les agents créer, gérer et inspecter des tâches planifiées par programme. Tous sont dans la catégorie `scheduler` et exigent qu'une instance de `TaskScheduler` soit configurée dans le système.

!!! info "La dépendance au planificateur"
    Les outils de planification ne fonctionnent que si un `TaskScheduler` est câblé dans le système (par `SystemBuilder`). Sans planificateur configuré, tous leurs appels rendent un résultat `success=False`, accompagné d'un message disant que le planificateur n'est pas disponible.

### schedule_task

**Clé de registre :** `schedule_task` | **Catégorie :** `scheduler`

Planifie une nouvelle tâche, ponctuelle ou récurrente.

**Paramètres :**

| Paramètre        | Type   | Obligatoire | Description                                                       |
|------------------|--------|----------|------------------------------------------------------------------------------|
| `prompt`         | string | Oui      | La question, ou le prompt, à exécuter à l'heure dite                         |
| `schedule_type`  | string | Oui      | L'un de `"cron"`, `"interval"` ou `"once"`                                   |
| `schedule_value` | string | Oui      | Une expression cron, un intervalle en secondes, ou une date-heure ISO 8601 pour une exécution unique |
| `agent`          | string | Non      | L'agent qui exécutera (`"simple"` par défaut)                                |
| `tools`          | string | Non      | Les noms d'outils de l'agent, séparés par des virgules (`"calculator,think"`, par exemple) |

**Des exemples de types de planification :**

| `schedule_type` | `schedule_value`       | Ce que ça veut dire                  |
|-----------------|------------------------|--------------------------------------|
| `once`          | `"2026-03-01T09:00:00Z"` | Une seule fois, à cette heure UTC   |
| `interval`      | `"3600"`               | Toutes les 3600 secondes (1 heure)   |
| `cron`          | `"0 9 * * 1-5"`        | À 09:00 UTC, du lundi au vendredi    |

**Rend :** du JSON avec `task_id`, `next_run` (ISO 8601) et `status`.

**Exemple (par un appel d'outil d'agent) :**

```python
from diapason.scheduler.tools import ScheduleTaskTool
from diapason.scheduler.scheduler import TaskScheduler
from diapason.scheduler.store import SchedulerStore

store = SchedulerStore(db_path="~/.diapason/scheduler.db")
scheduler = TaskScheduler(store=store, system=diapason_system)
scheduler.start()

tool = ScheduleTaskTool()
tool._scheduler = scheduler

result = tool.execute(
    prompt="Résume l'actualité du jour",
    schedule_type="cron",
    schedule_value="0 8 * * *",
    agent="simple",
)
# result.content: '{"task_id": "a3f9b12c", "next_run": "2026-02-26T08:00:00+00:00", "status": "active"}'
```

### list_scheduled_tasks

**Clé de registre :** `list_scheduled_tasks` | **Catégorie :** `scheduler`

Rend toutes les tâches planifiées, filtrées par statut si on le demande.

**Paramètres :**

| Paramètre | Type   | Obligatoire | Description                                                   |
|-----------|--------|----------|----------------------------------------------------------------------|
| `status`  | string | Non      | Filtre par statut : `"active"`, `"paused"`, `"completed"`, `"cancelled"` |

**Rend :** un tableau JSON d'objets de tâche.

### pause_scheduled_task

**Clé de registre :** `pause_scheduled_task` | **Catégorie :** `scheduler`

Met en pause une tâche planifiée active. La tâche est conservée et peut être reprise plus tard.

**Paramètres :**

| Paramètre | Type   | Obligatoire | Description                  |
|-----------|--------|----------|---------------------|
| `task_id` | string | Oui      | L'identifiant de la tâche à mettre en pause |

### resume_scheduled_task

**Clé de registre :** `resume_scheduled_task` | **Catégorie :** `scheduler`

Reprend une tâche mise en pause. L'heure de `next_run` est recalculée à partir de l'heure courante.

**Paramètres :**

| Paramètre | Type   | Obligatoire | Description                   |
|-----------|--------|----------|----------------------|
| `task_id` | string | Oui      | L'identifiant de la tâche à reprendre |

### cancel_scheduled_task

**Clé de registre :** `cancel_scheduled_task` | **Catégorie :** `scheduler`

Annule définitivement une tâche (statut mis à `"cancelled"` et `next_run` effacé). Une tâche annulée ne s'exécute plus jamais.

**Paramètres :**

| Paramètre | Type   | Obligatoire | Description                    |
|-----------|--------|----------|-----------------------|
| `task_id` | string | Oui      | L'identifiant de la tâche à annuler |

---

## L'enregistrement d'un outil

Les outils s'enregistrent avec le décorateur `@ToolRegistry.register()`, ce qui les rend découvrables par leur nom à l'exécution.

```python
from diapason.core.registry import ToolRegistry
from diapason.tools._stubs import BaseTool, ToolSpec
from diapason.core.types import ToolResult


@ToolRegistry.register("my_tool")
class MyTool(BaseTool):
    tool_id = "my_tool"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="my_tool",
            description="Un outil maison qui fait quelque chose d'utile.",
            parameters={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "L'entrée à traiter.",
                    },
                },
                "required": ["input"],
            },
            category="custom",
        )

    def execute(self, **params) -> ToolResult:
        value = params.get("input", "")
        return ToolResult(
            tool_name="my_tool",
            content=f"Traité : {value}",
            success=True,
        )
```

Une fois enregistré, l'outil s'utilise avec un agent :

```bash
diapason ask --agent orchestrator --tools my_tool "Traite ces données"
```

---

## Utiliser les outils avec les agents

### Depuis la ligne de commande

Les outils se donnent en liste séparée par des virgules, avec l'option `--tools`. Il faut choisir un agent (`orchestrator`, en général) :

```bash
# Un seul outil
diapason ask --agent orchestrator --tools calculator "Combien font 15 % de 340 ?"

# Plusieurs outils
diapason ask --agent orchestrator --tools calculator,think "Résous : 2x + 5 = 13"

# Tous les outils disponibles (il faut les énumérer)
diapason ask --agent orchestrator --tools calculator,think,retrieval,file_read "..."
```

### Depuis le SDK Python

Les outils se passent en liste de noms :

```python
from diapason import Diapason

j = Diapason()

# Utiliser les outils calculator et think
result = j.ask_full(
    "Quelle est l'aire d'un cercle de rayon 7 ?",
    agent="orchestrator",
    tools=["calculator", "think"],
)

for tr in result["tool_results"]:
    print(f"  {tr['tool_name']}: {tr['content']} (success={tr['success']})")

j.close()
```

Le SDK instancie tout seul les objets d'outils avec les dépendances qu'il faut. L'outil `retrieval` reçoit par exemple le moteur de mémoire configuré, et l'outil `llm` le moteur et le modèle actifs.
