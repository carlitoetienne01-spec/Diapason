# Se brancher à des serveurs MCP externes

Diapason sait étendre les capacités de ses agents en se connectant à des serveurs [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) externes. Tes agents utilisent alors les outils offerts par des services comme Home Assistant, des bases de données, des API maison ou n'importe quel serveur compatible MCP — sans que tu écrives une ligne de code d'outil.

## Comment ça marche

Au démarrage, Diapason lit la section `[tools.mcp]` de `config.toml`. Pour chaque serveur configuré, il :

1. Ouvre une connexion avec le transport qui convient (Streamable HTTP ou stdio).
2. Exécute la poignée de main MCP `initialize` (négociation de la version du protocole, puis notification `initialized`).
3. Découvre les outils disponibles avec `tools/list`.
4. Enveloppe chaque outil découvert dans un `BaseTool` standard, pour que les agents l'appellent comme n'importe quel outil intégré.

Si un serveur est injoignable ou renvoie une erreur, Diapason écrit un avertissement dans les journaux et continue de charger les autres. Un serveur cassé ne prive pas les autres outils d'exister.

## La configuration

Les serveurs MCP externes se configurent dans `config.toml`, sous `[tools.mcp]` :

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "homeassistant", "url": "http://172.16.3.1:9583/private_abc123"}]'
```

La valeur de `servers` est une **chaîne encodée en JSON** contenant un tableau d'objets serveur. Chaque objet décrit un serveur MCP externe.

!!! note
    La valeur doit être une chaîne JSON (entourée des guillemets simples de TOML), pas un tableau TOML natif. La raison : le système de configuration la transmet telle quelle, comme un champ texte unique.

## Le schéma d'un serveur

Chaque objet serveur accepte les champs suivants :

| Champ            | Type              | Requis | Description                                              |
|------------------|-------------------|--------|----------------------------------------------------------|
| `name`           | chaîne            | Non    | Nom lisible, utilisé dans les messages de journal. Vaut `<unnamed>` par défaut. |
| `url`            | chaîne            | Non*   | URL du transport Streamable HTTP.                        |
| `command`        | chaîne            | Non*   | Commande à lancer pour un serveur MCP en stdio.          |
| `args`           | liste de chaînes  | Non    | Arguments passés à la commande stdio.                    |
| `include_tools`  | liste de chaînes  | Non    | Liste blanche des noms d'outils à importer. Seuls ceux-là sont chargés. |
| `exclude_tools`  | liste de chaînes  | Non    | Liste noire des noms d'outils à écarter. Tous les autres sont chargés. |

*Il faut fournir `url` **ou** `command`. Si aucun des deux n'est présent, le serveur est ignoré avec un avertissement.

Quand `include_tools` et `exclude_tools` sont tous les deux donnés, la liste blanche s'applique d'abord, puis la liste noire filtre le résultat.

## Des exemples

### Home Assistant par Streamable HTTP

Se brancher au module complémentaire Home Assistant [ha-mcp](https://github.com/tevonsb/ha-mcp) :

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "homeassistant", "url": "http://172.16.3.1:9583/private_abc123"}]'
```

Tous les outils HA sont alors découverts (contrôle des entités, automatisations, historique, etc.) et mis à la disposition des agents.

### Un serveur stdio

Lancer un serveur MCP local comme sous-processus :

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "myserver", "command": "python", "args": ["-m", "my_mcp_server"]}]'
```

Diapason démarre le processus tout seul, dialogue avec lui en JSON-RPC sur stdin/stdout, et le termine à l'extinction.

### Plusieurs serveurs

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "homeassistant", "url": "http://172.16.3.1:9583/private_abc123"}, {"name": "database", "command": "db-mcp-server", "args": ["--db", "postgres://localhost/mydb"]}]'
```

### Filtrer les outils

