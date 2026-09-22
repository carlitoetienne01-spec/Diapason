# Le serveur d'API

Diapason embarque un serveur d'API compatible OpenAI, bâti sur FastAPI et uvicorn. Il expose des routes de complétion de discussion, de liste des modèles et de vérification de santé : c'est un remplacement direct de l'API OpenAI quand tu travailles avec des modèles locaux.

## Lancer le serveur

Le serveur réclame l'extra `[server]` (FastAPI + uvicorn) :

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync --extra server
```

Lance-le avec les réglages par défaut :

```bash
diapason serve
```

Le serveur lit ses valeurs par défaut dans `~/.diapason/config.toml` et détecte tout seul les moteurs et les modèles disponibles. Chaque option se remplace par un drapeau en ligne de commande :

```bash
diapason serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b --agent orchestrator
```

### Les options de la ligne de commande

| Option               | Description                                                                  | Défaut           |
|----------------------|------------------------------------------------------------------------------|--------------------|
| `--host`             | Adresse réseau sur laquelle écouter                                          | Depuis la config (`0.0.0.0`) |
| `--port`             | Port d'écoute                                                                | Depuis la config (`8000`)    |
| `-e` / `--engine`    | Moteur d'inférence (`ollama`, `vllm`, `llamacpp`, `sglang`)                  | Détecté automatiquement      |
| `-m` / `--model`     | Modèle par défaut pour les complétions                                       | Le premier disponible     |
| `-a` / `--agent`     | Agent pour les requêtes hors fil de l'eau (`simple`, `orchestrator`, `react`, `openhands`) | Depuis la config (`orchestrator`) |

Au démarrage, le serveur affiche un résumé :

```
Starting Diapason API server
  Engine: ollama
  Model:  qwen3:8b
  Agent:  orchestrator
  URL:    http://0.0.0.0:8000
```

!!! warning "Vérification des dépendances du serveur"
    Si l'extra `[server]` n'est pas installé, `diapason serve` s'arrête avec un message d'erreur clair qui explique comment installer les dépendances nécessaires.

## Les routes

### `POST /v1/chat/completions`

La route principale, celle qui engendre les complétions de discussion. Elle accepte le même format de requête que l'API Chat Completions d'OpenAI.

#### Le corps de la requête

```json
{
  "model": "qwen3:8b",
  "messages": [
    {"role": "system", "content": "Tu es un assistant serviable."},
    {"role": "user", "content": "Quelle est la capitale de la France ?"}
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "stream": false,
  "tools": null
}
```

| Paramètre     | Type              | Défaut  | Description                                                  |
|---------------|-------------------|---------|--------------------------------------------------------------|
| `model`       | `string`          | —       | **Obligatoire.** Identifiant du modèle à utiliser pour la génération. |
| `messages`    | `array`           | —       | **Obligatoire.** Tableau d'objets message, avec `role` et `content`. |
| `temperature` | `float`           | `0.7`   | Température d'échantillonnage (de 0.0 à 2.0).                |
| `max_tokens`  | `integer`         | `1024`  | Nombre maximum de jetons à générer.                          |
| `stream`      | `boolean`         | `false` | Rendre ou non la réponse au fil de l'eau, par SSE.           |
| `tools`       | `array` ou `null` | `null`  | Définitions d'outils, au format function-calling d'OpenAI.   |

Chaque objet message :

| Champ          | Type              | Description                                           |
|----------------|-------------------|-------------------------------------------------------|
| `role`         | `string`          | L'un de `system`, `user`, `assistant` ou `tool`.      |
| `content`      | `string`          | Le contenu du message.                                |
| `name`         | `string` ou `null`| Nom facultatif de l'auteur du message.                |
| `tool_calls`   | `array` ou `null` | Les appels d'outils faits par l'assistant (dans les messages `assistant`). |
| `tool_call_id` | `string` ou `null`| Identifiant de l'appel d'outil auquel ce message répond (dans les messages `tool`). |

#### La réponse (hors fil de l'eau)

```json
{
  "id": "chatcmpl-abc123def456",
  "object": "chat.completion",
  "created": 1740100800,
  "model": "qwen3:8b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "La capitale de la France est Paris.",
        "tool_calls": null
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 8,
    "total_tokens": 33
  }
}
```

Quand un agent est configuré sur le serveur, les requêtes hors fil de l'eau passent par lui : il peut raisonner sur plusieurs tours, avec des appels d'outils, avant de rendre une réponse finale. Sans agent configuré, les requêtes vont droit au moteur d'inférence.

#### Les appels d'outils

Quand la requête porte des `tools`, le moteur peut rendre des `tool_calls` dans le message de l'assistant :

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [
          {
            "id": "call_abc123",
            "type": "function",
            "function": {
              "name": "calculator",
              "arguments": "{\"expression\": \"2 + 2\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ]
}
```

