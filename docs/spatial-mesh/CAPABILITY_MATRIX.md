# Matrice des capacités — état réel au 25 août 2026, 17 h

*Engendrée depuis le code (`mesh/capabilities.py`, `mesh/tools.py`) et depuis
l'état constaté de la flotte (`~/.diapason/mesh.db`, lu en lecture seule), pas
depuis une intention. Le §28 du cahier des charges demande que cette matrice
« provienne des capacités réelles » : elle en provient.*

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
| `filesystem.workspace.read` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `filesystem.workspace.write` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `local_ai.available` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `tasks` / `projects` / `notes` / `habits` / `planning` (lecture) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| idem (écriture) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| `voice.input` / `voice.output` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |

**21 capacités déclarables. Une plateforme inconnue tombe sur un plancher en
lecture seule** — fail-closed, et c'est le bon défaut. Cardinalités :
macOS/Windows/Linux 21, Android 17, iOS/iPadOS 16, Web 13, Inconnu 5.

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
| **Jumelage** | ✅ | ❌ | ✅ | ⚠️ | ❌ | Windows : aucune app. Android : constaté, 2 appareils en base. |
| **Présence** | ✅ | ❌ | ✅ | ⚠️ | ❌ | Dérivée d'un horodatage, pas d'une connexion tenue. |
| **Handoff interne** (`success://`) | ✅ | ❌ | ✅ | ⚠️ | ❌ | 11 commandes réellement abouties. |
| **Chiffrement** | ⚠️ | — | ⚠️ | — | — | **Fichiers : bout en bout** (X25519 éphémère + AES-256-GCM, `mesh/coffre.py`). **Commandes : signées, en clair** (Ed25519). La distinction est délibérée — voir §4. |
| **Hors-ligne** | ✅ | — | ✅ | — | — | File avec deux politiques ; jamais de faux succès. |
| **Transfert de fichiers** | ✅ | ❌ | ❌ | ❌ | ❌ | **Livré** : `mesh/transfert.py`, `coffre.py`, `files_routes.py`, `envoi_fichier.py`. Manifeste, morceaux de 1 Mio, reprise, finalisation atomique. Banc réel entre deux processus. **Diapason ↔ Diapason seulement** : le client Dart ne sait pas recevoir. |
| **Suivi de main** | ✅ | ❌ | ❌ | ❌ | ❌ | **Livré.** Vision (21 points, 2 mains) à 4 ms/image ; entitlement caméra et `NSCameraUsageDescription` **présents** dans le paquet Tauri ; flux à 12 im/s par `getUserMedia`, images lues en mémoire, jamais écrites. |
| **OPEN / FIST / GRAB / RELEASE** | ✅ | ❌ | ❌ | ❌ | ❌ | **Livré**, sous leurs noms français : poses `PAUME_OUVERTE`, `POING`, `PINCE`, `POINTE` ; états `SAISI` (GRAB) et `RELACHE` (RELEASE). Hystérésis, confirmation sur N images, temps de repos — chacun testé. |
| **Cible spatiale / direction** | ❌ | ❌ | ❌ | ❌ | ❌ | Aucun matériel de la flotte ne mesure une direction. §34 s'applique : repli par nom, puis question explicite — et la question est désormais **répondable** (`/v1/gestures/drop/target`). |
| **Fusion voix + geste** | ❌ | ❌ | ❌ | ❌ | ❌ | Aucune fusion. Un armement **sonore** existe (le double-clap arme le mode gestes) mais c'est du niveau sonore, pas de la parole. |
| **Fichiers de l'app** | ⚠️ | ❌ | ⚠️ | ❌ | ❌ | `filesystem.workspace.*` est déclarable mais **aucun outil ne l'exerce** : le transfert écrit dans `get_data_dir()/transfers` sans consulter cette capacité. |
| **Système de fichiers arbitraire** | ❌ | ❌ | ❌ | ❌ | ❌ | Interdit par construction (`FORBIDDEN_PARAMETER_NAMES`, 12 noms). |
| **Arrière-plan permanent** | ⚠️ | — | ⚠️ | ❌ | ❌ | Android : sondage au premier plan seulement. iOS : interdit. |
| **Nearby / découverte** | ❌ | ❌ | ❌ | ❌ | ❌ | Aucun mDNS, aucun Bluetooth. Adresse LAN tapée à la main. |
| **Assistant → maillage** | ✅ | — | — | — | — | `mesh_devices`, `mesh_send` et `handoff_continue` sont dans `_TROUSSE_ASSISTANT`. L'abstention côté **voix** reste délibérée et gardée par un test. |

