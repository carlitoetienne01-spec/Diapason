# Feuille de route

## Les chantiers du moment

Voici les domaines où le développement est actif et où une contribution change le plus de choses :

- **Données de post-entraînement** — construire des jeux de données et des chaînes d'entraînement à partir des traces d'exécution, pour améliorer le routage des agents et le choix des outils
- **Chaînes d'orchestration multi-modèles** — faire travailler plusieurs modèles sur une même question (un petit modèle pour classer, un gros pour générer, par exemple)
- **Routage attentif à l'énergie** — se servir de la consommation électrique relevée par la télémétrie pour optimiser l'efficacité énergétique, en plus de la latence et de la qualité
- **Un écosystème de greffons** — des moteurs, des outils et des agents proposés par la communauté, distribués comme paquets Python
- **Mémoire fédérée** — des dorsales de mémoire qui se synchronisent d'un appareil à l'autre
- **Recherche de configuration guidée par un LLM :** l'apprentissage du harnais piloté par un modèle de pointe — un modèle de pointe analyse tes traces et propose des améliorations de configuration. Voir le [guide d'utilisation](../user-guide/llm-guided-spec-search.md) et l'[architecture](../architecture/learning.md#la-recherche-de-specification-guidee-par-llm-apprentissage-de-harnais-pilote-par-la-frontiere).

---

## Comment participer

