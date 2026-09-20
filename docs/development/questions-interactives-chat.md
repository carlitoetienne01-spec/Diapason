# Questions interactives dans la discussion

Livraison locale du 19 septembre 2026. Le modèle choisit le nombre de questions
utiles. La carte en affiche une à la fois, avec deux à quatre choix et une
réponse libre à chaque étape. Aucun quota de trois questions n'est imposé.
Le bouton « Envoyer mes réponses » reprend la demande dans la même discussion.
Le questionnaire passé se replie ; ses réponses restent consultables.

## Parcours et limites

- Le client active `interactiveQuestions` sur les nouvelles demandes du chat.
  Le modèle décide si des précisions sont utiles. Une instruction précise,
  une réponse factuelle et les informations déjà connues ne doivent pas
  déclencher un questionnaire. Cette décision reste celle du modèle.
- Le tour envoyé depuis le formulaire désactive ce cadrage : le rappel
  d'interface faisait reposer les mêmes questions au modèle local malgré
  les réponses reçues. Ce tour utilise les réponses pour réaliser le travail.
- L'outil `diapason_ask_questions` ne passe pas par un exécuteur : il produit
  un événement SSE `questions` et termine le tour. Aucun créneau d'inférence
  n'est conservé pendant la réflexion humaine. Si le même lot propose une
  action et un questionnaire, aucune action de ce lot n'est exécutée.
- Le serveur valide et borne tout le formulaire avant affichage : taille JSON
  (16 Ko), textes, nombre de choix et doublons. Les identifiants sont créés
  par le serveur. Répondre ne remplace jamais l'approbation d'un outil sensible.
- Le 9b écrivait parfois les questions en Markdown. Le rappel au tour courant
  a permis l'appel direct. Un filet étroit reconnaît encore une demande de
  précisions numérotée : une seule conversion supplémentaire, avec le seul
  outil de questionnaire et aucun exécuteur. Si elle échoue, la prose reste
  lisible. Une réponse ordinaire ne paie pas cette conversion.
- Les routes de fournisseurs qui transportent seulement du texte utilisent
  un bloc `diapason-questions` validé côté serveur. La prose normale continue
  à être diffusée. Ce chemin est vérifié avec un fournisseur simulé ; aucun
  service externe n'a été appelé pour cette livraison.

## Conservation et interface

`ChatMessage.questions` conserve le cadrage. Le message utilisateur suivant
porte `questionReply` avec l'identifiant de la demande et les réponses.
Ces données utilisent la sauvegarde et la synchronisation des conversations
existantes, sans nouvelle base ni modification de la règle de fusion.
Le texte transmis au modèle et copié par le bouton Copier est le texte du
questionnaire effectivement affiché, même après une conversion de secours.

L'envoi revalide le fil actif et le dernier message. Un double clic, une
ancienne carte ou un changement de discussion ne renvoie pas le formulaire.
Une saisie en cours dans le compositeur est conservée lorsqu'on envoie les
réponses du formulaire. Les brouillons internes au formulaire restent locaux
au composant ; les réponses envoyées, elles, sont synchronisées.

La carte reprend `CarteVitree`, les tokens du thème et la taille de caractères
de l'application. Sous 640 px, l'introduction et les descriptions secondaires
s'effacent. Le titre revient dans le champ visible après chaque étape, sans
imposer un panneau à hauteur fixe. Les transitions respectent la réduction
des animations du système.

## Vérifications

- Suite Python complète : 10 045 tests réussis, 40 ignorés.
  Les 19 tests ciblés finaux incluent aussi la conservation dans SQLite après
  réception d'une ancienne copie dépourvue du formulaire.
- Suite frontend complète : 950 tests réussis ; après le dernier ajout,
  les 15 tests ciblés du flux, du formulaire et du store passent.
- Interface réelle sur transport fictif : 340 et 736 px, thèmes Phosphor,
  Ardéchine et clair, retour aux réponses, saisie libre, repli de l'historique,
  un seul envoi après double clic, aucun débordement horizontal ni erreur JS.
