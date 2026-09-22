# Le point du matin

Un briefing quotidien personnalisé : il collecte les données de tes services connectés, en fait un récit parlé avec un modèle local, et te le livre en audio par la synthèse vocale.

## Démarrage rapide (5 minutes)

### 1. Installer et préparer Diapason

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync --extra dev
```

### 2. Démarrer un modèle local avec Ollama

```bash
# Installer Ollama : https://ollama.com
ollama pull qwen3.5:9b    # ou n'importe quel modèle qui te plaît
```

### 3. Configurer le point du matin

Modifie `~/.diapason/config.toml` :

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:9b"

[digest]
enabled = true
schedule = "0 6 * * *"          # tous les jours à 6 h (syntaxe cron)
timezone = "America/Los_Angeles"
persona = "diapason"
honorific = "sir"               # ou "ma'am", "boss", etc.
tts_backend = "cartesia"        # ou "openai"
voice_id = "c8f7835e-28a3-4f0c-80d7-c1302ac62aae"  # Alistair (voix masculine britannique)
voice_speed = 1.2
sections = ["health", "messages", "calendar", "world"]

[digest.health]
sources = ["oura"]

[digest.messages]
sources = ["gmail", "google_tasks", "slack", "imessage"]

[digest.calendar]
sources = ["gcalendar"]

[digest.world]
sources = ["weather", "hackernews", "news_rss"]
```

### 4. Connecter tes sources de données

```bash
# Google (un seul flux couvre Gmail, Agenda, Tâches, Contacts et Drive)
diapason connect gdrive
# Colle : <client_id>:<client_secret> — le navigateur s'ouvre tout seul

# Oura Ring (jeton d'accès personnel)
diapason connect oura
# Colle ton jeton, pris sur https://cloud.ouraring.com/personal-access-tokens

# Spotify
diapason connect spotify

# Strava
diapason connect strava
```

Pour la météo, GitHub et les actualités, écris directement les fichiers d'identifiants :

```bash
# Météo (OpenWeatherMap — gratuit sur https://openweathermap.org/api)
echo '{"api_key": "TA_CLE", "location": "San Francisco,CA,US"}' > ~/.diapason/connectors/weather.json

# Notifications GitHub (jeton à créer sur https://github.com/settings/tokens)
echo '{"token": "ghp_TON_JETON"}' > ~/.diapason/connectors/github.json

# Flux RSS d'actualités (aucune authentification — choisis tes flux)
cat > ~/.diapason/connectors/news_rss.json << 'EOF'
{"feeds": [
  {"name": "Arxiv CS.AI", "url": "https://rss.arxiv.org/rss/cs.AI"},
  {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
  {"name": "Bloomberg", "url": "https://feeds.bloomberg.com/markets/news.rss"},
  {"name": "WSJ", "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml"}
]}
EOF
```

Hacker News, iMessage et Apple Music fonctionnent tout seuls sur macOS, sans rien configurer.

### 5. Poser ta clé d'API pour la synthèse vocale

```bash
# Cartesia (inscription sur https://play.cartesia.ai)
export CARTESIA_API_KEY="sk_car_..."

# Ou OpenAI (https://platform.openai.com/api-keys)
export OPENAI_API_KEY="sk-proj-..."
```

### 6. Lancer ton premier point du matin

```bash
CARTESIA_API_KEY="sk_car_..." diapason digest --fresh
```

Le point du matin va :

1. Collecter les données de toutes les sources connectées
2. En faire un briefing parlé avec Qwen3.5 9B
3. Produire l'audio avec la voix Alistair de Cartesia
4. Afficher le texte et jouer l'audio

## Les commandes

```bash
diapason digest --fresh          # Génère un nouveau point, maintenant
diapason digest                  # Affiche le point du jour déjà en cache
diapason digest --text-only      # Affiche le texte sans l'audio
diapason digest --history        # Affiche les points précédents
diapason digest --schedule "0 6 * * *"   # Règle la programmation quotidienne
diapason digest --schedule off   # Désactive la programmation
diapason digest --schedule       # Affiche la programmation en cours
```

## Dire « Good morning »

