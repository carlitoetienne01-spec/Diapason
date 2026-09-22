# La primitive Intelligence

La primitive Intelligence représente **le modèle** — son identité, ses poids, son format de quantification, sa chaîne de repli, et le catalogue des modèles connus avec leurs métadonnées détaillées. Elle ne porte plus la logique de routage : l'analyse des requêtes et la sélection du modèle ont déménagé dans la [primitive Apprentissage](learning.md).

---

## Son rôle

La primitive Intelligence répond à une seule question : *quel est le modèle ?* Elle tient un catalogue des modèles connus avec leurs métadonnées (nombre de paramètres, longueur de contexte, besoins en VRAM, moteurs compatibles) et offre des fonctions d'aide pour enregistrer les modèles intégrés et y fusionner les modèles découverts à l'exécution auprès des moteurs en marche.

Elle apporte trois capacités clés :

1. **Le catalogue de modèles** — un registre des modèles connus avec leurs métadonnées (nombre de paramètres, longueur de contexte, besoins en VRAM, moteurs compatibles)
2. **La découverte automatique** — la fusion, dans le catalogue, des modèles découverts auprès des moteurs en marche
3. **La configuration du modèle** — `IntelligenceConfig` porte l'identité du modèle local, les chemins de ses poids, sa quantification et son moteur préféré

!!! info "Le routage a déménagé"
    L'analyse des requêtes (`build_routing_context`) et la sélection du modèle (`HeuristicRouter`, l'ABC `RouterPolicy`) vivent désormais dans la [primitive Apprentissage](learning.md). Des ré-exports de compatibilité ascendante restent dans `intelligence/_stubs.py` et `intelligence/router.py`, pour que le code existant continue de fonctionner.

---

## ModelSpec

Tout modèle du système est décrit par une dataclass `ModelSpec`, définie dans `core/types.py` :

```python
@dataclass(slots=True)
class ModelSpec:
    model_id: str                              # Identifiant unique (par exemple "qwen3:8b")
    name: str                                  # Nom lisible par un humain
    parameter_count_b: float                   # Nombre total de paramètres, en milliards
    context_length: int                        # Fenêtre de contexte maximale (en jetons)
    active_parameter_count_b: Optional[float]  # Paramètres actifs MoE (None si le modèle est dense)
    quantization: Quantization                 # Format de quantification (none, fp8, int4, etc.)
    min_vram_gb: float                         # VRAM minimale requise
    supported_engines: Sequence[str]           # Moteurs capables de faire tourner ce modèle
    provider: str                              # Fournisseur du modèle (par exemple "alibaba", "meta")
    requires_api_key: bool                     # Faut-il une clé d'API distante
    metadata: Dict[str, Any]                   # Métadonnées supplémentaires (tarif, architecture)
```

Les modèles s'enregistrent dans le `ModelRegistry` :

```python
from diapason.core.registry import ModelRegistry

# Enregistrer un modèle
ModelRegistry.register_value("qwen3:8b", ModelSpec(
    model_id="qwen3:8b",
    name="Qwen3 8B",
    parameter_count_b=8.2,
    context_length=32768,
    supported_engines=("vllm", "ollama", "llamacpp", "sglang"),
    provider="alibaba",
))
```

---

## Le catalogue de modèles

Le catalogue intégré est défini dans `intelligence/model_catalog.py`, sous la forme de la liste `BUILTIN_MODELS`. Il couvre trois catégories de modèles :

### Les modèles locaux — denses

| ID du modèle | Nom | Paramètres | Contexte | Moteurs compatibles |
|----------|------|-----------|---------|-------------------|
| `qwen3:8b` | Qwen3 8B | 8.2B | 32K | vLLM, Ollama, llama.cpp, SGLang |
| `qwen3:32b` | Qwen3 32B | 32B | 32K | Ollama, vLLM |
| `llama3.3:70b` | Llama 3.3 70B | 70B | 128K | Ollama, vLLM |
| `llama3.2:3b` | Llama 3.2 3B | 3B | 128K | Ollama, vLLM, llama.cpp |
| `deepseek-coder-v2:16b` | DeepSeek Coder V2 16B | 16B | 128K | Ollama, vLLM |
| `mistral:7b` | Mistral 7B | 7B | 32K | Ollama, vLLM, llama.cpp |

### Les modèles locaux — mélange d'experts (MoE)

| ID du modèle | Nom | Paramètres totaux / actifs | Contexte | VRAM minimale |
|----------|------|----------------------|---------|----------|
| `gpt-oss:120b` | GPT-OSS 120B | 117B / 5.1B | 128K | 12 Go |
| `glm-4.7-flash` | GLM 4.7 Flash | 30B / 3B | 128K | 8 Go |
| `trinity-mini` | Trinity Mini | 26B / 3B | 128K | 8 Go |

