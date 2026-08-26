# Diapason Spatial Mesh

*Documentation du chantier. Point d'entrée.*

| Document | Ce qu'il contient |
|---|---|
| [`INITIAL_AUDIT.md`](INITIAL_AUDIT.md) | L'audit de phase 0 : ce qui existe, ce qui manque, ce qui est impossible tel qu'imaginé, et les alternatives. |
| [`CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md) | La matrice réelle par plateforme, engendrée depuis le code et l'état constaté de la flotte. |
| [`../architecture/device-mesh.md`](../architecture/device-mesh.md) | La spec du maillage **existant** — modèle de confiance, enveloppe signée, catalogue fermé. À lire avant tout. |

## L'essentiel en trois phrases

Le maillage d'appareils **existe déjà** : 4 250 lignes, 274 tests, deux
appareils appairés et onze commandes réellement abouties. Il ne lui manquait
pas des fondations mais **trois raccordements**, livrés en phase 1 : deux
Diapason peuvent enfin se jumeler, l'assistant a enfin la main dessus, et les
tests ne peuvent plus écraser la clé privée de la machine. Le reste du
cahier des charges — transfert de fichiers, gestes de la main — se construit
maintenant sur une fondation vérifiée plutôt que supposée.

## Phase 1 — ce qui a été livré

| Réparation | Preuve |
|---|---|
| **Garde d'isolation des tests** (`tests/mesh/conftest.py`) | Deux tests prouvent que le foyer est détourné et qu'une clé créée en test n'atteint pas la machine. |
| **Adoption de l'identité de flotte** (`mesh/join.py`, `identity.adopt_owner_id`) | Deux instances jumelées pour de vrai sur la machine : l'invité adopte la flotte de l'hôte et l'inscrit à son registre. |
| **La main de l'assistant** (`_TROUSSE_ASSISTANT`) | `mesh_devices` répond « 2 appareils appairés ». Un test garde la présence, en miroir de celui qui garde l'absence côté voix. |
| **`desktop.open` remis à sa place** | Exige désormais une attestation (le contrôle 10 de `verify_command` devient vivant) et sort de l'énumération offerte au modèle. |
| **Chemin invité** (`diapason mesh join / devices / whoami`) | Les trois commandes tournent sur la machine. |
| **Documentation remise dans le vrai** | Deux affirmations fausses corrigées, trois limites bloquantes ajoutées. |

## Phase 1 bis — la fondation est désormais éprouvée

| Livré | Preuve |
|---|---|
| **Banc de bout en bout, deux processus** (`tests/mesh/test_banc_deux_processus.py`) | Deux identités Ed25519 distinctes, un vrai socket, une commande signée qui traverse et arrive dans la boîte de l'hôte. Casser volontairement l'endpoint du transport fait rougir le banc — il mord. |
| **Anti-rejeu sur socket réel** | La même enveloppe livrée deux fois : la seconde est refusée, nonce dépensé en base. |
| **Instantané de contrat des routes** (`tests/contract/mesh_api_surface.json`) | 21 routes figées ; renommer `commands/poll` fait rougir deux tests. Un cliquet distinct garde les **cinq portes du téléphone** et vérifie qu'elles restent exemptées du mur d'authentification. |
| **Trou de capacités au jumelage corrigé** | La réponse du jumelage ne portait aucune capacité : un invité fraîchement jumelé se voyait refuser TOUT envoi (« ne peut pas faire cela ») jusqu'à la première balise. Découvert en préparant le banc. |

Pourquoi deux processus et pas deux instances : le quatrième contrôle de
`verify_command` refuse une commande venant de soi-même, et l'identité n'est
pas injectable — elle se lit toujours dans `$DIAPASON_HOME`, qui appartient
au processus. Deux nœuds dans un processus partageraient la même clé, donc
le même identifiant, et se refuseraient avant même de vérifier la signature.

## Phase 2 — le handoff

« Continue ce projet sur mon téléphone » suppose que « ce projet » ait un
référent. Il n'en avait aucun : les dix-neuf routes du frontend sont
statiques, la ressource sélectionnée vit en état local de composant, et le
serveur n'en savait rien.

| Livré | Où |
|---|---|
| **Le cliché de l'écran courant** — volatile (3 min), jamais persisté, miroir exact d'`etat_bureau` | `desktop/contexte_app.py`, route `/v1/context/view` |
| **L'interface le publie** — écran global, plus la ressource dans Projets et Notes | `frontend/src/features/mesh/` |
| **Le modèle le voit** — voix ET chat, mais PAS au même endroit : message système en FIN de contexte côté voix, concaténé à l'ancre en TÊTE côté chat | `local_voice._turn_messages`, `routes._ensure_identity_prompt` |
| **`handoff_continue`** — part de ce qu'on regarde, ne demande aucun identifiant | `tools/mesh_tools.py` |

### Ce que ce handoff refuse de faire

Le §68 demande un `viewState`. **Il n'est pas envoyé, et c'est délibéré** :
le client mobile ouvre un écran et met en évidence une tâche ou un projet ;
il ne sait restaurer ni onglet, ni filtre, ni position de défilement — ces
états sont privés à leurs widgets, sans point d'entrée externe. Un champ qui
voyage sans être lu finit toujours par se faire promettre, et le §5 interdit
précisément cela. Le jour où le Dart saura restaurer une vue, il l'annoncera
par une capacité déclarée — le seul canal de négociation qui existe, puisque
`appVersion` est toujours vide côté client.

Corollaire tenu dans le code : **la phrase rendue vient du récepteur**,
jamais de ce qu'on a envoyé.

### Deux défauts trouvés en le construisant

- **« Mon PC » désignait le téléphone.** Avec une flotte nommée « PC du
  bureau » et « Mon téléphone », le seul mot partagé était « mon », et
  « PC » tombait sous un filtre de longueur destiné au bruit. Le filtre
  visait juste et visait mal : ce n'est pas la longueur qui rend un mot
  inutile, c'est d'être un mot outil.
- **L'outil levait une exception au premier appel réel** — un registre
  paresseux non initialisé, invisible pour des tests qui remplaçaient tous
  la résolution. Un test exerce désormais le vrai chemin.

## Phase 3 — le transfert de fichiers

Un maillage de commandes ne transporte pas un fichier : ses enveloppes sont
courtes, sans état, et y ajouter un champ signé casserait toutes les
signatures du client mobile. Le transfert a donc sa propre session, ses
propres routes, son propre seau de limitation.

| Livré | Où |
|---|---|
| **Le cœur** — manifeste, découpage, reprise, intégrité, déduplication par contenu, finalisation atomique | `mesh/transfert.py` |
| **Le chiffrement de session** — X25519 éphémère signé Ed25519, HKDF, AES-256-GCM par morceau | `mesh/coffre.py` |
| **Les routes** — offre signée, morceaux authentifiés par jeton de session, plafond en octets | `mesh/files_routes.py` |
| **L'émetteur** | `mesh/envoi_fichier.py` |
| **Le banc réel** — 2 Mo en trois morceaux entre deux processus, plus deux tentatives d'intrusion refusées | `tests/mesh/test_banc_deux_processus.py` |

### Les décisions, et pourquoi

- **Le nom reçu est une donnée hostile.** `../../.ssh/authorized_keys` est
  un nom de fichier valide pour celui qui l'envoie.
- **Rien n'est visible avant d'être entier.** Les morceaux vont dans un
  `.partiel` anonyme ; un `os.replace` atomique fait apparaître le fichier
  d'un coup. Un partiel qui porterait déjà son nom final serait ouvert par
  quelqu'un, un jour, au milieu d'un transfert.
- **L'empreinte est recalculée sur le disque**, jamais déduite du compte des
  morceaux : croire l'émetteur sur parole n'est pas vérifier.
- **Le contenu est chiffré.** Les commandes sont signées et voyagent en
  clair — savoir qui parle suffit pour « ouvre cet écran ». Un document
  personnel sur un Wi-Fi partagé, non. Paire X25519 **éphémère** signée par
  la clé d'appareil : pas de conversion Ed25519 → X25519 (elle n'existe pas
  dans `cryptography`, et détourner une clé de signature pour de l'accord de
  clé se paie plus tard), et une clé volée demain ne déchiffre pas un
  transfert d'aujourd'hui. Nonce **dérivé de l'index** : le réutiliser est la
  seule façon de casser GCM, et l'index authentifié fait qu'un morceau
  déplacé devient illisible plutôt que silencieusement faux.
- **La signature garde la porte, le jeton garde le couloir.** L'offre est
  vérifiée par le même `verify_payload` que les balises — sept contrôles,
  révocation comprise — et rend un jeton de session à usage unique.
- **Le transfert a son propre seau.** Partager celui du maillage était le
  piège : un fichier en mille morceaux aurait vidé le seau commun et fait
  échouer présence et relèves des autres appareils. Et le vrai plafond n'est
  pas un débit mais un **volume**, appliqué dans le routeur : un limiteur de
  requêtes ne dit rien de la taille d'un corps.
- **L'invariant réciproque est désormais testé** : toute route hors du mur
  d'authentification doit être dans un seau connu. Le test existant ne
  verrouillait qu'un sens — c'était le bug historique que le code raconte.

### Ce qui n'est pas fait

Le client Flutter ne peut pas recevoir de fichier : il n'a ni sélecteur de
fichiers, ni accès au stockage, ni capacité déclarée pour cela. Le transfert
est donc **Diapason ↔ Diapason** aujourd'hui. Le jour où le Dart saura
recevoir, il l'annoncera par une capacité — et rien côté serveur ne bougera.

## Phase 4 — les gestes

Le moteur, la détection **et la source d'images** fonctionnent et sont
mesurés. Détail dans [`GESTES.md`](GESTES.md).

| Pièce | État | Mesure |
|---|---|---|
| Détection de main (`desktop/vision_mains.py`) | ✅ | **4 ms/image** en taille caméra — 230 im/s possibles, sur le Neural Engine, sans toucher au créneau Ollama |
| Moteur de gestes (`desktop/gestes_main.py`) | ✅ | 16 tests : machine à états, hystérésis, temps de repos, seuils centralisés |
| Latence de reconnaissance | ✅ mesurée | ≤ 10 images pour un « attraper », figée par un test |
| Flux caméra (la fenêtre Tauri, `useModeGestes.ts`) | ✅ | 12 im/s, 640 px, `getUserMedia` depuis un paquet signé — le mur est tombé |
| Trancher entre deux appareils | ✅ | `/v1/gestures/drop/target`, 14 tests |
| Fusion voix + geste | ✅ | La main se dit dans le contexte (voix ET chat) et `geste_deposer` l'envoie — 15 tests |
| État d'énergie (§83) | ✅ | `OFF / READY / ACTIVE / LOW_POWER` — 12 im/s suivi, 3 au repos, 2 sur batterie faible |

### Poser une question sans moyen d'y répondre est une impasse

Le §34 interdit de deviner une direction, et le §81 fait donc demander « vers
lequel ? » dès que deux appareils sont capables. C'était juste, et c'était
inutilisable : `_deposer()` appelait `lacher()` **en première instruction**,
avant même de savoir s'il existait une cible. La question consommait donc ce
qu'elle proposait d'envoyer. Refaire le geste ré-attrapait le même objet et
reposait la même question — une boucle sans issue, dont chaque tour laissait
une ligne « dépôt refusé » dans le journal.

Quatre corrections, chacune testée :

- **L'objet n'est lâché que sur une issue terminale** — un envoi effectué, ou
  un écran qu'aucun client ne connaît. `AMBIGUOUS`, `ALL_OFFLINE` et
  `INCAPABLE` gardent la main fermée ; le TTL de 120 s empêche qu'elle hante
  la session.
- **La question devient répondable** : `POST /v1/gestures/drop/target`
  `{token, deviceId}`, et `POST /v1/gestures/drop/cancel` pour « laisse
  tomber ». Le `deviceId` reçu doit figurer dans la liste que le serveur a
  lui-même mesurée — on choisit *parmi*, on ne désigne pas. Le jeton sert de
  clé d'idempotence : deux clics n'envoient qu'une fois.
- **La question s'affiche là où le geste a lieu.** Elle voyage par
  `pendingDrop` dans `/state`, et se rend dans le **voyant**, seul élément du
  mode monté sur toutes les pages. Le panneau ne vit que dans la page
  Appareils — c'est-à-dire jamais là où l'on attrape un projet.
- **Le fantôme est mort** : `held` venait de la session, le presse-papiers de
  son module, et les deux pouvaient se contredire. Le voyant annonçait « dans
  ta main : Zéro à Héro » sur une main vide. Vider l'un vide désormais
  l'autre, et désarmer vide les deux.

Et un cinquième défaut trouvé en le construisant : **un appareil joignable
qui ne déclare pas la capacité n'était pas écarté**. On posait donc une
question dont l'une des réponses était un refus garanti. Le fixture de test
qui aurait dû l'attraper décrivait des appareils sans aucune capacité — une
flotte qui n'existe pas.

**Le mur, dit franchement** : la demande d'accès revient refusée
immédiatement, sans dialogue, et le statut reste « à demander ». Ce n'est pas
l'utilisateur qui refuse — c'est TCC qui n'a rien à afficher, faute de
`NSCameraUsageDescription` dans un `Info.plist` que l'interpréteur n'a pas.
Aucun réglage ne corrige cela. Trois sorties possibles sont décrites dans
`GESTES.md` ; le choix appartient à Carlito.

## Ce qui vient ensuite, dans l'ordre

L'ordre du §149 tient, moins ce qui est déjà fait. Les phases 2, 3 et 4 sont
livrées ; ce qui suit est ce qu'elles ont laissé ouvert, du moins cher au
plus cher :

1. **Handoff complet** — `app.show_resource` en fait l'essentiel ; manquent
   l'état de vue et une session nommée. Les deux attendent le Dart : il ne
   sait restaurer ni onglet, ni filtre, ni position de défilement.
2. **Découverte (mDNS)** — aujourd'hui l'adresse LAN se tape à la main.
3. **Une application Windows** — c'est ce qui manque au MVP du §121, et
   c'est de loin le plus cher. Le premier MVP démontrable reste Mac ↔ Mac,
   puis Mac ↔ Android.

## Trois règles qui ne se négocient pas

Elles viennent de l'audit et cassent le client Flutter si on les enfreint :

1. **Aucun flottant dans une enveloppe signée.** Python écrit `1e-07`, Dart
   écrit `1e-7` : signatures invalides, sans un mot d'explication.
2. **Ne pas incrémenter `COMMAND_VERSION` ni `PULL_VERSION`** avant qu'un
   client Dart acceptant deux versions soit déployé. Le Dart écrit `1` en dur.
3. **Ne pas ajouter de champ à `_POLL_FIELDS` / `_ACK_FIELDS`.** La signature
   couvre une liste explicite ; un champ absent côté Dart y entre comme
   `null` et invalide toutes les relèves.

Ajouter des **capacités** et des **outils** est en revanche sûr par
construction : le plafond écarte les verbes inconnus, le refus a lieu avant
l'envoi, et un client ancien répond `UNSUPPORTED` — statut accepté.
