# Service launchd (macOS)

Diapason fournit un LaunchAgent pour faire tourner le serveur d'API en tâche
de fond sur macOS : démarrage à l'ouverture de session, redémarrage
automatique, journaux capturés.

Depuis le 26 août 2026, ce service peut ouvrir **deux sockets dans un seul
processus**, et la différence entre les deux est tout ce que cette page a
d'important à dire.

!!! danger "Ce qui a changé, et pourquoi"
    Jusqu'au 26 août 2026, la façon documentée d'être joignable depuis un
    téléphone était `--host 0.0.0.0` (ou `--allow-network`). Cela mettait
    **l'application complète** — deux cent dix routes — sur le Wi-Fi. Elles
    restaient protégées dans l'ensemble (401 sans la clé, 403 sans signature)
    — à une fuite près : jusqu'au 26 août 2026, un POST au corps vide sur
    `/v1/mesh/commands/deliver`, sans la moindre créance, rendait
    l'identifiant permanent de la machine, un refus qui se présentait au lieu
    de faire écho (`src/diapason/mesh/dispatch.py`). Mais elles étaient
    surtout **joignables** : une seule route qui aurait oublié sa protection
    aurait été exposée le jour même.

    `--allow-network` **n'existe plus** : la commande échoue en nommant son
    remplaçant. Un `--host` non-loopback est **refusé** par
    `serve-service install`. Le besoin réel — « un téléphone ne peut pas
    joindre 127.0.0.1 » — a maintenant sa propre porte, plus étroite :
    `--maillage-reseau`.

## Le modèle à deux sockets

Un seul processus, deux applications FastAPI distinctes, deux sockets
(`src/diapason/cli/serve.py`, fonction `_servir_deux_sockets`).

|                        | `--host` / `--port`                                   | `--lan-host` / `--lan-port`                                   |
|------------------------|-------------------------------------------------------|---------------------------------------------------------------|
| Ce qui est monté       | l'application **complète** : chat, voix, Succès, outils, interface | **neuf routes** du maillage, pas une de plus            |
| Valeur par défaut      | `127.0.0.1` et `8000` (config `server.host` / `server.port`) | `--lan-host` : aucune — sans elle, **ce socket n'existe pas**. `--lan-port` : `8001`   |
| Doit rester            | sur la loopback, toujours                             | `0.0.0.0` si vos autres appareils doivent l'atteindre          |
| Créance exigée         | la clé d'API locale                                   | signature Ed25519 d'appareil, invitation à usage unique, ou jeton de session |
| Documentation exposée  | `/docs`, `/openapi.json`                              | aucune : `docs_url`, `redoc_url` et `openapi_url` sont `None`  |

La garantie est **structurelle, pas déclarative**. `create_lan_app()`
(`src/diapason/server/app.py`) monte les deux routeurs du maillage puis retire
toute route absente de `_PORTES_LAN`. Conséquence directe et vérifiable :

```bash
# Sur le second socket, le chat n'est pas refusé — il n'existe pas.
curl -i -X POST http://127.0.0.1:8001/v1/chat/completions
# HTTP/1.1 404 Not Found      ← et non 401, et non 403
```

Aucune liste de chemins ne peut se désynchroniser d'un handler qui n'est pas
monté.

Quand le second socket existe, c'est **lui** que le maillage annonce à vos
appareils appairés : `serve` enregistre `lan_host:lan_port` comme adresse
locale (`set_local_endpoint`, `src/diapason/cli/serve.py`). Annoncer le
premier socket reviendrait à donner à toute la flotte une adresse où elle ne
trouverait jamais rien. Au démarrage, le serveur affiche la ligne
« Maillage : http://… — neuf routes, signature d'appareil exigée ».

!!! warning "Un seul processus, impérativement"
    Les deux sockets doivent vivre dans le **même processus**. La boîte de
    réception des commandes (`src/diapason/mesh/executor.py`) et les sessions
    de transfert (`src/diapason/mesh/files_routes.py`) tiennent dans des
    globales en mémoire : avec deux processus, une commande reçue sur le
    réseau n'apparaîtrait jamais dans l'inbox lue en loopback, et un morceau
    de fichier rendrait 404 parce que son offre a ouvert la session ailleurs.
    N'installez donc pas deux services, un par socket.

## Prérequis

