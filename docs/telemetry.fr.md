# Télémétrie

Diapason envoie par défaut une **télémétrie d'usage anonyme**, pour que
l'équipe voie où le produit casse, quelles fonctionnalités servent vraiment,
et comment l'améliorer. Cette page dit exactement ce qui est collecté et ce
qui ne l'est pas, où vont les données, et comment s'y soustraire.

## En bref

- **Activée par défaut**, anonyme, aucun contenu de discussion.
- **Anonyme** — un UUID tiré au hasard par installation, pas d'adresse
  courriel, pas de nom, pas d'IP.
- **Aucun contenu de discussion, jamais.** Seulement des comptes, des durées
  et des noms de fonctionnalités.
- **Backend auto-hébergé** sur l'instance PostHog de l'équipe Diapason —
  les données ne sont ni vendues ni partagées avec des tiers.
- **Conservation 365 jours**, après quoi les événements sont supprimés
  automatiquement.

## Ce qu'on collecte

### Les événements du cycle de vie

| Événement | Source | Pourquoi on l'envoie |
|---|---|---|
| `install_started` | `install.sh` | Le haut de l'entonnoir d'installation |
| `install_stage_completed` | `install.sh` | Le temps par étape — où les gens abandonnent-ils ? |
| `install_completed` | `install.sh` | L'installation a-t-elle réussi ? |
| `install_failed` | `install.sh` | Quelle étape a échoué, et sur quel système |
| `app_opened` | Backend + frontend | DAU / WAU / MAU |
| `setup_completed` | Frontend | L'assistant de premier lancement est allé au bout |
| `first_chat_sent` | Backend | Le tout premier message — l'activation |
| `uninstall_started` | `uninstall.sh` (si tu le lances) | Un signal d'abandon |

### Les événements d'usage

| Événement | Pourquoi on l'envoie |
|---|---|
| `chat_session_ended` | Agrégé par session : nombre de tours, jetons, latence, nombre d'outils |
| `tool_first_used` | Quels outils intégrés sont vraiment adoptés |
| `model_changed` | À quelle fréquence on change de modèle |
| `feature_used` | Quelles fonctionnalités ont du trafic, lesquelles n'en ont pas |
| `connector_auth_completed` | Quels connecteurs les gens configurent |
| `error_shown_to_user` | La classe d'erreur vue par l'utilisateur (pas la trace d'appels) |
| `feedback_submitted` | Une note a-t-elle été donnée ? Un commentaire était-il joint ? |
| `settings_changed` | Quels réglages sont basculés |
| `usage_daily_summary` | Des comptes agrégés, une fois par jour |

La liste canonique qui fait foi, avec chaque nom de propriété et son
validateur de type, vit dans
[`src/diapason/analytics/events.py`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/src/diapason/analytics/events.py).
Ce fichier est le seul endroit où de nouveaux événements peuvent être
ajoutés — la relecture de PR fait le portier.

## Ce qu'on ne collecte jamais

Des garde-fous durs, imposés par le code :

- **Le contenu des discussions** — prompts, sorties du modèle, messages système, arguments d'outils.
- **Les chemins de fichiers** — tout ce qui correspond à `~/`, `$HOME`, `/Users/<name>`, `/home/<name>`, `file://`.
- **Les adresses courriel, les noms, les numéros de téléphone, les adresses postales.**
- **Les adresses IP** (IPv4 + IPv6). La géolocalisation par IP de PostHog est désactivée côté serveur aussi.
- **Les adresses MAC, les numéros de série du matériel, les UUID de disques.**
- **Les traces d'appels** — seulement des énumérations de classes d'erreur.
- **Les clés d'API, les jetons OAuth, les JWT, les jetons bearer, les affectations de mot de passe** —
  repérés et jetés au niveau de la valeur.
- **Les noms d'hôte** qui ont l'air personnels (`alice-macbook.local`, par exemple).
- **Les listes, les dictionnaires, les ensembles** — les valeurs composites ne
  partent jamais, pour qu'aucune donnée personnelle ne puisse se glisser en
  fraude à l'intérieur d'un conteneur.

Deux filtres indépendants tournent avant que le moindre événement quitte la machine :

1. [`src/diapason/analytics/redaction.py`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/src/diapason/analytics/redaction.py) — la correspondance de motifs au niveau de la valeur (plus de 20 expressions régulières pour les données personnelles).
2. [`src/diapason/analytics/events.py`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/src/diapason/analytics/events.py) — la liste d'autorisation structurelle (nom d'événement + nom de propriété + validateur de type).

Le moindre échec dans l'une ou l'autre couche → l'événement ou la propriété
est jeté en silence. Les tests qui couvrent les motifs : [`tests/analytics/test_redaction.py`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/tests/analytics/test_redaction.py).

## Où vont les données

- **Aujourd'hui** (alpha) : PostHog Cloud (région US), offre gratuite.
  Indiqué ici par souci de transparence.
- **La cible en production** : une instance PostHog auto-hébergée à
  `analytics.diapason.ai`, chez Hetzner US-East. Mono-locataire, opérée par
  l'équipe Diapason.
- **Jamais** vendues, jamais partagées avec des annonceurs, jamais utilisées
  pour autre chose que l'amélioration de Diapason.

## La conservation

- Conservation par défaut : **365 jours**, après quoi PostHog supprime les
  événements tout seul.
- `diapason analytics reset-id` rend orphelins tous tes événements passés,
  en générant un identifiant anonyme neuf pour les suivants.

## Comment fonctionne l'identité

Un seul UUID v4 est généré à la première installation et rangé dans
`~/.diapason/anon_id`. Le script d'installation, le backend et le frontend
lisent tous le même fichier : les événements de tout le cycle de vie se
rattachent ainsi à une seule personne — sans qu'on sache jamais qui est
cette personne.

Supprime le fichier (`rm ~/.diapason/anon_id`) et un UUID neuf sera généré au
prochain lancement de l'app. L'UUID précédent et ses événements deviennent
alors orphelins.

## Pour les chercheurs et les contributeurs

- **Ajouter un événement** : modifie `src/diapason/analytics/events.py`,
  déclare la spécification, puis mets cette page à jour. La relecture de PR
  impose les deux.
- **Ajouter un motif de donnée personnelle** : modifie
  `src/diapason/analytics/redaction.py` et ajoute un cas de test dans
  `tests/analytics/test_redaction.py`.
- **Inspecter ce que ton installation envoie** : lance avec
  `DIAPASON_LOG_LEVEL=DEBUG` et filtre sur `Analytics`. Tu verras chaque nom
  d'événement et son dictionnaire de propriétés (expurgé) avant qu'il parte.

## À voir aussi

- La télémétrie locale (FLOPs, énergie, latence rangés dans
  `~/.diapason/telemetry.db`) est un sous-système **distinct**, documenté
  dans [`src/diapason/telemetry/`](https://github.com/carlitoetienne01-spec/Diapason/tree/main/src/diapason/telemetry). Elle
  ne quitte jamais la machine et se règle par `[telemetry]` (et non
  `[analytics]`) dans `config.toml`.
