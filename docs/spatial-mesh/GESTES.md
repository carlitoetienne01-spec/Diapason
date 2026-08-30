# Les gestes — ce qui marche, et le mur qui est tombé

*25 août 2026. Phase 4 du cahier des charges (§110, §141).*

## En une phrase

Deux **vocabulaires** partagent la caméra sans partager leurs actions. Par
défaut le verrou est **Auto** : `ArbitreDeGeste` choisit d’après la pose
(index → curseur, poing/paume → transfert) après confirmation sur trois
images. On peut encore forcer transfert ou curseur. Dans tous les cas un
seul moteur avance par image : un pincement ne peut pas envoyer, un poing ne
peut pas cliquer. Le mur qui bloquait tout était que macOS refusait la
caméra au processus Python ; c’est désormais l’application qui capture. Le
§83 est tenu depuis le 25 août 2026 : la cadence suit ce que la caméra voit
et monte à 24 im/s uniquement pendant le suivi du pointeur.

## Ce qui est livré et vérifié

| Pièce | État | Mesure |
|---|---|---|
| **Détection de main** (`desktop/vision_mains.py`) | ✅ | **4 ms par image** en taille caméra, soit 230 images/s possibles. Sur le Neural Engine : le créneau Ollama n'est pas touché. |
| **Moteurs de gestes** (`gestes_main.py`, `pointeur_main.py`) | ✅ automatisé | Transfert : 16 tests. Pointeur : 24 tests sur la pose, les pertes brèves, le filtre adaptatif, le clic, le double-clic, le défilement et les annulations. |
| **Latence de reconnaissance** | ✅ mesurée | ≤ 10 images pour un « attraper », soit ~0,4 s à 15 im/s. Figée par un test. |
| **Flux caméra** (la fenêtre Tauri, `useModeGestes.ts`) | ✅ | 12 im/s pendant un transfert, 24 pendant un pointage suivi, 3 en veille ; 640 px, `getUserMedia` depuis un paquet signé. |
| **Curseur, clic, ouverture, défilement** | ⚠️ banc physique | Mode séparé macOS : Core Graphics et Accessibilité. Curseur figé pendant la pince ; scroll vertical dominant ≥ 500 ms. Coins hauts minimisent/ferment ; paume + balayage change d'app ou de Space (29 août soir). 32 tests Python. |
| **Trancher entre plusieurs appareils** | ✅ automatisé | Sélecteur global à la cadence des images : gauche/haut = précédent, droite/bas = suivant, ouverture = envoyer. Clic et voix conservés (§82). |
| **Fichier, photo ou vidéo réel** | ✅ automatisé | Dialogue natif Tauri, plafond 2 Gio, réception automatique par un pair `TRUSTED`, X25519 + AES-256-GCM et progression par morceaux. Aucun chemin local ne passe dans le JSON. |
| **Fusion voix + geste** | ✅ | La main se dit dans le contexte (voix ET chat) ; `geste_deposer` l'envoie et répond à la question posée. 15 tests. |
| **État d'énergie** (§83) | ✅ | `OFF / READY / ACTIVE / LOW_POWER`. 12 im/s dès qu'une main est suivie — batterie faible comprise —, **3 au repos**, 2 sur batterie faible sans main. 13 tests. |

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
   vérité. Cette horloge se suspend pendant un transfert explicitement lancé,
   puis repart à sa fin ; elle ne tue pas un envoi chiffré en cours.
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

## Choisir l'appareil avec le poing

Le système ne transforme pas le poing en pointeur spatial. Aucun capteur ne
mesure où l'utilisateur vise (§34), et une direction inventée serait plus
dangereuse qu'une question. Le mouvement agit sur un **sélecteur visible** :

1. La fermeture confirmée attrape l'objet et affiche les appareils de
   confiance `ONLINE` ou `IDLE` qui savent réellement le recevoir.
2. Le centre de la paume — poignet plus bases des quatre doigts — devient un
   point normalisé. L'axe horizontal est rendu comme un miroir : la droite de
   l'utilisateur reste la droite à l'écran.
3. Un déplacement de **11 %** vers la droite ou le bas avance d'un appareil ;
   vers la gauche ou le haut, il recule. Une pause de **240 ms** empêche de
   sauter deux cartes avant d'avoir vu la première bouger.
4. Ouvrir la main envoie vers la carte surlignée. Cliquer cette carte ou la
   nommer à la voix produit la même réponse fermée ; « laisse tomber » reste
   disponible.

Le sélecteur a ses preuves automatisées côté serveur et côté React. Il reste
à effectuer le banc physique du mouvement dans l'application reconstruite :
la documentation ne transforme pas un test de coordonnées en essai caméra.

## Contrôler le curseur avec l'index

Le pointage n'est pas une nouvelle pose ajoutée au moteur de transfert. C'est
un **vocabulaire distinct**, choisi automatiquement (Auto) ou verrouillé dans
le panneau. Cette séparation est la protection principale : quand le mode
effectif est `POINTER`, `/frame` rend avant toute ligne d'attraper/déposer et
le moteur poing/paume n'est pas appelé. Un objet déjà tenu ou un dépôt en
attente force le transfert ; une pince confirmée reste au pointeur.

1. Un index qui dépasse au moins deux autres doigts pendant trois images
   active le pointeur. Les doigts repliés se cachent souvent dans Vision : un
   seul point incertain ne casse donc plus la pose, tandis qu'une paume
   ouverte nette ne bouge rien.