### `GET /v1/models`

Liste tous les modèles disponibles sur le moteur d'inférence configuré.

#### La réponse

```json
{
  "object": "list",
  "data": [
    {
      "id": "qwen3:8b",
      "object": "model",
      "created": 1740100800,
      "owned_by": "diapason"
    },
    {
      "id": "llama3.1:8b",
      "object": "model",
      "created": 1740100800,
      "owned_by": "diapason"
    }
  ]
}
```

### `GET /health`

La route de vérification de santé : elle confirme que le moteur d'inférence répond.

#### La réponse (en bonne santé)

HTTP 200 :

```json
{"status": "ok"}
```

#### La réponse (en panne)

HTTP 503 :

```json
{"detail": "Engine unhealthy"}
```

### `GET /dashboard`

Sert le tableau de bord des économies, une page HTML qui affiche en direct le compte des appels d'inférence servis en local et l'économie estimée par rapport aux fournisseurs d'API dans le nuage. Le tableau de bord se rafraîchit tout seul toutes les 5 secondes en interrogeant la route `/v1/savings`.

### `GET /v1/channels`

Liste les canaux enregistrés et leur état de connexion.

#### La réponse

```json
{
  "channels": ["slack", "discord", "telegram"]
}
```

### `POST /v1/channels/send`

Envoie un message vers un canal précis.

#### Le corps de la requête

```json
{
  "target": "slack",
  "message": "Bonjour depuis Diapason !"
}
```

#### La réponse

```json
{
  "status": "sent",
  "target": "slack"
}
```

### `GET /v1/channels/status`

Montre l'état de connexion de tous les canaux configurés.

#### La réponse

```json
{
  "channels": {
    "slack": "connected",
    "discord": "connected",
    "telegram": "disconnected"
  }
}
```

!!! note "Les routes de canaux"
    Les routes de canaux exigent `[channel] enabled = true` dans ta configuration, et les identifiants propres à chaque plateforme dans les sous-sections `[channel.<platform>]`. Sans configuration, `GET /v1/channels` rend une liste vide et les autres routes de canaux répondent 503.

## Le fil de l'eau par SSE

Quand la requête porte `"stream": true`, le serveur rend une réponse `text/event-stream` en Server-Sent Events (SSE). Le format suit celui de l'API de streaming d'OpenAI.

Chaque événement est une ligne `data:` contenant un fragment JSON, suivie d'une ligne vide :

