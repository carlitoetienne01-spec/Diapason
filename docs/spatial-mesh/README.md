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

## Ce qui vient ensuite, dans l'ordre

L'ordre du §149 tient, moins ce qui est déjà fait :

1. **Handoff complet** — `app.show_resource` en fait l'essentiel ; manquent
   l'état de vue et une session nommée.
3. **Transfert de fichiers** — session dédiée, jamais dans l'enveloppe de
   commande. Voir les trois règles à ne pas enfreindre dans l'audit.
4. **Gestes** — entitlement caméra, flux, machine à états, et un drapeau.
   Jamais l'unique chemin vers une action (§82).

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
