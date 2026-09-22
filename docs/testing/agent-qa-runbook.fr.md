# Cahier de tests des agents

Scénarios de test manuels pour les agents persistants, en ligne de commande et dans l'app de bureau.

## Préparer l'environnement

| Prérequis | Commande / vérification |
|---|---|
| Ollama tourne avec le modèle | `ollama list` affiche `qwen3:8b` |
| Diapason initialisé | `uv run diapason doctor` tout au vert |
| Extension Rust construite | `uv run maturin develop -m rust/crates/diapason-python/Cargo.toml` |
| App de bureau lancée | `uv run diapason serve` + `cd frontend && npm run dev` |
| Identifiants Slack | `SLACK_BOT_TOKEN` et `SLACK_APP_TOKEN` définis, bot invité dans le canal de test |
| Identifiants Gmail | credentials.json OAuth téléchargé, jeton généré |
| Identifiants Twitter | Les 5 variables d'environnement définies (bearer + OAuth 1.0a) |
| Identifiants Discord | Jeton du bot défini, bot invité sur le serveur de test |
| Identifiants Telegram | Jeton du bot obtenu de @BotFather, identifiant du chat de test connu |
| Identifiants e-mail | Hôte SMTP/IMAP et identifiants du compte de test |

## Scénarios en ligne de commande

| # | Scénario | Étapes | Résultat attendu | OK |
|---|----------|--------|------------------|----|
| 1 | Lancement depuis un modèle | `diapason agents launch`, choisir research_monitor | Agent créé, config affichée avec les outils retenus | [ ] |
| 2 | Exécution manuelle | `diapason agents run <id>` | La sortie montre le raisonnement et les appels d'outils, statut -> idle | [ ] |
| 3 | Question immédiate | `diapason agents ask <id> "résume l'actualité récente de l'IA"` | Réponse synchrone dans le terminal | [ ] |
| 4 | Consigne mise en file | `diapason agents instruct <id> "concentre-toi sur la diffusion"`, puis `diapason agents run <id>` | En file -> remise, réponse dans `diapason agents messages <id>` | [ ] |
| 5 | Contrôle du statut | `diapason agents status` après 3 exécutions ou plus | total_runs, total_cost et last_run_at renseignés | [ ] |
| 6 | Pause et reprise | `diapason agents pause <id>`, vérifier que le tick est sauté, `diapason agents resume <id>`, vérifier qu'il se déclenche | Le statut bascule correctement | [ ] |
| 7 | Ordonnancement du démon | `diapason agents daemon` avec un agent à intervalle (60 s) | 3 ticks ou plus se déclenchent à l'heure, la mémoire s'accumule | [ ] |
| 8 | Budget épuisé | Fixer max_cost=0.001, lancer jusqu'au dépassement | Le statut passe à budget_exceeded | [ ] |
| 9 | Reprise après erreur | Tuer Ollama en plein tick, puis `diapason agents recover <id>` | Erreur -> reprise -> idle avec point de reprise | [ ] |
| 10 | Liaison à un canal | `diapason agents bind <id> --slack #test`, lancer un tick | L'agent envoie sur Slack | [ ] |
| 11 | Multi-agents | Lancer 3 agents à intervalles différents, lancer le démon | Chacun se déclenche indépendamment | [ ] |
| 12 | Outils des modèles | Créer un agent depuis chaque modèle, `diapason agents info <id>` | Tous les outils retenus par défaut sont listés | [ ] |

## Scénarios dans l'app de bureau