```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1740100800,"model":"qwen3:8b","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1740100800,"model":"qwen3:8b","choices":[{"index":0,"delta":{"content":"La"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1740100800,"model":"qwen3:8b","choices":[{"index":0,"delta":{"content":" capitale"},"finish_reason":null}]}

...

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1740100800,"model":"qwen3:8b","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

Le flux suit toujours cet ordre :

1. **Le fragment de rôle** — le premier fragment porte `"delta": {"role": "assistant"}`, sans contenu.
2. **Les fragments de contenu** — chacun des fragments suivants porte un `"delta": {"content": "..."}` avec un ou plusieurs jetons.
3. **Le fragment de fin** — un fragment au `delta` vide, avec `"finish_reason": "stop"`.
4. **Le signal de clôture** — la chaîne littérale `data: [DONE]` dit que le flux est terminé.

Les en-têtes de réponse portent `Cache-Control: no-cache` et `Connection: keep-alive`, comme l'exige le SSE.

## Des exemples de clients

=== "curl"

    **Une requête hors fil de l'eau :**

    ```bash
    curl http://localhost:8000/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d '{
        "model": "qwen3:8b",
        "messages": [
          {"role": "user", "content": "Explique en un paragraphe ce que sont les ordinateurs quantiques."}
        ],
        "temperature": 0.7,
        "max_tokens": 256
      }'
    ```

    **Une requête au fil de l'eau :**

    ```bash
    curl http://localhost:8000/v1/chat/completions \
      -H "Content-Type: application/json" \
      -N \
      -d '{
        "model": "qwen3:8b",
        "messages": [
          {"role": "user", "content": "Écris un haïku sur la programmation."}
        ],
        "stream": true
      }'
    ```

    **Lister les modèles :**

    ```bash
    curl http://localhost:8000/v1/models
    ```

    **Vérifier la santé :**

    ```bash
    curl http://localhost:8000/health
    ```

=== "Python (openai)"

    La bibliothèque Python d'OpenAI sert de client direct : il suffit de pointer `base_url` sur le serveur local.

    ```python
    from openai import OpenAI

    client = OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="not-needed",  # Exigée par la bibliothèque, mais jamais vérifiée
    )

    # Hors fil de l'eau
    response = client.chat.completions.create(
        model="qwen3:8b",
        messages=[
            {"role": "user", "content": "Quelle est la capitale de la France ?"}
        ],
        temperature=0.7,
        max_tokens=256,
    )
    print(response.choices[0].message.content)

    # Au fil de l'eau
    stream = client.chat.completions.create(
        model="qwen3:8b",
        messages=[
            {"role": "user", "content": "Écris un court poème sur l'IA."}
        ],
        stream=True,
    )
    for chunk in stream:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print()

    # Lister les modèles
    models = client.models.list()
    for model in models.data:
        print(model.id)
    ```

=== "Python (httpx)"

    Avec `httpx`, pour des requêtes HTTP directes :

    ```python
    import httpx
    import json

    BASE_URL = "http://localhost:8000"

    # Une requête hors fil de l'eau
    response = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model": "qwen3:8b",
            "messages": [
                {"role": "user", "content": "Quelle est la capitale de la France ?"}
            ],
            "temperature": 0.7,
            "max_tokens": 256,
        },
    )
    data = response.json()
    print(data["choices"][0]["message"]["content"])

    # Une requête au fil de l'eau
    with httpx.stream(
        "POST",
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model": "qwen3:8b",
            "messages": [
                {"role": "user", "content": "Écris un haïku sur le code."}
            ],
            "stream": True,
        },
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                chunk = json.loads(line[6:])
                content = chunk["choices"][0]["delta"].get("content", "")
                if content:
                    print(content, end="", flush=True)
    print()

    # Lister les modèles
    response = httpx.get(f"{BASE_URL}/v1/models")
    for model in response.json()["data"]:
        print(model["id"])

    # Vérifier la santé
    response = httpx.get(f"{BASE_URL}/health")
    print(response.json())
    ```

## La configuration par `config.toml`

La section `[server]` de `~/.diapason/config.toml` commande le comportement par défaut du serveur :

```toml
[server]
host = "0.0.0.0"
port = 8000
agent = "orchestrator"
model = ""
workers = 1
```

| Clé       | Type      | Défaut          | Description                                                                |
|-----------|-----------|-----------------|----------------------------------------------------------------------------|
| `host`    | `string`  | `"0.0.0.0"`    | Adresse réseau sur laquelle écouter. Mets `"127.0.0.1"` pour n'accepter que les connexions locales. |
| `port`    | `integer` | `8000`          | Le port d'écoute.                                                          |
| `agent`   | `string`  | `"orchestrator"`| Agent par défaut pour les requêtes hors fil de l'eau. Mets `""` pour aller droit au moteur. |
| `model`   | `string`  | `""`            | Nom du modèle par défaut. À vide, on se rabat sur `[intelligence] default_model`, puis sur le premier modèle trouvé sur le moteur. |
| `workers` | `integer` | `1`             | Nombre de processus uvicorn (réservé pour plus tard).                      |

Les drapeaux de la ligne de commande l'emportent sur le fichier de configuration. Par exemple, `diapason serve --port 9000` passe outre le réglage `port` du fichier.

Au démarrage, le serveur lit aussi d'autres sections de la configuration :

- **`[engine]`** — dit à quel moteur d'inférence se connecter, et sur quelle URL.
- **`[intelligence]`** — fournit le `default_model` de repli quand aucun modèle n'est précisé.
- **`[agent]`** — fournit `max_turns` pour les agents à plusieurs tours, comme `orchestrator`.

## Derrière un proxy inverse

En production, fais tourner Diapason derrière un proxy inverse comme Nginx ou Caddy : terminaison TLS, limitation de débit et authentification.

### Nginx

```nginx
server {
    listen 443 ssl;
    server_name diapason.example.com;

    ssl_certificate /etc/ssl/certs/diapason.pem;
    ssl_certificate_key /etc/ssl/private/diapason.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Le fil de l'eau SSE
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

!!! important "Coupe la mise en tampon pour le SSE"
    La directive `proxy_buffering off` est décisive pour les réponses au fil de l'eau. Sans elle, Nginx met les fragments SSE en tampon et les livre par paquets — ce qui vide le fil de l'eau de tout son sens.

### Caddy

```
diapason.example.com {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
```

Le réglage `flush_interval -1` coupe la mise en tampon des réponses, ce qu'exige le fil de l'eau SSE.

### Se lier à localhost

Derrière un proxy inverse, lie le serveur à `127.0.0.1` pour qu'il n'accepte que les connexions du proxy :

```bash
diapason serve --host 127.0.0.1 --port 8000
```

Ou dans `config.toml` :

```toml
[server]
host = "127.0.0.1"
port = 8000
```
