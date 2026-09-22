# Référence de la ligne de commande

Diapason s'utilise en ligne de commande par la commande `diapason`. Bâtie sur [Click](https://click.palletsprojects.com/), elle offre des sous-commandes pour interroger les modèles, gérer la mémoire, mesurer les performances et servir une API compatible OpenAI.

## Les options globales

```bash
diapason --version   # Affiche la version de Diapason
diapason --help      # Affiche l'aide générale, avec toutes les sous-commandes
```

## `diapason init`

Détecte le matériel de la machine (processeur, carte graphique, mémoire vive) et écrit un fichier de configuration dans `~/.diapason/config.toml`.

```bash
diapason init           # Interactif — refuse d'écraser une config existante
diapason init --force   # Écrase la config existante sans rien demander
```

| Option    | Description                                   |
|-----------|-----------------------------------------------|
| `--force` | Écrase la configuration existante sans rien demander |

La commande `init` détecte toute seule :

- **La plateforme** (Linux, macOS, Windows)
- **Le processeur** : marque et nombre de cœurs
- **La mémoire vive**, en Go
- **La carte graphique** : fabricant, modèle, VRAM et nombre d'unités (via `nvidia-smi`, `rocm-smi` ou `system_profiler`)

D'après ce qu'elle a trouvé, elle recommande un moteur d'inférence adapté et écrit un fichier TOML préconfiguré.

**Exemple de sortie :**

```
Detecting hardware...
  Platform : linux
  CPU      : AMD Ryzen 9 7950X (32 cores)
  RAM      : 64 GB
  GPU      : NVIDIA RTX 4090 (24.0 GB VRAM, x1)

Config written successfully.
```

---

## `diapason ask`

Envoie une question au moteur d'inférence (directement ou par un agent) et affiche la réponse.

```bash
diapason ask "Quelle est la capitale de la France ?"
```

### Les options

| Option                        | Type    | Défaut     | Description                                           |
|-------------------------------|---------|------------|-------------------------------------------------------|
| `-m`, `--model MODEL`         | chaîne  | auto       | Modèle à utiliser pour l'inférence                     |
| `-e`, `--engine ENGINE`       | chaîne  | auto       | Moteur d'inférence (ollama, vllm, llamacpp, etc.)      |
| `-t`, `--temperature TEMP`    | flottant| `0.7`      | Température d'échantillonnage                          |
| `--max-tokens N`              | entier  | `1024`     | Nombre maximum de jetons à générer                     |
| `--json`                      | drapeau | désactivé  | Rend le résultat JSON brut au lieu du texte simple     |
| `--no-stream`                 | drapeau | désactivé  | Coupe le fil de l'eau (mode synchrone)                 |
| `--no-context`                | drapeau | désactivé  | Coupe l'injection du contexte mémoire                  |
| `-a`, `--agent AGENT`         | chaîne  | aucun      | Agent à utiliser (`simple`, `orchestrator`)            |
| `--tools TOOLS`               | chaîne  | aucun      | Noms d'outils à activer, séparés par des virgules      |
| `-i`, `--image PATH`          | chemin  | aucun      | Fichier image pour un modèle de vision (`gemma3:4b`, par exemple) ; répétable |
| `-S`, `--screen`              | drapeau | désactivé  | Capture l'écran courant et l'envoie au modèle de vision |

### Le mode direct et le mode agent

**Le mode direct** (celui par défaut) envoie la question droit au moteur d'inférence :

```bash
diapason ask "Explique l'informatique quantique"
```

**Le mode agent** la fait passer par un agent, qui peut utiliser des outils et mener plusieurs tours :

```bash
diapason ask --agent orchestrator "Combien font 2+2 ?"
diapason ask --agent orchestrator --tools calculator,think "Calcule sqrt(144) + 3^2"
diapason ask --agent simple "Bonjour"
```

### Des exemples

```bash
# Une question simple
diapason ask "Qu'est-ce que l'apprentissage automatique ?"

# Choisir le modèle
diapason ask -m qwen3:8b "Résume ce concept"

# L'agent orchestrator, avec des outils
diapason ask --agent orchestrator --tools calculator "Combien font 15 % de 340 ?"

# Obtenir la sortie en JSON
diapason ask --json "Bonjour"

# Couper l'injection du contexte mémoire
diapason ask --no-context "Parle-moi de Python"

# Fixer le nombre maximum de jetons générés
diapason ask --max-tokens 2048 "Écris une dissertation détaillée sur l'IA"
```

