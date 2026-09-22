# Agents

Les agents sont la couche de logique agentique de Diapason. Ce sont eux qui décident comment une question est traitée — envoyée directement à un modèle, passée dans une boucle d'appel d'outils, raisonnée façon ReAct, exécutée comme du code façon CodeAct, décomposée récursivement, ou confiée à un environnement d'agent externe. Tous les agents implémentent la classe abstraite `BaseAgent` et sont enregistrés dans l'`AgentRegistry`.

## Vue d'ensemble

| Agent               | Clé de registre   | `accepts_tools` | Multi-tours | Description                                  |
|---------------------|-------------------|-----------------|-------------|----------------------------------------------|
| `SimpleAgent`       | `simple`          | Non             | Non         | Question-réponse en un seul tour             |
| `OrchestratorAgent` | `orchestrator`    | Oui             | Oui         | Boucle d'appel d'outils multi-tours (function_calling + structured) |
| `NativeReActAgent`  | `native_react`    | Oui             | Oui         | Boucle Pensée-Action-Observation             |
| `NativeOpenHandsAgent` | `native_openhands` | Oui         | Oui         | Exécution de code façon CodeAct + appels d'outils |
| `RLMAgent`          | `rlm`             | Oui             | Oui         | Modèle récursif avec REPL persistant         |
| `OpenHandsAgent`    | `openhands`       | Non             | Oui         | Enveloppe le vrai openhands-sdk              |
| `ClaudeCodeAgent`   | `claude_code`     | Non             | Oui         | Claude Agent SDK via un sous-processus Node.js |
| `OpenCodeAgent`     | `opencode`        | Non             | Oui         | L'agent de code [opencode](https://opencode.ai) sur ton moteur local |
| `OperativeAgent`    | `operative`       | Oui             | Oui         | Agent planifié persistant, avec gestion d'état |
| `MonitorOperativeAgent` | `monitor_operative` | Oui       | Oui         | Agent de longue haleine, avec 4 axes de stratégie configurables |

---

## Le persona persistant : SOUL.md, MEMORY.md, USER.md

Le prompt système de chaque agent est assemblé au début de la conversation par le `SystemPromptBuilder`, qui y injecte jusqu'à trois fichiers Markdown facultatifs — le **persona persistant**. Ce sont des fichiers en texte brut, à toi, que tu modifies, et qui sont chargés au début de chaque conversation. Il n'y a derrière eux ni base vectorielle ni cache d'embeddings.

| Fichier | Ce qu'il contient | Exemple de ligne |
|---------|-------------------|------------------|
| `SOUL.md` | Comment l'agent doit se comporter — le ton, la longueur, ce sur quoi il doit te contredire | `Sois concis. Conteste les hypothèses fragiles.` |
| `MEMORY.md` | Des faits sur toi, tes projets, tes préférences | `Je déploie sur Postgres, jamais sur MySQL.` |
| `USER.md` | Qui tu es — ton rôle, ton équipe, ton contexte | `Ingénieur back-end chez Acme, dans l'équipe paiements.` |

Ce persona est distinct du [moteur de mémoire](memory.md) et de sa recherche : le persona est un contexte Markdown toujours actif, chargé dans le prompt, tandis que le moteur de mémoire est un stockage de longue durée, interrogeable, que l'agent consulte à la demande.

### Où ils vivent

Par défaut, les fichiers sont lus depuis le dossier de configuration :

```
~/.diapason/SOUL.md
~/.diapason/MEMORY.md
~/.diapason/USER.md
```

(Le dossier de configuration respecte `$DIAPASON_HOME` / `$XDG_DATA_HOME` quand ils sont définis.) Les chemins se configurent sous `[memory_files]` :

```toml
[memory_files]
soul_path    = "~/.diapason/SOUL.md"
memory_path  = "~/.diapason/MEMORY.md"
user_path    = "~/.diapason/USER.md"
persona_name = ""    # persona nommé, facultatif — voir plus bas
```

### Comment ils sont chargés

Au début de chaque conversation, `SystemPromptBuilder` lit chaque fichier en UTF-8 et ajoute son contenu comme une section du prompt système, après le gabarit de l'agent et avant le catalogue de compétences :

- **Les trois sont facultatifs.** Un fichier absent ou vide est ignoré : n'importe quel sous-ensemble fonctionne, et une installation dépourvue de fichiers de persona se comporte exactement comme avant.
- **Les modifications prennent effet à la conversation suivante.** Les fichiers sont lus une seule fois, quand le prompt d'une conversation est construit : rien à redémarrer, rien à réindexer — modifie ou supprime une ligne, et elle s'applique dès la prochaine conversation que tu démarres.
- **Chaque section est bornée en longueur.** Les fichiers sont tronqués selon un budget de caractères par section, pour qu'un gros `MEMORY.md` ne puisse pas chasser le reste du prompt.

### Les personas nommés

Une même installation peut répondre sous plusieurs personas sans toucher à la configuration globale. Un persona nommé vit dans son propre dossier :

```
~/.diapason/personas/<name>/SOUL.md
~/.diapason/personas/<name>/MEMORY.md
~/.diapason/personas/<name>/USER.md
```

Choisis-en un à chaque appel, ou renonce complètement :

```bash
diapason ask --persona work  "résume mes PR ouvertes"
diapason ask --persona none  "combien font 2 + 2 ?"     # n'injecte aucun persona
```

Définis `persona_name` sous `[memory_files]` pour faire d'un persona nommé celui par défaut. `persona_name = "none"` (ce qui revient à `--persona none`) désactive l'injection de persona pour cette exécution.

### Les modifier

`SOUL.md`, `MEMORY.md` et `USER.md` sont du Markdown ordinaire — ouvre-les dans n'importe quel éditeur. `MEMORY.md` et `USER.md` peuvent aussi être mis à jour par l'agent lui-même, par les outils `memory_manage` et `user_profile_manage` quand ils sont activés : l'agent peut donc noter un fait nouveau au milieu d'une conversation. Ces outils visent toujours les `MEMORY.md` et `USER.md` par défaut (sous `~/.diapason/`), jamais les copies d'un persona nommé — celles-là, modifie-les à la main.

