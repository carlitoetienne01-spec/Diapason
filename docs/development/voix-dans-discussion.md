# La voix dans le fil de Discussion

Intégration du 27 septembre 2026. Le moteur local et le timbre Orion sont
ceux de « Parler » ; le compositeur utilise la session partagée au lieu
d'ouvrir une seconde conversation dans une fenêtre modale.

## Comportement

- Au repos, le bouton principal porte une onde, sans texte. Le focus dans
  le champ, un brouillon ou une pièce jointe le remplace par la flèche
  d'envoi. Une flèche sans contenu reste désactivée.
- Le menu + regroupe les pièces jointes, la recherche approfondie et les
  permissions existantes. Sur le Mac, il conserve aussi le mode temporaire
  de conversation entre IA. Son retour de focus ne doit pas mettre en pause
  une session qu'il vient d'ouvrir.
- Le focus dans le texte suspend le micro ; la commande de reprise le
  réactive. Envoyer le texte termine la session vocale. Changer de discussion
  ou de page arrête aussi la session, avant d'utiliser un autre contexte.
- La barre vocale propose pause, clavier, interruption et fermeture. Le
  bouton principal reste unique. Le pourcentage de tokens est retiré.
- Les bulles gardent les alignements habituels sans étiquettes de locuteur.
  Le brouillon de reconnaissance est provisoire ; seul le texte utilisateur
  final rejoint l'historique. Une réponse interrompue est signalée.

## Historique et contexte

`TalkToDiapasonHost` possède l'unique `useVoiceLive` de la vue, exposé par
`contexteVoix`. `useConversationVocale` rattache la session à une discussion
immuable ; chaque rang de transcription donne un identifiant stable de
message, révisé sans dupliquer les phrases.

Les messages passent par le store puis par la synchronisation existante
des conversations. L'heure d'une bulle est celle de sa création, pas celle
de sa dernière révision. Voir `conversations-sync.md` pour les règles de
fusion entre la fenêtre principale et le mini-panneau.

Le démarrage transmet les seize derniers messages non vides, dont le texte
extrait des documents. Le serveur valide les rôles user/assistant, les
types et une taille totale maximale d'un Mio. Aucun rôle système ou outil
fourni par le client n'entre dans ce contexte. Les images ne sont pas
transmises par ce chemin. Les plafonds des outils et les contrôles de voix
restent ceux de la session locale.

Le serveur émet le texte assistant progressivement avant de synthétiser
chaque phrase. L'événement final remplace la même bulle. Ce texte indique
la réponse préparée ; il ne prétend pas être un sous-titrage aligné à chaque
échantillon sonore.

## Visualiseur sensible, signal réel

`BarreVocale` analyse le micro pendant l'écoute et la sortie audio pendant
la parole d'Orion. Le niveau RMS est transformé uniquement pour le dessin :
seuil proche de −50 dB, montée de 35 ms et descente de 160 ms. Le gain de
capture et la reconnaissance ne changent pas. Sans signal, avec le micro
en pause ou en mouvement réduit, il n'y a pas d'animation inventée.

## Vérification de cette intégration

- TypeScript et compilation du bundle réussis ; 1 650 tests frontend.
- 617 tests voix, routes et conversations réussis ; sept tests optionnels
  sautés et trois hors sélection. Tests avec un dossier de configuration
  temporaire, sans toucher aux préférences réelles.
- Navigateur isolé, API simulée : contexte transmis, une seule bulle par
  réponse progressive, sauvegarde, pause/reprise et retour voix après envoi
  écrit. Aucun débordement horizontal à 340, 375, 460 et 1 100 px.
- Signal synthétique faible dans le mini-panneau : huit rangées de pixels
  actives, puis deux au repos. Menu entièrement dans la fenêtre 340 × 600.
  Ce contrôle ne mesure pas la qualité de reconnaissance d'une vraie voix.