### Les modèles distants

| ID du modèle | Fournisseur | Contexte | Tarif (entrée/sortie par million de jetons) |
|----------|----------|---------|--------------------------------------|
| `gpt-4o` | OpenAI | 128K | 2,50 $ / 10,00 $ |
| `gpt-4o-mini` | OpenAI | 128K | 0,15 $ / 0,60 $ |
| `gpt-5-mini` | OpenAI | 400K | 0,25 $ / 2,00 $ |
| `claude-sonnet-4-20250514` | Anthropic | 200K | 3,00 $ / 15,00 $ |
| `claude-opus-4-20250514` | Anthropic | 200K | 15,00 $ / 75,00 $ |
| `claude-opus-4-6` | Anthropic | 200K | 5,00 $ / 25,00 $ |
| `gemini-2.5-pro` | Google | 1M | 1,25 $ / 10,00 $ |
| `gemini-2.5-flash` | Google | 1M | 0,30 $ / 2,50 $ |

### Enregistrer les modèles intégrés

La fonction `register_builtin_models()` peuple le `ModelRegistry` avec tous les modèles intégrés. Elle saute ceux qui sont déjà enregistrés : on peut donc l'appeler plusieurs fois sans risque.

```python
from diapason.intelligence import register_builtin_models

register_builtin_models()
# Tous les BUILTIN_MODELS sont maintenant dans le ModelRegistry
```

---

## La découverte automatique : fusionner les modèles trouvés à l'exécution

Quand les moteurs sont découverts à l'exécution, ils annoncent des modèles qui ne sont pas forcément au catalogue intégré. La fonction `merge_discovered_models()` leur crée des entrées `ModelSpec` minimales :

```python
from diapason.intelligence import merge_discovered_models

# Les modèles annoncés par Ollama qui ne sont pas au catalogue
merge_discovered_models("ollama", ["phi3:3.8b", "codellama:7b"])
```

Pour chaque identifiant de modèle absent du registre, une `ModelSpec` est créée avec l'identifiant du modèle à la fois comme `model_id` et comme `name`, et des valeurs nulles par défaut pour les champs inconnus. Le système de routage peut ainsi choisir parmi tous les modèles disponibles, même ceux dont il n'a aucune métadonnée.

---

## IntelligenceConfig

La dataclass `IntelligenceConfig` (dans `core/config.py`) porte l'identité complète du modèle que le système est configuré pour utiliser, ainsi que les paramètres d'échantillonnage par défaut de la génération :

```python
@dataclass(slots=True)
class IntelligenceConfig:
    """Le modèle — identité, chemins, quantification, chaîne de repli et défauts de génération."""

    default_model: str = ""       # Clé du modèle principal (par exemple "qwen3:8b")
    fallback_model: str = ""      # Repli quand le modèle par défaut est indisponible
    model_path: str = ""          # Poids locaux (dépôt HF, fichier GGUF, etc.)
    checkpoint_path: str = ""     # Chemin du point de contrôle ou de l'adaptateur (LoRA, par exemple)
    quantization: str = "none"    # none, fp8, int8, int4, gguf_q4, gguf_q8
    preferred_engine: str = ""    # Impose un moteur pour ce modèle (par exemple "vllm")
    provider: str = ""            # local, openai, anthropic, google
    # Défauts de génération (chaque appel peut les écraser)
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 0.9
    top_k: int = 40
    repetition_penalty: float = 1.0
    stop_sequences: str = ""      # Chaînes d'arrêt séparées par des virgules
```

### Les champs d'identité du modèle

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `default_model` | `str` | `""` | La clé du modèle principal dans le registre. Résolue au démarrage ; elle l'emporte sur tout défaut du moteur. |
| `fallback_model` | `str` | `""` | Utilisé quand le modèle par défaut n'est disponible sur aucun moteur en marche. |
| `model_path` | `str` | `""` | Chemin ou identifiant de dépôt HuggingFace des poids locaux (`"./models/qwen3-8b.gguf"` ou `"Qwen/Qwen3-8B"`, par exemple). |
| `checkpoint_path` | `str` | `""` | Chemin d'un point de contrôle affiné ou d'un dossier d'adaptateur LoRA. |
| `quantization` | `str` | `"none"` | Format de quantification. Valeurs acceptées : `none`, `fp8`, `int8`, `int4`, `gguf_q4`, `gguf_q8`. |
| `preferred_engine` | `str` | `""` | Quand il est posé, `SystemBuilder`, `sdk.py` et `cli/ask.py` prennent cette clé de moteur au lieu de `config.engine.default`. |
| `provider` | `str` | `""` | Indice sur le fournisseur du modèle : `local`, `openai`, `anthropic`, `google`. Le moteur Cloud s'en sert pour router les appels d'API. |

### Les champs de défauts de génération