---

## BaseAgent ABC

Tous les agents dérivent de la classe abstraite `BaseAgent`.

```python
from abc import ABC, abstractmethod
from diapason.agents._stubs import AgentContext, AgentResult

class BaseAgent(ABC):
    agent_id: str
    accepts_tools: bool = False

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        bus: Optional[EventBus] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> None: ...

    @abstractmethod
    def run(
        self,
        input: str,
        context: AgentContext | None = None,
        **kwargs,
    ) -> AgentResult:
        """Exécute l'agent sur l'entrée donnée."""
```

L'attribut de classe `accepts_tools` décide si un agent peut recevoir des outils, par `--tools` en ligne de commande ou par `tools=` dans le SDK. Les agents dont `accepts_tools = False` ignorent les arguments d'outils.

`BaseAgent` fournit aussi des méthodes utilitaires concrètes (`_emit_turn_start`, `_emit_turn_end`, `_build_messages`, `_generate`, `_max_turns_result`, `_strip_think_tags`) dont les sous-classes se servent pour ne pas dupliquer la logique commune. Le détail est dans la [documentation d'architecture](../architecture/agents.md#la-classe-abstraite-baseagent).

**ToolUsingAgent** est une classe de base intermédiaire (elle dérive de `BaseAgent`) qui pose `accepts_tools = True` et ajoute un `ToolExecutor` ainsi qu'une limite de boucle `max_turns`. Tous les agents qui se servent d'outils dérivent de cette classe.

### AgentContext

Le contexte d'exécution remis à un agent à chaque appel.

| Champ            | Type               | Description                                    |
|------------------|--------------------|------------------------------------------------|
| `conversation`   | `Conversation`     | L'historique des messages (pré-rempli avec le contexte si l'injection de mémoire est active) |
| `tools`          | `list[str]`        | Les noms des outils dont l'agent dispose       |
| `memory_results` | `list[Any]`        | Les résultats de mémoire récupérés à l'avance  |
| `metadata`       | `dict[str, Any]`   | Des métadonnées libres pour l'exécution        |

### AgentResult

Le résultat rendu quand un agent a fini son exécution.

| Champ          | Type               | Description                                    |
|----------------|--------------------|------------------------------------------------|
| `content`      | `str`              | Le texte de la réponse finale                  |
| `tool_results` | `list[ToolResult]` | Les résultats des outils exécutés pendant l'exécution |
| `turns`        | `int`              | Le nombre de tours (d'appels d'inférence) effectués |
| `metadata`     | `dict[str, Any]`   | Des métadonnées libres sur l'exécution         |

---

## SimpleAgent

Le `SimpleAgent` est un agent à un seul tour : il envoie la question directement au moteur d'inférence et rend la réponse. Il ne gère pas l'appel d'outils.

**Comment il marche :**

1. Il construit une liste de messages à partir du contexte de conversation (s'il y en a un) et de la question de l'utilisateur.
2. Il appelle le moteur d'inférence via `_generate()`.
3. Il rend la réponse sous forme d'`AgentResult`, avec `turns=1`.

**Paramètres du constructeur :**

| Paramètre     | Type              | Défaut  | Description                        |
|---------------|-------------------|---------|------------------------------------|
| `engine`      | `InferenceEngine` | --      | Le moteur d'inférence à utiliser   |
| `model`       | `str`             | --      | L'identifiant du modèle            |
| `bus`         | `EventBus`        | `None`  | Le bus d'événements pour la télémétrie |
| `temperature` | `float`           | `0.7`   | La température d'échantillonnage   |
| `max_tokens`  | `int`             | `1024`  | Le nombre maximum de jetons à produire |

**Quand s'en servir :** pour de la question-réponse directe, sans appel d'outils ni raisonnement sur plusieurs tours.

---

## OrchestratorAgent

L'`OrchestratorAgent` est un agent multi-tours qui met en œuvre une boucle d'appel d'outils. C'est l'agent principal pour les questions qui demandent un calcul, une recherche de connaissances ou un raisonnement structuré. Il dérive de `ToolUsingAgent`.

**Comment il marche :**

1. Il construit la liste de messages initiale à partir du contexte et de la question de l'utilisateur.
2. Il envoie les messages au moteur, accompagnés des définitions d'outils (au format function-calling d'OpenAI).
3. Si le moteur répond avec des `tool_calls`, le `ToolExecutor` répartit chaque appel.
4. Les résultats d'outils sont ajoutés comme messages `TOOL`, et la boucle continue.
5. Si aucun `tool_calls` n'est rendu, la réponse est tenue pour la réponse finale.
6. La boucle s'arrête après `max_turns` itérations (10 par défaut) et rend le contenu disponible, assorti du drapeau de métadonnée `max_turns_exceeded`.

**Paramètres du constructeur :**

| Paramètre       | Type              | Défaut  | Description                          |
|-----------------|-------------------|---------|--------------------------------------|
| `engine`        | `InferenceEngine` | --      | Le moteur d'inférence à utiliser     |
| `model`         | `str`             | --      | L'identifiant du modèle              |
| `tools`         | `list[BaseTool]`  | `[]`    | Les instances d'outils à mettre à disposition |
| `bus`           | `EventBus`        | `None`  | Le bus d'événements pour la télémétrie |
| `max_turns`     | `int`             | `10`    | Le nombre maximum de tours d'appel d'outils |
| `temperature`   | `float`           | `0.7`   | La température d'échantillonnage     |
| `max_tokens`    | `int`             | `1024`  | Le nombre maximum de jetons à produire |
| `mode`          | `str`             | `"function_calling"` | Le mode d'appel d'outils (`function_calling` ou `structured`) |
| `system_prompt` | `str`             | `None`  | Un prompt système personnalisé       |