- Essai réel avec `qwen3.5:9b` : demande de programme d'anglais → questionnaire ;
  réponses → programme sans nouveau questionnaire ; demande de cinq verbes
  déjà précise → réponse directe. Les réponses ont été générées localement,
  hors des conversations personnelles de Carlito.

La génération du formulaire dépend toujours du modèle et de la charge de la
machine. Cette fonctionnalité ne garantit pas une génération instantanée.

Application locale reconstruite, installée et relancée ; serveur rechargé et
`/health` vérifié. L'empreinte du point d'entrée du bundle desktop, de sa copie
statique et de la page réellement servie est identique. Rien n'a été publié
sur GitHub dans cette livraison.

## Correction du cas qwen3:14b — 19 septembre, après la capture de 22 h 19

La demande « Prepare moi un programme pour la programmation » avait reçu
une simple reformulation, sans événement `questions`. Le défaut est reproduit
avec le même historique, les consignes de l'installation et les 44 outils
autorisés, dans un banc dont l'exécuteur interdit toute action. L'historique
personnel n'est pas modifié. Le déplacement du rappel avant la demande ne
corrige pas le défaut : cette hypothèse a été écartée.

Deux corrections ciblées :

- Une conception de programme ou de plan autonome utilise le catalogue léger
  existant. Tous les outils restent accessibles ; les références à un projet,
  des tâches ou un dossier conservent le contrôle de lecture. Il ne s'agit
  pas d'obliger tous les programmes à poser les mêmes questions.
- Le filet de conversion reconnaît aussi une courte question de préférence
  sans liste numérotée, comme « Quel langage de programmation veux-tu apprendre ? ».
  Une citation, une question factuelle ou une question suivie d'une explication
  n'y entre pas. La conversion reste unique, sans exécuteur.

Essais locaux avec **qwen3:14b**, sur l'historique de la capture :

| Parcours | Résultat observé |
|---|---|
| Avant, schémas complets | Reformulation seule en 57,79 s |
| Après, catalogue puis conversion | Événement `questions` valide en 29,35 s ; choix Python, JavaScript, Java, C++ |
| Réponses au formulaire | Programme Python de quatre semaines, sans nouveau questionnaire, en 99,82 s |
| Demande précise de cinq verbes, sans question | Cinq traductions, sans questionnaire, en 17,96 s |

Ces temps mesurent des essais ponctuels, pas une garantie de rapidité. La
génération du programme reste lente sur ce modèle. Les essais ne valident
pas la fiabilité factuelle générale du modèle (notamment l'autre réponse
visible sur la capture, relative à Haïti).

La suite Python complète passe : **10 061 réussis, 40 ignorés**. Elle inclut
le parcours SSE avec une trousse volumineuse, le choix cliquable après une
question courte, la borne d'une conversion et l'absence d'action pendant
le cadrage. Lint, formatage et contrôle d'identité passent également.

## Compatibilité Gemma — capture de 22 h 49

Le `gemma3:4b` installé renvoie HTTP 400 avec `does not support tools`.
L'adaptateur supprimait alors les outils mais conservait la consigne demandant
de les appeler. La phrase « Appelle diapason_ask_questions » apparaissait donc
comme une réponse. C'était un défaut de protocole, pas de rendu de la carte.

Le chat exige maintenant un signal explicite lorsque les outils sont refusés.
Seul le refus confirmé de ces outils déclenche ce chemin : un autre HTTP 400
reste une erreur. Le repli historique des autres appelants de l'adaptateur
reste inchangé. Les modèles qui acceptent les fonctions gardent leur parcours.