1. Parcours les chantiers ci-dessous et repère une entrée qui t'intéresse
2. Regarde si un [ticket GitHub](https://github.com/carlitoetienne01-spec/Diapason/issues) existe déjà pour elle — sinon, [ouvres-en un](https://github.com/carlitoetienne01-spec/Diapason/issues/new/choose)
3. Commente **« take »** sur le ticket pour qu'il te soit attribué automatiquement
4. Lis le [guide de contribution](https://github.com/carlitoetienne01-spec/Diapason/blob/main/CONTRIBUTING.md) pour l'installation de l'environnement de développement et le processus de pull request

---

## Les chantiers

Le développement de Diapason est réparti en **cinq chantiers indépendants**. Tu peux prendre celui qui correspond à tes compétences et à tes envies — ils sont faits pour avancer en parallèle, sans se bloquer les uns les autres.

Chaque entrée porte une étiquette de maturité :

| Étiquette | Ce qu'elle veut dire | Ce que tu peux faire |
|-----|---------|---------------------|
| **Prêt** | Bien délimité, le chemin d'implémentation est clair | Prends-le — cherche une spec dans les [tickets](https://github.com/carlitoetienne01-spec/Diapason/issues), ou écris-en une |
| **À concevoir** | L'idée est claire, mais il faut une spec avant d'écrire du code | Ouvre une [discussion de conception](https://github.com/carlitoetienne01-spec/Diapason/discussions) ou rédige une RFC |
| **En recherche** | Exploratoire, à creuser avant de concevoir | Lis les articles qui s'y rapportent, prototype, partage ce que tu trouves |
| ~~**Fait**~~ | Livré depuis l'écriture de cette page | Rien à faire — la ligne reste, barrée, pour que personne ne le reconstruise |

Une feuille de route qui annonce encore du travail déjà fait est pire qu'une
feuille de route périmée : elle envoie quelqu'un reconstruire ce qui existe
déjà, et il ne l'apprend qu'à la relecture. Les lignes barrées disent ce qui a
été livré et où, pour que l'affirmation se vérifie en un seul `grep`.

---

### Chantier 1 : opérateurs continus et agents

Les opérateurs sont ce qui distingue Diapason — des agents persistants, programmés, dotés d'un état, qui tournent seuls sur des appareils personnels. L'architecture actuelle, rythmée par des tics (OperatorManager → TaskScheduler → AgentExecutor → OperativeAgent), est solide, mais demande à être durcie pour une autonomie vraiment longue.

#### Là où tu peux aider

| Entrée | Maturité | Détails |
|------|----------|---------|
| Contrôles de santé et suivi du battement de cœur des opérateurs | **Prêt** | Ajouter des sondes de vivacité à OperatorManager ; les faire remonter dans `diapason operators status`. Détecter les opérateurs figés au-delà de la boucle de réconciliation existante. |
| Collecte de métriques pour les manifestes d'opérateurs | **Prêt** | À moitié fait, ce qui est pire que pas commencé : `OperatorManager.collect_metrics()` existe et lit la liste `metrics` du manifeste, mais **rien ne l'appelle** — aucun site d'appel dans `src/` ni dans `tests/`. Ce qui reste n'est pas d'écrire le collecteur, c'est de le brancher sur un tic et sur `diapason operators status`. Vérifie les sites d'appel avant de commencer. |
| ~~Application de la politique de capacités~~ | **Fait** | Livré sous la forme de `operators/capability_guard.py`, vérifié dans `activate()` et dans `run_once()`. À noter : le conseil que portait cette ligne était faux et aurait livré une fonctionnalité cassée — se brancher directement sur `CapabilityPolicy` refuse *tous* les opérateurs sur une installation par défaut, parce que les autorisations sous lesquelles un opérateur tourne sont celles que `ToolExecutor` se donne à sa construction, laquelle n'a pas encore eu lieu au moment de l'activation. Le garde vérifie donc le vocabulaire et la cohérence avec les outils nommés à chaque installation, et ne consulte la politique que si un administrateur en a fourni une. |
| Limitation de débit par opérateur | **Prêt** | Empêcher un opérateur emballé de marteler l'inférence. Ajouter des limites de débit configurables à OperatorManager. |
| Composition et chaînage d'opérateurs | **À concevoir** | Exprimer des dépendances entre opérateurs (l'opérateur A passe ses résultats à l'opérateur B). Demande de concevoir le passage des données et la sémantique d'ordonnancement. |
| Opérateurs déclenchés par événement | **À concevoir** | Des opérateurs qui se déclenchent sur les événements de l'EventBus (un nouveau fichier indexé, un message reçu sur un canal) et pas seulement sur un cron ou un intervalle. |
| Versionnage et retour en arrière des opérateurs | **À concevoir** | Faire tourner la v2 d'un opérateur à côté de la v1. Revenir automatiquement en arrière après des échecs répétés. |
| Des opérateurs qui s'améliorent seuls, par Learning | **En recherche** | Des opérateurs qui se servent du retour des traces pour ajuster leurs propres prompts, leur choix d'outils et leurs politiques de routage, à travers la primitive Learning. |

---

### Chantier 2 : clients mobiles et messagerie

Une IA personnelle doit être joignable depuis les appareils que les gens ont vraiment sur eux. Diapason tourne sur des portables, des stations de travail et des serveurs — mais on s'en sert depuis son téléphone.

**Ce qui marche aujourd'hui :**

- **iMessage et SMS** par SendBlue — bidirectionnel, détection automatique entre iMessage et SMS, réponses dans le fil, avancement en direct
- **Slack** par Socket Mode (slack-bolt) — messages privés bidirectionnels, réponses dans le fil, mise en forme Slack, avancement en direct
- **Bureau et navigateur** — l'onglet Interact, avec le fil de l'eau en direct, l'avancement des outils et le pied de page de télémétrie

#### Là où tu peux aider

| Entrée | Maturité | Détails |
|------|----------|---------|
| WhatsApp par l'API Meta Cloud | **À concevoir** | Le protocole Baileys est bloqué par WhatsApp (erreurs 405). Il faut passer par l'API officielle Meta WhatsApp Business. Demande l'inscription d'un compte Meta Business. |
| WhatsApp par Baileys (contournement) | **Bloqué** | WhatsApp bloque activement les connexions Baileys non officielles (405 Method Not Allowed). Surveille le [dépôt Baileys](https://github.com/WhiskeySockets/Baileys) pour les évolutions du protocole. |
| Messages riches Slack (Block Kit) | **Prêt** | Les réponses Slack actuelles utilisent la mise en forme mrkdwn. Ajouter la prise en charge de Block Kit, pour des réponses structurées avec boutons, sections et pièces jointes. **Bon premier ticket.** |
| Système de notifications unifié | **À concevoir** | Des notifications poussées quand un opérateur finit une tâche ou réclame ton attention. Demande un adaptateur de notification par canal. |
| Signal en bidirectionnel | **À concevoir** | Aujourd'hui en envoi seul, par l'API REST signal-cli. Ajouter une écoute des messages entrants, avec relève en arrière-plan. |
| Interface vocale | **En recherche** | Une boucle parole-vers-texte (Whisper) → agent → texte-vers-parole sur les canaux téléphoniques. Le module `speech/` existant sert de socle. |
| Restauration automatique des canaux au redémarrage | **Prêt** | Le démon Slack et SendBlue se restaurent tout seuls depuis les liaisons enregistrées quand le serveur redémarre. Il faut rendre ça plus solide dans les cas limites. |

---

### Chantier 3 : collaboration sécurisée avec le cloud

La tension au cœur de l'IA personnelle : les modèles locaux préservent la vie privée mais manquent de capacité ; les modèles du cloud sont puissants mais obligent à confier tes données à un fournisseur. Ce chantier résout ça par une **inférence collaborative à la Minions** (le local s'occupe du contexte, le cloud du raisonnement) et par du **calcul confidentiel fondé sur les TEE** (le cloud ne voit pas tes données, même pendant l'inférence).

**Références :**

- [Minions: Cost-Efficient Local-Cloud LLM Collaboration](https://github.com/HazyResearch/minions)
- [TEE for Confidential AI Inference](https://openreview.net/forum?id=ey87M5iKcX) ([PDF](https://openreview.net/pdf?id=ey87M5iKcX))

#### Là où tu peux aider

| Entrée | Maturité | Détails |
|------|----------|---------|
| Analyseur de complexité des requêtes | **Prêt** | Classer les questions entrantes par difficulté, pour décider du routage vers le local ou vers le cloud. Prolonge la logique de routage de `MultiEngine`. |
| ~~Suivi du coût par requête~~ | **Presque fait** | Branché de bout en bout : `estimate_cost()` dans `engine/cloud.py` → le `cost_usd` de la réponse → `telemetry/instrumented_engine.py` et `wrapper.py` → la colonne `cost_usd` → `aggregator.py`. Un modèle sans tarif rapporte `$0.00` **et consigne un avertissement**, parce que zéro ne se distingue pas d'un tour local gratuit. Ce qui reste est plus étroit que l'entrée d'origine : dans `cloud.py`, un chemin non-OpenAI écrit encore `0.0` en dur au lieu d'appeler `estimate_cost()`. |
| Chaîne de caviardage avant envoi au cloud | **Prêt** | Brancher le `GuardrailsEngine` existant en mode REDACT comme étape obligatoire avant toute transmission vers le cloud. |
| Protocole Minion (séquentiel) | **À concevoir** | Le modèle local extrait et résume un contexte long → le modèle du cloud raisonne sur le résultat compressé. Réimplémentation native de l'idée centrale de [Minions](https://github.com/HazyResearch/minions). |
| Protocole Minion (parallèle) | **À concevoir** | Le modèle local et celui du cloud travaillent en même temps sur des aspects différents d'une même question ; les résultats sont fusionnés. Demande une nouvelle abstraction `HybridInferenceEngine`. |
| Vérification de l'attestation TEE | **À concevoir** | Vérifier par attestation cryptographique que l'inférence du cloud s'est déroulée dans un environnement d'exécution de confiance. |
| Suivi de teinte à la frontière local / cloud | **À concevoir** | Le `TaintSet` suit déjà les étiquettes PII et Secret. Ajouter une contrainte de routage, pour que les données teintées n'aillent que vers des points d'accès TEE attestés. |
| Décodage spéculatif (brouillon local, vérification dans le cloud) | **En recherche** | Le modèle local produit des jetons candidats ; celui du cloud les valide en parallèle, pour réduire la latence. |

---

### Chantier 4 : tutoriels et documentation

Diapason a une documentation de référence et quatre tutoriels, mais il reste des trous importants sur les agents continus, l'évaluation des modèles de langue, les approches d'apprentissage et les outils sur mesure. Les tutoriels vidéo sont pensés comme une occasion de contribuer — les tutoriels écrits viennent d'abord, avec leur script vidéo, pour que n'importe qui puisse enregistrer.

#### Là où tu peux aider

| Entrée | Maturité | Détails |
|------|----------|---------|
| Tutoriel « Construire des agents continus » | **Prêt** | Écrire un manifeste d'opérateur en TOML, l'activer, la persistance de session d'un tic à l'autre, le mode démon. Exemple : un opérateur de veille qui surveille arxiv chaque jour. |
| Tutoriel « Ajouter ses propres outils » | **Prêt** | Implémenter `BaseTool`, l'enregistrer par `ToolRegistry`, le brancher aux agents. Exemple : un outil d'API météo. **Bon premier ticket.** |
| Tutoriel « Tester et comparer les modèles de langue » | **Prêt** | Lancer des bancs d'essai, comparer les modèles locaux et ceux du cloud, lire la télémétrie (latence, coût, énergie par jeton). S'appuie sur le cadre `bench/` existant. |
| Guides d'installation par plateforme | **Prêt** | Étoffer `installation.md` avec des marches à suivre propres à chaque plateforme : macOS + Ollama, Ubuntu + NVIDIA + vLLM, Windows + Ollama, Raspberry Pi. **Bon premier ticket.** |
| Tutoriel « Apprentissage et choix du modèle » | **À concevoir** | Les politiques du routeur (heuristique, apprise, GRPO), les approches proposées comme l'échantillonnage de Thompson, les signaux de récompense tirés des traces. |
| De quoi produire des tutoriels vidéo | **À concevoir** | Mettre en place le processus d'enregistrement, l'hébergement (YouTube), l'intégration dans MkDocs. Écrire les scripts vidéo en même temps que les tutoriels écrits. |
| Tutoriels interactifs en carnet Jupyter | **À concevoir** | Des versions carnet des tutoriels clés, pour apprendre cellule par cellule, en explorant. |

---

### Chantier 5 : couvrir plus de matériel

Une IA personnelle, c'est une IA qui tourne sur le matériel que les gens possèdent vraiment. Chaque nouvelle cible matérielle élargit le cercle de ceux qui peuvent se servir de Diapason, et produit des données pour le programme de recherche (les arbitrages entre énergie, coût et latence d'une puce à l'autre).

Ajouter une cible matérielle touche jusqu'à quatre morceaux : la détection du matériel dans `core/config.py`, un adaptateur de moteur d'inférence dans `engine/`, un moniteur d'énergie dans `telemetry/`, et une entrée dans la base de caractéristiques de cartes graphiques, dans `telemetry/gpu_monitor.py`.

#### Là où tu peux aider

| Entrée | Maturité | Détails |
|------|----------|---------|
| Le chemin iGPU AMD Ryzen AI | **Prêt** | L'iGPU RDNA 3.5 de Strix Point encaisse du 7-8B par Vulkan. La dorsale Vulkan de llama.cpp fonctionne dès aujourd'hui. Il manque la détection du matériel et le moniteur d'énergie. **Bon premier ticket.** |
| ~~Élargir la base de caractéristiques des cartes graphiques~~ | **Fait** | Les trois cibles nommées ici sont arrivées dans `GPU_SPECS` (`telemetry/gpu_monitor.py`) : Arc B580/B570, Jetson Orin NX, Snapdragon X Elite/X Plus — aux côtés de NVIDIA, AMD et Apple Silicon. Ajouter une *nouvelle* puce reste un bon premier ticket ; ces trois-là ne le sont plus. |
| Carte graphique Intel Arc (B580/B570) | **À concevoir** | 12 Go de VRAM, une carte grand public à ~250 $. Tenable pour des modèles de 7-8B. Côté moteur : IPEX-LLM ou la dorsale SYCL de llama.cpp. |
| NVIDIA Jetson Orin | **À concevoir** | Ce qui se fait de mieux en périphérie. L'Orin NX 16 Go tient des modèles de 7-8B à 15-25 jetons/s. Il manque la détection du matériel, un moniteur d'énergie (tegrastats) et un guide de déploiement. |
| NPU Qualcomm Snapdragon X Elite | **À concevoir** | 45 TOPS, sur les portables Windows Arm. Le chemin tenable : ONNX Runtime + QNN Execution Provider. |
| NPU Intel Lunar Lake par OpenVINO | **À concevoir** | 48 TOPS — la pile logicielle NPU la plus mûre pour les portables x86. Un nouveau moteur enveloppant OpenVINO GenAI. |
| Raspberry Pi 5 | **À concevoir** | Processeur seul, par llama.cpp ARM NEON, pour des modèles de 1-3B. Un point d'entrée à 100 $ pour les bricoleurs. |
| Une suite de bancs d'essai matériels unifiée | **À concevoir** | Un banc d'essai normalisé qui fait tourner les mêmes charges sur tout le matériel pris en charge, et produit des chiffres d'énergie, de latence, de débit et de coût comparables. |