**Quand s'en servir :** pour les questions qui demandent un calcul, une recherche en mémoire, des appels à un sous-modèle, la lecture de fichiers ou un raisonnement en plusieurs étapes.

!!! info "La boucle d'appel d'outils"
    L'orchestrateur suit la convention function-calling d'OpenAI. Pour que la boucle s'enclenche, le moteur doit savoir renvoyer des `tool_calls` dans sa réponse. Si des outils sont fournis mais que le moteur ne renvoie aucun appel d'outil, l'agent se comporte comme un agent à un seul tour.

---

## NativeReActAgent

Le `NativeReActAgent` met en œuvre une boucle **Pensée-Action-Observation**, suivant le motif ReAct. Il demande au modèle de produire une sortie structurée (`Thought:`, `Action:`, `Action Input:`, `Final Answer:`) et analyse la réponse pour déclencher l'exécution des outils. Il dérive de `ToolUsingAgent`.

**Comment il marche :**

1. Il construit un prompt système avec des descriptions d'outils enrichies (noms, schémas de paramètres, catégories) via `build_tool_descriptions()`. L'analyse ne tient pas compte de la casse.
2. Il produit une réponse et analyse la sortie structurée ReAct.
3. S'il y trouve un `Final Answer:`, il le rend.
4. S'il y trouve une `Action:`, il exécute l'outil et réinjecte le résultat comme `Observation:`.
5. Il boucle jusqu'à ce qu'une réponse finale soit produite, ou que `max_turns` soit dépassé.

**Paramètres du constructeur :**

| Paramètre     | Type              | Défaut  | Description                        |
|---------------|-------------------|---------|------------------------------------|
| `engine`      | `InferenceEngine` | --      | Le moteur d'inférence à utiliser   |
| `model`       | `str`             | --      | L'identifiant du modèle            |
| `tools`       | `list[BaseTool]`  | `[]`    | Les instances d'outils à mettre à disposition |
| `bus`         | `EventBus`        | `None`  | Le bus d'événements pour la télémétrie |
| `max_turns`   | `int`             | `10`    | Le nombre maximum de tours de raisonnement |
| `temperature` | `float`           | `0.7`   | La température d'échantillonnage   |
| `max_tokens`  | `int`             | `1024`  | Le nombre maximum de jetons à produire |

**Quand s'en servir :** pour les questions qui gagnent à un raisonnement explicite, étape par étape, avec usage d'outils — quand tu veux voir le cheminement de pensée de l'agent.

!!! note "Compatibilité ascendante"
    L'alias de registre `"react"` pointe vers `NativeReActAgent`. L'ancien import `from diapason.agents.react import ReActAgent` fonctionne encore.

---

## NativeOpenHandsAgent

Le `NativeOpenHandsAgent` est un agent façon CodeAct : il produit et exécute du code Python, à côté d'appels d'outils structurés. Il peut aussi aller chercher à l'avance le contenu des URL présentes dans l'entrée de l'utilisateur, pour donner au modèle un contexte direct. Il dérive de `ToolUsingAgent`.

**Comment il marche :**

1. Il construit un prompt système détaillé, avec des descriptions d'outils enrichies (via le constructeur partagé `build_tool_descriptions()`) et des instructions d'exécution de code.
2. Il va chercher à l'avance les URL présentes dans l'entrée de l'utilisateur, et en insère le contenu directement.
3. À chaque tour, il produit une réponse et tente d'en extraire des blocs de code ou des appels d'outils.
4. Le code est exécuté par `code_interpreter` ; les appels d'outils sont répartis par `ToolExecutor`.
5. S'il ne trouve ni l'un ni l'autre, il rend le contenu comme réponse finale.

**Paramètres du constructeur :**

| Paramètre     | Type              | Défaut  | Description                        |
|---------------|-------------------|---------|------------------------------------|
| `engine`      | `InferenceEngine` | --      | Le moteur d'inférence à utiliser   |
| `model`       | `str`             | --      | L'identifiant du modèle            |
| `tools`       | `list[BaseTool]`  | `[]`    | Les instances d'outils à mettre à disposition |
| `bus`         | `EventBus`        | `None`  | Le bus d'événements pour la télémétrie |
| `max_turns`   | `int`             | `3`     | Le nombre maximum de tours         |
| `temperature` | `float`           | `0.7`   | La température d'échantillonnage   |
| `max_tokens`  | `int`             | `2048`  | Le nombre maximum de jetons à produire |

**Quand s'en servir :** pour les questions qui portent sur le contenu d'une URL, pour de l'exécution de code, ou pour les tâches où le modèle peut écrire et lancer du Python afin de résoudre le problème.

---

## RLMAgent

Le `RLMAgent` met en œuvre la décomposition récursive au moyen d'un REPL persistant, d'après l'article RLM. Le contexte est rangé dans une variable Python plutôt qu'injecté dans le prompt, ce qui permet de traiter des entrées de longueur quelconque par des appels récursifs à un sous-modèle. Il dérive de `ToolUsingAgent`.

**Comment il marche :**

1. Il crée un REPL persistant, doté des rappels `llm_query()` et `llm_batch()`.
2. Il injecte le contexte venu d'`AgentContext` dans le REPL, sous forme de variable.
3. Il produit du code et l'exécute dans le REPL.
4. Si `FINAL(value)` est appelé, il rend cette valeur comme réponse finale.
5. S'il ne trouve aucun bloc de code, il traite le contenu comme une réponse textuelle directe.

**Paramètres du constructeur :**