Diapason installé, avec les dépendances serveur :

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason && uv sync --extra server
which diapason
```

Un moteur d'inférence (Ollama, par exemple) doit tourner et être joignable.

## Installer le service

### Usage local (le défaut, et le bon défaut)

```bash
diapason serve-service install
```

Le LaunchAgent écrit par cette commande n'ouvre **aucun** socket réseau :
l'application complète écoute sur `127.0.0.1:8000` et n'en sort pas. Vous
n'avez aucune clé à fournir : le serveur en crée une au démarrage sous
`~/.diapason/auth/local_api_key` si vous n'en avez pas configuré, et les
routes `/v1/*` restent protégées par elle même en loopback (`/health` et
l'interface restent ouverts).

### Quand un autre appareil doit joindre ce Mac

```bash
diapason serve-service install --maillage-reseau
# ou, pour choisir le port du maillage :
diapason serve-service install --maillage-reseau --lan-port 8123
```

Ce que cette option fait exactement (`src/diapason/cli/serve_service_cmd.py`) :

- l'application complète **reste** sur `127.0.0.1:8000` ;
- un **second** socket s'ouvre sur `0.0.0.0:8001` (défaut de `--lan-port`) et
  ne porte que les neuf routes du maillage ;
- la commande affiche un avertissement explicite : « toute machine de votre
  réseau local pourra l'atteindre » ;
- `--lan-port` égal à `--port` est **refusé** (macOS lie les deux en silence
  via `SO_REUSEADDR`, Linux échoue) ; `diapason serve` applique le même refus.

### Ce que la commande refuse désormais

```bash
$ diapason serve-service install --host 0.0.0.0
Refusing to bind '0.0.0.0' from a background service: it would expose the API
beyond this machine.
  • Pour un usage local : gardez 127.0.0.1.
  • Pour que vos autres appareils atteignent ce Mac : gardez 127.0.0.1 ET
    ajoutez --maillage-reseau.
```

```bash
$ diapason serve-service install --allow-network
--allow-network n'existe plus : elle exposait l'API ENTIÈRE au réseau […]
  • Pour que vos autres appareils atteignent ce Mac : --maillage-reseau,
    qui n'expose que les neuf routes du maillage, signature d'appareil exigée.
  • L'application complète reste sur 127.0.0.1, toujours.
```

Les deux sortent en code 1 sans rien installer. `--allow-network` échoue au
lieu d'être un alias silencieux de `--maillage-reseau` : la même commande ne
doit pas se mettre à faire autre chose sans le dire.

!!! note "Installer, c'est lancer"
    Le plist porte `RunAtLoad`, donc l'installation démarre le service. Si le
    port `--port` est déjà servi par un processus qui n'est pas ce
    LaunchAgent, l'installation est **refusée** plutôt que de créer deux
    serveurs sur le même port. Réinstaller par-dessus son propre service
    reste permis : launchd remplace un job de même étiquette, il n'en empile
    pas un second, et la commande annonce
    « ↻ Remplacement du service existant (PID …) ».

## Ce que le maillage expose — et ce qu'il n'expose pas

Les neuf routes, telles qu'elles sont listées dans `_PORTES_LAN`
(`src/diapason/server/app.py`), avec la créance que chacune vérifie :

| Route                                    | Ce qu'elle prouve                                                        |
|------------------------------------------|--------------------------------------------------------------------------|
| `POST /v1/mesh/pairings/redeem`          | invitation à usage unique, valable **dix minutes** (`PAIRING_TTL_MS`)     |
| `POST /v1/mesh/commands/deliver`         | signature Ed25519 de l'enveloppe, liée aux arguments exacts ; nonce à usage unique |
| `POST /v1/mesh/commands/poll`            | signature Ed25519 de l'appareil (sept contrôles, dont la révocation)      |
| `POST /v1/mesh/commands/ack`             | signature Ed25519 de l'appareil                                           |
| `POST /v1/mesh/presence`                 | signature Ed25519 de la balise, horodatage à ±30 s                        |
| `POST /v1/mesh/files/offer`              | signature Ed25519 sur le manifeste et la clé éphémère                     |
| `POST /v1/mesh/files/{session_id}/chunk`         | jeton de session (`X-Transfer-Token`), comparé à temps constant           |
| `POST /v1/mesh/files/{session_id}/finish`        | jeton de session                                                          |
| `POST /v1/mesh/files/{session_id}/status`        | jeton de session                                                          |

Pas de clé d'API sur ce socket, et c'est délibéré : une clé partagée
prouverait **moins** — elle ne dit ni quel appareil parle, ni ce qu'il
prétend. Une clé publique d'appareil est enregistrée au jumelage ; la révoquer
coupe tout immédiatement, au même point de passage.

Ce qui **n'est pas** sur ce socket, et rend donc 404 :

- le chat, les modèles, la voix, les gestes, Succès (`/v1/chat/completions`,
  `/v1/models`, `/v1/voice/live`, `/v1/gestures/frame`, `/v1/succes/tasks`…) ;
- le **plan de contrôle** du maillage lui-même : émettre une invitation
  (`POST /v1/mesh/pairings`), envoyer une commande (`POST /v1/mesh/commands`),
  lister ou révoquer un appareil (`/v1/mesh/devices…`). Ce sont les gestes de
  ce poste, pas ceux d'un pair : ils restent derrière la loopback et la clé.

Le limiteur de débit (`RateLimitMiddleware`) est monté **avec** ces routes :
hors du mur d'authentification ne veut pas dire hors du limiteur.

## Ce que cela coûte

Ouvrir le second socket n'est pas gratuit, et la page ne serait pas honnête
si elle s'arrêtait aux garanties.

!!! warning "Le plan de commandes est SIGNÉ, pas CHIFFRÉ"
    Les enveloppes du maillage voyagent en **HTTP clair** sur le réseau local
    (`http://…`, voir `src/diapason/mesh/transport.py` et
    `src/diapason/mesh/beacon.py` — aucun TLS nulle part). La signature
    Ed25519 garantit *qui parle* et *que rien n'a été modifié*. Elle ne cache
    rien.

    Voyagent donc **en clair**, lisibles par qui écoute le même réseau :

    - le **titre et le corps** d'une notification envoyée à un autre appareil
      (`notifications.show`, arguments `title` / `body`) ;
    - la **cible** de `desktop.open` : l'application, l'URL, le fichier ou la
      recherche que vous demandez d'ouvrir à distance ;
    - le **nom du fichier**, sa taille, son type MIME et son **sha256** dans
      le manifeste de `files/offer` — ainsi que le **chemin de destination**
      complet rendu par `files/{session_id}/finish` ;
    - les identifiants d'appareil et de propriétaire, l'adresse annoncée,
      l'état de l'application et les capacités déclarées, dans chaque balise
      de présence ;
    - le **jeton d'invitation** pendant le jumelage, et le **jeton de
      session** rendu par `files/offer`.

!!! success "Le contenu des fichiers, lui, est chiffré de bout en bout"
    `src/diapason/mesh/coffre.py` : une paire **X25519 éphémère par session**,
    signée par la clé Ed25519 de l'appareil ; clé de session dérivée par
    **HKDF-SHA256** avec l'identifiant de session en sel ; chaque morceau
    scellé en **AES-256-GCM**, nonce dérivé du compteur, index du morceau
    authentifié — réordonner les morceaux invalide le déchiffrement. La paire
    éphémère meurt avec la session : une clé d'appareil volée demain ne
    déchiffre pas un transfert d'aujourd'hui. Si `cryptography` manque, le
    transfert **refuse de partir en clair**. Les fichiers reçus atterrissent
    dans `~/.diapason/transfers`, en droits `0600` (`src/diapason/mesh/transfert.py`, `src/diapason/mesh/files_routes.py`) — un fichier venu du
    réseau ne s'exécute pas — et ne deviennent visibles qu'après
    recalcul du sha256 sur ce qui est réellement sur le disque.

Autrement dit : sur un réseau que vous ne contrôlez pas — café, hôtel, bureau
partagé — n'ouvrez pas le second socket. Ce que vos appareils s'envoient y
resterait confidentiel quant au *contenu des fichiers*, mais pas quant à ce
que vous faites.

Deux garde-fous existants s'appliquent encore à ce qui **sort** de la machine
(`src/diapason/mesh/transport.py`) : en mode `local_only`, seul un appareil
`TRUSTED` joignable à une **adresse privée** peut être commandé ; et
`desktop.open` — le seul verbe qui pilote le bureau plutôt que Succès — exige
que l'émetteur atteste l'accord de l'utilisateur, faute de quoi le récepteur
refuse l'enveloppe.

## Revenir en arrière

Refermer le socket réseau, sans rien perdre d'autre :

```bash
diapason serve-service install     # sans --maillage-reseau : le plist est réécrit
```

Le LaunchAgent est remplacé (même étiquette) et ne porte plus
`--lan-host` / `--lan-port`. Vérifiez :

```bash
grep -A 12 ProgramArguments ~/Library/LaunchAgents/com.diapason.serve.plist
lsof -nP -iTCP:8001 -sTCP:LISTEN    # plus personne n'écoute sur le port du maillage
```

Tout arrêter :

```bash
diapason serve-service uninstall   # bootout + suppression du plist
```

Retirer un appareil plutôt que le socket : après révocation, le registre ne
rend plus sa clé publique (`public_key_of` répond `None` pour un appareil qui
n'est pas `TRUSTED`), donc le même point de passage refuse aussitôt ses
commandes, ses balises, ses relèves et ses offres de fichier.

```bash
CLE=$(cat ~/.diapason/auth/local_api_key)
curl -X POST -H "Authorization: Bearer $CLE" \
  http://127.0.0.1:8000/v1/mesh/devices/<deviceId>/revoke
```

La révocation est **terminale** : le seul retour en arrière est de supprimer
l'appareil (`DELETE /v1/mesh/devices/<deviceId>`) et de le rejumeler.

(Cette route est sur l'application complète, en loopback : elle n'est pas
joignable depuis le réseau.)

## Vérifier

```bash
diapason serve-service status
```

affiche si le LaunchAgent est chargé, le chemin du plist, si `/health`
répond — « chargé » n'est pas « répond » — et où sont les journaux. À la main :

```bash
launchctl list | grep diapason        # PID, dernier code de sortie, étiquette
curl http://127.0.0.1:8000/health     # l'application complète

# Le maillage : une enveloppe vide est REFUSÉE (403), pas introuvable (404).
curl -i -X POST -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:8001/v1/mesh/presence
```

Un `403` signifie que le socket du maillage est ouvert et qu'il exige une
signature d'appareil. Un `404`, ou une connexion refusée, signifie qu'il n'est
pas ouvert.

## Gérer le service

```bash
diapason serve-service restart        # launchctl kickstart -k
diapason serve-service logs           # la fin des deux journaux (40 lignes)
diapason serve-service logs --lines 200
diapason serve-service uninstall
```

Les équivalents `launchctl`, pour le plist installé par la CLI :

```bash
launchctl bootout   gui/$(id -u)/com.diapason.serve
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.diapason.serve.plist
launchctl kickstart -k gui/$(id -u)/com.diapason.serve
```

## Journaux

Le service installé par la CLI écrit dans `~/.diapason/logs/` (la racine suit
`DIAPASON_HOME`, puis `XDG_DATA_HOME/diapason`, puis `~/.diapason`) :

```bash
tail -f ~/.diapason/logs/serve.out.log ~/.diapason/logs/serve.err.log
```

Ces deux fichiers sont **tronqués à chaque installation** : un mur de lignes
d'une tentative précédente rend l'état courant illisible.

Le plist livré dans le dépôt, lui, écrit dans `/tmp/diapason.stdout.log` et
`/tmp/diapason.stderr.log` — que macOS peut vider au redémarrage.

## Le plist livré dans le dépôt

`deploy/launchd/com.diapason.serve.plist` est un exemple lisible ; ce n'est
pas lui que `serve-service install` pose. Il **n'ouvre aucun socket réseau** :

```xml
<key>ProgramArguments</key>
<array>
    <string>/usr/local/bin/diapason</string>
    <string>serve</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8000</string>
</array>
```

Pour l'ouvrir à la main, **ajoutez quatre entrées** à ce tableau : le nom
d'option `lan-host` précédé de deux tirets, puis `0.0.0.0`, puis le nom
d'option `lan-port` précédé de deux tirets, puis `8001`.

!!! note "Pourquoi ces quatre lignes ne sont pas livrées commentées"
    Un commentaire XML ne peut pas contenir deux tirets consécutifs. Les
    quatre entrées ne **peuvent donc pas** être livrées en commentaire prêt à
    décommenter : elles s'ajoutent, ou elles n'existent pas. C'est aussi la
    raison pour laquelle le plist les décrit en toutes lettres.

!!! danger "Ne mettez jamais 0.0.0.0 sur `--host`"
    C'est exactement l'erreur qui a servi les deux cent dix routes sur le
    Wi-Fi. `--host` porte l'application complète ; `--lan-host` porte les neuf
    routes. Les deux options ne sont pas interchangeables, et l'une n'est pas
    une version « plus permissive » de l'autre.

### Le plist écrit par la CLI diffère

`diapason serve-service install` génère son propre plist
(`src/diapason/desktop/launch_agent.py`) contre l'interpréteur réellement en
cours d'exécution. Les différences qui comptent :

| Clé                 | Plist du dépôt                        | Plist écrit par la CLI                                   |
|---------------------|---------------------------------------|-----------------------------------------------------------|
| Programme           | `/usr/local/bin/diapason serve`       | `<python courant> -m diapason.cli serve`                  |
| `KeepAlive`         | `true` (relance toujours)             | `{ SuccessfulExit: false }` — relance **au plantage seulement** |
| `ThrottleInterval`  | absent                                | `10`                                                       |
| `ProcessType`       | absent                                | `Interactive`                                              |
| `WorkingDirectory`  | absent                                | le dossier personnel (le projet peut être sous un dossier protégé par TCC) |
| Journaux            | `/tmp/diapason.*.log`                 | `~/.diapason/logs/serve.{out,err}.log`                    |

!!! warning "Une étiquette, un serveur"
    Les deux chemins utilisent la même étiquette, `com.diapason.serve`, et
    c'est ce qui les empêche de s'empiler : launchd remplace un job dont il
    détient déjà l'étiquette. Un plist portant une **autre** étiquette ferait
    tourner un *second* serveur à côté du premier, en silence — la CLI ne le
    verrait jamais, et les deux se disputeraient le port 8000 sans qu'aucun ne
    signale d'erreur.

## Modifier la configuration

### Changer le port

```bash
diapason serve-service install --port 9000
```

Ou, dans un plist tenu à la main, chaque argument dans son propre `<string>` :

```xml
<key>ProgramArguments</key>
<array>
    <string>/usr/local/bin/diapason</string>
    <string>serve</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>9000</string>
</array>
```

### Choisir un moteur et un modèle

```xml
<key>ProgramArguments</key>
<array>
    <string>/usr/local/bin/diapason</string>
    <string>serve</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8000</string>
    <string>--engine</string>
    <string>ollama</string>
    <string>--model</string>
    <string>qwen3:8b</string>
</array>
```

### Variables d'environnement

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>DIAPASON_HOME</key>
    <string>/Users/vous/.diapason</string>
    <key>OLLAMA_HOST</key>
    <string>http://localhost:11434</string>
</dict>
```

Les variables du projet se lisent sous le préfixe `DIAPASON_`
(`src/diapason/core/env.py`) — par exemple `DIAPASON_HOME`,
`DIAPASON_CONFIG`, `DIAPASON_API_KEY`. Les préfixes d'avant le changement de
nom continuent d'être lus, en second : voir
[Migration vers Diapason](../getting-started/migration-to-diapason.md), la
seule page où ces anciens noms s'écrivent — `scripts/check_project_identity.py`
fait rougir la CI partout ailleurs, pour qu'ils ne se réinstallent pas dans la
documentation courante. `OLLAMA_HOST`, en revanche, est lu **sans** préfixe,
sous son propre nom (`src/diapason/server/cloud_router.py`,
`src/diapason/cli/model.py`).

!!! tip "Pas besoin de poser une clé pour un serveur loopback"
    `DIAPASON_API_KEY` n'est **pas** nécessaire ici : au démarrage, une clé
    locale est créée si besoin sous `~/.diapason/auth/local_api_key`, dans un
    dossier en droits propriétaire seul. Une clé fournie doit faire au moins
    32 octets — `diapason auth generate-key` en produit une. Elle protège
    l'application complète ; elle ne joue **aucun** rôle sur le socket du
    maillage, qui exige une signature d'appareil.

### Un autre chemin pour `diapason`

```xml
<key>ProgramArguments</key>
<array>
    <string>/Users/vous/.local/bin/diapason</string>
    <string>serve</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8000</string>
</array>
```

### Appliquer un changement

```bash
launchctl bootout   gui/$(id -u)/com.diapason.serve
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.diapason.serve.plist
```

## Installation à l'échelle du système

Les instructions ci-dessus posent un **agent utilisateur** (il ne tourne que
lorsque vous êtes connecté). Pour un démon qui démarre au boot :

```bash
sudo cp deploy/launchd/com.diapason.serve.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.diapason.serve.plist
sudo launchctl load /Library/LaunchDaemons/com.diapason.serve.plist
```

!!! note
    Un démon de `/Library/LaunchDaemons/` tourne en root par défaut. Ajoutez
    une clé `UserName` pour le faire tourner sous un compte moins privilégié :

    ```xml
    <key>UserName</key>
    <string>diapason</string>
    ```

    `--host` reste `127.0.0.1` ici aussi : un démon système n'est pas une
    raison d'exposer l'application complète.

## Voir aussi

- [Architecture du maillage d'appareils](../architecture/device-mesh.md)
- `diapason mesh join`, `diapason mesh devices`, `diapason mesh send`
  (`src/diapason/cli/mesh_cmd.py`) — jumeler un appareil, lister la flotte,
  envoyer un fichier chiffré à un pair.
