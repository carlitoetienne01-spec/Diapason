# Discussion simple

Une IA conversationnelle légère, sans outils et sans la machinerie d'un agent. C'est la configuration Diapason la plus simple qui soit : Ollama et un modèle local, rien de plus. Idéale pour discuter de tout et de rien, poser des questions, brasser des idées et démarrer vite.

## Démarrage rapide (3 minutes)

### 1. Installer Ollama et télécharger un modèle

```bash
# Installe Ollama : https://ollama.com
ollama pull qwen3.5:4b
```

### 2. Installer et initialiser Diapason

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync
diapason init --preset chat-simple
```

### 3. Poser une question

```bash
diapason ask "Qu'est-ce que l'informatique quantique ?"
```

C'est tout. Aucune clé d'API, aucun outil, aucun nuage — juste un modèle local qui répond à tes questions.

## Les commandes de la CLI

```bash
# Une seule question
diapason ask "Explique la différence entre TCP et UDP"

# Une session de discussion interactive (conversation à plusieurs tours)
diapason chat

# Démarrer le serveur d'API pour l'app navigateur ou l'app de bureau
diapason serve

# Changer de modèle pour une seule question
diapason ask -m qwen3.5:9b "Explique la relativité générale"

# Régler la température (0.0 = déterministe, 1.0 = créatif)
diapason ask -t 0.2 "Liste les planètes du système solaire"

# Rendre le JSON brut
diapason ask --json "Combien font 2+2 ?"
```

## Référence de configuration

Le préréglage écrit ceci dans `~/.diapason/config.toml` :

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:4b"       # Rapide et léger
# default_model = "qwen3.5:9b"     # Meilleure qualité
# default_model = "llama3.1:8b"    # Un autre modèle

[agent]
default_agent = "simple"            # Un seul tour, aucun outil

[server]
host = "0.0.0.0"
port = 8000
```

### Le choix du modèle

| Modèle | Paramètres | Vitesse | Qualité | Pour quoi |
|--------|-----------|---------|---------|-----------|
| `qwen3.5:4b` | 4B | Rapide | Bonne | Réponses rapides, machine modeste |
| `qwen3.5:9b` | 9B | Équilibrée | Meilleure | Discussion générale, explications |
| `qwen3.5:35b` | 35B | Plus lente | La meilleure | Raisonnement complexe, analyse détaillée |
| `llama3.1:8b` | 8B | Équilibrée | Bonne | Une autre voie si tu préfères les modèles Meta |

Pour changer de modèle, modifie `~/.diapason/config.toml` ou remplace-le question par question :

```bash
diapason ask -m qwen3.5:35b "Écris une comparaison détaillée de REST et de GraphQL"
```

Pour télécharger un nouveau modèle :

```bash
ollama pull qwen3.5:35b
```

## Utiliser l'app navigateur

Démarre le serveur et l'interface React en une seule commande :

```bash
./scripts/quickstart.sh
```

Ça ouvre [http://localhost:5173](http://localhost:5173) dans ton navigateur, avec l'interface de discussion complète, les réponses au fil de l'eau et le tableau de bord de consommation.

Pour ne lancer que le serveur d'API (pour l'app de bureau ou pour des clients externes) :

```bash
diapason serve
```

Le serveur est compatible OpenAI : n'importe quel client qui fonctionne avec l'API OpenAI peut pointer vers `http://localhost:8000/v1`.

## Utiliser l'app de bureau

1. Démarre le serveur : `diapason serve` (ou `./scripts/quickstart.sh`).
2. Construis l'app de bureau depuis le dépôt authentifié. Aucune version n'est
   publiée pour l'instant ; sur le Mac de Carlito, lance `./scripts/install-desktop.sh`.
3. L'app se connecte toute seule à `http://localhost:8000`.

## Changer de modèle

Tu peux changer le modèle par défaut quand tu veux :

**Modifier la configuration :**

```bash
# Ouvrir le fichier de configuration
${EDITOR:-nano} ~/.diapason/config.toml
# Remplacer default_model par le modèle de ton choix
```

**Télécharger et basculer d'un coup :**

```bash
ollama pull deepseek-r1:14b
diapason ask -m deepseek-r1:14b "Bonjour"
```

**Passer par une variable d'environnement :**

```bash
DIAPASON_MODEL=qwen3.5:9b diapason ask "Bonjour"
```

## Dépannage

**« No running engine found »** — assure-toi qu'Ollama tourne. Démarre-le avec `ollama serve` ou ouvre l'app de bureau Ollama.

**« Model not found »** — télécharge d'abord le modèle avec `ollama pull <nom-du-modèle>`. Liste les modèles disponibles avec `ollama list`.

**Les réponses sont lentes** — prends un modèle plus petit (`qwen3.5:4b`). Vérifie la mémoire disponible : un modèle a besoin d'à peu près autant de Go de mémoire vive qu'il compte de milliards de paramètres (un modèle 9B demande environ 9 Go).

**Tu veux ajouter des outils plus tard ?** — bascule sur la configuration [Assistant de code](code-assistant.md) ou [Recherche approfondie](deep-research.md). La discussion simple est minimale à dessein.

**L'app navigateur ne charge pas** — assure-toi que le serveur (`diapason serve`) et l'interface tournent tous les deux. Le script `./scripts/quickstart.sh` démarre les deux tout seul.