| Paramètre          | Type              | Défaut             | Description                        |
|--------------------|-------------------|--------------------|-------------------------------------|
| `engine`           | `InferenceEngine` | --                 | Le moteur d'inférence à utiliser   |
| `model`            | `str`             | --                 | L'identifiant du modèle            |
| `tools`            | `list[BaseTool]`  | `[]`               | Les instances d'outils (facultatif) |
| `bus`              | `EventBus`        | `None`             | Le bus d'événements pour la télémétrie |
| `max_turns`        | `int`             | `10`               | Le nombre maximum de tours d'exécution de code |
| `temperature`      | `float`           | `0.7`              | La température d'échantillonnage   |
| `max_tokens`       | `int`             | `2048`             | Le nombre maximum de jetons à produire |
| `sub_model`        | `str`             | identique à `model` | Le modèle des appels au sous-modèle |
| `sub_temperature`  | `float`           | `0.3`              | La température des appels au sous-modèle |
| `sub_max_tokens`   | `int`             | `1024`             | Les jetons maximum des appels au sous-modèle |
| `max_output_chars` | `int`             | `10000`            | Le nombre maximum de caractères en sortie du REPL |
| `system_prompt`    | `str`             | `RLM_SYSTEM_PROMPT` | Remplace le prompt système         |

**Quand s'en servir :** pour les tâches à long contexte qui gagnent à une décomposition récursive — résumer de gros documents, traiter des données structurées, ou tout ce qui demande de manipuler le contexte par programme.

---

## OpenHandsAgent (SDK)

L'`OpenHandsAgent` enveloppe le vrai paquet `openhands-sdk`, pour du développement logiciel piloté par l'IA. Il dérive directement de `BaseAgent` (la gestion des outils est assurée en interne par le SDK).

**Comment il marche :**

1. Il importe `openhands.sdk` à l'exécution.
2. Il crée un LLM, un Agent et une Conversation issus du SDK.
3. Il envoie l'entrée et déroule la conversation.
4. Il rend le contenu du message final.

**Paramètres du constructeur :**

| Paramètre     | Type              | Défaut        | Description                        |
|---------------|-------------------|---------------|------------------------------------|
| `engine`      | `InferenceEngine` | --            | Le moteur d'inférence (solution de repli) |
| `model`       | `str`             | --            | L'identifiant du modèle            |
| `bus`         | `EventBus`        | `None`        | Le bus d'événements pour la télémétrie |
| `temperature` | `float`           | `0.7`         | La température d'échantillonnage   |
| `max_tokens`  | `int`             | `1024`        | Le nombre maximum de jetons à produire |
| `workspace`   | `str`             | `os.getcwd()` | Le dossier de travail de l'agent   |
| `api_key`     | `str`             | `$LLM_API_KEY`| La clé d'API du fournisseur de LLM |

**Quand s'en servir :** pour les tâches de développement logiciel (débogage, édition de code, réparation de tests) où le SDK OpenHands fournit un environnement d'agent de développement complet.

!!! warning "Dépendance facultative"
    Nécessite `openhands-sdk` (`uv sync --extra openhands`) et Python 3.12 ou plus.

---

## Se servir des agents

### En ligne de commande

```bash
# L'agent simple
diapason ask --agent simple "Quelle est la capitale de la France ?"

# L'orchestrateur, avec des outils
diapason ask --agent orchestrator --tools calculator,think "Combien vaut sqrt(256) ?"

# NativeReActAgent
diapason ask --agent native_react --tools calculator "Combien font 2+2 ?"

# L'alias ReAct (identique à native_react)
diapason ask --agent react --tools calculator,think "Résous étape par étape : 15 % de 340"

# NativeOpenHandsAgent
diapason ask --agent native_openhands --tools calculator,web_search "Résume example.com"

# RLMAgent
diapason ask --agent rlm "Résume ce long document"

# L'agent OpenHands (SDK)
diapason ask --agent openhands "Corrige le bug dans test_utils.py"
```

### Par le SDK Python

```python
from diapason import Diapason

j = Diapason()

# L'agent simple
response = j.ask("Bonjour", agent="simple")

# L'orchestrateur, avec des outils
response = j.ask(
    "Calcule 15 % de 340",
    agent="orchestrator",
    tools=["calculator"],
)

# NativeReActAgent, avec des outils
response = j.ask(
    "Combien vaut sqrt(256) ?",
    agent="native_react",
    tools=["calculator", "think"],
)

# Le résultat complet, avec le détail des outils
result = j.ask_full(
    "Quelle est la racine carrée de 144 ?",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(result["content"])
print(result["turns"])
print(result["tool_results"])

j.close()
```

---

## ClaudeCodeAgent

Le `ClaudeCodeAgent` enveloppe le SDK `@anthropic-ai/claude-code` par un pont vers un sous-processus Node.js livré avec Diapason. Contrairement aux autres agents, l'inférence est entièrement prise en charge par le Claude Agent SDK — le paramètre `engine` n'est accepté que pour respecter l'interface de `BaseAgent`, et il n'est pas utilisé.

!!! warning "Ce qu'il faut"
    Nécessite Node.js 22 ou plus dans le `PATH`, et une variable d'environnement `ANTHROPIC_API_KEY` (ou passe `api_key=` directement). Le lanceur livré avec Diapason s'installe tout seul dans `~/.diapason/claude_code_runner/` au premier usage, par `npm install`.

**Comment il marche :**