---

## 3. L'état réel de la flotte

Lu dans `~/.diapason/mesh.db`, le 25 août 2026 à 17 h.

| Appareil | Plateforme | Transport | Confiance | Dernier contact (heure locale) |
|---|---|---|---|---|
| Cette machine | macOS / laptop | — | soi (jamais dans son propre registre) | permanent |
| « PC du bureau » | Windows / desktop | `lan` (`127.0.0.1:8100`) | TRUSTED | **16 août 2026, 22 h 34** |
| « Mon téléphone » | Android / phone | `pull` | TRUSTED | 18 août 2026, 15 h 29 |

**16 commandes émises : 11 SUCCESS, 3 EXPIRED, 2 OFFLINE.**

Trois précisions que la version précédente taisait :

- Le « PC du bureau » pointe vers une **seconde instance sur cette machine**,
  pas vers un vrai second ordinateur. Le seul pair réellement distant est le
  téléphone.
- **Cinq des onze SUCCESS visaient des appareils de banc effacés depuis.** Vers
  des pairs encore inscrits : 4 vers le PC, 2 vers le téléphone.
- Deux `app.show_resource` créées le 25 août à 5 h ont **expiré** — le banc du
  handoff. Le maillage n'a donc pas dormi sept jours sans rien tenter ; il a
  tenté, et personne n'écoutait.

Trois invitations dorment en base, toutes du 25 août vers 1 h 23, toutes
expirées ; une seule avait été utilisée.

---

## 4. Ce qui bloque chaque case ❌ ou ⚠️ importante

| Case | Ce qui manque exactement |
|---|---|
| Windows, toutes lignes | **Une application.** Le squelette Flutter de Succès n'a jamais été construit. C'est ce qui rend le MVP Mac ↔ Windows du §121 inatteignable tel qu'écrit ; le premier MVP démontrable est Mac ↔ Mac, puis Mac ↔ Android. |
| Transfert vers un téléphone | Le client Dart n'a ni sélecteur de fichiers, ni accès au stockage, ni capacité déclarée pour recevoir. Rien ne bougera côté serveur le jour où il l'annoncera. |
| Gestes — état d'énergie (§83) | La cadence est figée à 12 im/s. Aucun `OFF / READY / ACTIVE / LOW_POWER`, aucune adaptation sur batterie. **C'est le seul point du §83 encore ouvert** : les quatre chemins d'extinction, eux, existent et sont testés. |
| `desktop/camera.py` | Session AVFoundation native, écrite, **importée nulle part** : du code mort. Ce n'est pas elle qui alimente les gestes — c'est la fenêtre Tauri. À supprimer ou à assumer. |
| Découverte | Un service mDNS, et l'écoute sur autre chose que `127.0.0.1`. |
| Chiffrement des **commandes** | Elles sont signées, pas chiffrées. Suffisant sur un LAN de confiance — savoir qui parle suffit pour « ouvre cet écran » — et insuffisant dès qu'un relais existe. Les **fichiers**, eux, sont chiffrés : un document personnel sur un Wi-Fi partagé n'est pas une commande. |
| Fusion voix + geste | Le contexte du tour vocal est le point d'insertion prévu. Attention : `handoff_continue` repart de l'écran courant, **pas** du presse-papiers spatial — répondre « sur l'iPad » à la voix enverrait ce qui est affiché, pas ce qui est dans la main. |
| `filesystem.workspace.*` | Une capacité que rien n'exerce est une promesse en attente. Soit un outil la consomme, soit elle sort du catalogue. |

---

*Cette matrice se relit avec [`INITIAL_AUDIT.md`](INITIAL_AUDIT.md), qui
explique **pourquoi** chaque case est dans cet état, et avec
[`GESTES.md`](GESTES.md) pour le détail du mur caméra et de sa levée.*
