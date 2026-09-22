# Service systemd (Linux)

Diapason est livré avec un fichier d'unité systemd qui fait tourner le serveur d'API comme un service d'arrière-plan géré, sous Linux. Tu y gagnes le démarrage automatique au boot, la reprise après plantage, et l'intégration aux outils habituels de gestion de services Linux.

## Ce qu'il faut avant

Avant d'installer le service, assure-toi que :

1. Diapason est installé dans un environnement virtuel à `/opt/diapason/.venv` (ou ajuste les chemins en conséquence).
2. Un utilisateur système dédié `diapason` existe (recommandé, pour la sécurité).
3. Un moteur d'inférence (Ollama, par exemple) tourne et est joignable.

Crée l'utilisateur et le répertoire d'installation :

```bash
sudo useradd --system --create-home --home-dir /opt/diapason diapason
sudo -u diapason python3 -m venv /opt/diapason/.venv
sudo -u diapason git clone https://github.com/carlitoetienne01-spec/Diapason.git /opt/diapason/Diapason
cd /opt/diapason/Diapason && sudo -u diapason uv sync --extra server
```

## Installer le service

L'unité écoute sur `0.0.0.0`, donc **une clé d'API est obligatoire** — et l'unité
déclare `EnvironmentFile=/etc/diapason/env` (sans préfixe `-`), elle **refusera
donc de démarrer** tant que ce fichier n'existe pas avec une clé dedans. Crée-le
d'abord :

```bash
sudo mkdir -p /etc/diapason
echo "DIAPASON_API_KEY=$(diapason auth generate-key)" | sudo tee /etc/diapason/env
sudo chmod 600 /etc/diapason/env
```

Copie ensuite le fichier d'unité, recharge le démon et active le service :

```bash
sudo cp deploy/systemd/diapason.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable diapason
sudo systemctl start diapason
```

Les clients doivent envoyer `Authorization: Bearer <key>` sur les requêtes
`/v1/*` et `/api/*`. (Si tu écoutes plutôt sur `127.0.0.1`, la clé est
facultative et tu peux retirer la ligne `EnvironmentFile`.)

Vérifie qu'il tourne :

```bash
sudo systemctl status diapason
```

## Référence du fichier de service

Le fichier d'unité fourni, à `deploy/systemd/diapason.service` :

```ini
[Unit]
Description=Diapason API Server
After=network.target

[Service]
Type=simple
User=diapason
WorkingDirectory=/opt/diapason
ExecStart=/opt/diapason/.venv/bin/diapason serve --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
Environment=HOME=/opt/diapason

[Install]
WantedBy=multi-user.target
```

### La section `[Unit]`

| Directive     | Valeur             | Description                                                                 |
|---------------|--------------------|-----------------------------------------------------------------------------|
| `Description` | `Diapason API Server` | Nom lisible, affiché dans `systemctl status` et dans les journaux.     |
| `After`       | `network.target`   | Retarde le démarrage jusqu'à ce que la pile réseau soit disponible, puisque le serveur écoute sur une socket réseau et peut avoir besoin de joindre un moteur distant. |

### La section `[Service]`

| Directive          | Valeur                                                             | Description                                                                                     |
|--------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| `Type`             | `simple`                                                           | Le processus lancé par `ExecStart` est le processus principal du service. systemd considère le service démarré immédiatement. |
| `User`             | `diapason`                                                       | Fait tourner le serveur sous l'utilisateur `diapason` plutôt que root, ce qui limite les dégâts en cas de faille. |
| `WorkingDirectory` | `/opt/diapason`                                                  | Fixe le répertoire de travail du processus. C'est là que Diapason cherche ses fichiers locaux et écrit ses données. |
| `ExecStart`        | `/opt/diapason/.venv/bin/diapason serve --host 0.0.0.0 --port 8000` | La commande qui démarre le serveur. Elle passe par le chemin complet du binaire `diapason` dans l'environnement virtuel. |
| `Restart`          | `on-failure`                                                       | Redémarre le service tout seul s'il sort avec un code de sortie non nul. Pas de redémarrage après un arrêt propre (`systemctl stop`). |
| `RestartSec`       | `5`                                                                | Attend 5 secondes avant de tenter un redémarrage, ce qui évite les boucles de redémarrage rapide quand le service plante dès le lancement. |
| `Environment`      | `HOME=/opt/diapason`                                             | Fixe la variable d'environnement `HOME` pour que Diapason trouve sa configuration à `~/.diapason/config.toml` (soit `/opt/diapason/.diapason/config.toml`). |

### La section `[Install]`

| Directive    | Valeur              | Description                                                                                 |
|--------------|---------------------|---------------------------------------------------------------------------------------------|
| `WantedBy`   | `multi-user.target` | Le service démarre quand le système atteint le mode multi-utilisateur (la cible de démarrage standard des serveurs). `systemctl enable` crée un lien symbolique sous cette cible. |

