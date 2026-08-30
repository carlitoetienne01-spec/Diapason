# Matrice des capacités — état réel au 28 août 2026

*Engendrée depuis le code (`mesh/capabilities.py`, `mesh/tools.py`) et depuis
l'état constaté de la flotte par l'API locale, pas depuis une intention. Le
§28 du cahier des charges demande que cette matrice « provienne des capacités
réelles » : elle en provient.*

> **Pourquoi cette page a été refaite.** La version précédente datait du même
> jour, à 1 h 14 — avant les phases 3 et 4. Onze commits l'ont périmée en
> quinze heures : elle annonçait « Transfert de fichiers : n'existe pas » et
> « OPEN / FIST / GRAB / RELEASE : rien » alors que les deux étaient livrés et
> testés le matin même. Une matrice qui sous-estime ce qui existe fait
> reconstruire du travail déjà fait — c'est le défaut exact que le §3 interdit.
> Toute modification du maillage ou des gestes doit désormais repasser ici.

Légende : ✅ fonctionnel et constaté · ⚠️ limité ou non éprouvé ·
❌ non supporté · 🚧 en développement · — sans objet

---

## 1. Ce que le maillage sait faire, par plateforme

Le plafond (`PLATFORM_CAPABILITIES`) dit ce qu'une classe d'appareil peut
honorer **en principe**. Les capacités effectives sont l'**intersection** de
ce qu'un appareil déclare et de ce plafond — jamais l'union.

| Capacité | macOS | Windows | Linux | Android | iOS | iPadOS | Web | Inconnu |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| `app.navigate` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| `app.open` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| `app.show_resource` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| `notifications.show` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `desktop.open` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `automation.approved.run` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `local_ai.available` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `tasks` / `projects` / `notes` / `habits` / `planning` (lecture) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| idem (écriture) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| `voice.input` / `voice.output` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |

**19 capacités déclarables. Une plateforme inconnue tombe sur un plancher en
lecture seule** — fail-closed, et c'est le bon défaut. Cardinalités recomptées
depuis le code : macOS/Windows/Linux 19, Android/iOS/iPadOS 16, Web 13,
Inconnu 5.

Elles étaient 21 jusqu'au 25 août 2026 : `filesystem.workspace.read` et
`.write` ont été **retirées**. Personne ne les avait jamais déclarées — un
Diapason DÉRIVE sa déclaration du catalogue d'outils (cinq verbes, aucun qui
touche un fichier), le client Dart en déclare trois, et les deux appareils
réellement appairés quatre et trois. Elles laissaient pourtant croire
qu'elles gouvernaient `/v1/mesh/files`, qui ne les a jamais consultées.
Android et iOS ont désormais le même plafond : le seul verbe qui les
distinguait était celui-là.