1. Au premier appel, il copie le `claude_code_runner/` livré avec Diapason vers `~/.diapason/claude_code_runner/` et lance `npm install --production` si `node_modules` manque.
2. Il construit une charge utile de requête JSON (prompt, clé d'API, espace de travail, outils autorisés, prompt système, identifiant de session) et l'envoie sur le `stdin` d'un sous-processus `node dist/index.js`.
3. Le lanceur Node.js appelle le Claude Agent SDK et écrit sur `stdout` du JSON délimité par des sentinelles.
4. Côté Python, la sortie comprise entre les marqueurs `---DIAPASON_OUTPUT_START---` et `---DIAPASON_OUTPUT_END---` est analysée : contenu, résultats d'outils et métadonnées en sont extraits.
5. Il rend un `AgentResult` avec `turns=1`.

**Paramètres du constructeur :**

| Paramètre        | Type              | Défaut              | Description                                      |
|------------------|-------------------|---------------------|--------------------------------------------------|
| `engine`         | `InferenceEngine` | --                  | Accepté pour respecter l'interface ; non utilisé |
| `model`          | `str`             | --                  | Accepté pour respecter l'interface ; non utilisé |
| `bus`            | `EventBus`        | `None`              | Le bus d'événements pour la télémétrie           |
| `temperature`    | `float`           | `0.7`               | Accepté pour respecter l'interface ; non utilisé |
| `max_tokens`     | `int`             | `1024`              | Accepté pour respecter l'interface ; non utilisé |
| `api_key`        | `str`             | `$ANTHROPIC_API_KEY`| La clé d'API Anthropic                           |
| `workspace`      | `str`             | `os.getcwd()`       | Le dossier de travail de l'agent Claude          |
| `session_id`     | `str`             | `""`                | Un identifiant de session facultatif, pour la continuité de la conversation |
| `allowed_tools`  | `list[str]`       | `None` (tous)       | Les noms des outils Claude Code à autoriser      |
| `system_prompt`  | `str`             | `""`                | Un prompt système supplémentaire pour l'agent    |
| `timeout`        | `int`             | `300`               | Le délai d'attente du sous-processus, en secondes |

**Quand s'en servir :** pour les tâches de génie logiciel où les outils intégrés du Claude Agent SDK (édition de code, exécution shell, opérations sur les fichiers) offrent des capacités que les agents à outils de Diapason n'ont pas.

```python
from diapason.agents.claude_code import ClaudeCodeAgent

agent = ClaudeCodeAgent(
    engine=None,          # non utilisé
    model="",             # non utilisé
    workspace="/path/to/project",
    allowed_tools=["Read", "Write", "Bash"],
    timeout=120,
)
result = agent.run("Ajoute des annotations de type à toutes les fonctions de utils.py")
print(result.content)
```

```bash
# En ligne de commande
diapason ask --agent claude_code "Refactorise les tests pour qu'ils utilisent des fixtures pytest"
```

!!! info "accepts_tools = False"
    Le `ClaudeCodeAgent` n'accepte pas les outils Diapason par `--tools`. L'accès aux outils de l'agent Claude se règle à part, par le paramètre de constructeur `allowed_tools`, qui transmet des noms d'outils compris par le Claude Agent SDK lui-même.

---

## OpenCodeAgent

L'`OpenCodeAgent` délègue les tâches de code à [opencode](https://opencode.ai), l'agent de code open-source, en le faisant tourner **sur ton moteur local**. opencode s'occupe de la boucle agentique, des modifications de fichiers et de l'usage des outils ; Diapason fournit le modèle — le travail d'agent de code reste ainsi local d'abord.

!!! warning "Ce qu'il faut"
    Nécessite le binaire `opencode` dans le `PATH` (`npm i -g opencode-ai` ou `brew install anomalyco/tap/opencode`). Il n'est **pas** livré avec Diapason ; `run()` rend une erreur claire s'il manque. Aucune `ANTHROPIC_API_KEY` n'est nécessaire — l'inférence passe par ton moteur Diapason.

**Comment il marche :**

1. Il déduit du `engine` une URL de base compatible OpenAI (Ollama, vLLM ou llama.cpp à `<host>/v1`, par exemple) et écrit dans l'espace de travail un `opencode.json` qui l'enregistre comme fournisseur `@ai-sdk/openai-compatible` (`diapason/<model>`).
2. Il lance un `opencode serve` sans interface (en boucle locale, sur un port tiré au hasard) et attend `/global/health`.
3. Il crée une session (`POST /session`) et envoie la tâche (`POST /session/{id}/message`) avec `model={providerID, modelID}` et l'`agent` choisi (`build` ou `plan`).
4. Il analyse les `parts` du message rendu — les parties texte vers `content`, les parties outil vers `tool_results` — pour en faire un `AgentResult`.
5. `close()` libère la session et le serveur.

**Paramètres du constructeur (une sélection) :**

| Paramètre           | Type              | Défaut           | Description                                              |
|---------------------|-------------------|------------------|----------------------------------------------------------|
| `engine`            | `InferenceEngine` | --               | Sert à déduire l'URL du fournisseur local compatible OpenAI |
| `model`             | `str`             | --               | L'identifiant du modèle servi par le fournisseur (`qwen3:8b`, par exemple) |
| `workspace`         | `str`             | `os.getcwd()`    | Le dossier dans lequel opencode travaille                |
| `agent`             | `str`             | `"build"`        | L'agent opencode : `build` (accès complet) ou `plan` (lecture seule) |
| `provider_base_url` | `str`             | déduite          | Remplace l'URL de base OpenAI déduite du moteur          |
| `provider_id`       | `str`             | `"diapason"`   | L'identifiant de fournisseur opencode à enregistrer et utiliser |
| `model_id`          | `str`             | `model`          | L'identifiant du modèle chez le fournisseur              |
| `server_password`   | `str`             | `$OPENCODE_SERVER_PASSWORD` | Une authentification basique facultative pour le serveur opencode |
| `timeout`           | `int`             | `600`            | Le délai d'attente HTTP, en secondes                     |

```python
from diapason.agents.opencode import OpenCodeAgent

agent = OpenCodeAgent(engine, "qwen3:8b", workspace="/path/to/project", agent="build")
result = agent.run("Ajoute des annotations de type à utils.py et lance les tests")
print(result.content)
agent.close()
```

```bash
# En ligne de commande (opencode doit être installé)
diapason ask --agent opencode "Refactorise le parseur pour qu'il utilise une machine à états"
```

!!! tip "Les fournisseurs traversants"
    Si aucune URL de base ne peut être déduite du `engine`, passe `model` sous la forme `provider/model` (`ollama/llama3`, par exemple) : opencode le résout depuis sa propre configuration, et aucun `opencode.json` n'est écrit.

!!! warning "La capacité du modèle compte"
    La boucle agentique d'opencode (planifier, appeler correctement les outils,
    mener à terme plusieurs étapes) demande un modèle raisonnablement capable.
    À l'essai, un modèle local **27B** (Qwen3.5-27B servi par vLLM) a résolu
    proprement une suite de 7 tâches de code (création, modification, correction
    de bug, implémentation jusqu'à faire passer les tests, multi-fichiers —
    vérifié en lançant le code et les tests). Un modèle **8B** (qwen3:8b) s'est
    montré peu fiable : appels d'outils mal formés, code syntaxiquement cassé,
    tâches à moitié faites. Pour du vrai travail de code, préfère un modèle
    local capable (ou un modèle distant).