## Les options de configuration

### Changer l'adresse d'écoute et le port

Modifie la ligne `ExecStart` pour changer l'hôte ou le port :

```ini
ExecStart=/opt/diapason/.venv/bin/diapason serve --host 127.0.0.1 --port 9000
```

!!! tip
    Écouter sur `127.0.0.1` réserve l'accès à la machine locale. À utiliser derrière un proxy inverse comme Nginx ou Caddy.

### Fixer le moteur et le modèle

Passe des drapeaux supplémentaires à `diapason serve` :

```ini
ExecStart=/opt/diapason/.venv/bin/diapason serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b
```

### Ajouter des variables d'environnement

Ajoute plusieurs directives `Environment`, ou passe par `EnvironmentFile` pour les configurations compliquées :

```ini
[Service]
Environment=HOME=/opt/diapason
Environment=DIAPASON_ENGINE_DEFAULT=vllm
Environment=DIAPASON_OLLAMA_HOST=http://localhost:11434
```

Ou charge-les depuis un fichier :

```ini
[Service]
EnvironmentFile=/opt/diapason/.env
```

### Changer l'utilisateur

Si tu préfères un autre utilisateur de service, mets à jour la directive `User` et les chemins :

```ini
[Service]
User=myuser
WorkingDirectory=/home/myuser/diapason
ExecStart=/home/myuser/diapason/.venv/bin/diapason serve --host 0.0.0.0 --port 8000
Environment=HOME=/home/myuser/diapason
```

### Utiliser un fichier de configuration

Assure-toi que le fichier de configuration existe là où pointe `HOME` :

```bash
sudo -u diapason mkdir -p /opt/diapason/.diapason
sudo -u diapason cp config.toml /opt/diapason/.diapason/config.toml
```

Le serveur lit `~/.diapason/config.toml` au démarrage, où `~` se résout depuis la variable d'environnement `HOME`.

## Lire les journaux

Les journaux de Diapason sont récupérés par journald. Consulte-les avec `journalctl` :

```bash
# Voir tous les journaux du service
sudo journalctl -u diapason

# Suivre les journaux en direct
sudo journalctl -u diapason -f

# Voir les journaux depuis le dernier démarrage
sudo journalctl -u diapason -b

# Voir les journaux de la dernière heure
sudo journalctl -u diapason --since "1 hour ago"

# Ne voir que les messages de niveau erreur
sudo journalctl -u diapason -p err
```

## Gérer le service

### Démarrer, arrêter, redémarrer

```bash
# Démarrer le service
sudo systemctl start diapason

# Arrêter le service
sudo systemctl stop diapason

# Redémarrer le service (arrêt + démarrage)
sudo systemctl restart diapason

# Recharger la configuration sans redémarrage complet (envoie SIGHUP)
sudo systemctl reload-or-restart diapason
```

### Vérifier l'état

```bash
sudo systemctl status diapason
```

Exemple de sortie :

```
● diapason.service - Diapason API Server
     Loaded: loaded (/etc/systemd/system/diapason.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-02-21 10:00:00 UTC; 2h ago
   Main PID: 12345 (diapason)
      Tasks: 4 (limit: 4915)
     Memory: 256.0M
        CPU: 1min 23s
     CGroup: /system.slice/diapason.service
             └─12345 /opt/diapason/.venv/bin/python /opt/diapason/.venv/bin/diapason serve --host 0.0.0.0 --port 8000
```

### Activer et désactiver le démarrage au boot

```bash
# Activer le démarrage automatique au boot
sudo systemctl enable diapason

# Désactiver le démarrage automatique au boot
sudo systemctl disable diapason
```

### Appliquer les changements après modification du fichier d'unité

Après avoir modifié `/etc/systemd/system/diapason.service`, recharge le démon systemd et redémarre le service :

```bash
sudo systemctl daemon-reload
sudo systemctl restart diapason
```

## Tourner aux côtés d'Ollama

Si Ollama est lui aussi géré par systemd, tu peux ajouter une dépendance d'ordre pour que le service Diapason attende le démarrage d'Ollama :

```ini
[Unit]
Description=Diapason API Server
After=network.target ollama.service
Requires=ollama.service
```

| Directive  | Description                                                              |
|------------|--------------------------------------------------------------------------|
| `After`    | Garantit que Diapason démarre après Ollama.                            |
| `Requires` | Si Ollama ne démarre pas, Diapason ne démarrera pas non plus.          |

!!! note
    Utilise `Wants` plutôt que `Requires` si tu veux que Diapason démarre même quand Ollama n'est pas disponible (par exemple si tu comptes lancer Ollama à la main plus tard).