Ces champs fixent les paramètres d'échantillonnage par défaut de chaque appel d'inférence. Un appel donné peut les écraser en passant des arguments nommés à `engine.generate()`.

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `temperature` | `float` | `0.7` | Température d'échantillonnage. Plus elle est basse, plus la sortie est déterministe ; plus elle est haute, plus elle varie. |
| `max_tokens` | `int` | `1024` | Nombre maximum de jetons à générer par appel. |
| `top_p` | `float` | `0.9` | Masse de probabilité de l'échantillonnage par noyau. À chaque étape, seuls les jetons qui composent la masse top-p sont considérés. |
| `top_k` | `int` | `40` | Échantillonnage top-k : à chaque étape, seuls les k jetons les plus probables sont considérés. |
| `repetition_penalty` | `float` | `1.0` | Pénalise les suites de jetons répétées. Au-delà de 1.0, la répétition diminue. |
| `stop_sequences` | `str` | `""` | Chaînes d'arrêt séparées par des virgules. La génération s'arrête dès qu'une de ces chaînes apparaît dans la sortie. |

!!! note "Déménagé depuis Agent"
    Les paramètres de génération (`temperature`, `max_tokens`) vivaient auparavant sous `[agent]` dans le fichier de configuration. Ils vivent désormais sous `[intelligence]`. Les anciennes configurations qui les portent sous `[agent]` sont migrées automatiquement au chargement. Voir le [guide de migration de la configuration](../getting-started/configuration.md#migration-guide) pour le détail.

### La configuration TOML

```toml
[intelligence]
default_model = "qwen3:8b"
fallback_model = "llama3.2:3b"
temperature = 0.7
max_tokens = 1024
# top_p = 0.9
# top_k = 40
# repetition_penalty = 1.0
# stop_sequences = ""

# Pour imposer des poids locaux (facultatif)
# model_path = "./models/qwen3-8b-instruct.gguf"
# checkpoint_path = "./checkpoints/my-lora"
# quantization = "gguf_q4"

# Le moteur choisi pour ce modèle (prioritaire sur [engine].default)
# preferred_engine = "vllm"

# Le fournisseur, pour les modèles distants
# provider = "openai"
```

### L'ordre de priorité du choix du moteur

Au moment de décider quel moteur utiliser, `SystemBuilder`, `sdk.py` et `cli/ask.py` regardent `config.intelligence.preferred_engine` avant `config.engine.default` :

```
1. L'option --engine de la CLI, ou le paramètre engine_key= du SDK
2. config.intelligence.preferred_engine  ← le nouveau champ
3. config.engine.default
4. Le premier moteur en bonne santé découvert à l'exécution
```

Tu peux ainsi épingler un modèle donné à un moteur donné sans toucher au moteur par défaut du système. Un modèle quantifié en GGUF, par exemple, peut être épinglé à `llamacpp` pendant que le défaut global reste `ollama` :

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "llama3.2:3b"
model_path = "./models/llama-3.2-3b.Q4_K_M.gguf"
quantization = "gguf_q4"
preferred_engine = "llamacpp"
```

---

## L'API publique

`intelligence/__init__.py` exporte exactement trois noms :

```python
from diapason.intelligence import (
    BUILTIN_MODELS,           # List[ModelSpec] — le catalogue intégré complet
    merge_discovered_models,  # (engine_key, model_ids) -> None
    register_builtin_models,  # () -> None
)
```

### Les cales de compatibilité ascendante

Les noms suivants restent importables depuis `diapason.intelligence` par des modules-cales, mais leur emplacement canonique a changé :

| Nom | Ancien emplacement | Emplacement canonique |
|------|-------------|-------------------|
| `RouterPolicy` | `intelligence/_stubs.py` | `learning/_stubs.py` |
| `QueryAnalyzer` | `intelligence/_stubs.py` | `learning/_stubs.py` |
| `HeuristicRouter` | `intelligence/router.py` | `learning/router.py` |
| `build_routing_context` | `intelligence/router.py` | `learning/router.py` |
| `DefaultQueryAnalyzer` | `intelligence/router.py` | `learning/router.py` |

Le code neuf doit importer depuis les emplacements canoniques `learning.*`. Les cales de `intelligence/_stubs.py` et `intelligence/router.py` ne sont gardées que pour la compatibilité ascendante.

---

## L'intégration avec Apprentissage

La primitive Apprentissage consomme le catalogue de modèles pour prendre ses décisions de routage. `HeuristicRouter` et `TraceDrivenPolicy` lisent tous deux le `ModelRegistry` pour comparer les tailles des modèles au moment de départager des candidats. Voir la documentation [Apprentissage et traces](learning.md) pour tout le détail des politiques de routage, de l'ABC `RouterPolicy` et de la boucle de rétroaction guidée par les traces.