---

## OperativeAgent

L'`OperativeAgent` est un agent autonome, persistant et planifié, avec persistance de session et rappel d'état intégrés. Il est conçu pour les « opérateurs » — des agents autonomes qui tournent à intervalles réguliers, avec gestion automatique de l'état d'un battement à l'autre. Il dérive de `ToolUsingAgent`.

**Comment il marche :**

1. **Chargement de la session** — il restaure l'historique de conversation des battements précédents depuis le magasin de sessions.
2. **Rappel d'état** — il récupère le JSON d'état précédent depuis le moteur de mémoire.
3. **Injection du prompt système** — il injecte les instructions de protocole de l'opérateur.
4. **Boucle d'outils** — la boucle function-calling standard (la même que celle de l'OrchestratorAgent).
5. **Enregistrement de la session** — il consigne le prompt et la réponse du battement dans le magasin de sessions.
6. **Persistance de l'état** — il enregistre l'état automatiquement si l'agent ne l'a pas fait explicitement via l'outil `memory_store`.

**Paramètres du constructeur :**

| Paramètre        | Type              | Défaut  | Description                                      |
|------------------|-------------------|---------|--------------------------------------------------|
| `engine`         | `InferenceEngine` | --      | Le moteur d'inférence à utiliser                 |
| `model`          | `str`             | --      | L'identifiant du modèle                          |
| `tools`          | `list[BaseTool]`  | `[]`    | Les instances d'outils à mettre à disposition    |
| `bus`            | `EventBus`        | `None`  | Le bus d'événements pour la télémétrie           |
| `max_turns`      | `int`             | `20`    | Le nombre maximum de tours d'appel d'outils      |
| `temperature`    | `float`           | `0.3`   | La température d'échantillonnage                 |
| `max_tokens`     | `int`             | `2048`  | Le nombre maximum de jetons à produire           |
| `system_prompt`  | `str`             | `None`  | Un prompt système personnalisé pour l'opérateur  |
| `operator_id`    | `str`             | `None`  | L'identifiant unique pour la persistance de la session et de l'état |
| `session_store`  | `Any`             | `None`  | Le magasin de sessions pour l'historique de conversation |
| `memory_backend` | `Any`             | `None`  | Le moteur de mémoire pour le rappel et la persistance de l'état |

**Quand s'en servir :** pour les agents autonomes qui tournent à intervalles réguliers (via `TaskScheduler`, par exemple) et doivent garder un état entre deux appels. L'agent gère tout seul l'historique de session et la persistance de l'état d'un battement à l'autre.

```python
from diapason.agents.operative import OperativeAgent

agent = OperativeAgent(
    engine,
    model="qwen3:8b",
    tools=[...],
    operator_id="daily-report",
    session_store=session_store,
    memory_backend=memory_backend,
    system_prompt="Tu es un agent de rapport quotidien. Rassemble et résume l'actualité.",
)
result = agent.run("Produis le rapport du jour")
```

```bash
# En ligne de commande
diapason ask --agent operative "Vérifie l'état du système"
```

---

## MonitorOperativeAgent

Le `MonitorOperativeAgent` est un agent de longue haleine, doté de quatre axes de stratégie configurables pour gérer l'information d'un tour et d'une session à l'autre. Il étend `ToolUsingAgent` avec une compression des observations, une extraction en mémoire, une récupération et une décomposition des tâches, toutes pilotées par la stratégie. Il hérite aussi de la persistance d'état entre sessions du motif OperativeAgent.

**Les axes de stratégie :**

| Axe | Valeurs admises | Défaut | Description |
|-----|-----------------|--------|-------------|
| `memory_extraction` | `causality_graph`, `scratchpad`, `structured_json`, `none` | `causality_graph` | Comment les constats sont consignés en mémoire |
| `observation_compression` | `summarize`, `truncate`, `none` | `summarize` | Comment les sorties d'outils sont compressées avant d'entrer dans le contexte |
| `retrieval_strategy` | `hybrid_with_self_eval`, `keyword`, `semantic`, `none` | `hybrid_with_self_eval` | Comment le contexte antérieur est rappelé au début de chaque exécution |
| `task_decomposition` | `phased`, `monolithic`, `hierarchical` | `phased` | Comment les tâches complexes sont découpées |

**Comment il marche :**

1. Il construit un prompt système avec la configuration de stratégie et les descriptions d'outils.
2. Il rappelle l'état précédent depuis le moteur de mémoire.
3. Il charge l'historique de session des battements précédents.
4. Il déroule une boucle d'outils function-calling, en appliquant les stratégies configurées :
    - **Compression des observations** : les longues sorties d'outils sont résumées (par le modèle) ou tronquées avant d'entrer dans le contexte de messages.
    - **Extraction en mémoire** : après chaque appel d'outil, les constats sont extraits et rangés selon la stratégie de mémoire (relations causales, notes de brouillon, ou JSON structuré).
5. Il enregistre la session et consigne l'état automatiquement.

**Paramètres du constructeur :**