**Cinq colonnes sur huit n'ont aucun producteur.** La base ne contient que
`WINDOWS` et `ANDROID` ; aucun client `LINUX`, `IOS`, `IPADOS`, `WEB` ni
`UNKNOWN` n'existe, ici ou dans Succès. Ce sont des plafonds écrits d'avance,
pas des chemins éprouvés. (La version précédente n'en signalait que deux.)

Quand un client web apparaîtra, `WEB` est à revoir : il accorde `app.open` et
refuse `notifications.show`, ce qui est probablement l'inverse de ce qu'un
navigateur moderne sait faire.

### Le catalogue fermé : cinq verbes, dont quatre visibles du modèle

| Verbe | Paramètres | Confirmation | Hors-ligne |
|---|---|:--:|---|
| `app.navigate` | `route` | non | REQUIRE_ONLINE |
| `app.open` | *(aucun)* | non | REQUIRE_ONLINE |
| `app.show_resource` | `resourceType` (task/project/note/habit), `resourceId` | non | QUEUE_UNTIL_EXPIRATION |
| `desktop.open` | `target`, `kind` (auto/app/url/search/file) | **oui** | REQUIRE_ONLINE |
| `notifications.show` | `title`, `body` | non | QUEUE_UNTIL_EXPIRATION |

`desktop.open` est retiré de ce que le modèle voit (`_HORS_PORTEE_DU_MODELE`,
`tools/mesh_tools.py`) : c'est la seule qui pilote le bureau plutôt que
l'application. Le modèle n'a donc accès qu'à **quatre** de ces cinq verbes.

---

## 2. Ce que le cahier des charges demande (§28), confronté au réel

| Fonction demandée | macOS | Windows | Android | iOS/iPadOS | Web | Note |
|---|:--:|:--:|:--:|:--:|:--:|---|
| **Jumelage** | ✅ | ✅ | ✅ | ⚠️ | ❌ | Le vrai PC Windows `SUCCES` et le Mac sont appairés, chacun avec l'identité et la clé publique actuelles de l'autre. Android : constaté, 2 appareils en base. |
| **Présence** | ✅ | ✅ | ✅ | ⚠️ | ❌ | Le 28 août, le Mac voyait `SUCCES` `ONLINE` à `192.168.0.198:8001`. Présence dérivée d'un horodatage, pas d'une connexion tenue. |
| **Handoff interne** (`success://`) | ✅ | ⚠️ | ✅ | ⚠️ | ❌ | Windows déclare les verbes requis, mais aucun handoff de ressource n'a encore été vérifié sur le PC physique. |
| **Chiffrement** | ⚠️ | ⚠️ | ⚠️ | — | — | **Fichiers : bout en bout**, éprouvé Mac ↔ Windows (X25519 éphémère + AES-256-GCM, `mesh/coffre.py`). **Commandes : signées, en clair** (Ed25519). La distinction est délibérée — voir §4. |
| **Hors-ligne** | ✅ | — | ✅ | — | — | File avec deux politiques ; jamais de faux succès. |
| **Transfert de fichiers** | ✅ | ✅ | ❌ | ❌ | ❌ | **Livré et éprouvé sur deux machines physiques** : le 28 août, `NOTICE` (479 octets) a traversé Mac → Windows puis Windows → Mac ; les deux copies ont l'empreinte SHA-256 `0b8c2b5250940ddbb954b74c0dbac1e4e28b7a86f1934a3c9796d5549b591f60`. Manifeste, chiffrement, reprise, réception automatique réservée aux pairs `TRUSTED`, animation après empreinte vérifiée et finalisation atomique. **Diapason ↔ Diapason seulement** : le client Dart ne sait pas recevoir. La nouvelle expérience physique attend le déploiement de ce lot sur les deux machines. |
| **Suivi de main** | ✅ | ❌ | ❌ | ❌ | ❌ | **Livré.** Vision (21 points, 2 mains) à 4 ms/image ; entitlement caméra et `NSCameraUsageDescription` **présents** dans le paquet Tauri ; flux par `getUserMedia` à une cadence que le SERVEUR décide (§83 : 12 im/s transfert, 24 pointeur suivi, 3 au repos, 2 sur batterie faible), images lues en mémoire, jamais écrites. |
| **OPEN / FIST / GRAB / RELEASE** | ✅ | ❌ | ❌ | ❌ | ❌ | **Livré**, sous leurs noms français : poses `PAUME_OUVERTE` et `POING` ; états `SAISI` (GRAB) et `RELACHE` (RELEASE). Hystérésis, confirmation sur N images, temps de repos — chacun testé. `PINCE` et `POINTE` ont été retirées le 25 août 2026 : la machine à états ne les consultait pas, et `PINCE` était classée AVANT le poing — un poing serré, pouce contre l'index, ne saisissait donc rien. |
| **Sélecteur d'appareils au poing** | ⚠️ | ❌ | ❌ | ❌ | ❌ | Livré et testé automatiquement sur macOS : tous les pairs joignables et capables sont rendus, un déplacement franc change le surlignage, la paume ouverte confirme. ⚠️ jusqu'au banc physique caméra après reconstruction de l'app. Le clic et la voix restent disponibles. |
| **Curseur / clic / double-clic / défilement** | ⚠️ | ❌ | ❌ | ❌ | ❌ | Vocabulaire `POINTER` : pince figée ; scroll vertical dominant ≥ 500 ms. Paume→dos active l’app visible suivante (pas ⌘Tab) ; pince + bord → Spaces. Bande basse tenue → minimiser / capture (`screencapture`) / fermer. Diapason cède le premier plan avant ⌘W/⌘M. |
| **Cible spatiale / pointage physique** | ❌ | ❌ | ❌ | ❌ | ❌ | Aucun matériel de la flotte ne mesure où l'on pointe. Le sélecteur ci-dessus ne le prétend pas : le mouvement déplace un choix **visible**, sans attribuer une position réelle aux appareils (§34). |
| **Fusion voix + geste** | ✅ | ❌ | ❌ | ❌ | ❌ | **Livrée** : `geste_deposer` (`tools/gestes_spatiaux.py`) envoie ce que la MAIN tient — jamais ce que le modèle nomme — et répond à la question « vers lequel ? ». La main se dit dans le contexte, voix ET chat. Banc : `tests/tools/test_geste_deposer.py`, **18 tests** — les 15 de la fusion que compte [`GESTES.md`](GESTES.md), plus trois qui gardent le refus d'un appareil inventé et la cloche de `mesh_send`. L'outil n'est **pas** derrière cette cloche, délibérément ; `mesh_send`, qui choisit et l'objet et la cible, l'est désormais. L'armement, lui, reste **sonore** (le double-clap arme le mode gestes) : du niveau sonore, pas de la parole. |
| **Fichiers de l'app** | ✅ | ✅ | ❌ | ❌ | ❌ | Le transfert écrit dans le dossier privé `.diapason/transfers` de chaque système, sous un nom assaini, jamais en écrasant. Sur Mac, le dialogue Tauri prépare un fichier, une photo ou une vidéo que le geste envoie ; Windows reçoit et peut émettre par la CLI. Un pair `TRUSTED` est accepté automatiquement, plafond 2 Gio, confirmation finale signée. **Aucune capacité** — et plus aucune ne prétend le contraire. |
| **Système de fichiers arbitraire** | ❌ | ❌ | ❌ | ❌ | ❌ | Interdit par construction (`FORBIDDEN_PARAMETER_NAMES`, 12 noms). |
| **Arrière-plan permanent** | ⚠️ | — | ⚠️ | ❌ | ❌ | Android : sondage au premier plan seulement. iOS : interdit. |
| **Nearby / découverte** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | mDNS livré en Python multiplateforme : pseudonyme opaque tournant, aucun nom ni identifiant diffusé, et l'adresse n'est retenue qu'après une balise Ed25519 du pair. Le socket LAN et les échanges entre deux machines physiques sont validés ; il reste à isoler la preuve que l'adresse est retrouvée par multicast plutôt que conservée du jumelage. Aucun Bluetooth. |
| **Assistant → maillage** | ✅ | — | — | — | — | `mesh_devices`, `mesh_send` et `handoff_continue` sont dans `_TROUSSE_ASSISTANT`. L'abstention côté **voix** reste délibérée et gardée par un test. |

---

## 3. L'état réel de la flotte

Lu par l'API locale du Mac le 28 août 2026 à 1 h 59.

| Appareil | Plateforme | Transport | Confiance | Dernier contact (heure locale) |
|---|---|---|---|---|
| Cette machine | macOS / laptop | — | soi (jamais dans son propre registre) | permanent |
| `SUCCES` | Windows / laptop | `lan` (`192.168.0.198:8001`) | TRUSTED, `SCELLE`, ONLINE | **28 août 2026, 1 h 59** |
| « Mon téléphone » | Android / phone | `pull` | TRUSTED, OFFLINE | 18 août 2026, 15 h 29 |

**16 commandes émises : 11 SUCCESS, 3 EXPIRED, 2 OFFLINE.**

Trois précisions que la version précédente taisait :

- L'ancien « PC du bureau » de banc a été remplacé par `SUCCES`, le vrai PC
  Windows. Son adresse LAN, sa présence et son application Diapason 1.0.0 ont
  été constatées depuis le Mac.
- L'historique des commandes précède ce PC physique : ses anciens SUCCESS ne
  prouvent donc aucun handoff vers `SUCCES`. C'est pourquoi la case Windows du
  handoff reste ⚠️ malgré les capacités qu'il déclare.
- Deux `app.show_resource` créées le 25 août à 5 h ont **expiré** — le banc du
  handoff. Le maillage n'a donc pas dormi sept jours sans rien tenter ; il a
  tenté, et personne n'écoutait.

Trois invitations dorment en base, toutes du 25 août vers 1 h 23, toutes
expirées ; une seule avait été utilisée.

---

## 4. Ce qui bloque chaque case ❌ ou ⚠️ importante

| Case | Ce qui manque exactement |
|---|---|
| Distribution Windows | Le bootstrap, le service, l'extension native, le runner, le `.msi` de validation, la fenêtre Tauri et le banc Mac ↔ Windows sont verts sur le PC réel. Il manque encore une release signée, son updater et une procédure de publication reproductible ; l'artefact installé n'est pas présenté comme un installateur public. |
| Transfert vers un téléphone | Le client Dart n'a ni sélecteur de fichiers, ni accès au stockage, ni capacité déclarée pour recevoir. Rien ne bougera côté serveur le jour où il l'annoncera. |
| Sélecteur gestuel | Le contrat et les bancs de coordonnées/React sont verts. Il reste à reconstruire l'app Mac et à faire le geste devant la vraie caméra ; jusque-là la case reste ⚠️, pas ✅. |
| Découverte | Le service mDNS existe désormais (`mesh/discovery.py`, `zeroconf`). Il ne publie qu'un pseudonyme tournant et `v=1`, puis exige une balise signée avant de retenir l'adresse. Les deux sockets LAN et le trafic entre machines physiques sont validés. Il reste un banc ciblé qui efface une adresse connue et prouve que mDNS seul la rétablit ; sans lui, le succès du transfert ne distingue pas découverte et adresse conservée au jumelage. |
| Chiffrement des **commandes** | Elles sont signées, pas chiffrées. Suffisant sur un LAN de confiance — savoir qui parle suffit pour « ouvre cet écran » — et insuffisant dès qu'un relais existe. Les **fichiers**, eux, sont chiffrés : un document personnel sur un Wi-Fi partagé n'est pas une commande. |

---

*Cette matrice se relit avec [`INITIAL_AUDIT.md`](INITIAL_AUDIT.md), qui
explique **pourquoi** chaque case est dans cet état, et avec
[`GESTES.md`](GESTES.md) pour le détail du mur caméra et de sa levée.*
