# Les gestes — ce qui marche, et le mur qui est tombé

*25 août 2026. Phase 4 du cahier des charges (§110, §141).*

## En une phrase

Le geste **attrape et dépose pour de vrai** : le moteur, la détection et la
source d'images fonctionnent et sont mesurés, et quand deux appareils sont
capables, la question « vers lequel ? » se pose — et se répond. Le mur qui
bloquait tout était que macOS refusait la caméra au processus Python, pour
une raison qu'aucun réglage ne corrigeait ; c'est désormais l'application qui
capture. Le §83 est tenu depuis le 25 août 2026 : la cadence suit ce que
la caméra voit.

## Ce qui est livré et vérifié

| Pièce | État | Mesure |
|---|---|---|
| **Détection de main** (`desktop/vision_mains.py`) | ✅ | **4 ms par image** en taille caméra, soit 230 images/s possibles. Sur le Neural Engine : le créneau Ollama n'est pas touché. |
| **Moteur de gestes** (`desktop/gestes_main.py`) | ✅ | 16 tests. Machine à états, hystérésis, temps de repos, seuils centralisés. |
| **Latence de reconnaissance** | ✅ mesurée | ≤ 10 images pour un « attraper », soit ~0,4 s à 15 im/s. Figée par un test. |
| **Flux caméra** (la fenêtre Tauri, `useModeGestes.ts`) | ✅ | 12 im/s, 640 px, `getUserMedia` depuis un paquet signé. Le mur est tombé — voir ci-dessous. |
| **Trancher entre deux appareils** | ✅ | `/v1/gestures/drop/target` : la question du §81 est enfin répondable, et l'objet n'est plus perdu en la posant. 14 tests. |
| **Fusion voix + geste** | ✅ | La main se dit dans le contexte (voix ET chat) ; `geste_deposer` l'envoie et répond à la question posée. 15 tests. |
| **État d'énergie** (§83) | ✅ | `OFF / READY / ACTIVE / LOW_POWER`. 12 im/s une main suivie, **3 au repos**, 2 sur batterie faible. 13 tests. |

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

## Une seule main, et c'est un choix

Vision en lit deux ; le serveur n'en demande qu'une. Le moteur n'a aucune
notion d'identité de main — `observer()` reçoit une liste de points et rien
d'autre. À deux mains il faudrait deux moteurs et une règle disant laquelle
agit, sans quoi la seconde main de l'utilisateur, ou celle de quelqu'un qui
passe, deviendrait un geste.

Vision rend la main la plus SÛRE, ce qui est le bon défaut. La limite que ce
choix ne corrige pas : avec deux mains dans le champ, celle qui gagne peut
changer d'une image à l'autre. Le moteur verrait la main se téléporter, et
comme une main perdue annule le geste (§12), le geste échoue — bruyamment,
ce qui vaut mieux que de déposer au hasard.

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

## L'état d'énergie (§83)

Le §78 empêche la caméra de guetter en permanence ; le §83 lui interdit de
coûter le même prix qu'on s'en serve ou non. La cadence était **figée à douze
images par seconde**, du premier instant au désarmement : armer le mode puis
aller lire un document, c'était douze captures, douze encodages JPEG et douze
appels à Vision par seconde, pendant dix minutes, pour filmer une chaise.

| État | Quand | Cadence |
|---|---|---|
| `OFF` | non armé | 0 |
| `READY` | armé, aucune main depuis 3 s | **3 im/s** |
| `ACTIVE` | une main est suivie | 12 im/s |
| `LOW_POWER` | sur batterie, ≤ 20 % | 2 im/s |

**C'est le serveur qui décide, l'interface obéit.** Elle ne peut pas décider :
elle ne sait pas si une main a été vue — c'est Vision qui le dit, côté
serveur. La cadence voyage donc avec **chaque image**, et pas seulement dans
l'état sondé chaque seconde : sans cela l'interface filmerait encore au ralenti
pendant jusqu'à une seconde après qu'une main est entrée dans le champ,
c'est-à-dire au moment précis où la cadence compte.

Trois choses que ce module refuse de faire :