| # | Scénario | Étapes | Résultat attendu | OK |
|---|----------|--------|------------------|----|
| 1 | Assistant de modèle | Nouvel agent -> choisir chaque modèle -> terminer l'assistant | L'agent apparaît dans la grille avec la bonne config | [ ] |
| 2 | Agent sur mesure | Nouvel agent -> Sur mesure -> planification manuelle, choisir les outils, renseigner les identifiants | Outils et identifiants enregistrés, agent créé | [ ] |
| 3 | Lancer maintenant | Cliquer sur « Lancer maintenant » sur la carte de l'agent | Pastille de statut : vert -> bleu -> vert, les compteurs augmentent | [ ] |
| 4 | Discussion immédiate | Onglet Interagir -> taper un message -> envoyer (mode immédiat) | La réponse apparaît dans l'interface de discussion | [ ] |
| 5 | Discussion en file | Onglet Interagir -> envoyer (mode file) -> cliquer sur « Lancer maintenant » | Le message est remis au tick, la réponse apparaît | [ ] |
| 6 | Gestion des tâches | Onglet Tâches -> créer une tâche -> lancer l'agent | Le statut de la tâche évolue, les trouvailles se remplissent | [ ] |
| 7 | Inspection de la mémoire | Lancer 3 ticks ou plus -> onglet Mémoire | La mémoire de synthèse reflète ce que l'agent a accumulé | [ ] |
| 8 | Inspection de la trace | Lancer un tick -> onglet Journaux | Les étapes de la trace sont visibles, avec les appels d'outils et leurs résultats | [ ] |
| 9 | Apprentissage | Activer l'apprentissage par les traces -> onglet Apprentissage -> déclencher | Des entrées apparaissent dans le journal d'apprentissage | [ ] |
| 10 | Erreur et reprise | Arrêter Ollama -> lancer l'agent -> vérifier le badge d'erreur -> cliquer sur « Récupérer » | L'état d'erreur s'affiche, la reprise ramène à idle | [ ] |

## Matrice de tests par canal

| Canal | Test d'envoi | Test de réception | Test de fil / réponse | Modèle d'agent | OK |
|-------|--------------|-------------------|-----------------------|----------------|----|
| Slack | Publier dans #test-channel | Message entrant en Socket Mode | Répondre dans le fil (thread_ts) | inbox_triager | [ ] |
| Gmail | Envoyer un e-mail au destinataire de test | Relève des non-lus -> le gestionnaire se déclenche | Répondre dans le fil (threadId) | inbox_triager | [ ] |
| E-mail (SMTP/IMAP) | Envoyer par SMTP | Relève IMAP des UNSEEN | En-tête In-Reply-To | inbox_triager | [ ] |
| iMessage (BlueBubbles) | Envoyer à un numéro de téléphone | s.o. (envoi seulement) | s.o. | research_monitor | [ ] |
| Twitter/X | Publier un tweet et envoyer un DM | Relever les mentions | Répondre (in_reply_to_tweet_id) | research_monitor | [ ] |
| Discord | Publier dans #test-channel | Événement message de la Gateway | s.o. | code_reviewer | [ ] |
| Telegram | Envoyer dans le chat de test | Mise à jour en long-poll | reply_to_message_id | research_monitor | [ ] |
| WhatsApp (Baileys) | Envoyer au numéro de test | Message entrant Baileys | s.o. | inbox_triager | [ ] |

## Charge et cas limites

| # | Scénario | Comment tester | Critère de réussite | OK |
|---|----------|----------------|---------------------|----|
| 1 | Déluge de messages | Mettre 50 messages en file en ligne de commande, lancer un tick | Les 50 sont remis, une réponse est produite | [ ] |
| 2 | Démon de longue durée | Laisser tourner le démon 1 heure, avec un agent à 60 s d'intervalle | Pas de fuite mémoire, pas de blocage, ~60 ticks | [ ] |
| 3 | Pause / reprise rapides | Script : pause -> reprise -> pause -> reprise pendant un tick | État propre, aucune corruption | [ ] |
| 4 | Révocation d'identifiants | Révoquer le jeton Slack en plein tick | L'agent reçoit une erreur d'outil, le tick va au bout, le statut n'est pas corrompu | [ ] |
| 5 | Charge multi-agents | 10 agents sur le démon, intervalles variés | Tous se déclenchent à l'heure, sans interférence | [ ] |
| 6 | Grosse réponse | L'agent produit une réponse de plus de 10 000 caractères | summary_memory tronquée à 2 000 caractères, réponse complète dans les messages | [ ] |
| 7 | Intégrité du point de reprise | Tuer le processus en plein tick, redémarrer, récupérer | Point de reprise restauré, l'agent repart proprement | [ ] |