Pour Gemma, un unique appel sans outil produit un questionnaire avec le
[format JSON contraint d'Ollama](https://docs.ollama.com/capabilities/structured-outputs).
Le modèle identifie d'abord le sujet courant et les précisions connues avant
de choisir ses questions. Sans cette distinction, l'historique sur Python
faisait parfois conclure à tort que le nouveau programme était déjà cadré.
Ces indications internes ne sont ni affichées ni enregistrées comme des faits.
Une liste vide poursuit la réponse ordinaire ; les réponses au formulaire
ne repassent pas par cette décision. Le cadrage ne conserve aucun créneau
d'inférence après la production de ses choix.

Le JSON reste hors du texte diffusé. Les mêmes validations et événements SSE
alimentent les mêmes cartes. Une coupure, une réponse invalide ou un appel
d'action inattendu ne deviennent pas un questionnaire réussi ; une annulation
se propage et ferme le flux. Le nom interne de l'outil est aussi refusé dans
les textes d'un formulaire. Après un refus d'outils, le tour ordinaire ne
reçoit plus la consigne impossible de les appeler et n'en exécute aucun.

Essais réels, hors de la conversation personnelle :

- Historique de la capture, nouvelle demande sur le trading : trois questions
  cliquables concernant le trading, en **4,81 s**, sans nom interne affiché.
- Demande précise de cinq verbes, avec le même historique : décision sans
  questionnaire en **1,56 s** (mesure de la décision, pas de toute la réponse).
- Reprise après réponses, avec une demande d'aperçu théorique en quatre étapes :
  texte produit en **10,41 s**, sans nouveau questionnaire. Cet essai plus court
  ne mesure pas le temps d'un programme complet et ne valide pas des conseils
  financiers générés par le modèle.

Vérifications finales : **10 075 tests Python réussis, 40 ignorés** ; lint,
formatage et contrôle d'identité réussis. Le test de transport couvre le
HTTP 400 d'Ollama, le JSON fragmenté et le SSE final, avec aucun exécuteur
appelé. Aucun changement de l'interface ni de la base des conversations.

## Nombre choisi par le modèle — nuit du 19 au 20 septembre 2026

La limite de trois a été retirée du schéma de l'outil, des deux modèles de
validation Python, des consignes (y compris correction/conversion) et du
lecteur TypeScript. Le modèle choisit les précisions nécessaires, sans quota ;
les consignes demandent de respecter les informations déjà connues, d'éviter
les reformulations répétées et de ne pas ajouter des préférences facultatives
quand l'utilisateur a circonscrit le besoin. La décision sémantique reste celle
du modèle, pas une garantie d'absence de questions superflues sur tout sujet.

La taille JSON reste limitée à 16 Ko. Le client borne également les textes
cumulés à 16 Ko, sans compter les identifiants et valeurs par défaut ajoutés
par le serveur. Les générations dédiées au cadrage/conversion disposent de
8192 jetons au lieu de 2048 ; ce plafond ne force pas une réponse plus longue.
Une réponse incomplète reste un échec explicite, jamais une liste tronquée
présentée comme complète. Les plafonds ordinaires du chat sont conservés.

Une seule question apparaît à la fois. La progression remplace les repères
multipliés par question : elle occupe au plus 84 px, indépendamment du nombre
d'étapes, et son animation respecte la réduction des mouvements. Le retour
aux choix et à la saisie libre reste possible. Les réponses envoyées reprennent
la demande sans nouveau questionnaire sur ce tour ; elles ne déclenchent pas
une boucle de questions sans fin.

Essais réels avec `gemma3:4b`, conversations synthétiques isolées :

| Demande | Résultat observé |
|---|---|
| Organisation d'une conférence, plusieurs paramètres manquants | 8 questions, 13,50 s |
| Programme Python, seul le temps quotidien reste à préciser | 1 question sur le temps disponible, 3,09 s |
| Cinq verbes et traductions, sans questions | Réponse directe, 2,61 s |

Un premier essai ajoutait des préférences facultatives à la demande simple.
La consigne de respect du périmètre a été précisée avant les résultats ci-dessus.
Ces temps sont des observations ponctuelles. Les suggestions de choix produites
par le modèle ne constituent pas une vérification factuelle de leur pertinence.

Vérifications : **10 082 tests Python réussis, 40 ignorés ; 953 tests frontend
réussis**. Les tests couvrent 1, 4, 6, 9 et 12 questions selon le parcours,
la borne de données, les réponses complètes et la suspension des actions.
Banc d'interface isolé : douze étapes parcourues à 340 px, retour à l'étape
précédente avec conservation du choix et de la saisie, un envoi contenant les
douze réponses, reprise sans questionnaire, thèmes Phosphor et Ardéchine.
Largeur du contenu de la carte = largeur disponible (296 px), barre = 84 px.
