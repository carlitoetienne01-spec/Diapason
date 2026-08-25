# Les gestes — ce qui marche, et le seul mur qui reste

*25 août 2026. Phase 4 du cahier des charges (§110, §141).*

## En une phrase

Le moteur de gestes et la détection de main **fonctionnent et sont mesurés** ;
il manque uniquement une **source d'images**, parce que macOS refuse la
caméra au processus Python — et refuse pour une raison qu'aucun réglage ne
corrige.

## Ce qui est livré et vérifié

| Pièce | État | Mesure |
|---|---|---|
| **Détection de main** (`desktop/vision_mains.py`) | ✅ | **4 ms par image** en taille caméra, soit 230 images/s possibles. Sur le Neural Engine : le créneau Ollama n'est pas touché. |
| **Moteur de gestes** (`desktop/gestes_main.py`) | ✅ | 16 tests. Machine à états, hystérésis, temps de repos, seuils centralisés. |
| **Latence de reconnaissance** | ✅ mesurée | ≤ 10 images pour un « attraper », soit ~0,4 s à 15 im/s. Figée par un test. |
| **Flux caméra** (`desktop/camera.py`) | ⚠️ écrit, **bloqué** | Voir ci-dessous. |

### Ce que le moteur refuse de faire, et c'est le point

Le §11 est la règle qui structure tout : **ne jamais déclencher depuis une
seule image**. Une main qui passe devant l'objectif ressemble à un poing
pendant deux ou trois images — c'est ainsi qu'un document part tout seul.
Trois protections, chacune testée :

- **Confirmation sur N images** avant de croire une pose.
- **Hystérésis** : le seuil pour entrer dans un état est plus exigeant que
  celui pour en sortir. Sans cela, une main qui hésite à la frontière fait
  osciller l'état dix fois par seconde — et chaque oscillation serait une
  action.
- **Temps de repos** après un geste : sans lui, ouvrir la main après un
  « attraper » déclenche aussitôt un « relâcher », puis l'inverse, en boucle.

Et une main **perdue** au milieu d'un geste l'**annule** — la figer laisserait
un objet « attrapé » que personne ne tient, que le prochain relâchement
déposerait n'importe où.

La latence est le **prix** de ces protections. Elle n'est pas cachée : elle
est chiffrée par un test qui rougit si un réglage la fait exploser.

## Le mur : macOS ne pose pas la question

Constaté, pas supposé. La demande d'accès à la caméra revient **refusée
immédiatement**, sans qu'aucune boîte de dialogue n'apparaisse, et le statut
reste « à demander ».

macOS ne refuse pas la caméra à l'utilisateur : **il refuse de lui poser la
question.** Le processus qui demande n'est pas une application au sens du
système — l'interpréteur Python d'uv est un exécutable nu, sans paquet, donc
sans `Info.plist`, donc sans `NSCameraUsageDescription`. TCC exige cette clé
pour afficher une demande ; sans elle, il n'y a rien à afficher.

**Aucun réglage ne débloque cela.** Envoyer l'utilisateur dans Réglages
Système serait un mauvais conseil : il n'y trouverait aucune ligne à cocher.
Le message d'erreur du code le dit, plutôt que de faire chercher au mauvais
endroit.

*(Le micro fonctionne, lui — son autorisation a été accordée par un autre
chemin, quand une application empaquetée la demandait. Ce n'est pas une
contradiction : la permission suit le **paquet**, pas le binaire.)*

## Le mur est tombé — option A retenue et livrée

**L'application capture, le serveur voit.** C'est le chemin choisi le
25 août 2026, et il est en place :

| Pièce | Où |
|---|---|
| `NSCameraUsageDescription` (la phrase que macOS affiche) | `frontend/src-tauri/Info.plist` |
| `com.apple.security.device.camera` | `frontend/src-tauri/Entitlements.plist` |
| Capture par la fenêtre (`getUserMedia`, 12 im/s, 640 px) | `frontend/src/features/gestes/useModeGestes.ts` |
| Routes armer / image / désarmer | `server/gestes_routes.py` |
| Panneau visible, dans la page Appareils | `frontend/src/features/gestes/PanneauGestes.tsx` |

Vérifié dans l'app construite : la description et le droit sont bien dans le
paquet signé. macOS peut donc enfin poser la question — ce qu'il refusait de
faire au processus Python.

### Ce qui éteint la caméra, et c'est le plus important

Le §78 exige que rien ne guette en permanence. Quatre chemins mènent à
l'extinction, chacun testé :

1. Le bouton **Arrêter**.
2. **Quatre-vingt-dix secondes sans image** — un mode armé qu'on oublierait
   laisserait la caméra allumée, et le voyant vert cesserait de dire la
   vérité.
3. **Dix minutes** au maximum, même si la main bouge : la caméra coûte (§83).
4. Le **démontage du composant** — page fermée, navigation ailleurs : les
   pistes sont coupées dans tous les cas.

Et quand le serveur se désarme tout seul, l'interface le suit : la prochaine
image reçoit un refus poli, et la caméra s'éteint sans qu'on ait à y penser.

## Les autres sorties, pour mémoire

Le choix appartenait à Carlito ; il a pris la première.

### A. L'application Diapason capture (recommandé)

L'app Tauri **est** un paquet : elle a un `Info.plist` et des entitlements.
Deux ajouts (`NSCameraUsageDescription`, `com.apple.security.device.camera`),
et sa WebView peut appeler `getUserMedia`. Les images restent dans l'app ; on
peut soit les envoyer au serveur local pour Vision, soit calculer les points
côté JS.

- **Pour** : chemin natif, permission demandée normalement, une seule app à
  autoriser.
- **Contre** : il faut reconstruire l'app, et la CSP actuelle interdit tout
  hôte externe (donc pas de bibliothèque de suivi de main tierce — ce qui
  tombe bien, Vision est côté serveur).

### B. Empaqueter un petit exécutable de capture

Un `.app` minuscule dont le seul rôle est d'ouvrir la caméra et de pousser
les images au serveur local.

- **Pour** : le serveur Python garde toute la logique.
- **Contre** : un second binaire à construire, signer et maintenir.

### C. Renoncer à la caméra, garder les gestes du trackpad

Le trackpad ne demande aucune permission caméra, ne consomme pas de batterie
et n'allume aucun voyant. Il ne sert pas les mêmes moments — il faut avoir la
main dessus — mais pour « monter le son » ou « ouvrir la voix », il est
supérieur.

## Ce qui reste vrai quel que soit le choix

- **Les gestes ne seront jamais l'unique chemin vers une action** (§82) :
  tout ce qu'un geste déclenche restera atteignable au clic, au clavier et à
  la voix.
- **Un mode armé** (§78) : la caméra ne guette pas en permanence. On arme,
  on fait le geste, ça se désarme. Le voyant vert dit la vérité.
- **Aucune image n'est gardée ni n'est envoyée** : Vision tourne sur la
  machine, et seuls des points articulaires sortent du pont.
