# Assistant de code

Un agent orchestrator qui exécute du code, lit et écrit des fichiers et accède au shell. Il sait écrire des scripts, lire et expliquer du code, lancer des tests, corriger des bugs et exécuter des commandes shell — le tout en local, sur ta machine.

## Démarrage rapide (5 minutes)

### 1. Installer et initialiser

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync --extra dev
diapason init --preset code-assistant
```

Cela écrit un `~/.diapason/config.toml` déjà réglé pour l'assistant de code.

### 2. Démarrer un modèle local avec Ollama

```bash
# Installe Ollama depuis https://ollama.com
ollama pull qwen3.5:9b
```

### 3. Poser une question de code

```bash
diapason ask "Écris un script Python qui lit un fichier CSV et affiche les 5 premières lignes"
```

L'agent orchestrator prévoit la marche à suivre, écrit le code, et peut l'exécuter si tu l'y autorises.

## Les commandes de la CLI

```bash
# Poser une question de code (avec cette configuration, l'agent orchestrator est pris par défaut)
diapason ask "Écris un script Python qui analyse du JSON lu sur l'entrée standard"

# Lire et expliquer du code existant
diapason ask "Lis main.py et explique-moi l'architecture"

# Corriger un bug
diapason ask "Trouve et corrige le bug dans test_utils.py"

# Lancer les tests
diapason ask "Lance la suite de tests et résume les échecs"

# Nommer explicitement l'agent et les outils
diapason ask --agent orchestrator --tools code_interpreter "Calcule les 20 premiers nombres de Fibonacci"

# Discussion interactive, pour coder par allers-retours
diapason chat
```

## Référence de configuration

Le préréglage écrit ceci dans `~/.diapason/config.toml` :

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:9b"
# default_model = "qwen3.5:35b"    # Mieux pour les tâches de code difficiles

[agent]
default_agent = "orchestrator"      # Plusieurs tours, avec choix des outils
max_turns = 10

[tools]
enabled = ["code_interpreter", "file_read", "file_write", "shell_exec", "web_search", "think", "calculator"]
```

### Les réglages qui comptent

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `intelligence.default_model` | `qwen3.5:9b` | Le modèle qui génère le code. Prends `qwen3.5:35b` pour les tâches difficiles : réusinage, changements répartis sur plusieurs fichiers. |
| `agent.default_agent` | `orchestrator` | L'agent multi-tours, qui choisit ses outils au fil des tours jusqu'à tenir une réponse. |
| `agent.max_turns` | `10` | Nombre maximum de tours d'appel d'outils. À augmenter pour les tâches en plusieurs étapes. |
| `tools.enabled` | 7 outils | `code_interpreter` (exécute du Python), `file_read`, `file_write`, `shell_exec` (lance des commandes shell), `web_search`, `think`, `calculator`. |

### Les outils, en détail

| Outil | Ce qu'il fait |
|------|-------------|
| `code_interpreter` | Exécute du code Python dans un bac à sable et rend la sortie. |
| `file_read` | Lit des fichiers, chemin validé. L'agent peut inspecter le code source, les configurations, les journaux. |
| `file_write` | Écrit ou modifie des fichiers. L'agent peut créer des scripts, corriger du code, écrire des configurations. |
| `shell_exec` | Lance des commandes shell (`git status`, `pytest`, `ls`, par exemple). |
| `web_search` | Cherche sur le web de la documentation, des réponses Stack Overflow, etc. |
| `think` | Brouillon de raisonnement interne, pour préparer une solution en plusieurs étapes. |
| `calculator` | Évalue des expressions mathématiques. |

## Des exemples de tâches

```bash
# Écrire un nouveau script
diapason ask "Écris un script Python qui convertit du YAML en JSON"

# Expliquer du code existant
diapason ask "Lis src/diapason/core/events.py et explique-moi le motif EventBus"

# Déboguer un test qui échoue
diapason ask "Lance pytest tests/test_memory.py -v et corrige les échecs"

# Réusiner du code
diapason ask "Lis utils.py et réusine la fonction parse_config avec des dataclasses"

# Générer des tests
diapason ask "Lis src/diapason/tools/calculator.py et écris-en les tests unitaires"

# Tâches shell
diapason ask "Trouve tous les fichiers Python de plus de 100 Ko dans ce dépôt"
```

## Notes de sécurité

Les outils `shell_exec` et `code_interpreter` exécutent de vraies commandes sur ta machine. À garder en tête :

- **shell_exec** lance les commandes avec ton compte utilisateur. Il peut lire, écrire et supprimer des fichiers. Évite de faire travailler l'agent dans un dossier contenant des données sensibles sans relire ses appels d'outils.
- **code_interpreter** exécute du code Python. Il a accès à ton environnement Python et aux paquets installés.
- En mode interactif (`diapason chat`), l'agent demande confirmation avant d'exécuter une commande potentiellement destructrice.
- Pour un cloisonnement plus fort, passe par l'agent `sandboxed` : `diapason ask --agent sandboxed --tools code_interpreter "..."`, qui tourne dans un conteneur Docker/Podman.

## Dépannage

**« Tool not found: code_interpreter »** — vérifie que ton `config.toml` contient bien `code_interpreter` dans la liste `tools.enabled`.

**L'agent tourne en rond sans avancer** — augmente `max_turns` si la tâche est difficile, ou prends un modèle plus gros (`qwen3.5:35b`). Le 9b suffit à la plupart des tâches sur un seul fichier ; un réusinage réparti sur plusieurs fichiers profite d'un nombre de paramètres plus élevé.

**Une commande shell échoue** — l'outil `shell_exec` lance les commandes depuis le dossier où tu as démarré `diapason`. Écris `cd /chemin && commande` dans ton prompt si besoin, ou lance `diapason` depuis le dossier du projet.

**La recherche web ne marche pas** — installe avec `uv sync --extra tools-search` et renseigne `TAVILY_API_KEY`.

**L'exécution de code reste bloquée** — `code_interpreter` a un délai d'attente par défaut. Un script trop long est interrompu. Découpe les grosses tâches en étapes plus petites.
