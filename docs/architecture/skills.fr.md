---
title: L'architecture des compétences
description: Plongée technique dans la conception du système de compétences, ses composants et ses points d'intégration
---

# L'architecture des compétences

Les compétences forment une **couche d'orchestration transversale**, posée en travers des cinq primitives existantes (Intelligence, Moteur, Agents, Mémoire/Outils, Apprentissage). Elles relient les outils, les agents, la mémoire et l'apprentissage en flux de travail réutilisables, sans remplacer ni absorber aucune primitive.

## La conception du système

```
                    ┌──────────────────────┐
                    │   SystemBuilder      │
                    │   .build()           │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   SkillManager       │
                    │   • discover()       │
                    │   • get_skill_tools()│
                    │   • get_catalog_xml()│
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼──────┐ ┌───────▼───────┐
    │  SkillTool     │ │  Catalogue  │ │  Chargeur     │
    │  (BaseTool)    │ │  XML        │ │  d'overlay    │
    │  → liste des   │ │  → prompt   │ │  → description│
    │    outils de   │ │    système  │ │    optimisée  │
    │    l'agent     │ │             │ │    + few-shot │
    └────────────────┘ └─────────────┘ └───────────────┘
```

## Les composants clés

### SkillManifest (`skills/types.py`)

La structure de données canonique d'une compétence chargée :

```python
@dataclass(slots=True)
class SkillManifest:
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    steps: List[SkillStep] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    signature: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    depends: List[str] = field(default_factory=list)
    user_invocable: bool = True
    disable_model_invocation: bool = False
    markdown_content: str = ""
```

### SkillManager (`skills/manager.py`)

Le coordinateur central. Créé par `SystemBuilder.build()` au moment de composer le système.

**Le cycle de vie :**

1. `discover(paths)` — balaie les dossiers de compétences dans l'ordre de priorité, charge les manifestes, valide le graphe de dépendances, applique les overlays d'optimisation
2. `get_skill_tools()` — habille chaque compétence découverte en `SkillTool(BaseTool)` et branche les rappels de résolution des sous-compétences
3. `get_catalog_xml()` — engendre le XML léger `<available_skills>` à injecter dans le prompt système
4. `get_few_shot_examples()` — rend les chaînes few-shot mises en forme, tirées des overlays d'optimisation

### SkillTool (`skills/tool_adapter.py`)

L'adaptateur qui fait passer n'importe quelle compétence pour un `BaseTool` ordinaire aux yeux des agents :

- la propriété `spec` dérive le `ToolSpec` du manifeste — elle extrait toute seule les paramètres d'entrée des gabarits d'arguments des étapes
- `execute(**params)` lance le pipeline (s'il y a des étapes), rend le contenu markdown (s'il y a un SKILL.md), ou les deux
- `_build_result_metadata()` marque chaque invocation avec `skill`, `skill_source` et `skill_kind`, pour l'analyse des traces en aval

### SkillParser (`skills/parser.py`)

Un parseur en deux passes pour le front-matter des SKILL.md compatibles agentskills.io :

1. **La passe stricte** — valide les champs obligatoires (`name`, `description`), les limites de longueur et les règles de nommage en kebab-case
2. **La passe tolérante** — range les champs maison, hors spécification, à leur place canonique, par la table `FIELD_MAPPING`. Les champs sans correspondance sont journalisés et conservés dans `metadata.diapason.original_frontmatter`

La table de correspondance est une donnée, pas un chemin de code. Prendre en charge de nouveaux champs maison, c'est ajouter des entrées — aucune logique ne change.

### SkillExecutor (`skills/executor.py`)

L'exécuteur de pipeline, séquentiel :

- les étapes portant `tool_name` → déléguées à `ToolExecutor.execute()`
- les étapes portant `skill_name` → déléguées à un rappel de résolution (posé par le SkillManager)
- le rendu des gabarits : la syntaxe `{placeholder}` est résolue depuis un dictionnaire de contexte partagé
- `output_key` garde le résultat de chaque étape pour les étapes suivantes
- publie les événements `SKILL_EXECUTE_START` / `SKILL_EXECUTE_END` sur l'EventBus

### Les résolveurs de source (`skills/sources/`)

Un résolveur par source d'import, tous implémentant la classe abstraite `SourceResolver` :

| Résolveur | Disposition du dépôt | Traitement particulier |
|----------|-------------|------------------|
| `HermesResolver` | `skills/<category>/<skill>/` | Saute `DESCRIPTION.md`, lit les métadonnées maison de Hermes |
| `OpenClawResolver` | `skills/<owner>/<skill>/` | Lit les fichiers annexes `_meta.json` |
| `GitHubResolver` | Parcours récursif à la recherche des `SKILL.md` | Générique — accepte l'URL de n'importe quel dépôt |