| Paramètre                | Type              | Défaut                    | Description                                      |
|--------------------------|-------------------|---------------------------|--------------------------------------------------|
| `engine`                 | `InferenceEngine` | --                        | Le moteur d'inférence à utiliser                 |
| `model`                  | `str`             | --                        | L'identifiant du modèle                          |
| `tools`                  | `list[BaseTool]`  | `[]`                      | Les instances d'outils à mettre à disposition    |
| `bus`                    | `EventBus`        | `None`                    | Le bus d'événements pour la télémétrie           |
| `max_turns`              | `int`             | `25`                      | Le nombre maximum de tours d'appel d'outils      |
| `temperature`            | `float`           | `0.3`                     | La température d'échantillonnage                 |
| `max_tokens`             | `int`             | `4096`                    | Le nombre maximum de jetons à produire           |
| `system_prompt`          | `str`             | `None`                    | Un prompt système personnalisé (remplace celui par défaut) |
| `memory_extraction`      | `str`             | `"causality_graph"`       | La stratégie d'extraction en mémoire             |
| `observation_compression`| `str`             | `"summarize"`             | La stratégie de compression des observations     |
| `retrieval_strategy`     | `str`             | `"hybrid_with_self_eval"` | La stratégie de récupération                     |
| `task_decomposition`     | `str`             | `"phased"`                | La stratégie de décomposition des tâches         |
| `operator_id`            | `str`             | `None`                    | L'identifiant unique pour la persistance de la session et de l'état |
| `session_store`          | `Any`             | `None`                    | Le magasin de sessions pour l'historique de conversation |
| `memory_backend`         | `Any`             | `None`                    | Le moteur de mémoire pour la persistance de l'état et des constats |

**Quand s'en servir :** pour l'évaluation sur des bancs d'essai de longue haleine et les tâches complexes en plusieurs étapes, qui gagnent à des stratégies configurables de gestion de la mémoire, de compression du contexte et de décomposition des tâches. Particulièrement utile sur des bancs comme GAIA, FRAMES et LifelongAgent, où le choix de stratégie pèse sur les résultats.

```python
from diapason.agents.monitor_operative import MonitorOperativeAgent

agent = MonitorOperativeAgent(
    engine,
    model="qwen3:8b",
    tools=[...],
    operator_id="research-agent",
    memory_extraction="causality_graph",
    observation_compression="summarize",
    retrieval_strategy="hybrid_with_self_eval",
    task_decomposition="phased",
    session_store=session_store,
    memory_backend=memory_backend,
)
result = agent.run("Cherche la cause première de la panne en production")
```

```bash
# En ligne de commande
diapason ask --agent monitor_operative "Analyse les constats de l'audit de sécurité"
```

---

## SandboxedAgent

Le `SandboxedAgent` est une enveloppe transparente qui exécute **n'importe quel** `BaseAgent` à l'intérieur d'un conteneur Docker (ou Podman). Il suit le même motif d'enveloppe que `GuardrailsEngine` — la configuration de l'agent interne est sérialisée et envoyée sur le stdin du conteneur, et le résultat est relu sur son stdout.