- Serveur réel, sans ouvrir le micro ni jouer le son : le contexte écrit
  est repris correctement, un texte provisoire précède six paquets audio,
  puis arrive le texte final. Sur cet essai à chaud, texte à 1,16 s et audio
  à 1,86 s après une trame textuelle ; ce n'est pas une mesure depuis la fin
  d'une question parlée.
- App macOS installée : menu + vérifié, flèche désactivée après focus sur
  le champ vide, onde rétablie après retour dans le fil. Le micro reste fermé
  jusqu'à une action explicite de l'utilisateur.

## Régression du délai avec un chat déjà rempli

L'essai réel après intégration a révélé un cas absent du petit contexte de
validation : importer seize messages remplissait immédiatement la fenêtre
glissante de la voix. Le premier tour en retirait déjà le début, puis chaque
réponse déplaçait à nouveau ce début. Ollama devait relire environ deux à
trois mille jetons par tour. Les journaux montrent huit à dix secondes avant
le premier jeton, avec transcription et synthèse encore rapides.

Le contexte écrit importé est maintenant stable pendant toute la séance.
Il précède la fenêtre bornée des seize messages vocaux récents, soit au plus
trente-deux messages dans la session. Les seize messages écrits sont tous
conservés avec leurs rôles ; les fichiers et l'historique persisté ne sont
pas modifiés. Le préchauffage reçoit aussi ce contexte écrit et l'attend
avant READY. Il n'y a aucun changement de modèle, de fenêtre de tokens,
de timbre, de reconnaissance ou de paramètres de synthèse.

Comparaison locale sur le même serveur, les mêmes trois questions et le
même historique de 16 messages (quelques milliers de caractères), sans micro
ni lecture sonore. Le sujet et la taille exacte de cet historique ne sont
pas reproduits ici. Délai **depuis réception du texte jusqu'au premier
paquet audio** :

| Tour | Avant | Après |
|---|---:|---:|
| Question sur le sujet de l'historique | 9,173 s | 2,543 s |
| Exercice sur ce sujet | 9,445 s | 2,773 s |
| Rappel d'un fait de l'historique | 8,712 s | 3,053 s |

La préparation passe de 7,078 à 14,189 s sur cette paire d'essais ; son coût
est visible avant l'écoute. Les formulations des réponses varient, mais
le sujet reste conservé aux trois tours. Ces mesures n'incluent ni la
reconnaissance vocale ni le lecteur et ne garantissent pas un délai maximal
dans toutes les conditions de charge.

Validation de la correction : 565 tests voix, routes et cache du modèle
passent ; sept tests optionnels sautés et trois hors sélection. Un test de
douze échanges vérifie que le préfixe importé reste identique après la
borne des échanges récents, tandis que question et réponse les plus
récentes sont conservées. Deux tests exercent le contexte importé dans la
requête de préchauffage et dans le démarrage de la session. Serveur rechargé
avant la mesure après correction ; aucune reconstruction du bureau n'est
nécessaire pour ces changements Python.

Preuves temporaires : `/private/tmp/diapason-chat-latence-avant.log`,
`/private/tmp/diapason-chat-latence-apres.log` et
`/private/tmp/diapason-chat-cache-tests-complets.log`.

## Réouverture sans recharger Orion

Le 27 septembre, le délai « Connexion en cours » était distinct du délai
avant la réponse : chaque fermeture détruisait le processus Orion, et chaque
ouverture rechargeait ses poids puis synthétisait toute la phrase de chauffe.

Une séance fermée normalement rend désormais son ouvrier **déjà préparé et
sans requête en cours** à une réserve locale. Elle ne contient qu'un seul
ouvrier, pendant deux minutes au maximum. Le micro, la capture et le socket
restent gérés et fermés par le parcours existant ; la réserve n'a aucun accès
au microphone et ne fait aucun calcul en arrière-plan. Une nouvelle séance
prend seule cet ouvrier et vérifie sa réponse à une sonde avant de le déclarer
prêt. Le contexte de conversation n'est jamais conservé dans cette réserve.