2. La position de l'index est lissée et ramenée sur l'écran principal. Les
   marges de la caméra permettent d'atteindre les bords sans sortir la main du
   champ. Le filtre adaptatif absorbe le tremblement à l'arrêt et réduit son
   lissage quand le doigt accélère, au lieu d'ajouter le même retard partout.
3. Un pincement pouce-index confirmé sur deux images clique après deux images
   de relâchement, **sans plafond de durée** : viser un bouton n'est pas un
   abandon. Pendant la pince, le curseur **reste à l'ancre** du contact — il
   ne suit plus le tremblement (29 août 2026 : dérive + scroll trop facile
   rataient les onglets). Le clic reste à cet endroit. Le seuil tient compte
   de l'écart que Vision conserve entre deux doigts réellement en contact et
   tolère 140 ms d'occlusion du pouce. Une jauge visible montre l'approche
   avant de promettre un clic. Deux pincements rapprochés portent un état de
   double-clic natif : Finder ouvre alors le fichier ou le dossier comme avec
   la souris.
4. Le défilement exige **500 ms** de pince **et** un déplacement vertical
   dominant d'au moins ~5,5 % d'écran ; un micro-mouvement en visant un onglet
   ne l'arme plus. La libération après défilement ne clique pas.
5. **Bureau** : **paume ouverte** face caméra, puis **retournement** pour
   montrer le dos → l'app visible **suivante passe au premier plan**
   (activation directe, pas ⌘Tab / pas de sélecteur) ; dos → paume → app
   précédente. L'arbitre Auto garde le pointeur sur une paume déjà en mode
   curseur. Pendant la paume, le curseur **continue de suivre** la main.
   Pince + glissement **horizontal depuis un bord** → Spaces. Pince
   **tenue ~0,85 s sans bouger** en bande **basse** : gauche → minimiser
   (⌘M), droite → fermer (⌘W). **Geste 🤙** (pouce + auriculaire tendus,
   maintenu ~0,35 s) → tu **traces la zone** à capturer (`screencapture -is`,
   PNG sur le Bureau ; Échap annule). Les coins hauts restent des clics (onglets). Avant un
   raccourci, Diapason cède le premier plan s'il l'occupe. Clavier et souris
   restent disponibles (§82).
6. Après 280 ms sans main, le suivi est réellement déclaré perdu et doit être
   acquis de nouveau. Une occlusion brève fige le curseur et reprend dès
   l'image suivante. Dans les deux cas, tout pincement en cours est annulé
   sans produire de clic.

L'application Tauri applique l'intention avec Core Graphics. Elle vérifie
`CGPreflightPostEventAccess` avant le premier mouvement et ouvre la demande
macOS si nécessaire ; un refus coupe le mode et affiche le chemin exact vers
Réglages Système, jamais un faux succès. Cette première livraison vise
**macOS et l'écran principal**. Windows n'a pas encore de suivi de main et les
écrans secondaires ne sont pas encore mappés. Le clic, le clavier et la souris
restent disponibles conformément au §82.

## Attraper un fichier, une photo ou une vidéo

Un écran web ne peut pas promettre un chemin local exploitable par le serveur.
Le bouton **Choisir un fichier, une photo ou une vidéo** ouvre donc le dialogue
natif Tauri. Il prépare **un fichier à la fois**, pendant dix minutes au plus ;
le prochain poing l'attrape avant le contexte de la page affichée.

Le presse-papiers spatial garde le chemin uniquement dans le processus Python.
React ne reçoit que `type`, un identifiant opaque, le nom, la taille et le type
MIME. À l'ouverture de la main, seuls les pairs de bureau joignables en LAN et
portant une adresse vérifiée sont proposés. Le transfert n'est pas réinventé :
il emprunte la phase 3, attend l'accord du destinataire jusqu'à 120 secondes,
chiffre chaque morceau, affiche la progression entière et ne rend un succès
qu'après la confirmation signée et la vérification d'empreinte du récepteur.

Le plafond est **2 Gio**, tous types confondus. Le client Flutter ne sait pas
encore recevoir ; un téléphone en transport `pull` n'apparaît donc pas dans ce
sélecteur de fichiers. Un refus, une expiration ou une erreur sont affichés
comme tels — jamais convertis en succès.

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
| `ACTIVE` | une main est suivie en transfert | 12 im/s |
| `ACTIVE` pointeur | un index est suivi | **24 im/s** |
| `LOW_POWER` | **aucune main**, sur batterie, ≤ 20 % | 2 im/s |
| `READY` | armé, aucune main depuis 3 s | **3 im/s** |

L'ordre du tableau est celui des règles : **une main suivie l'emporte sur la
batterie faible**. Le contraire a été livré le 25 août 2026 et corrigé le 26 —
la batterie était consultée en premier, donc à 18 % un geste en cours tombait
à deux images par seconde. Or un geste se compte en IMAGES (« ≤ 10 images pour
un attraper »), pas en secondes : à deux images par seconde, un attraper
demande cinq secondes de poing fermé et échoue. Un geste qui échoue se
recommence, à pleine cadence, autant de fois qu'il échoue — l'économie coûtait
de l'énergie. On économise ENTRE les gestes, jamais pendant.

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