Voir aussi la référence [`ContainerRunner`](#containerrunner) plus bas, qui gère le cycle de vie du conteneur.

**Comment il marche :**

1. Il construit une charge utile JSON avec le prompt, l'identifiant de l'agent enveloppé et le modèle.
2. Il appelle `ContainerRunner.run()`, qui démarre un conteneur avec `--network none` et `--rm`, écrit la charge utile sur stdin et attend une sortie JSON sur stdout.
3. Les chemins montés sont confrontés à une liste blanche configurable avant que le conteneur ne démarre.
4. Il analyse la sortie délimitée par des sentinelles et rend un `AgentResult`.

**Paramètres du constructeur :**

| Paramètre              | Type              | Défaut       | Description                                       |
|------------------------|-------------------|--------------|---------------------------------------------------|
| `agent`                | `BaseAgent`       | --           | L'agent enveloppé, à exécuter dans le conteneur   |
| `runner`               | `ContainerRunner` | --           | Le lanceur de conteneur qui gère le cycle de vie Docker |
| `engine`               | `InferenceEngine` | `None`       | Remplace le moteur (par défaut, celui de l'agent enveloppé) |
| `model`                | `str`             | `""`         | Remplace le modèle (par défaut, celui de l'agent enveloppé) |
| `workspace`            | `str`             | `""`         | Le dossier de travail à l'intérieur du conteneur  |
| `mounts`               | `list[str]`       | `[]`         | Les chemins de l'hôte à monter (en lecture seule) |
| `secrets`              | `dict[str, str]`  | `{}`         | Injectés dans la charge utile (pas dans les variables d'environnement) |
| `bus`                  | `EventBus`        | `None`       | Le bus d'événements pour la télémétrie            |

```python
from diapason.sandbox import ContainerRunner, SandboxedAgent
from diapason.agents.simple import SimpleAgent

runner = ContainerRunner(
    image="diapason-sandbox:latest",
    timeout=60,
    mount_allowlist_path="/etc/diapason/mount_allowlist.json",
)
inner = SimpleAgent(engine, model="qwen3:8b")
agent = SandboxedAgent(
    agent=inner,
    runner=runner,
    mounts=["/home/user/data"],
)
result = agent.run("Résume les fichiers CSV de /home/user/data")
```

---

## ContainerRunner

Le `ContainerRunner` gère le cycle de vie du conteneur Docker (ou Podman) pour l'exécution en bac à sable. Le `SandboxedAgent` s'en sert directement, mais il s'utilise aussi tout seul.

**Paramètres du constructeur :**

| Paramètre              | Type   | Défaut                       | Description                                    |
|------------------------|--------|------------------------------|------------------------------------------------|
| `image`                | `str`  | `"diapason-sandbox:latest"`| L'image Docker à lancer                        |
| `timeout`              | `int`  | `300`                        | La durée maximale d'exécution du conteneur, en secondes |
| `mount_allowlist_path` | `str`  | `""`                         | Le chemin du fichier JSON de liste blanche des montages |
| `max_concurrent`       | `int`  | `5`                          | Le nombre maximum de conteneurs simultanés (indicatif) |
| `runtime`              | `str`  | `"docker"`                   | Le binaire d'exécution de conteneurs (`docker` ou `podman`) |

**Format de la liste blanche des montages :**

```json title="mount_allowlist.json"
{
  "roots": [
    {"path": "/home/user/projects", "read_only": false},
    {"path": "/data/shared", "read_only": true}
  ],
  "blocked_patterns": [".ssh", ".env", "*.pem", "*.key"]
}
```

Si `mount_allowlist_path` n'est pas défini, aucune restriction de racine n'est appliquée. Les motifs bloqués comprennent toujours, par défaut, `.ssh`, `.env`, `*.pem`, `*.key`, les fichiers d'identifiants et les dossiers de configuration des services cloud.

!!! warning "Docker est nécessaire"
    Le `ContainerRunner` lève une `RuntimeError` si le moteur d'exécution configuré (`docker` ou `podman`) est introuvable dans le `PATH`.

---

## L'enregistrement des agents

Les agents s'enregistrent par le décorateur `@AgentRegistry.register()`, ce qui les rend trouvables par leur nom à l'exécution :

```python
from diapason.core.registry import AgentRegistry

# Vérifier qu'un agent est enregistré
AgentRegistry.contains("orchestrator")  # True

# Récupérer la classe de l'agent
agent_cls = AgentRegistry.get("orchestrator")

# Lister toutes les clés d'agents enregistrées
AgentRegistry.keys()
# ["simple", "orchestrator", "native_react", "react", "native_openhands",
#  "rlm", "openhands", "claude_code", "operative", "monitor_operative"]
```

---

## L'intégration au bus d'événements

Tous les agents publient des événements sur l'`EventBus` quand un bus leur est fourni :

| Événement               | Quand                                               |
|-------------------------|-----------------------------------------------------|
| `AGENT_TURN_START`      | Au début d'une exécution (via `_emit_turn_start`)   |
| `AGENT_TURN_END`        | À la fin d'une exécution (via `_emit_turn_end`)     |
| `TOOL_CALL_START`       | Avant chaque exécution d'outil (sous-classes de `ToolUsingAgent`) |
| `TOOL_CALL_END`         | Après chaque exécution d'outil (sous-classes de `ToolUsingAgent`) |

!!! info "Les événements d'inférence"
    Les événements `INFERENCE_START` / `INFERENCE_END` sont publiés par l'enveloppe `InstrumentedEngine`, pas par les agents eux-mêmes. La télémétrie reste ainsi facultative et transparente pour le code des agents.

Ces événements permettent aux systèmes de télémétrie et de traces d'enregistrer automatiquement le détail des interactions.

---

## Le flux des agents gérés

L'API des agents gérés (`/v1/managed-agents/{id}/messages`) sait diffuser **les vrais jetons du modèle** au fil de l'eau, par SSE. Envoie un message avec `stream: true` pour recevoir les jetons de la réponse à mesure qu'ils sont produits, au lieu d'attendre la réponse entière.

### Comment ça marche

Le point d'entrée de diffusion appelle directement `engine.stream_full()`, qui produit des objets `StreamChunk` contenant des jetons de contenu, des fragments d'appels d'outils et des motifs de fin. C'est un vrai flux jeton par jeton venu du modèle — pas un rejeu mot à mot après coup.

Pour les agents multi-tours qui appellent des outils, la boucle de diffusion, d'elle-même :

1. Transmet les jetons de contenu au client à mesure qu'ils arrivent.
2. Accumule les fragments d'appels d'outils (OpenAI les envoie par morceaux).
3. Exécute les outils dès réception de `finish_reason="tool_calls"`.
4. Émet les résultats d'outils sous forme d'événements SSE nommés (`event: tool_result`).
5. Réinjecte les résultats dans le modèle pour le tour suivant.
6. Recommence jusqu'à ce que le modèle produise une réponse textuelle finale, ou que `max_turns` soit atteint.

### Diffuser des messages

```bash
curl -N -X POST http://localhost:8000/v1/managed-agents/{id}/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "Combien font 2+2 ?", "stream": true}'
```

La réponse suit le format SSE d'OpenAI :

1. **Les morceaux de contenu** — `data: {"choices": [{"delta": {"content": "token"}}]}`
2. **Les appels d'outils** (si le modèle demande à se servir d'un outil) — `event: tool_calls\ndata: {"calls": [{"tool_name": "...", "arguments": "..."}]}`
3. **Les résultats d'outils** — `event: tool_result\ndata: {"tool_name": "...", "output": "..."}`
4. **Le morceau final** — `data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}`
5. **La sentinelle de fin** — `data: [DONE]`

Avec `stream: false` (le défaut), le point d'entrée se comporte exactement comme avant — le message est mis en file, et l'agent doit être déclenché à part, par `/run`.

### Le détail du comportement

- Le message de l'utilisateur est toujours rangé en base avant que la diffusion commence.
- Une fois la diffusion terminée, la réponse complète ainsi rassemblée est consignée comme message `agent_to_user`.
- L'historique des messages précédents est chargé automatiquement comme contexte du modèle.
- C'est la méthode `stream_full()` du moteur qui assure le vrai flux de jetons. Les moteurs qui ne la redéfinissent pas retombent sur l'implémentation par défaut, laquelle enveloppe la méthode `stream()` ordinaire.
- Si le moteur n'est pas disponible sur le serveur, une erreur `503` est rendue.
- Pendant la diffusion, l'exécution des outils passe par le `ToolRegistry` pour trouver et instancier les outils.

### Exemple en Python

```python
import httpx

with httpx.stream(
    "POST",
    "http://localhost:8000/v1/managed-agents/{id}/messages",
    json={"content": "Résume l'actualité du jour", "stream": True},
) as response:
    for line in response.iter_lines():
        if line.startswith("data:") and "[DONE]" not in line:
            print(line[5:].strip())
```