Une phrase interrompue, un protocole invalide, une préparation annulée ou un
ouvrier muet impose sa destruction. Le délai de repos libère le processus,
et l'arrêt normal du serveur le libère également. Le préchauffage du modèle
de réponse avec le contexte exact reste attendu avant READY : cette
optimisation n'annonce pas une séance prête avant sa vraie préparation.

Mesures serveur, sur le même historique de 16 messages et sans ouvrir de
micro ni jouer de son :

| Ouverture | Avant | Après |
|---|---:|---:|
| Première ouverture de la série | 11,559 s | 28,898 s |
| Réouverture immédiate | 3,560 s | 0,189 s |
| Réouverture immédiate suivante | 3,383 s | 0,213 s |

La première ouverture après correction suit le redémarrage du serveur et
chevauche sa chauffe de fond ; elle n'est pas comparable à une réouverture.
Elle confirme que **le démarrage à froid reste long**. Le gain mesuré porte
sur les réouvertures, avec Orion et le contexte encore prêts. Un contexte
modifié, un calcul déjà lancé, une fermeture en cours de synthèse ou une
pause de plus de deux minutes peut réintroduire une préparation plus longue.
Ces chiffres vont de l'ouverture du WebSocket à READY et ne mesurent pas
l'autorisation du microphone ni la disponibilité de la capture côté bureau.

Validation : 576 tests du parcours vocal/routes/cache passent (7 sautés,
3 hors sélection), puis un test supplémentaire vérifie le nettoyage via le
cycle de vie réel du serveur. Les douze tests de réserve passent, dont
l'exclusivité, la limite à un ouvrier, les erreurs, l'annulation, l'expiration,
la sonde bloquée et l'absence de mélange d'historiques. Deux phrases de
1,84 et 4,48 secondes gardent exactement les mêmes octets PCM après reprise
du vrai moteur. Dans l'application installée, « Je t'écoute » est observé
après réouverture ; ce contrôle ne fournit pas un chronométrage précis du
clic jusqu'à la capture. Aucun changement frontend pour cette correction.

Preuves temporaires : `/private/tmp/diapason-ouverture-avant.log`,
`/private/tmp/diapason-ouverture-apres.log`,
`/private/tmp/diapason-reserve-son.log`,
`/private/tmp/diapason-reserve-tests.log` et
`/private/tmp/diapason-reserve-lifecycle-reel.log`.

## 27 septembre, plantage du visualiseur à la déconnexion

La capture de Carlito affiche « The given destination is not connected » dans
la frontière d’erreur de toute l’application. `LectureVocale.arreter()` retire
les connexions de sa sortie avant le nettoyage de l’effet de `OndeVocale`.
L’appel `source.disconnect(analyseur)` tentait alors de retirer une connexion
qui n’existe plus : Web Audio lève `InvalidAccessError`, et React remplace le
chat par l’écran d’erreur. Les anciens doubles de test rendaient tous les
appels à `disconnect` inoffensifs, contrairement au navigateur.

Le nettoyage ciblé tolère maintenant cette seule erreur de branche déjà
déconnectée ; il ne débranche pas les autres sorties et ne masque pas les
autres exceptions. L’analyseur est libéré même après ce cas. La capture utilise
la même règle, avec un arrêt idempotent pour libérer une seule fois son worklet.
Un visualiseur ne recrée pas d’analyseur sur un contexte déjà fermé.

Validation : TypeScript et **51 tests frontend ciblés** réussis, dont la
régression d’un lecteur arrêté avant le démontage du visualiseur, le maintien
des autres branches et deux arrêts de capture successifs. Banc temporaire avec
le vrai Web Audio du navigateur et le vrai `BarreVocale` sous `StrictMode` :
l’ancien appel reproduit exactement l’erreur de destination non connectée ;
cinq cycles écoute → voix → interruption → pause → reprise → fermeture passent
avec le correctif, ainsi qu’un contexte fermé avant le démontage. Aucun micro
ouvert et aucun son joué. Le banc temporaire est retiré après vérification.
