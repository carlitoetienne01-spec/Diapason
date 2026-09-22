# Le déploiement avec Docker

Diapason fournit des images Docker pour les déploiements sur processeur seul comme pour ceux accélérés par carte graphique, ainsi qu'une configuration Docker Compose qui réunit le serveur d'API et un moteur d'inférence Ollama.

## Démarrer vite

Le conteneur écoute sur `0.0.0.0` : une **clé d'API est donc obligatoire** — le
serveur refuse de démarrer sur une adresse autre que la boucle locale sans clé.
Pose-la d'abord :

```bash
cd deploy/docker
cp .env.example .env
echo "DIAPASON_API_KEY=$(diapason auth generate-key)" > .env   # ou colle la tienne
```

Lance ensuite le serveur d'API et le moteur Ollama d'un seul coup avec Docker Compose :

```bash
docker compose up -d
```

`docker compose` lit `DIAPASON_API_KEY` dans `.env` (ou dans l'environnement de
ton shell) et échoue tout de suite si elle n'est pas posée. Les clients doivent
ensuite envoyer `Authorization: Bearer <key>` sur les requêtes `/v1/*` et
`/api/*`.

Deux services se lèvent :

| Service  | Port  | Description                        |
|----------|-------|------------------------------------|
| `diapason` | 8000  | Le serveur d'API Diapason        |
| `ollama` | 11434 | Le moteur d'inférence Ollama       |

Vérifie que le serveur tourne :

```bash
curl http://localhost:8000/health
```

Réponse attendue :

```json
{"status": "ok"}
```

## Les images Docker

### L'image processeur seul (`Dockerfile`)

Le `Dockerfile` par défaut passe par une construction multi-étages fondée sur `python:3.12-slim`, pour produire une image minimale.

**Les étapes de construction :**

1. **L'étape builder** — installe `uv` et le paquet `diapason[server]` (qui embarque FastAPI, uvicorn et toutes les dépendances du serveur) depuis les sources du projet.
2. **L'étape runtime** — ne copie que les paquets Python installés et le code de l'application depuis l'étape précédente, ce qui garde l'image finale petite.

```dockerfile
FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server]"

FROM python:3.12-slim

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["diapason"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
```

Construis-la à la main :

```bash
docker build -t diapason:latest .
```

Lance-la toute seule :

```bash
docker run -d -p 8000:8000 diapason:latest
```

### L'image GPU (`Dockerfile.gpu`)

L'image GPU est bâtie sur `nvidia/cuda:12.4.0-runtime-ubuntu22.04` et embarque les bibliothèques d'exécution de CUDA 12.4 : elle permet l'inférence accélérée par carte graphique, associée à un moteur qui sait s'en servir comme vLLM ou SGLang.

```dockerfile
FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04 AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server]"

FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["diapason"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
```

Construis l'image GPU :

```bash
docker build -f Dockerfile.gpu -t diapason:gpu .
```

Lance-la avec l'accès à la carte graphique (il faut le [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)) :

```bash
docker run -d --gpus all -p 8000:8000 diapason:gpu
```

