# Spatial Mesh — audit initial

*Phase 0 du cahier des charges « Diapason Spatial Mesh ». 25 août 2026.
17 agents d'audit, trois dépôts lus, aucune ligne de production modifiée
avant la rédaction de ce document.*

---

## Le constat qui change le plan

**Le chantier ne part pas de zéro : un Device Mesh existe déjà, et il est
vivant.** `src/diapason/mesh/` compte 16 modules et ~4 250 lignes, couvertes
par 261 tests. Il est monté (`server/api_routes.py:1086`), un battement de
cœur tourne dans le cycle de vie du serveur (`server/app.py:262`), le mur
d'authentification connaît ses routes nommément
(`server/auth_middleware.py:99-136`), et l'interface a sa page
(`frontend/src/pages/DevicesPage.tsx`, 537 lignes, route `/devices`).

Preuve d'exécution réelle, pas de montage : `~/.diapason/mesh.db` contient
**2 appareils TRUSTED et 14 commandes dont 11 en SUCCESS**, la dernière le
18 août 2026, avec un vrai téléphone Android. La chaîne complète —
signature Ed25519, vérification contre la clé enregistrée au jumelage,
nonce dépensé, exécution, accusé — a fonctionné de bout en bout.

**Et l'écosystème compte deux dépôts, pas un.** Le client multiplateforme
est *Succès* (`~/Desktop/Porfolio/Succes`), 23 336 lignes de Dart/Flutter,
avec son propre `lib/services/mesh/` (~1 100 lignes) et 828 lignes de tests
de maillage. Il cible six plateformes ; Android est réellement construit,
iOS à moitié préparé, les quatre autres sont des squelettes `flutter
create` jamais retouchés.

Conséquence directe sur le cahier des charges : **la Phase 1 (§107 — device
identity, registry, pairing, trust, presence, capabilities) est déjà
écrite.** Le §3 interdit de réécrire ce qui existe. Le travail de cette
phase n'est donc pas de construire la fondation, mais de **réparer les
trois défauts qui l'empêchent de porter**, décrits plus bas.

---

## Architecture détectée

```
Diapason (~/Projets/Diapason)                 Succès (~/Desktop/Porfolio/Succes)
├── src/diapason/          Python 3.13        ├── lib/            23 336 l. Dart
│   ├── mesh/         16 mod., 4 250 l.  ←──→ │   └── services/mesh/  1 111 l.
│   ├── server/       FastAPI, 127.0.0.1      │       (client de sondage HTTP)
│   ├── tools/        ~100 outils             ├── android/   construit
│   └── succes/       73 routes métier        ├── ios/       à moitié préparé
├── frontend/         React 19 + Vite 6       └── windows/macos/linux/web
│   ├── src/          → sert AUSSI le web         squelettes intouchés
│   └── src-tauri/    Tauri 2, Rust, 4 004 l.
└── rust/             17 crates, extension PyO3
```