- **Baisser la cadence pendant qu'une main est suivie.** Le geste se mesure en
  IMAGES — « ≤ 10 images pour un attraper », figé par un test — donc une
  cadence qui tombe au milieu d'un geste l'allonge en secondes sans que
  personne l'ait demandé. On économise entre les gestes, jamais pendant.
- **Rendre une cadence nulle tant qu'on est armé.** Zéro serait une caméra
  éteinte qui se croit armée : le mode ne verrait plus jamais une main revenir.
- **Lire la batterie à chaque image.** `pmset` est un sous-processus ; douze
  fois par seconde, il coûterait bien plus que ce que l'économie rapporte. La
  mesure est gardée trente secondes — un câble rebranché est vu au pire trente
  secondes plus tard.

## La fusion voix + geste

« Envoie ça sur mon téléphone. » Le mot **ça** n'avait aucun référent : le
presse-papiers spatial n'était connu que du module des gestes. `handoff_continue`
repartait de l'écran courant, donc répondre « sur l'iPad » après avoir attrapé un
projet envoyait ce qui était affiché **à cet instant**, pas ce qui était dans la
main. Le maillon manquant n'était pas un réglage : c'était une absence totale de
raccordement.

**Deux pièces, et il fallait les deux.** Une phrase de contexte seule aurait
laissé le modèle avec un référent qu'il n'a aucun moyen d'envoyer ; un outil seul
lui ferait envoyer quelque chose qu'il ne sait pas nommer.

| Pièce | Où |
|---|---|
| `Dans la main (geste) : le projet « Zéro à Héro ».` | `presse_papiers_spatial.decrire` |
| Injection côté voix (message système, en fin de contexte) | `local_voice._turn_messages` |
| Injection côté chat (concaténée à l'ancre, en tête) | `routes._ensure_identity_prompt` |
| L'outil | `tools/gestes_spatiaux.py`, `geste_deposer` |

### Quatre décisions, et leurs raisons

**Un outil de plus, et pas `handoff_continue` élargi.** Deux référents dans un
même outil, c'est « je ne sais plus lequel des deux tu veux ». Et aucun ne prime
naturellement : la main peut être vide, l'écran peut avoir changé depuis la
saisie. Un outil, un référent.

**Aucun identifiant de ressource en paramètre.** Le référent est la main, pas le
modèle. Un outil qui accepterait « envoie le projet p1 » laisserait le modèle
inventer ce qu'il envoie — ce que le geste existe précisément pour éviter.

**Répondre à la question, jamais en ouvrir une seconde.** Si le serveur attend
déjà un choix, l'outil tranche **avec les mêmes candidats** et réutilise le jeton
comme clé d'idempotence. Sans cela, un clic à l'écran et une réponse à la voix
enverraient deux fois.

**Main vide : le contexte se tait, l'outil parle.** La dissymétrie est voulue.
Une phrase « ta main est vide » dans le contexte serait présente à presque tous
les tours, n'apprendrait rien, et inviterait le modèle à commenter un état dont
personne n'a parlé. L'outil, lui, le dit franchement — parce qu'on l'a appelé.

### Pourquoi celui-ci est à la voix, alors que `mesh_send` ne l'est pas

`mesh_send` choisit une action dans une énumération **ouverte** et un appareil
d'après une phrase **transcrite**. La cloche d'approbation couvre le risque, pas
l'ambiguïté : aucune confirmation ne dé-entend un mot mal transcrit.

`geste_deposer` ne choisit ni l'objet (c'est la main) ni l'action (elle découle
du type de l'objet), et devant une question en attente il tranche dans une liste
**fermée** que le serveur a mesurée. Une transcription approximative ne peut donc
pas inventer une cible : au pire elle ne correspond à aucun candidat, et la
question se repose.

### Une différence assumée avec le geste

Le geste ne mesure aucune direction : il ne propose que les appareils
**joignables**, et refuse s'il n'y en a pas. À la voix, l'utilisateur a **nommé**
l'appareil — le mettre en file pour qu'il le récupère au réveil respecte ce qu'il
a demandé. Dans les deux cas la phrase rendue vient du répartiteur, jamais de
l'envoi.