!!! note "Le NVIDIA Container Toolkit est requis"
    La machine hôte doit avoir le NVIDIA Container Toolkit installé pour que `--gpus` fonctionne. Voir le [guide d'installation NVIDIA](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) pour la marche à suivre.

## La configuration Docker Compose

Le `docker-compose.yml` décrit un déploiement complet, avec le serveur d'API Diapason et un moteur Ollama :

```yaml
version: "3.9"

services:
  diapason:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DIAPASON_ENGINE_DEFAULT=ollama
      - DIAPASON_OLLAMA_HOST=http://ollama:11434
    depends_on:
      - ollama
    restart: unless-stopped

  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama
    restart: unless-stopped

volumes:
  ollama-models:
```

### Les variables d'environnement

Le service `diapason` se configure par des variables d'environnement :

| Variable                      | Description                                             | Défaut                     |
|-------------------------------|---------------------------------------------------------|----------------------------|
| `DIAPASON_ENGINE_DEFAULT`   | Le moteur d'inférence à utiliser                        | `ollama`                   |
| `DIAPASON_OLLAMA_HOST`      | L'URL du serveur Ollama (par le nom de service Docker)  | `http://ollama:11434`      |

### Les volumes

Le volume nommé `ollama-models` conserve les modèles téléchargés d'un redémarrage de conteneur à l'autre : il n'y a pas à les retélécharger après un cycle `docker compose down` / `docker compose up`.

### Les dépendances entre services

Le service `diapason` déclare `depends_on: ollama`, ce qui garantit que le conteneur Ollama démarre avant le serveur d'API. Les deux services emploient `restart: unless-stopped` pour se relever tout seuls après un plantage.

## La configuration sur mesure

### Monter un fichier de configuration

Pour utiliser un `config.toml` à toi, monte-le dans le conteneur au chemin attendu (`~/.diapason/config.toml`, qui devient `/root/.diapason/config.toml` dans le conteneur) :

```yaml
services:
  diapason:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./my-config.toml:/root/.diapason/config.toml:ro
    environment:
      - DIAPASON_ENGINE_DEFAULT=ollama
      - DIAPASON_OLLAMA_HOST=http://ollama:11434
    depends_on:
      - ollama
    restart: unless-stopped
```

### Conserver les données

Pour conserver les données de télémétrie, les bases de mémoire et les enregistrements de traces d'un redémarrage de conteneur à l'autre, monte tout le dossier de données de Diapason :

```yaml
services:
  diapason:
    # ... le reste de la config ...
    volumes:
      - diapason-data:/root/.diapason

volumes:
  ollama-models:
  diapason-data:
```

Ce qui est ainsi préservé :

- `telemetry.db` — les relevés de télémétrie des appels d'inférence
- `memory.db` — la mémoire SQLite par défaut
- `traces.db` — les enregistrements de traces d'interaction
- `config.toml` — la configuration de l'utilisateur

### Utiliser l'image GPU avec Compose

Pour employer le Dockerfile GPU dans ton montage Compose, change le champ `dockerfile` et ajoute les réservations de ressources GPU :

```yaml
services:
  diapason:
    build:
      context: .
      dockerfile: Dockerfile.gpu
    ports:
      - "8000:8000"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    environment:
      - DIAPASON_ENGINE_DEFAULT=ollama
      - DIAPASON_OLLAMA_HOST=http://ollama:11434
    depends_on:
      - ollama
    restart: unless-stopped
```

## La vérification de santé

Le serveur d'API expose une route `GET /health` qui vérifie si le moteur d'inférence sous-jacent répond :

```bash
curl http://localhost:8000/health
```

En bonne santé, il rend un HTTP 200 :

```json
{"status": "ok"}
```

Un moteur en panne rend un HTTP 503 :

```json
{"detail": "Engine unhealthy"}
```

Tu peux brancher tout ça sur le `healthcheck` de ton Docker Compose :

```yaml
services:
  diapason:
    # ... le reste de la config ...
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

## Construire des images sur mesure

### Ajouter des dépendances

Pour inclure d'autres moteurs d'inférence (vLLM, par exemple) ou la mémoire ColBERT, modifie la commande d'installation dans le Dockerfile :

```dockerfile
RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server,inference-vllm,memory-colbert]"
```

### Remplacer la commande par défaut

Le point d'entrée est `diapason` et la commande par défaut est `serve --host 0.0.0.0 --port 8000`. Remplace la commande pour changer les options du serveur :

```bash
docker run -d -p 9000:9000 diapason:latest \
  serve --host 0.0.0.0 --port 9000 --engine ollama --model qwen3:8b
```

Ou dans Docker Compose :

```yaml
services:
  diapason:
    build: .
    command: ["serve", "--host", "0.0.0.0", "--port", "9000", "--model", "qwen3:8b"]
    ports:
      - "9000:9000"
```

### Les options de ligne de commande de `diapason serve`

| Option               | Description                                         |
|----------------------|-----------------------------------------------------|
| `--host`             | Adresse d'écoute (défaut : depuis la config, en général `0.0.0.0`) |
| `--port`             | Numéro de port (défaut : depuis la config, en général `8000`)      |
| `-e` / `--engine`    | Moteur d'inférence (`ollama`, `vllm`, `llamacpp`, `sglang`)  |
| `-m` / `--model`     | Nom du modèle par défaut                                 |
| `-a` / `--agent`     | Agent pour les requêtes hors fil de l'eau (`simple`, `orchestrator`, `react`, `openhands`) |

## Récupérer les modèles

Une fois le conteneur Ollama démarré, il te faut récupérer au moins un modèle avant que le serveur d'API puisse répondre aux requêtes :

```bash
docker compose exec ollama ollama pull qwen3:8b
```

Vérifie que les modèles sont visibles par l'API :

```bash
curl http://localhost:8000/v1/models
```