Quand tu discutes avec Diapason (en ligne de commande, dans l'app de bureau ou dans le navigateur), dire « Good morning » ou « morning digest » déclenche le point du matin tout seul — pas besoin de passer explicitement par la commande `digest`.

## Référence de la configuration

### Les sections

La liste `sections` décide de ce que couvre le point du matin, par ordre de priorité :

| Section | Sources | Ce qu'elle apporte |
|---------|---------|-----------------|
| `health` | `oura`, `apple_health`, `strava` | Sommeil, forme, activité, séances |
| `messages` | `gmail`, `google_tasks`, `slack`, `notion`, `imessage`, `github_notifications` | Tri des courriels, tâches, SMS, Slack, PR |
| `calendar` | `gcalendar` | Les événements et l'emploi du temps du jour |
| `world` | `weather`, `hackernews`, `news_rss` | Prévisions météo, actualité tech, flux RSS |
| `music` | `spotify`, `apple_music` | Les morceaux écoutés récemment (à activer soi-même) |

### Les voix de la synthèse vocale

**Cartesia** (recommandé — naturel, expressif) :

| Voix | Identifiant | Description |
|-------|----|-------------|
| Alistair | `c8f7835e-28a3-4f0c-80d7-c1302ac62aae` | Voix masculine britannique, raffinée |
| Benedict | `3c0f09d6-e0d7-499c-a594-70c5b7b93048` | Voix masculine britannique, policée et formelle |
| Harrison | `df89f42f-f285-4613-adbf-14eedcec4c9e` | Voix masculine britannique, nette et professionnelle |
| Sterling | `b134c304-d095-4d2b-a77a-914f5e8e84e7` | Grave, assurée, digne |

**Synthèse vocale d'OpenAI** :

| Voix | Description |
|-------|-------------|
| `onyx` | Masculine, grave |
| `nova` | Féminine, chaleureuse |
| `alloy` | Neutre |
| `shimmer` | Féminine, expressive |

### Le personnage

Le champ `persona` charge un fichier de prompt depuis `configs/diapason/prompts/personas/{name}.md`. Le personnage `diapason`, celui par défaut, livre ses briefings avec un humour britannique pince-sans-rire, fait passer l'urgent devant, et lit les données de santé comme des tendances plutôt que comme des chiffres bruts.

Pour créer ton propre personnage, ajoute un nouveau fichier `.md` dans le dossier des personas.

### Les flux d'actualités

Ajoute n'importe quel flux RSS ou Atom à `~/.diapason/connectors/news_rss.json` :

```json
{"feeds": [
  {"name": "Arxiv CS.AI", "url": "https://rss.arxiv.org/rss/cs.AI"},
  {"name": "Arxiv CS.LG", "url": "https://rss.arxiv.org/rss/cs.LG"},
  {"name": "NYT Top Stories", "url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"},
  {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
  {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss"},
  {"name": "WSJ World News", "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml"},
  {"name": "Hacker News", "url": "https://hnrss.org/frontpage"}
]}
```

## Les routes d'API

Le point du matin est aussi disponible par le serveur FastAPI :

```bash
diapason serve  # Démarre le serveur

# GET  /api/digest           — Le texte du point du jour
# GET  /api/digest/audio     — Diffuse l'audio du point (MP3)
# POST /api/digest/generate  — Force une nouvelle génération
# GET  /api/digest/history   — Les points précédents
# GET  /api/digest/schedule  — La programmation en cours
# POST /api/digest/schedule  — Modifie la programmation {"enabled": true, "cron": "0 6 * * *"}
```

## L'interface

L'app de bureau et l'app navigateur affichent un lecteur audio dans le fil dès qu'un point du matin est généré. Les boutons « Connecter » de l'assistant de configuration s'occupent des flux OAuth tout seuls : tu cliques, tu autorises dans la fenêtre du navigateur, c'est fini.

## En cas de problème

**« Aucun point pour aujourd'hui »** — Lance `diapason digest --fresh` pour en générer un.

**Des sections vides** — Vérifie l'état des connecteurs avec `diapason connect --list`. Assure-toi que les jetons n'ont pas expiré (ceux de Google et de Spotify expirent au bout d'une heure et sont renouvelés tout seuls à l'utilisation suivante).

**La météo ne marche pas** — Une clé d'API OpenWeatherMap peut mettre jusqu'à deux heures à s'activer après sa création. Utilise le format `Ville,Région,Pays` (`Palo Alto,CA,US`, par exemple).

**Un 403 de GitHub** — Ton jeton d'accès personnel a besoin de la permission `notifications` sous « Account permissions », et non sous « Repository permissions ».

**L'audio ne se joue pas** — Vérifie que `CARTESIA_API_KEY` ou `OPENAI_API_KEY` est bien posée. Vérifie aussi tes crédits sur https://play.cartesia.ai ou https://platform.openai.com.