### SkillImporter (`skills/importer.py`)

Prend un `ResolvedSkill` rendu par un résolveur de source et l'installe sur le disque :

1. Analyser le SKILL.md source avec `SkillParser`
2. Traduire les références aux outils (`Bash` → `shell_exec`, `Read` → `file_read`, etc.)
3. Vérifier la compatibilité (plateforme, outils manquants)
4. Copier le SKILL.md et les références, ressources et gabarits (les scripts restent derrière `--with-scripts`)
5. Écrire le fichier de provenance `.source` : SHA du commit, outils traduits, horodatages

### SkillOverlay (`skills/overlay.py`)

Le stockage annexe de ce que produit l'optimisation, dans `~/.diapason/learning/skills/<name>/optimized.toml` :

```toml
[optimized]
skill_name = "research-and-summarize"
optimizer = "dspy"
optimized_at = "2026-04-08T14:30:00Z"
trace_count = 47
description = "Une description optimisée"

[[optimized.few_shot]]
input = "les mécanismes d'attention des transformeurs"
output = "## Avancées récentes..."
```

L'overlay est le **contrat** entre l'optimiseur et le SkillManager. Les deux côtés s'entendent sur le schéma ; chacun peut être remplacé sans toucher à l'autre.

### SkillOptimizer (`learning/agents/skill_optimizer.py`)

Une enveloppe autour de DSPy/GEPA, compétence par compétence :

1. Range les traces par `metadata.skill` (le marquage posé en C1)
2. Saute les compétences sous le seuil `min_traces_per_skill`
3. Appelle `_run_dspy()` ou `_run_gepa()` pour chaque compétence retenue
4. Écrit les fichiers TOML d'overlay

## Les points d'intégration

### Le branchement dans SystemBuilder

C'est `SystemBuilder.build()` qui intègre les compétences :

```python
# 1. Créer le SkillManager
skill_manager = SkillManager(bus, capability_policy=...)

# 2. Découvrir les compétences sur le disque
skill_manager.discover(paths=[workspace_skills, user_skills])

# 3. Les habiller en outils et les fondre dans la liste d'outils
skill_tools = skill_manager.get_skill_tools(tool_executor=...)
tool_list.extend(skill_tools)

# 4. Récupérer les exemples few-shot pour les agents
system._skill_few_shot_examples = skill_manager.get_few_shot_examples()
```

### Le cheminement des métadonnées de trace

Quand un agent invoque un `SkillTool` :

```
SkillTool.execute()
  → ToolResult(metadata={"skill": name, "skill_source": src, "skill_kind": kind})
    → ToolExecutor._json_safe_metadata() écarte les valeurs non sérialisables
      → événement TOOL_CALL_END, avec ses métadonnées
        → TraceCollector._on_tool_end() → TraceStep(metadata=...)
          → TraceStore enregistre dans SQLite (les métadonnées en JSON)
            → SkillOptimizer._bucket_traces_by_skill() lit metadata.skill
```

### L'injection des exemples few-shot dans l'agent

Les exemples few-shot optimisés cheminent ainsi :

```
SkillManager.get_few_shot_examples()
  → system._skill_few_shot_examples (rangé sur DiapasonSystem)
    → _run_agent() → agent_kwargs["skill_few_shot_examples"]
      → ToolUsingAgent._skill_few_shot_examples
        → native_react.run() → REACT_SYSTEM_PROMPT.format(skill_examples=...)
```

## Le graphe de dépendances

Une compétence peut en composer d'autres. À la découverte, le SkillManager vérifie :

1. **La détection des cycles** — l'algorithme de Kahn, pour le tri topologique
2. **Le respect de la profondeur maximale** — configurable (5 par défaut)
3. **L'union des capacités** — le parent doit déclarer toutes les capacités de ses enfants, transitivement

## La disposition des fichiers

```
src/diapason/skills/
├── __init__.py           # Les exports publics
├── types.py              # SkillManifest, SkillStep
├── manager.py            # SkillManager
├── executor.py           # SkillExecutor + délégation aux sous-compétences
├── loader.py             # Chargement TOML + Markdown + dossier
├── tool_adapter.py       # L'enveloppe SkillTool(BaseTool)
├── parser.py             # Parseur agentskills.io strict + tolérant
├── tool_translator.py    # Traduction des noms d'outils externes
├── importer.py           # Installation depuis les sources résolues
├── overlay.py            # Le stockage annexe de l'optimisation
├── dependency.py         # Validation du graphe
├── security.py           # Niveaux de confiance, validation des capacités
├── index.py              # L'index des compétences, adossé à Git
└── sources/
    ├── base.py            # La classe abstraite SourceResolver
    ├── hermes.py          # HermesResolver
    ├── openclaw.py        # OpenClawResolver
    └── github.py          # GitHubResolver
```
