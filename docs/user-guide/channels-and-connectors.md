# Canaux et connecteurs

Diapason a deux types d'intégrations :

- **Les connecteurs de données** — un accès en lecture seule à tes données personnelles (Gmail, iMessage, Google Drive, etc.) pour que ton agent puisse y chercher et y enquêter
- **Les canaux de messagerie** — des façons de parler À ton agent depuis ton téléphone ou d'autres plateformes (iMessage/SMS, Slack)

---

# Les canaux de messagerie

## iMessage et SMS (par SendBlue)

**Ce que ça fait :** ça donne un numéro de téléphone à ton agent. Écris-lui depuis n'importe quel téléphone (iMessage sur iPhone, SMS sur Android) et il te répond.

### La mise en place

1. **Crée un compte SendBlue :** [sendblue.com](https://www.sendblue.com/) — il existe une offre gratuite
2. **Récupère tes identifiants d'API :** tableau de bord → API Keys → copie l'**API Key ID** et l'**API Secret Key**
3. **Note ton numéro de téléphone SendBlue** — c'est le numéro auquel on écrit pour joindre ton agent
4. **Branche-le dans Diapason :**
   - Bureau/navigateur : Agents → ton agent → onglet **Canaux de messagerie** → iMessage/SMS → saisis l'API Key ID, l'API Secret Key et le numéro de téléphone
   - L'agent envoie un accusé de réception puis un message de test pour vérifier que ça marche
5. **Installe le webhook** pour que les textos entrants arrivent jusqu'à ton agent :
   - Il te faut une URL publique — sers-toi de [ngrok](https://ngrok.com/) pour percer un tunnel vers ton serveur local : `ngrok http 9001`
   - Enregistre l'URL du webhook auprès de SendBlue :
   ```bash
   curl -X PUT https://api.sendblue.co/api/account/webhooks \
     -H "sb-api-key-id: YOUR_KEY" \
     -H "sb-api-secret-key: YOUR_SECRET" \
     -H "Content-Type: application/json" \
     -d '{"webhooks": {"receive": ["https://YOUR-NGROK-URL.ngrok-free.dev/webhooks/sendblue"]}}'
   ```

### Comment ça marche

- Quelqu'un écrit à ton numéro SendBlue → SendBlue envoie un webhook à ton serveur
- L'agent répond aussitôt « Message received! Working on it now... »
- L'agent fouille tes données (15 à 60 s) → il envoie la réponse en iMessage ou en SMS
- iMessage (bulles bleues) pour les appareils Apple, SMS (vertes) pour Android — automatiquement

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| Aucune réponse après un texto | Vérifie que ngrok tourne et que l'URL du webhook est bien enregistrée |
| « Disconnected » dans l'onglet Canaux de messagerie | Clique sur Reconnecter — le serveur a peut-être redémarré |
| L'URL ngrok a changé | Réenregistre l'URL du webhook auprès de SendBlue (voir l'étape 5) |
| Les messages ne passent que dans un sens | L'offre gratuite exige que le contact écrive au numéro en premier |

---

## Slack

**Ce que ça fait :** tu écris à ton agent en MP dans Slack et tu reçois ses réponses d'enquête dans le fil.

### La mise en place

Le plus rapide est de passer par le manifeste d'app — colle ce JSON et tout est configuré d'un coup :

1. Va sur [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From an app manifest**
2. Sélectionne ton espace de travail, puis colle ce manifeste :

```json
{
    "display_information": { "name": "Diapason" },
    "features": {
        "app_home": {
            "home_tab_enabled": true,
            "messages_tab_enabled": true,
            "messages_tab_read_only_enabled": false
        },
        "bot_user": { "display_name": "Diapason", "always_online": true }
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "chat:write", "im:write", "im:read", "im:history",
                "users:read", "channels:read", "channels:history",
                "app_mentions:read"
            ]
        }
    },
    "settings": {
        "event_subscriptions": { "bot_events": ["message.im"] },
        "socket_mode_enabled": true
    }
}
```

3. Clique sur **Create** → **Install to Workspace** → **Allow**
4. Copie le **Bot User OAuth Token** (`xoxb-...`) depuis **OAuth & Permissions**
5. Va dans **Basic Information** → **App-Level Tokens** → **Generate Token** → ajoute la portée `connections:write` → copie le jeton (`xapp-...`)
6. **Branche-le dans Diapason :**
   - Bureau/navigateur : Agents → ton agent → onglet **Canaux de messagerie** → Slack → colle les deux jetons
   - CLI : les jetons sont enregistrés au moment où tu relies le canal

### Comment ça marche

- Tu écris à @Diapason en MP dans Slack → le mode Socket reçoit l'événement en direct
- L'agent répond « Message received! Working on it now... » dans un **fil** sous ton message
- L'agent enquête (15 à 60 s) → la réponse apparaît dans le même fil
- Si le traitement dépasse 60 s : « Still working! Will reply ASAP » dans le fil
- Toutes les réponses utilisent la mise en forme Slack (*gras*, _italique_, `code`, listes)

### À ne pas oublier

- **Réinstalle après chaque changement :** chaque fois que tu ajoutes une portée ou un événement, réinstalle l'app
- **Jeton d'app et jeton de bot :** le jeton de bot (`xoxb-`) sert aux appels d'API, le jeton d'app (`xapp-`) au mode Socket. Il te faut les deux.
- **N'utilise pas l'interface Event Subscriptions pour la Request URL :** avec le mode Socket, elle ne sert à rien. Passe par le manifeste d'app ci-dessus.

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| « Sending messages to this app has been turned off » | App Home → active Messages Tab → « Allow users to send messages » |
| Le bot ne répond pas | Vérifie que le mode Socket est activé, que l'événement `message.im` est souscrit et que l'app a été réinstallée |
| Erreur « missing_scope » | Ajoute la portée → réinstalle l'app |
| Le bot est invisible dans Slack | Clique sur le « + » à côté de Direct Messages → cherche « Diapason » |
| Event Subscriptions refuse d'enregistrer | Passe par le manifeste d'app (ça évite l'exigence de Request URL) |

---

# Les connecteurs de données

## Gmail

**Ce qu'il indexe :** les courriels et les fils de discussion de ta boîte Gmail.

### La mise en place (mot de passe d'application — recommandé)

1. **Active la double authentification** sur ton compte Google :
   [Ouvrir les réglages de sécurité Google →](https://myaccount.google.com/signinoptions/two-step-verification)

2. **Génère un mot de passe d'application** pour « Mail » :
   [Ouvrir les mots de passe d'application →](https://myaccount.google.com/apppasswords)
   - Choisis « Mail » comme application
   - Copie le mot de passe de 16 caractères (`qpde kebj evhy zljc`, par exemple)

3. **Branche-le dans Diapason :**
   - Bureau/navigateur : Agents → ton agent → onglet Canaux → Gmail → Reconnecter
   - CLI : `uv run diapason connect gmail_imap`
   - Saisis ton adresse courriel et le mot de passe d'application

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| La page « App Passwords » n'est pas accessible | Active d'abord la double authentification |
| La connexion échoue | Assure-toi d'utiliser le mot de passe d'application, et non ton mot de passe Google habituel |
| Aucun courriel ne se synchronise | Vérifie qu'IMAP est activé : [Réglages Gmail → Transfert et POP/IMAP](https://mail.google.com/mail/u/0/#settings/fwdandpop) |
| Seuls les courriels récents arrivent | Par défaut, les 500 derniers courriels sont synchronisés. Augmente ce nombre avec le réglage `max_messages` |

---

## Google Drive

**Ce qu'il indexe :** les documents, les feuilles de calcul, les PDF et les autres fichiers de ton Drive.

### La mise en place

1. **Va sur la Google Cloud Console** et crée un projet (ou reprends-en un existant) :
   [Créer un projet →](https://console.cloud.google.com/projectcreate)

2. **Active l'API Google Drive :**
   [Activer l'API Drive →](https://console.cloud.google.com/apis/library/drive.googleapis.com)

3. **Crée des identifiants OAuth :**
   [Ouvrir Credentials →](https://console.cloud.google.com/apis/credentials)
   - Clique sur « Create Credentials » → « OAuth 2.0 Client ID »
   - Choisis « Desktop app » comme type d'application
   - Copie le **Client ID** et le **Client Secret**

4. **Ajoute-toi comme utilisateur de test** (obligatoire tant que l'app n'est pas vérifiée) :
   [Ouvrir OAuth Consent Screen →](https://console.cloud.google.com/apis/credentials/consent)
   - Descends jusqu'à « Test users » → clique sur « + Add Users »
   - Ajoute ton adresse Gmail (`toi@gmail.com`, par exemple)

5. **Ajoute l'URI de redirection :**
   [Ouvrir Credentials →](https://console.cloud.google.com/apis/credentials)
   - Clique sur ton client OAuth → Authorized redirect URIs
   - Ajoute : `http://localhost:8789/callback`

6. **Branche-le dans Diapason :**
   - Bureau/navigateur : Agents → onglet Canaux → Google Drive → colle le Client ID et le Client Secret
   - Ton navigateur ouvre la page de consentement de Google → accorde l'accès en lecture seule
   - Tu vois « Authorization successful! » → les données du Drive commencent à se synchroniser

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| « Access blocked: app has not completed verification » | Ajoute ton adresse comme utilisateur de test (étape 4 ci-dessus) |
| « Error 400: redirect_uri_mismatch » | Ajoute `http://localhost:8789/callback` aux URI de redirection autorisées (étape 5) |
| « Error 403: access_denied » | Assure-toi d'avoir choisi « Desktop app » à la création du client OAuth |
| Connecté mais 0 fichier | Vérifie que tu as bien accordé l'accès en lecture au Drive sur l'écran de consentement. Essaie de te reconnecter. |
| Jeton expiré | Les jetons d'accès expirent au bout d'une heure. Reconnecte-toi pour en obtenir un nouveau. (Le rafraîchissement automatique arrive bientôt.) |

---

## Google Agenda

**Ce qu'il indexe :** les événements, les réunions et les entrées d'agenda.

### La mise en place

Comme pour Google Drive — reprends le même projet Google Cloud et le même client OAuth.

1. **Active l'API Google Calendar :**
   [Activer l'API Calendar →](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com)

2. Suis les étapes 3 à 6 de la section Google Drive ci-dessus (le même Client ID / Client Secret fait l'affaire)

### Quand ça coince

Comme pour Google Drive. Et en plus :

| Le pépin | Que faire |
|-------|----------|
| Seul l'agenda principal apparaît | Le connecteur lit tous les agendas auxquels tu as accès |
| Les agendas partagés manquent | Les agendas partagés par d'autres personnes peuvent exiger des permissions supplémentaires |

---

## Google Contacts

**Ce qu'il indexe :** les personnes, les numéros de téléphone, les adresses courriel et les coordonnées.

### La mise en place

Comme pour Google Drive — reprends le même projet Google Cloud et le même client OAuth.

1. **Active l'API People :**
   [Activer l'API People →](https://console.cloud.google.com/apis/library/people.googleapis.com)

2. Suis les étapes 3 à 6 de la section Google Drive ci-dessus

---

## Slack

Slack joue deux rôles dans Diapason :

- **Source de données** — il indexe les messages des canaux, les MP et les fils pour que ton agent puisse y chercher
- **Canal de messagerie** — il te laisse écrire à ton agent en MP, directement dans Slack

On recommande de créer **une seule app Slack** qui fait les deux. Le manifeste ci-dessous contient toutes les portées nécessaires.

### La mise en place rapide (manifeste d'app — recommandé)

1. **Va sur les [réglages des apps Slack →](https://api.slack.com/apps)**

2. **Create New App → « From an app manifest »** → sélectionne ton espace de travail

3. **Colle ce manifeste JSON** (il contient toutes les portées pour la source de données et la messagerie) :

   ```json
   {
       "display_information": { "name": "Diapason" },
       "features": {
           "app_home": {
               "home_tab_enabled": true,
               "messages_tab_enabled": true,
               "messages_tab_read_only_enabled": false
           },
           "bot_user": { "display_name": "Diapason", "always_online": true }
       },
       "oauth_config": {
           "scopes": {
               "bot": [
                   "channels:read", "channels:history", "channels:join",
                   "groups:read", "groups:history",
                   "im:read", "im:write", "im:history",
                   "mpim:read", "mpim:history",
                   "chat:write",
                   "users:read",
                   "app_mentions:read"
               ]
           }
       },
       "settings": {
           "event_subscriptions": { "bot_events": ["message.im"] },
           "socket_mode_enabled": true
       }
   }
   ```

4. **Relis, puis clique sur Create**

5. **Installe l'app :** Install App → Install to Workspace → Authorize

6. **Copie le jeton de bot :** va dans OAuth & Permissions → copie le **Bot User OAuth Token** (`xoxb-...`)

7. **Crée un jeton d'app (pour les MP) :**
   - Va dans Basic Information → App-Level Tokens → Generate Token
   - Nomme-le « socket » → ajoute la portée `connections:write` → Generate
   - Copie le jeton (`xapp-...`)

8. **(Facultatif) Mets l'icône de l'app :**
   - Va dans Basic Information → Display Information
   - Importe l'[icône Diapason](https://github.com/carlitoetienne01-spec/Diapason/blob/main/assets/diapason-slack-icon.jpg)

### Les portées requises pour le jeton de bot (référence)

| Portée | À quoi elle sert |
|-------|----------|
| `channels:read` | Lister les canaux publics |
| `channels:history` | Lire les messages des canaux publics |
| `channels:join` | Rejoindre automatiquement les canaux publics pour les indexer |
| `groups:read` | Lister les canaux privés |
| `groups:history` | Lire les messages des canaux privés |
| `im:read` | Lister les conversations en MP |
| `im:write` | Ouvrir une conversation en MP |
| `im:history` | Lire l'historique des MP et recevoir les événements de MP |
| `mpim:read` | Lister les MP de groupe |
| `mpim:history` | Lire les messages des MP de groupe |
| `chat:write` | Envoyer des messages et des réponses |
| `users:read` | Consulter les infos d'un utilisateur |
| `app_mentions:read` | Voir les @mentions du bot |

**La portée du jeton d'app :** `connections:write` (indispensable au mode Socket et aux MP)

### Le branchement dans Diapason

**Comme source de données** (lire les messages des canaux) :
- Bureau/navigateur : Sources de données → Slack → colle le jeton de bot (`xoxb-...`)
- CLI : `uv run diapason connect slack`

**Comme canal de messagerie** (écrire à ton agent en MP) :
- Bureau/navigateur : Sources de données → Canaux de messagerie → Slack → Configurer
- Saisis le **jeton de bot** (`xoxb-...`) et le **jeton d'app** (`xapp-...`)
- Ou bien : Agents → choisis l'agent → Canaux de messagerie → Slack → Configurer

**Écrire à ton agent en MP :**
- Dans Slack, trouve **Diapason** sous Apps (ou sous Direct Messages)
- Si tu ne le vois pas : clique sur le « + » à côté de Direct Messages → cherche « Diapason »
- Envoie un message → l'agent répond dans un fil

### À ne pas oublier

- **Réinstalle après un changement de portées :** chaque fois que tu ajoutes une portée ou que tu changes les souscriptions d'événements, tu DOIS réinstaller l'app.
- **Jeton d'app et jeton de bot :** le jeton de bot (`xoxb-`) sert aux appels d'API. Le jeton d'app (`xapp-`) sert au mode Socket. Il te faut les deux pour que les MP fonctionnent.
- **La visibilité des canaux :** le bot ne peut lire que les canaux où il a été ajouté. Invite-le avec `/invite @Diapason` dans chaque canal que tu veux indexer.
- **Les réponses en fil :** si tu réponds dans un fil, le bot le voit. Les nouveaux messages de premier niveau marchent aussi.

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| « not_allowed_token_type » | Utilise le jeton de **bot** (`xoxb-...`), pas un jeton d'utilisateur (`xoxp-`) ni un jeton de session (`xoxe-`) |
| « Sending messages to this app has been turned off » | Va dans App Home → active « Messages Tab » → coche « Allow users to send messages from the messages tab » |
| Le bot ne répond pas aux MP | Assure-toi que le mode Socket est activé, que l'événement `message.im` est souscrit, et que l'app a été réinstallée après les changements |
| Erreur « missing_scope » | Ajoute la portée manquante dans OAuth & Permissions → réinstalle l'app |
| Le bot est invisible dans Slack | Va dans Install App → Reinstall to Workspace |
| Aucun message trouvé (source de données) | Le bot ne voit que les canaux où il a été ajouté. Invite-le : `/invite @Diapason` dans le canal |
| Le mode Socket se connecte mais ne reçoit aucun événement | Vérifie que `message.im` figure bien dans les `bot_events` du manifeste, puis réinstalle l'app |

---

## Notion

**Ce qu'il indexe :** les pages, les bases de données et leur contenu.

### La mise en place

1. **Crée une intégration interne :**
   [Ouvrir les intégrations Notion →](https://www.notion.so/profile/integrations)
   - Clique sur « New integration »
   - Donne-lui un nom (« Diapason », par exemple)
   - Sélectionne ton espace de travail
   - Copie l'**Internal Integration Secret** (il commence par `ntn_`)

2. **Partage des pages avec ton intégration :**
   - Ouvre une page Notion que tu veux indexer
   - Clique sur « ... » (en haut à droite) → « Connections » → trouve ton intégration → clique dessus
   - Recommence pour chaque page ou base de données

3. **Branche-le dans Diapason :**
   - Bureau/navigateur : Agents → onglet Canaux → Notion → colle le jeton
   - CLI : `uv run diapason connect notion`

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| 0 page trouvée | Il faut partager les pages explicitement avec l'intégration (étape 2). Elle ne voit que les pages que tu lui as connectées. |
| Le contenu d'une base de données manque | Partage la page de la base elle-même, pas seulement des entrées isolées |
| Jeton expiré | Les jetons d'intégration Notion n'expirent pas. Si ça s'arrête de marcher, régénère-le sur la page des intégrations. |

---

## Granola

**Ce qu'il indexe :** les notes de réunion et les transcriptions générées par l'app Granola.

### La mise en place

1. **Ouvre l'app de bureau Granola** → Settings → API
2. **Copie ta clé d'API** (elle commence par `grn_`)
3. **Branche-la dans Diapason :**
   - Bureau/navigateur : Agents → onglet Canaux → Granola → colle la clé
   - CLI : `uv run diapason connect granola`

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| Aucune clé d'API dans les réglages | L'API Granola n'existe que sur les offres Business et Enterprise |
| 0 note de réunion | Vérifie que tu as bien des réunions enregistrées dans Granola |

---

## Apple Notes

**Ce qu'il indexe :** les notes de l'app Notes de macOS.

### La mise en place (automatique)

1. **Accorde l'Accès complet au disque** à ton app de terminal :
   - Ouvre Réglages Système → Confidentialité et sécurité → Accès complet au disque
   - Active l'accès pour Terminal, iTerm, Warp ou l'app de bureau Diapason

2. Apple Notes est détecté tout seul une fois l'Accès complet au disque accordé

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| « Non connecté » malgré l'Accès complet au disque | Relance ton app de terminal après avoir accordé l'accès |
| Le contenu des notes est illisible | Quelques très vieilles notes peuvent avoir des soucis d'encodage. La plupart passent proprement. |
| Des notes manquent | Seules les notes stockées en local ou dans iCloud sont indexées. Celles qui vivent dans un compte tiers (Gmail, Exchange) peuvent ne pas apparaître. |

---

## iMessage

**Ce qu'il indexe :** les messages texte de l'app Messages de macOS.

### La mise en place (automatique)

Comme Apple Notes — il faut l'Accès complet au disque.

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| « Non connecté » | Accorde l'Accès complet au disque (voir Apple Notes ci-dessus) |
| Synchronisation très lente | Les bases iMessage peuvent être énormes (plus de 50 000 messages). La première synchronisation peut prendre de 10 à 30 secondes. |
| Les messages récents manquent | Les messages viennent de la base locale. Si Messages.app n'a pas encore fait sa synchronisation iCloud, les messages récents peuvent manquer. |

---

## Outlook / Microsoft 365

**Ce qu'il indexe :** les courriels, par IMAP.

### La mise en place

1. **Active la double authentification** sur ton compte Microsoft :
   [Ouvrir la sécurité Microsoft →](https://account.microsoft.com/security)

2. **Génère un mot de passe d'application :**
   - Va dans Sécurité → Options de sécurité avancées → Mots de passe d'application
   - Crée un nouveau mot de passe d'application

3. **Branche-le dans Diapason :**
   - Bureau/navigateur : Agents → onglet Canaux → Outlook → saisis l'adresse courriel et le mot de passe d'application
   - CLI : `uv run diapason connect outlook`

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| La connexion échoue | Utilise le mot de passe d'application, pas ton mot de passe Microsoft habituel |
| « Authentication failed » | Certaines organisations Microsoft 365 désactivent IMAP. Demande à ton administrateur informatique. |
| Seule la boîte de réception arrive | Pour l'instant, seul le dossier Boîte de réception est synchronisé |

---

## Obsidian

**Ce qu'il indexe :** les fichiers Markdown de ton coffre Obsidian.

### La mise en place

1. Trouve le dossier de ton coffre Obsidian (celui qui contient le répertoire `.obsidian`)
2. **Branche-le dans Diapason :**
   - Bureau/navigateur : Agents → onglet Canaux → Obsidian → colle le chemin du coffre
   - CLI : `uv run diapason connect obsidian --path /path/to/vault`

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| « Non connecté » | Revérifie que le chemin existe et qu'il contient bien un dossier `.obsidian` |
| Des fichiers manquent | Seuls les fichiers `.md`, `.markdown` et `.txt` sont indexés. Les fichiers binaires et les images sont ignorés. |
| Synchronisation lente pour les gros coffres | Un coffre de plus de 1000 fichiers peut mettre une minute à se synchroniser |

---

## Dropbox

**Ce qu'il indexe :** les fichiers et les documents de ton Dropbox.

### La mise en place

1. **Crée une app Dropbox :**
   [Ouvrir la Dropbox App Console →](https://www.dropbox.com/developers/apps/create)
   - Choisis « Scoped access » → « Full Dropbox »

2. **Règle les permissions :**
   - Dans l'onglet Permissions, active `files.metadata.read` et `files.content.read`

3. **Génère un jeton d'accès :**
   - Va dans l'onglet Settings → « Generated access token » → Generate

4. **Branche-le dans Diapason :**
   - Bureau/navigateur : Agents → onglet Canaux → Dropbox → colle le jeton
   - CLI : `uv run diapason connect dropbox`

### Quand ça coince

| Le pépin | Que faire |
|-------|----------|
| « Invalid access token » | Les jetons courts de Dropbox expirent au bout de 4 heures. Génères-en un nouveau. |
| Des fichiers manquent | Vérifie que tu as bien activé les bonnes permissions (étape 2) |

---

## Quand ça coince, en général

### Pour tous les connecteurs

| Le pépin | Que faire |
|-------|----------|
| « Connecté — aucune donnée synchronisée » | Le connecteur s'est authentifié mais n'a pas encore synchronisé. Lance `uv run diapason deep-research-setup --skip-chat` pour déclencher une synchronisation. |
| Les données semblent périmées | Les connecteurs synchronisent à la demande. Lance la commande de mise en place ou clique sur « Reconnecter » pour resynchroniser. |
| Tu veux remettre un connecteur à zéro | Clique sur « Reconnecter » dans l'onglet Canaux, ou supprime le fichier d'identifiants `~/.diapason/connectors/{connector}.json` |

### Où sont rangés les identifiants

Tous les identifiants sont enregistrés en local dans `~/.diapason/connectors/`, avec les permissions de fichier `0600` (lecture et écriture pour le propriétaire seulement). Aucun identifiant n'est envoyé à un serveur — tout reste sur ta machine.

```
~/.diapason/connectors/
├── gmail_imap.json    # Adresse Gmail + mot de passe d'application
├── gdrive.json        # Jetons OAuth Google Drive
├── gcalendar.json     # Jetons OAuth Google Agenda
├── gcontacts.json     # Jetons OAuth Google Contacts
├── slack.json         # Jeton de bot Slack
├── notion.json        # Jeton d'intégration Notion
├── granola.json       # Clé d'API Granola
├── outlook.json       # Adresse Outlook + mot de passe d'application
└── dropbox.json       # Jeton d'accès Dropbox
```