### Les images en entrée

Les modèles capables de vision (`gemma3:4b`, par exemple) savent lire des images
en plus de ta question. Joins une ou plusieurs images avec `-i`/`--image`, ou
capture l'écran courant avec `-S`/`--screen` :

```bash
# Interroger une image du disque
diapason ask -i screenshot.png "Que montre cette image ?"

# Envoyer plusieurs images (l'option est répétable)
diapason ask -i chart-a.png -i chart-b.png "Compare ces deux graphiques"

# Capturer l'écran courant et l'interroger
diapason ask --screen "Résume ce qu'il y a sur mon écran"
```

La vision ne marche qu'en **mode direct**. Si tu passes aussi `--agent`, l'image
est ignorée et une note te le dit — relance avec `--agent ""` pour forcer le mode
direct.

La fenêtre de contexte d'Ollama s'ajuste pour les grandes images ou les longues
questions, avec la variable d'environnement `DIAPASON_NUM_CTX` (`16384` par
défaut) :

```bash
DIAPASON_NUM_CTX=8192 diapason ask --screen "Qu'y a-t-il sur mon écran ?"
```

Pour le serveur, pose-la plutôt une fois pour toutes dans `config.toml` —
`[intelligence] num_ctx = 32768` — pour que la discussion de l'app de bureau
garde de la place pour son historique après le préfixe d'outils de 10 000 jetons
(voir `docs/development/diagnostic-performances-2026-09-19.md`). La variable
d'environnement l'emporte quand les deux sont posées.