Quand un serveur expose des dizaines d'outils et que tu n'en veux que quelques-uns, dresse une liste blanche avec `include_tools` :

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "ha", "url": "http://172.16.3.1:9583/private_abc123", "include_tools": ["hassTurnOn", "hassTurnOff", "hassGetState"]}]'
```

Pour tout charger sauf certains outils, passe par `exclude_tools` :

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "ha", "url": "http://172.16.3.1:9583/private_abc123", "exclude_tools": ["hassCreateBackup", "hassDeleteBackup"]}]'
```

## Les types de transport

### Streamable HTTP

Utilisé quand le champ `url` est rempli. Le transport envoie les requêtes JSON-RPC en HTTP POST vers l'URL donnée, avec `httpx`. Il suit l'en-tête `Mcp-Session-Id` d'une requête à l'autre, comme l'exige la spécification MCP Streamable HTTP.

**Quand s'en servir :** serveurs MCP distants, services exposés comme points d'accès HTTP (le module complémentaire MCP de Home Assistant, un serveur MCP hébergé dans le nuage, par exemple).

**Paramètres de connexion :**

- Délai de connexion : 10 secondes
- Délai de requête : 60 secondes

### Stdio

Utilisé quand le champ `command` est rempli. Diapason lance la commande comme sous-processus et dialogue avec elle en lignes JSON-RPC sur stdin/stdout.

**Quand s'en servir :** serveurs MCP locaux distribués comme outils en ligne de commande, développement et tests, serveurs qui ont besoin d'accéder aux fichiers de la même machine.

!!! info "L'alias SSETransport"
    `SSETransport` existe comme alias rétrocompatible de `StreamableHTTPTransport`. Les deux désignent la même implémentation.

## Le traitement des erreurs

Diapason encaisse les défaillances d'un serveur MCP sans broncher :

- **Serveur injoignable :** un avertissement est écrit dans les journaux et le serveur est ignoré. Tous les autres serveurs et les outils intégrés continuent de se charger normalement.
- **Délai dépassé :** les requêtes HTTP expirent au bout de 60 secondes. Le serveur est ignoré avec un avertissement.
- **Configuration invalide :** si le JSON de `servers` est mal formé, ou si une entrée n'a ni `url` ni `command`, un avertissement est écrit et l'entrée est ignorée.
- **Échec de la découverte d'outils :** si `tools/list` échoue sur un serveur, l'erreur est attrapée et le serveur est ignoré.
- **Échec d'un appel d'outil à l'exécution :** si un appel d'outil vers un serveur MCP externe échoue à l'exécution, il rend un `ToolResult` avec `success=False` et le message d'erreur.

La défaillance d'un serveur, quelle qu'elle soit, ne fait jamais planter Diapason et n'empêche pas les autres outils de fonctionner.

## En cas de problème

### Le serveur n'est pas découvert

1. Vérifie que `[tools.mcp]` porte bien `enabled = true`.
2. Vérifie que le JSON de `servers` est valide. L'erreur classique : écrire un tableau TOML au lieu d'une chaîne JSON.
3. Cherche dans les journaux de Diapason les avertissements du genre `Failed to discover external MCP tools`.

### Connexion refusée ou délai dépassé

1. Vérifie que le serveur tourne et qu'il est joignable depuis la machine qui fait tourner Diapason : `curl -v http://host:port/`.
2. Vérifie les règles de pare-feu entre le conteneur Diapason et le serveur MCP.
3. Avec Docker, assure-toi que les deux conteneurs sont sur le même réseau, ou utilise les adresses IP de l'hôte.

### Les outils n'apparaissent pas

1. Relance avec les journaux en mode débogage pour voir quels outils ont été découverts.
2. Regarde si les filtres `include_tools` ou `exclude_tools` ne sont pas trop serrés.
3. Vérifie que le serveur MCP expose réellement des outils par `tools/list` (certains n'exposent que des ressources ou des prompts).

### Le serveur stdio plante aussitôt

1. Teste la commande à la main : `python -m my_mcp_server` doit démarrer et attendre une entrée sur stdin.
2. Regarde la sortie d'erreur du sous-processus dans les journaux de Diapason.
3. Assure-toi que toutes les dépendances du serveur MCP sont installées dans le même environnement.