**Quatre applications, pas plus** : le frontend React (un seul bundle servi
à la fois par le serveur Python et par Tauri), l'app de bureau Tauri, le
workspace Rust (une extension PyO3 obligatoire), et le cœur Python.
`desktop/` à la racine est un vestige mort (un binaire Ollama de 77 Mo et
une copie d'`overlay.html`, aucun Cargo.toml).

## Applications présentes

| Cible | État | Preuve |
|---|---|---|
| macOS (Tauri) | **Construit, installé, en usage** | `scripts/install-desktop.sh` |
| Web (PWA) | Produit par le même bundle | `frontend/vite.config.ts:33-52` |
| Android (Succès) | **Construit, appairé, 11 commandes réussies** | `mesh.db` |
| iOS (Succès) | Flanc préparé, jamais livré | `BUILD_IOS.md` |
| Windows | **N'existe pas** — squelette Flutter intouché | — |
| Linux | Squelette Flutter intouché | — |

## Technologies utilisées

Python 3.13 / FastAPI / SQLite (WAL) ; React 19, Vite 6, TypeScript 5.7,
Tailwind 4, react-router 7, zustand 5 ; Tauri 2 + Rust 1.88 ; Dart/Flutter
avec Riverpod ; Ollama local (`-np 1`, **un seul créneau d'inférence**),
Whisper, Kokoro, Vision d'Apple.

## Backend détecté

Il n'y a **pas de backend cloud**. Le serveur FastAPI tourne sur la machine
de l'utilisateur (launchd `com.diapason.serve`), écoute **127.0.0.1 par
défaut**, et le frontend Tauri a une CSP qui limite `connect-src` à
`'self'` + localhost (`tauri.conf.json:28`). Le §39 du cahier (relais
Internet) suppose un serveur qui n'existe pas et n'est pas souhaitable ici :
voir « Alternatives proposées ».

## Modèle de données

Bases SQLite dans `~/.diapason/` : `mesh.db` (appareils, invitations,
commandes, nonces), `knowledge.db` (savoir indexé, 4 000+ fragments),
`traces.db`, `succes.db`, `approvals.db`, `memory.db`. **Aucun système de
migration** — chaque magasin crée son schéma à l'ouverture.

## Authentification

Clé porteuse locale (`~/.diapason/auth`) sur toutes les routes, **sauf cinq
routes de maillage** délibérément ouvertes (`auth_middleware.py:99-115`) :
`pairings/redeem` (l'invitation à usage unique EST la créance) et
`commands/{deliver,poll,ack}` + `presence` (la signature Ed25519 est la
créance). Le téléphone ne détient jamais de clé d'API. Ces exemptions
vivent dans **deux listes écrites à la main** — voir Risques.

## Gestion des permissions

Elle existe et elle est sérieuse, à trois étages :

1. **Plafond de plateforme** (`mesh/capabilities.py:88-110`) —
   `PLATFORM_CAPABILITIES` : ce qu'une classe d'appareil peut honorer *en
   principe*. iOS/iPadOS excluent l'automatisation et l'écriture de
   fichiers ; le Web est client seul ; une plateforme inconnue tombe sur un
   plancher en lecture seule. Les capacités effectives sont
   l'**intersection** du déclaré et du plafond, jamais l'union.
2. **Catalogue fermé** (`mesh/tools.py`) — cinq verbes distants seulement,
   avec `FORBIDDEN_PARAMETER_NAMES` qui refuse structurellement tout
   paramètre nommé `command`, `path`, `url`, `sql`, `script`, `eval`… Le
   §54 du cahier est **déjà satisfait, et gardé par un test**.
3. **Cloche d'approbation** (`server/approval_bridge.py`) pour les outils
   qui la déclarent, avec notification macOS depuis le 24 août.

## Synchronisation actuelle

Le thread horaire des connecteurs (`connectors/scheduler.py`, 3 600 s) et
le battement de maillage (15 s). **Aucun mécanisme d'outbox/inbox,
d'événements de domaine, de versionnage optimiste ni de résolution de
conflits** côté Python — le §61-63 du cahier part de zéro. Côté Dart, une
fusion LWW avec pierres tombales existe pour les sous-tâches, testée.

## Capacités offline

Tout est local par nature. La file du maillage (`mesh/queue.py`) porte deux
politiques : `REQUIRE_ONLINE` et `QUEUE_UNTIL_EXPIRATION`. Le §100 (« jamais
de faux SUCCESS ») est **déjà respecté** : `dispatch.py` est la seule source
des phrases rendues, et chaque statut terminal porte une phrase vraie de ce
statut et d'aucun autre.

## Support deep links

Le protocole `success://` demandé au §21 **existe déjà des deux côtés** :
cinq routes adressables côté Dart (`mesh_routes.dart:49-60`), traduites en
vues, avec refus explicite d'une route inconnue plutôt qu'un écran
approchant. Côté React, `MeshHost.tsx` consomme la boîte de réception et
refuse de naviguer « à peu près ».

## Support temps réel

WebSocket pour la voix. Le maillage n'en utilise pas : il fonctionne par
**sondage** (le téléphone relève toutes les 2 s au premier plan) et par
livraison HTTP directe quand une adresse LAN est connue.

## Modules Diapason existants réutilisables

- `security/signing.py` — `generate_keypair`, `sign`, `verify`, base64.
  `cryptography>=43` est une dépendance **de base**, avec ce commentaire :
  « Ed25519 for device identity: the mesh cannot treat its own identity as
  optional ».
- `mesh/commands.py:287-392` — `verify_command` et ses **onze contrôles
  ordonnés** (version, flotte, destinataire, origine, expiration,
  signature, outil, schéma, capacités, confirmation, nonce en dernier).
- `mesh/resolver.py` — « mon PC » → appareil, avec statut `AMBIGUOUS` qui
  rend une **question prête à dire** incluant l'état de présence.
- `desktop/ocr.py` — le patron d'import paresseux d'un framework natif
  (Vision), à copier tel quel pour la caméra.
- Le patron de test de routeur FastAPI (`tests/mesh/test_routes.py:17-45`)
  et de magasin SQLite (`tests/mesh/test_registry.py:24-50`).

## Code potentiellement réutilisable pour les gestes

`VNDetectHumanHandPoseRequest` est **disponible dans le venv** (vérifié :
21 points articulaires, 2 mains). Il tourne sur le Neural Engine et ne
touche donc **pas** au créneau Ollama unique. Manque le flux caméra
(`pyobjc-framework-AVFoundation`) et l'entitlement
`com.apple.security.device.camera`, absent d'`Entitlements.plist`.

---

## Risques techniques

### Bloquants — découverts par cet audit, corrigés dans cette phase

1. **Deux Diapason ne peuvent pas se jumeler utilement.**
   `adopt_owner_id()` (`mesh/identity.py:121-144`) n'a **aucun appelant** —
   vérifié. Or `owner_id()` frappe un identifiant aléatoire local au premier
   appel, et `signed.py:107-111` refuse toute enveloppe dont l'`ownerId`
   diffère, *avant même de regarder la signature*. Deux installations
   obtiennent donc `TRUSTED` puis se refusent mutuellement chaque balise,
   chaque relève et chaque commande. Le protocole transmet pourtant
   l'`ownerId` de l'hôte dans la réponse au *redeem* : le client Python ne
   le consomme jamais. Le téléphone Dart, lui, l'adopte — c'est pourquoi le
   maillage marche avec Android et pas entre deux ordinateurs.
   **Les tests masquent le défaut** : `test_beacon.py:29` injecte le même
   `OWNER` des deux côtés.

2. **L'assistant n'a aucune main sur le maillage.** `mesh_devices` et
   `mesh_send` sont enregistrés mais absents de `_TROUSSE_ASSISTANT` —
   vérifié, zéro occurrence. 4 250 lignes sans une poignée. L'absence côté
   **voix** est délibérée, documentée et gardée par un test-fusible
   (`test_voice_boundary.py`) parce que `execute_voice_tool` court-circuite
   la cloche ; l'absence côté **chat** n'est justifiée nulle part.

3. **Aucune garde d'isolation pour les tests de maillage.** Il n'existe pas
   de `tests/mesh/conftest.py` — vérifié. `registry.py:110`, `queue.py:80` et
   `commands.py:226` retombent sur le vrai `~/.diapason/mesh.db`, et
   `identity.py:86` sur le vrai répertoire d'identité. **Un test distrait
   peut écraser la clé privée de la machine et orpheliner la flotte.**

### Élevés — documentés, à traiter

4. `_await_ack` appelle `time.sleep()` jusqu'à 4 s
   (`tools/mesh_tools.py:295-297`). Branché au chat sans passage par un
   thread, chaque envoi gèlerait la boucle d'événements — tout le serveur.
5. `resolver.py:92` compare par sous-chaîne sans frontière de mot : un
   appareil nommé « PC » marque 80 sur « ouvre epcot ». Un score unique en
   tête vaut `RESOLVED` : c'est une direction devinée, ce que le §34
   interdit.
6. **Les quatre routes `/v1/mesh` que le client Dart appelle ne sont figées
   par aucun instantané de contrat.** Le cliquet existant ne surveille que
   `/v1/succes`, que le Dart n'appelle pas. Renommer une route passe tous
   les tests des deux dépôts et casse le téléphone en silence.
7. **Le client Dart n'applique qu'un contrôle sur onze** (la signature). Ni
   version, ni destinataire, ni expiration, ni schéma ne sont vérifiés
   localement : il délègue entièrement à l'hôte.
8. Toute nouvelle route `/v1/mesh` part **derrière** le mur d'authentification
   et dans le mauvais seau de limitation, car les exemptions sont deux
   listes manuelles. Le téléphone reçoit un 401 traduit en « vérifie que
   l'ordinateur est allumé » — un diagnostic qui envoie chercher au mauvais
   endroit.

### Latents — à ne pas déclencher

9. **Ne jamais mettre de flottant dans une enveloppe signée.** Python écrit
   `1e-07`, Dart écrit `1e-7` : signatures invalides sans un mot
   d'explication. Règle : entiers ou chaînes, jamais de flottant. Cela
   condamne d'emblée l'idée d'une progression fractionnaire signée.
10. **Ne jamais incrémenter `COMMAND_VERSION` ni `PULL_VERSION`** avant
    d'avoir livré un client Dart qui accepte deux versions : le Dart écrit
    `1` en dur et ne lit jamais la version de l'hôte. Il n'y a pas de
    fenêtre de compatibilité aujourd'hui.
11. **Ne jamais ajouter de champ à `_POLL_FIELDS` / `_ACK_FIELDS`** : la
    signature couvre une liste explicite, un champ absent côté Dart y entre
    comme `null` et invalide toutes les relèves du téléphone.

## Limitations OS

- **iOS/iPadOS** : pas de caméra en arrière-plan, pas d'observation d'autres
  applications, pas de système de fichiers arbitraire. Le §29 du cahier est
  correct et le plafond de plateforme le code déjà.
- **macOS** : l'app est signée *ad hoc* (`signingIdentity: "-"`), donc le
  droit Accessibilité est révoqué à **chaque recompilation**.
- **Tauri** : aucune permission `fs`, `http` ni `shell` déclarée, et une CSP
  qui interdit au JS de joindre une adresse LAN. Un transfert direct entre
  appareils devra passer par le serveur Python, pas par le frontend.
- **Entitlements** : `com.apple.security.device.camera` **absent**. Aucun
  geste n'est possible avant de l'ajouter.

## Dette technique pertinente

*Cette liste est datée du 25 août 2026 au matin. Les lignes ~~barrées~~ ont
été traitées dans la journée ; elles restent ici parce qu'un audit qu'on
réécrit cesse d'être un constat.*

- ~~`MagicMock/load_config().security.audit_log_path/` à la racine : **44
  vraies bases SQLite** créées par un test qui a passé un `MagicMock` comme
  chemin. Le mécanisme est toujours actif.~~ **Traité.** Le répertoire est
  supprimé (42 fichiers, toutes bases vides). La cause n'était pas
  `__repr__` mais `__fspath__` : `Path(MagicMock())` rend
  « MagicMock/<nom>/<id> », et `AuditLogger` le créait sans broncher.
  `AuditLogger` refuse désormais ce qui n'est ni `str` ni `Path`, avec deux
  tests. Une passe complète (9 154 tests) ne le recrée plus.
- `src/diapason/evals/tests/` (~87 Ko de tests) est **hors** de
  `testpaths` : jamais collecté, mais livré dans la roue.
- ~~`.github/CODEOWNERS` désigne trois comptes étrangers au dépôt (héritage
  de fork) : si la règle de branche est active, aucune PR n'est
  débloquable.~~ **Traité.** Le fichier nomme `@carlitoetienne01-spec`,
  vérifié contre cinq sources (`git remote`, `pyproject.toml`, `mkdocs.yml`,
  `README.md`, l'endpoint de mise à jour Tauri). L'organisation
  `@open-diapason`, qui n'existe nulle part ailleurs, a disparu — ce dépôt
  vit sur un compte personnel, où un slug d'équipe est inopérant.
- ~~`desktop/` à la racine est un vestige mort (un binaire Ollama de 77 Mo et
  une copie d'`overlay.html`, aucun Cargo.toml).~~ **Traité.** Les deux
  fichiers étaient suivis par git et référencés nulle part : `overlay.html`
  était l'octet pour octet identique à celui de `frontend/src-tauri/src/`,
  et le binaire n'est sidecar d'aucun `tauri.conf.json` — la CI le télécharge
  à la demande dans `frontend/src-tauri/binaries/`, dont le `.gitignore`
  interdit précisément de le committer. 73 Mo de moins dans l'arbre de
  travail ; **rien de moins dans le clone**, le blob restant dans
  l'historique.
- **Aucun runner macOS n'exécute pytest**, et la CI n'installe ni `desktop`,
  ni `speech`, ni `voice-local`. Tout le code caméra/Vision/PyObjC est hors
  d'atteinte de la CI : il ne sera vérifié qu'à la main sur cette machine.
- La doc `docs/architecture/device-mesh.md` **ment sur deux points** : elle
  affirme que le modèle voit deux outils (il n'en voit aucun) et son tableau
  des actions omet `desktop.open`, la plus puissante des cinq — la seule qui
  pilote le bureau plutôt que l'application.

---

## Fonctionnalités immédiatement réalisables

- Réparer les trois défauts bloquants (cette phase).
- Compléter le chemin **invité** du jumelage : la route `redeem` existe et
  est testée, mais aucun client de ce dépôt ne l'appelle — ni écran
  « rejoindre », ni commande CLI.
- Ajouter des **capacités et des outils** au catalogue : sûr par
  construction. Le plafond écarte silencieusement les verbes inconnus, le
  refus a lieu avant l'envoi, et un client ancien répond `UNSUPPORTED` —
  statut accepté. Un vieux téléphone dégrade proprement au lieu de tomber.
- Figer les routes `/v1/mesh` dans un instantané de contrat.

## Fonctionnalités nécessitant des adaptations

- ~~**Transfert de fichiers** (§41-46) : rien n'existe. Le maillage actuel est
  un maillage de *commandes*, sans état, avec des enveloppes qui expirent.
  Une session de transfert reprenable demande un cycle de vie que ni
  `commands.py` ni `queue.py` ne portent. Chiffrer le contenu demande en
  plus un échange de clés de session (X25519) qui n'existe pas : aujourd'hui
  les enveloppes sont **signées, pas chiffrées**, et le transport est en
  clair sur le LAN.~~ **Traité** : session dédiée, X25519 + AES-256-GCM,
  consentement et banc physique Mac ↔ Windows validés au 28 août 2026.
- ~~**Gestes** : le framework est là, l'entitlement caméra et le flux ne le
  sont pas. Et la CI ne pourra jamais les vérifier.~~ **Traité** : entitlement,
  flux Tauri et moteur sont livrés ; la caméra reste vérifiée localement sur
  le Mac, pas par le runner.
- **Handoff** (§68) : `app.show_resource` en fait déjà l'essentiel. Ce qui
  manque est l'état de vue (`viewState`) et une session nommée.

## Fonctionnalités impossibles telles qu'imaginées

- ~~**Le MVP Mac ↔ Windows (§121)** : il n'y a pas d'application Windows. Le
  squelette Flutter de Succès n'a jamais été construit, et le portage
  demanderait au minimum un magasin sécurisé Windows et une campagne de
  tests. **Alternative** : le premier MVP démontrable est **Mac ↔ Mac**
  (deux instances), puis **Mac ↔ Android**, qui est déjà appairé et a déjà
  exécuté onze commandes.~~ **Traité le 28 août 2026** : un `.msi` Tauri de
  validation a été construit et installé sur le vrai PC, puis un fichier a
  traversé dans les deux sens avec une empreinte identique.
- **Relais Internet (§39)** : suppose un serveur que l'architecture n'a pas
  et que la promesse de confidentialité de ce projet écarte. **Alternative** :
  rester en LAN direct + sondage, et n'ouvrir la question que si un besoin
  réel de hors-réseau apparaît.
- **Direction spatiale / UWB (§35-36)** : aucun matériel de la flotte ne
  mesure une direction. Le §34 l'anticipe correctement — le repli par nom,
  proximité et choix explicite est déjà ce que fait `resolver.py`.
- **Caméra en arrière-plan permanente** : interdite sur iOS, coûteuse
  ailleurs. Le §83 (`OFF / READY / ACTIVE / LOW_POWER`) est la bonne réponse.

## Alternatives proposées

1. **Réparer avant d'étendre.** Les trois défauts bloquants coûtent moins
   d'une journée et rendent vivantes 4 250 lignes déjà écrites. Aucune
   fonctionnalité neuve n'a autant de valeur par ligne.
2. ~~**MVP Mac ↔ Mac puis Mac ↔ Android**, au lieu de Mac ↔ Windows.~~ Le MVP
   physique Mac ↔ Windows est désormais la preuve obtenue.
3. **Le transfert de fichiers ne passe pas par l'enveloppe de commande** :
   une session dédiée, avec son propre cycle de vie, et la commande ne porte
   que l'*offre*. Cela évite de toucher aux champs signés — ce qui casserait
   le téléphone.
4. **Les gestes en dernier, derrière un drapeau**, et jamais comme unique
   chemin vers une action (§82).

---

## Ce que cette phase livre

Conformément au §157 — « si une partie de ma demande… crée l'alternative
techniquement correcte puis continue » — la Phase 1 livre les **réparations
de la fondation existante** plutôt qu'une fondation en double :

1. La garde d'isolation des tests de maillage (protège la clé privée).
2. L'adoption de l'identité de flotte au jumelage (deux Diapason peuvent
   enfin se joindre), avec le chemin invité complet.
3. La main de l'assistant sur le maillage, gardée par un test symétrique de
   celui qui garde l'abstention côté voix.
4. La documentation remise dans le vrai.

Chaque point est vérifié sur la machine, pas seulement testé.