Les questions de météo lisent la page des prévisions sur sept jours
d'Environnement Canada pour la ville nommée dans la question ; quand aucune ville
n'est nommée, la discussion prend `[tools] ville = "Ottawa"` dans `config.toml`
(n'importe quelle ville de la table de `server/sources_officielles.py`). Sans
ville configurée, la question doit en nommer une — Diapason ne devine jamais un
lieu.

!!! note "Garder la vision sur la machine"
    Les images sont sensibles. Diapason affiche un avertissement de
    confidentialité avant d'envoyer une image à un moteur qui n'est pas local :
    une capture d'écran ne quitte donc jamais ta machine sans que tu le voies.
    Utilise un moteur local (`ollama` avec `gemma3:4b`, par exemple) pour garder
    la vision entièrement chez toi.

### Le format de la sortie JSON

Avec `--json` en **mode direct**, la sortie contient :

```json
{
  "content": "Le texte de la réponse…",
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 85,
    "total_tokens": 97
  }
}
```

Avec `--json` en **mode agent**, elle contient :

```json
{
  "content": "Le texte de la réponse…",
  "turns": 3,
  "tool_results": [
    {
      "tool_name": "calculator",
      "content": "51.0",
      "success": true
    }
  ]
}
```

---

## `diapason model`

Gère et inspecte les modèles de langue offerts par les moteurs en marche.

### `diapason model list`

Liste tous les modèles offerts par les moteurs d'inférence en marche, dans une table Rich : nombre de paramètres, longueur de contexte et VRAM nécessaire.

```bash
diapason model list
```

**Exemple de sortie :**

```
           Available Models
┌─────────┬────────────────┬────────┬─────────┬──────┐
│ Engine  │ Model          │ Params │ Context │ VRAM │
├─────────┼────────────────┼────────┼─────────┼──────┤
│ ollama  │ qwen3:8b       │ 8B     │ 32,768  │ 6GB  │
│ ollama  │ llama3.2:3b    │ 3B     │ 8,192   │ 3GB  │
└─────────┴────────────────┴────────┴─────────┴──────┘
```

### `diapason model info <model>`

Affiche le détail d'un modèle donné.

```bash
diapason model info qwen3:8b
```

**Exemple de sortie :**

```
┌─ Qwen 3 8B ──────────────────────────────┐
│ Model ID:     qwen3:8b                    │
│ Name:         Qwen 3 8B                   │
│ Parameters:   8B                          │
│ Context:      32,768                      │
│ Quantization: none                        │
│ Min VRAM:     6GB                         │
│ Engines:      ollama, vllm                │
│ Provider:     Alibaba                     │
│ API Key:      not required                │
└───────────────────────────────────────────┘
```

### `diapason model pull <model>`

Télécharge un modèle par Ollama. Une barre de progression suit le téléchargement.

```bash
diapason model pull qwen3:8b
```

!!! note
    La commande `pull` a besoin d'une instance Ollama en marche. Elle se connecte à l'API d'Ollama, à l'hôte configuré dans ton `config.toml`.

---

## `diapason pearl`

Accède aux outils natifs de Pearl — le nœud, le portefeuille et le RPC — depuis la ligne de commande de Diapason.

```bash
diapason pearl doctor
diapason pearl node -- <pearld args>
diapason pearl wallet -- <oyster args>
diapason pearl ctl -- <prlctl args>
diapason pearl address
```

Toutes les commandes d'enrobage de Pearl prennent la forme
`diapason pearl <command>`. Celles qui passent la main renvoient aux binaires
natifs de Pearl :

| Commande Diapason | Binaire Pearl | Usage |
|--------------------|--------------|-----|
| `diapason pearl doctor` | aucun | Vérifie que `pearld`, `oyster` et `prlctl` sont trouvables |
| `diapason pearl node` | `pearld` | Fait tourner le nœud complet Pearl |
| `diapason pearl wallet` | `oyster` | Fait tourner le démon de portefeuille Oyster |
| `diapason pearl ctl` | `prlctl` | Interroge le RPC du nœud ou du portefeuille Pearl |
| `diapason pearl address` | `prlctl --wallet getnewaddress` | Génère une adresse de portefeuille avec Oyster |

Utilise `PEARL_HOME=/path/to/pearl` ou `--pearl-home /path/to/pearl` si le
dossier `bin/` de Pearl n'est pas dans le `PATH`. Voir le
[guide de la ligne de commande Pearl](pearl.md) pour des exemples.

---

## `diapason memory`

Gère la mémoire documentaire qui sert à la génération augmentée par récupération.

### `diapason memory index <path>`

Indexe dans la mémoire les documents d'un fichier ou d'un dossier.

```bash
diapason memory index ./docs/
diapason memory index ./notes.md
diapason memory index ./data/ --chunk-size 256 --chunk-overlap 32
diapason memory index ./docs/ --backend sqlite
```

| Option                      | Type   | Défaut  | Description                          |
|-----------------------------|--------|---------|--------------------------------------|
| `--backend`, `-b`           | chaîne | config  | Remplace le moteur de mémoire par défaut |
| `--chunk-size`              | entier | `512`   | Taille des morceaux, en jetons       |
| `--chunk-overlap`           | entier | `64`    | Recouvrement entre morceaux, en jetons |

La chaîne d'ingestion accepte le texte, le markdown, les fichiers de code et le PDF (avec `pdfplumber` installé). Les fichiers binaires et les dossiers cachés sont sautés automatiquement.

### `diapason memory search <query>`

Cherche dans la mémoire les morceaux de documents pertinents.

```bash
diapason memory search "les bases de l'apprentissage automatique"
diapason memory search -k 10 "réseaux de neurones"
diapason memory search --backend faiss "embeddings"
```

| Option             | Type   | Défaut  | Description                          |
|--------------------|--------|---------|--------------------------------------|
| `--top-k`, `-k`    | entier | `5`     | Nombre de résultats à rendre         |
| `--backend`, `-b`  | chaîne | config  | Remplace le moteur de mémoire par défaut |

Les résultats s'affichent dans une table : rang, score, fichier source et un aperçu du contenu.

### `diapason memory stats`

Affiche les statistiques de la mémoire : nombre de documents et taille de la base.

```bash
diapason memory stats
diapason memory stats --backend sqlite
```

| Option             | Type   | Défaut  | Description                          |
|--------------------|--------|---------|--------------------------------------|
| `--backend`, `-b`  | chaîne | config  | Remplace le moteur de mémoire par défaut |

---

## `diapason telemetry`

Interroge et gère les données de télémétrie d'inférence, stockées en SQLite.

### `diapason telemetry stats`

Affiche les statistiques agrégées — nombre d'appels, jetons, coût et latence — détaillées par modèle et par moteur.

```bash
diapason telemetry stats
diapason telemetry stats -n 5    # Les 5 premiers modèles
```

| Option          | Type   | Défaut | Description                   |
|-----------------|--------|--------|-------------------------------|
| `-n`, `--top`   | entier | `10`   | Nombre de modèles de tête à afficher |

### `diapason telemetry export`

Exporte les enregistrements bruts de télémétrie, en JSON ou en CSV.

```bash
diapason telemetry export                          # JSON sur la sortie standard
diapason telemetry export --format csv             # CSV sur la sortie standard
diapason telemetry export --format json -o data.json  # JSON dans un fichier
diapason telemetry export -f csv -o metrics.csv    # CSV dans un fichier
```

| Option                | Type   | Défaut   | Description                     |
|-----------------------|--------|----------|---------------------------------|
| `-f`, `--format`      | choix  | `json`   | Format de sortie : `json` ou `csv` |
| `-o`, `--output`      | chemin | stdout   | Chemin du fichier de sortie     |

### `diapason telemetry clear`

Supprime de la base tous les enregistrements de télémétrie.

```bash
diapason telemetry clear         # Demande confirmation
diapason telemetry clear --yes   # Sans confirmation
```

| Option         | Type    | Défaut    | Description                   |
|----------------|---------|-----------|-------------------------------|
| `-y`, `--yes`  | drapeau | désactivé | Passe la demande de confirmation |

!!! warning
    Cela supprime définitivement toutes les données de télémétrie stockées. Utilise `--yes` pour passer la confirmation dans un script automatisé.

---

## `diapason bench`

Mesure les performances d'inférence d'un moteur en marche.

### `diapason bench run`

Lance les mesures et rend les résultats.

```bash
diapason bench run                               # Toutes les mesures, 10 échantillons
diapason bench run -n 20                         # 20 échantillons par mesure
diapason bench run -b latency                    # Seulement la latence
diapason bench run -b throughput -n 50 --json    # Débit, 50 échantillons, sortie JSON
diapason bench run -o results.jsonl              # Écrit les résultats JSONL dans un fichier
diapason bench run -m qwen3:8b -e ollama         # Un modèle et un moteur précis
```

| Option                     | Type    | Défaut    | Description                              |
|----------------------------|---------|-----------|------------------------------------------|
| `-m`, `--model MODEL`      | chaîne  | auto      | Modèle à mesurer                         |
| `-e`, `--engine ENGINE`    | chaîne  | auto      | Moteur d'inférence                       |
| `-n`, `--samples N`        | entier  | `10`      | Nombre d'échantillons par mesure         |
| `-b`, `--benchmark NAME`   | chaîne  | toutes    | Mesure précise à lancer                  |
| `-o`, `--output PATH`      | chemin  | aucun     | Écrit les résultats JSONL dans un fichier |
| `--json`                   | drapeau | désactivé | Affiche le résumé JSON sur la sortie standard |

Les mesures disponibles :

- **latency** — la latence d'inférence par appel (moyenne, p50, p95, min, max)
- **throughput** — le débit, en jetons par seconde

---

## `diapason channel`

Gère les canaux de messagerie, pour parler sur plusieurs plateformes. Les canaux se connectent directement aux API des plateformes (Telegram, Discord, Slack, etc.) — aucune passerelle n'est nécessaire.

### `diapason channel list`

Liste les canaux enregistrés et leur état de connexion.

```bash
diapason channel list
```

### `diapason channel send`

Envoie un message à un canal précis.

```bash
diapason channel send slack "Bonjour de la part de Diapason !"
diapason channel send discord "Construction terminée"
```

| Argument    | Type   | Description                          |
|-------------|--------|--------------------------------------|
| `TARGET`    | chaîne | Nom du canal destinataire            |
| `MESSAGE`   | chaîne | Contenu du message                   |

### `diapason channel status`

Affiche l'état de connexion des canaux configurés.

```bash
diapason channel status
```

!!! note "Ce dont chaque canal a besoin"
    Chaque canal réclame les identifiants de sa plateforme (jetons de robot, clés d'API), configurés dans la section `[channel.<platform>]` de ta config. Voir [Configuration](../getting-started/configuration.md) pour le détail.

---

## `diapason serve`

Démarre un serveur d'API compatible OpenAI.

```bash
diapason serve                                      # Hôte et port par défaut, pris dans la config
diapason serve --port 8000                          # Un autre port
diapason serve --model qwen3:8b                     # Choisir le modèle par défaut
diapason serve --agent orchestrator                 # Faire passer les requêtes par un agent

# Laisse tes autres appareils joindre cette machine — les routes du maillage
# seules, sur un second socket. L'application entière reste sur 127.0.0.1.
diapason serve --lan-host 0.0.0.0                   # Maillage sur 0.0.0.0:8001
diapason serve --lan-host 0.0.0.0 --lan-port 8123   # …sur un autre port
```

| Option                   | Type    | Défaut | Description                              |
|--------------------------|---------|--------|------------------------------------------|
| `--host HOST`            | chaîne  | config | Adresse d'écoute de l'application **entière** |
| `--port PORT`            | entier  | config | Numéro de port                           |
| `--lan-host HOST`        | chaîne  | aucun  | Adresse d'écoute du **maillage seul**, sur un second socket (`0.0.0.0`, par exemple). Omise : pas de second socket du tout |
| `--lan-port PORT`        | entier  | `8001` | Port de ce second socket. Doit différer de `--port` |
| `-e`, `--engine ENGINE`  | chaîne  | auto   | Moteur d'inférence                       |
| `-m`, `--model MODEL`    | chaîne  | config | Modèle par défaut pour l'inférence       |
| `-a`, `--agent AGENT`    | chaîne  | aucun  | Agent pour les requêtes hors fil de l'eau |

!!! note "Ce dont le serveur a besoin"
    La commande `serve` réclame l'extra `server` :

    ```bash
    uv sync --extra server
    ```

    Cela installe FastAPI, uvicorn et leurs dépendances.

### Deux sockets, un seul processus {#two-sockets-one-process}

`--host` porte toute l'application, et a vocation à rester sur `127.0.0.1`.
`--lan-host` ouvre un *second* socket, qui monte neuf routes de maillage et rien
d'autre (`create_lan_app` dans `src/diapason/server/app.py`) :

| Méthode | Chemin                                  | Description                       |
|--------|-----------------------------------------|-----------------------------------|
| POST   | `/v1/mesh/pairings/redeem`              | Consommer un code d'invitation    |
| POST   | `/v1/mesh/commands/deliver`             | Remettre une commande à cet appareil |
| POST   | `/v1/mesh/commands/poll`                | Relever les commandes adressées ici |
| POST   | `/v1/mesh/commands/ack`                 | Accuser réception d'une commande  |
| POST   | `/v1/mesh/presence`                     | Battement de présence d'un pair   |
| POST   | `/v1/mesh/files/offer`                  | Proposer un fichier, ouvrir une session |
| POST   | `/v1/mesh/files/{session_id}/chunk`     | Pousser un morceau chiffré        |
| POST   | `/v1/mesh/files/{session_id}/finish`    | Vérifier l'empreinte, révéler le fichier |
| POST   | `/v1/mesh/files/{session_id}/status`    | Quels morceaux manquent encore (reprise) |

Quelques conséquences à connaître avant d'ouvrir ce port :

- `POST /v1/chat/completions` sur le socket du maillage répond **404**, pas 401 —
  la route n'y est pas montée du tout. La discussion, la voix et Succès restent
  sur `--host`.
- Ces neuf routes s'authentifient par **signature d'appareil Ed25519**, par
  invitation ou par jeton de session — *pas* par la clé d'API locale.
- Le second socket ne sert ni `/docs`, ni `/redoc`, ni de schéma OpenAPI.
- Les deux sockets tournent dans un **seul processus** : la boîte aux lettres des
  commandes et les sessions de transfert vivent en mémoire, et deux processus les
  perdraient.
- Un `--lan-port` égal à `--port` est refusé avant que quoi que ce soit ne
  démarre (code de sortie `2`) : sur macOS les deux se lieraient en silence, sur
  Linux le second échouerait.
- Quand un second socket existe, c'est l'adresse qu'on donne aux pairs — la
  balise du maillage annonce `--lan-host:--lan-port`, pas la paire de bouclage.

Au démarrage, la ligne du maillage s'affiche seule, avant le bloc `Starting Diapason API server` :

```
  Maillage : http://0.0.0.0:8001 — neuf routes, créance d'appareil exigée
```

`--host 0.0.0.0` existe toujours, et met toujours l'API *entière* sur le réseau,
protégée par la seule clé d'API locale. Préfère `--lan-host`, à moins de vouloir
vraiment que toutes les routes soient joignables.

### Les routes de l'API

Le serveur expose les routes compatibles OpenAI suivantes :

| Méthode | Chemin                   | Description                    |
|--------|--------------------------|--------------------------------|
| POST   | `/v1/chat/completions`   | Complétions de discussion (au fil de l'eau ou non) |
| GET    | `/v1/models`             | Liste les modèles disponibles  |
| GET    | `/health`                | Contrôle de santé              |
| GET    | `/v1/channels`           | Liste les canaux de messagerie disponibles |
| POST   | `/v1/channels/send`      | Envoie un message à un canal   |
| GET    | `/v1/channels/status`    | État de connexion du pont de canaux |

**Exemple avec curl :**

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:8b",
    "messages": [{"role": "user", "content": "Bonjour !"}]
  }'
```

Quand un agent est configuré (`--agent orchestrator`, par exemple), les requêtes hors fil de l'eau passent par l'agent, avec accès à tous les outils enregistrés. Pour les agents capables d'outils (`orchestrator`, `react`, `openhands`), tous les outils enregistrés sont chargés et mis à disposition automatiquement.

---

## `diapason serve-service`

Garde le serveur d'API en marche dès l'ouverture de session, comme LaunchAgent
macOS. Toutes les sous-commandes sortent en erreur sur une autre plateforme.

```bash
diapason serve-service install                    # 127.0.0.1:8000, à chaque ouverture de session
diapason serve-service install --maillage-reseau  # …plus le maillage sur 0.0.0.0:8001
diapason serve-service status
diapason serve-service restart
diapason serve-service logs --lines 100
diapason serve-service uninstall
```

### `diapason serve-service install`

| Option              | Type    | Défaut      | Description                                    |
|---------------------|---------|-------------|------------------------------------------------|
| `--host HOST`       | chaîne  | `127.0.0.1` | Adresse d'écoute de l'application entière. Une valeur hors bouclage est **refusée** |
| `--port PORT`       | entier  | `8000`      | Port de l'application entière                  |
| `--maillage-reseau` | drapeau | désactivé   | Ouvre aussi le socket du maillage sur `0.0.0.0` |
| `--lan-port PORT`   | entier  | `8001`      | Port de ce socket de maillage                  |

`--maillage-reseau` ajoute `--lan-host 0.0.0.0 --lan-port <port>` à la ligne de
commande `serve` écrite dans le plist — les neuf routes du maillage, signature
d'appareil exigée. L'application entière reste sur le bouclage dans les deux cas.
L'installation affiche d'abord un avertissement, parce que n'importe quelle
machine de ton réseau pourra joindre ce port.

!!! warning "`--allow-network` n'existe plus"
    L'ancien `--allow-network` mettait l'API **entière** sur le réseau. Il
    n'installe plus rien : la commande échoue, nomme `--maillage-reseau` comme
    remplaçante et sort en non-zéro. Elle échoue plutôt que d'aliaser en silence
    — une même commande ne doit pas se mettre à faire autre chose sans le dire.

Les autres refus, tous avant la moindre installation :

- `--host` ailleurs que `127.0.0.1`, `localhost` ou `::1`.
- `--lan-port` égal à `--port` quand `--maillage-reseau` est posé.
- `--port` déjà servi par autre chose que cet agent. Installer, c'est *lancer*
  (le plist porte `RunAtLoad`) : un second serveur sur le même port serait un
  doublon silencieux. Réinstaller par-dessus le service de Diapason lui-même est
  permis — launchd remplace un job de même étiquette.

`status` rend compte de quatre faits distincts : si le LaunchAgent est chargé, où
vit son plist, si `http://127.0.0.1:8000/health` répond vraiment, et où sont les
journaux. Chargé n'est pas la même chose que répond. Voir le
[guide de déploiement launchd](../deployment/launchd.md) pour le plist lui-même.

---

## `diapason mesh`

La flotte des appareils appairés : la rejoindre, voir qui en fait partie, lui
envoyer un fichier. L'appairage se fait par invitation — la machine hôte affiche
un code sous **Appareils → Ajouter un appareil** (la page Appareils), et l'invité
le consomme ici.

### `diapason mesh join`

Rejoindre la flotte d'un autre Diapason.

```bash
diapason mesh join 192.168.0.5:8000 ABCD-1234
diapason mesh join 192.168.0.5:8001 ABCD-1234 --address 192.168.0.9:8001
```

| Argument  | Type   | Description                                           |
|-----------|--------|-------------------------------------------------------|
| `HOST`    | chaîne | L'adresse de l'autre machine, `192.168.0.5:8000` par exemple |
| `TOKEN`   | chaîne | Le code d'invitation qu'elle affiche sous Appareils → Ajouter un appareil |

| Option            | Type   | Défaut  | Description                                          |
|-------------------|--------|---------|------------------------------------------------------|
| `--address ADDR`  | chaîne | deviné  | L'adresse à laquelle **cet** appareil est joignable  |

Quand ça marche, la commande affiche l'identité de flotte de l'hôte, son
identifiant d'appareil, son adresse et les capacités accordées jusque-là — ou
`rien pour l'instant` quand aucune ne l'a été, plutôt que de te laisser supposer
une permission que tu n'as pas reçue. Un appairage refusé sort en `1`.

`HOST` peut être le socket du maillage aussi bien que le principal :
`pairings/redeem` est l'une des neuf routes qu'il porte. Un appareil dont le
registre contient déjà au moins un appareil non révoqué — quel que soit son
niveau de confiance — refuse de rejoindre une *autre* flotte ; celui dont le
registre est illisible aussi. Adopter une autre identité de flotte perdrait tous
ses pairs d'un coup, alors la commande s'arrête et c'est toi qui décides.

### `diapason mesh devices`

Liste les appareils de la flotte, avec leur présence.

```bash
diapason mesh devices
diapason mesh devices --all   # y compris les appareils révoqués
```

Les colonnes : nom, plateforme, niveau de confiance, présence, identifiant d'appareil.

### `diapason mesh send`

Envoie un fichier à un appareil de la flotte.

```bash
diapason mesh send ~/Documents/rapport.pdf "mon PC"
diapason mesh send ./photo.jpg "mon téléphone"
```

| Argument   | Type | Description                                                  |
|------------|------|--------------------------------------------------------------|
| `FICHIER`  | chemin | Le fichier à envoyer. Doit exister et ne pas être un dossier |
| `APPAREIL` | chaîne | La cible, désignée comme le résolveur du maillage la lit : par nom (`"PC du bureau"`) ou par type (`"mon téléphone"`). Un identifiant d'appareil n'est **pas** accepté — le résolveur ne rapproche que des noms, des types d'appareils et des plateformes |

La commande ne prend aucune option. Ce qu'elle fait, dans l'ordre :

1. Lit le registre et ne garde que les appareils `TRUSTED`. Si aucun n'est
   appairé, elle le dit et sort en `1`.
2. Résout `APPAREIL` par le résolveur du maillage. Une formule qui désigne deux
   appareils est **refusée, jamais tranchée au hasard** ; de même pour celle qui
   ne correspond à rien, ou qui désigne cette machine-ci. La phrase du résolveur
   s'affiche telle quelle et la commande sort en `1`.
3. Affiche le nom du fichier et sa taille lisible, puis un compteur
   `n/total morceaux` à mesure que les morceaux partent.
4. Affiche le message du récepteur : vert quand le transfert est arrivé
   (`COMPLETE`, ou `ALREADY_PRESENT` quand la déduplication par contenu a trouvé
   le fichier déjà là, entier et vérifié), jaune pour tout autre statut. Quand le
   récepteur rend un chemin, il s'affiche sous la forme `chez <device> : <path>`.

Un refus du destinataire ou du transport est relayé tel quel, en rouge, avec le
code de sortie `1` — lui sait pourquoi, l'expéditeur non.

C'est le premier appelant en production du cœur de transfert de fichiers : le
pair doit être joignable, ce qui sur un vrai réseau veut dire qu'il fait tourner
`diapason serve` avec `--lan-host` (voir
[Deux sockets, un seul processus](#two-sockets-one-process)).

### `diapason mesh whoami`

Affiche l'identité de cet appareil dans la flotte : identifiant et nom
d'appareil, plateforme, identifiant de flotte (celui du propriétaire) et la clé
**publique**. La clé privée n'apparaît nulle part.

```bash
diapason mesh whoami
```

---

## La recherche de spécification guidée par LLM (pas encore de commande)

La recherche de spécification guidée par LLM (le sous-système d'apprentissage de
harnais piloté par la frontière) n'est exposée que comme bibliothèque Python — il
n'existe pour l'instant aucune sous-commande `diapason` de premier niveau.
Construis directement un `SpecSearchOrchestrator` depuis
`diapason.learning.spec_search.orchestrator` et appelle `.run(trigger)` avec un
déclencheur de `diapason.learning.spec_search.triggers`. Voir
[`docs/user-guide/llm-guided-spec-search.md`](llm-guided-spec-search.md)
pour l'architecture et les briques
(`splits.py`, corpus externes, `external_adapter`).
