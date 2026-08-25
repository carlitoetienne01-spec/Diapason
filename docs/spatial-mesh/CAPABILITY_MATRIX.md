# Matrice des capacités — état réel au 25 août 2026

*Engendrée depuis le code (`mesh/capabilities.py`) et depuis l'état constaté
de la flotte, pas depuis une intention. Le §28 du cahier des charges demande
que cette matrice « provienne des capacités réelles » : elle en provient.*

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
lecture seule** — fail-closed, et c'est le bon défaut.

Deux entrées de cette table n'ont **aucun producteur** : `IPADOS` et `WEB`
n'existent aujourd'hui que comme code de plafond, qu'aucun client ne
traverse. `WEB` accorde `app.open` et refuse `notifications.show`, ce qui est
probablement l'inverse de ce qu'un navigateur moderne sait faire — à revoir
le jour où un client web apparaîtra.

## 2. Ce que le cahier des charges demande (§28), confronté au réel

| Fonction demandée | macOS | Windows | Android | iOS/iPadOS | Web | Note |
|---|:--:|:--:|:--:|:--:|:--:|---|
| **Jumelage** | ✅ | ❌ | ✅ | ⚠️ | ❌ | Windows : aucune app. Android : constaté, 2 appareils en base. |
| **Présence** | ✅ | ❌ | ✅ | ⚠️ | ❌ | Dérivée d'un horodatage, pas d'une connexion tenue. |
| **Handoff interne** (`success://`) | ✅ | ❌ | ✅ | ⚠️ | ❌ | 11 commandes réellement abouties. |
| **Chiffrement** | ⚠️ | — | ⚠️ | — | — | Enveloppes **signées** (Ed25519), transport **en clair** sur le LAN. Pas de chiffrement de bout en bout. |
| **Hors-ligne** | ✅ | — | ✅ | — | — | File avec deux politiques ; jamais de faux succès. |
| **Transfert de fichiers** | ❌ | ❌ | ❌ | ❌ | ❌ | **N'existe pas.** Rien dans `mesh/`. |
| **Suivi de main** | 🚧 | ❌ | ❌ | ❌ | ❌ | Vision présent (21 points, 2 mains) ; entitlement caméra **absent**, flux caméra absent. |
| **OPEN / FIST / GRAB / RELEASE** | ❌ | ❌ | ❌ | ❌ | ❌ | Rien. |
| **Cible spatiale / direction** | ❌ | ❌ | ❌ | ❌ | ❌ | Aucun matériel de la flotte ne mesure une direction. §34 s'applique : repli par nom. |
| **Fusion voix + geste** | ❌ | ❌ | ❌ | ❌ | ❌ | Le contexte du tour vocal est le point d'insertion prévu. |
| **Fichiers de l'app** | ⚠️ | ❌ | ⚠️ | ❌ | ❌ | Capacité déclarable, aucun outil qui l'exerce. |
| **Système de fichiers arbitraire** | ❌ | ❌ | ❌ | ❌ | ❌ | Interdit par construction (`FORBIDDEN_PARAMETER_NAMES`). |
| **Arrière-plan permanent** | ⚠️ | — | ⚠️ | ❌ | ❌ | Android : sondage au premier plan seulement, limite écrite dans l'interface. iOS : interdit. |
| **Nearby / découverte** | ❌ | ❌ | ❌ | ❌ | ❌ | Aucun mDNS, aucun Bluetooth. Adresse LAN tapée à la main. |
| **Assistant → maillage** | ❌ | — | — | — | — | Outils écrits, **absents de la trousse**. Corrigé dans cette phase. |

## 3. L'état réel de la flotte

| Appareil | Plateforme | Transport | Confiance | Dernier contact |
|---|---|---|---|---|
| Cette machine | macOS / laptop | — | soi | permanent |
| « PC du bureau » | Windows / desktop | `lan` (`127.0.0.1:8100`) | TRUSTED | 17 août 2026 |
| « Mon téléphone » | Android / phone | `pull` | TRUSTED | 18 août 2026 |

**14 commandes émises, 11 en SUCCESS, 2 hors-ligne, 1 expirée.** Le « PC du
bureau » pointe vers une seconde instance sur *cette* machine, pas vers un
vrai second ordinateur : le seul pair réellement distant est le téléphone.
La flotte est en sommeil depuis sept jours.

## 4. Ce qui bloque chaque case ❌ importante

| Case | Ce qui manque exactement |
|---|---|
| Windows, toutes lignes | Une application. Le squelette Flutter n'a jamais été construit. |
| Transfert de fichiers | Une session avec cycle de vie (le maillage est sans état), un échange de clés X25519, un manifeste et des morceaux. **Ne doit pas passer par l'enveloppe de commande** : y toucher casse le téléphone. |
| Suivi de main | `com.apple.security.device.camera` dans `Entitlements.plist`, `pyobjc-framework-AVFoundation`, et un état d'énergie (§83). |
| Découverte | Un service mDNS et l'écoute sur autre chose que `127.0.0.1`. |
| Chiffrement de bout en bout | Aujourd'hui les enveloppes sont signées ; le contenu voyage en clair. Suffisant sur un LAN de confiance, insuffisant dès qu'un relais existe. |

---

*Cette matrice se relit avec `INITIAL_AUDIT.md`, qui explique **pourquoi**
chaque case est dans cet état.*
