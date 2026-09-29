# Mode Étudier — contrat de réalisation

Parcours autorisé le 29 septembre 2026 : documents ou sujet → cours structuré →
entraînement ou examen dans Discussion → correction expliquée → notions à revoir.
ECC Product Capability cadre ce contrat ; Eval Harness et TDD Workflow cadrent
sa vérification. Aucun agent parallèle, aucun changement des travaux vocaux ou
mobiles en cours. Installation autorisée ensuite pour rendre ce parcours
accessible dans l'application ouverte.

## Garanties du premier parcours

- Données locales, modèle local existant, aucun outil d'action pendant la génération.
- Sources bornées et déclarées : un document tronqué est refusé, jamais présenté
  comme intégral. Les références sont des extraits textuels vérifiés, pas des
  numéros de page inventés. Les documents numérisés demandent un texte lisible.
- Cours, objectifs et questions préparés avant l'épreuve. QCM et réponses libres.
- Corrigé absent des réponses HTTP avant la fin de l'examen. L'entraînement
  autorise les indices et la correction immédiate ; leur utilisation est enregistrée.
- Sauvegarde serveur par discussion, reprise après rechargement, protection des
  réponses contre deux fenêtres concurrentes. Aucun créneau de modèle pendant
  la réflexion de l'étudiant.
- QCM corrigés de façon déterministe ; réponses libres évaluées critère par
  critère avec une correction explicitement proposée par le modèle. Aucun score
  présenté comme une preuve de maîtrise durable.
- Interface utilisable au clavier, à 340 px et au téléphone, sans ouvrir de micro
  automatiquement. Dictée relue avant validation ; erreur audio ≠ erreur scolaire.

## Évaluations exigées

Validation du schéma, sources inexistantes, texte tronqué, choix ambigus, corrigé
non exposé, indices interdits à l'examen, sauvegarde/reprise, conflit de version,
double soumission, réponses vides, erreur du modèle, score hors barème, évaluation
non terminée, cohérence des routes téléphone. Puis TypeScript, fonctions pures et
parcours de navigateur avec transport isolé ; essai local réel séparé si disponible.

## Limites à annoncer

Ce parcours n'est pas une certification de la qualité pédagogique universelle.
La bibliothèque de longs ouvrages avec OCR, la planification automatique des
révisions, les schémas interactifs et les bacs à sable par matière demandent des
étapes dédiées après ce premier parcours. La continuité orale a été ajoutée
dans l'étape décrite à la fin de ce document.
Les extraits d'un examen ne sont jamais utilisés comme consignes d'outils.

## Réalisation vérifiée le 29 septembre 2026

Entrée dans le chat : menu « + », puis « Étudier un cours · Tests et examens ».
La préparation demande le sujet, le niveau, deux à douze questions et, en option,
deux documents totalisant au plus 48 000 caractères. Les études sont liées à la
discussion et enregistrées dans `etudes.db`, avec les permissions privées des
autres bases de Diapason. Une suppression via la route de discussion retire les
études et empêche une préparation tardive de les recréer. Cette base ne fait pas
encore partie de la synchronisation chiffrée entre serveurs indépendants.

Les consignes d'ECC ont servi à la conception, aux cas d'échec et aux contrôles.
Elles ne sont pas chargées dans le modèle comme un prétendu savoir pédagogique
universel. Les composants pédagogiques sont propres à Diapason.

### Preuves

- Python : **86 tests réussis**, dont les parcours Étudier, documents,
  conversations et contrat téléphone ; **89 % de couverture** du nouveau code
  serveur Étudier. Les suites historiques signalent encore des connexions SQLite
  non fermées dans leurs fixtures ; aucun échec de test.
- Interface : **43 tests réussis**, TypeScript valide, compilation Vite dans un
  dossier temporaire et contrôle du graphe des chargements réussis. Les alertes
  Vite de taille de certains morceaux existants restent présentes.
- Navigateur : lancement depuis le menu du chat ; examen avec QCM et réponse
  ouverte ; enregistrement, rechargement, reprise, bilan et réponses verrouillées.
  En entraînement : indice enregistré, mauvaise réponse notée zéro, accès au
  cours conservé. À 340 px, aucune largeur débordante et boutons de 42 px minimum.
- Modèle local réel `qwen3.5:9b`, documents synthétiques de fractions : cours avec
  **2 questions en 120,34 s**, puis corrigé attendu **4/4** ; cours avec
  **5 questions en 96,14 s**, puis corrigé attendu **8/8**. Ces durées ne sont pas
  celles d'une réponse de chat : le cours et le corrigé complet sont préparés.
- Trois contre-épreuves de correction locale : erreur manifeste **0/3**,
  reformulation correcte **2/2**, demande de points sans réponse **0/3**. Un seul
  essai par cas : pas de statistique de fiabilité extrapolée à toutes les matières.
- Les premiers essais réels ont révélé un corrigé de QCM hors des choix, puis
  une citation modifiée. Une réparation bornée est maintenant possible avant
  publication ; le modèle choisit un passage référencé et le serveur restitue
  son texte original. L'existence d'un extrait est contrôlée automatiquement,
  pas la validité scientifique de toute explication produite.

### État de livraison et suites

**L'application de bureau a été reconstruite, installée et relancée ; le serveur
a été rechargé.** La signature de l'application a été vérifiée. Le menu « + »
ouvre Étudier dans la fenêtre native, et l'API active répond avec authentification.
Un nouveau cours de fractions à deux questions a été préparé par le modèle réel
depuis cette fenêtre : QCM **1/1**, réponse ouverte expliquée **3/3**, puis bilan
**4/4**, avec les deux réponses enregistrées. Les essais restent dans une
discussion séparée, sans modifier les discussions existantes.

Ce contrôle a également révélé que les fractions étaient affichées en notation
LaTeX brute dans les questions et les corrigés. Le rendu mathématique déjà utilisé
par le chat couvre maintenant les textes d'étude, sans autoriser les commandes
de confiance ni charger les images des documents. Les contrôles TypeScript et les
43 tests d'interface ont été relancés avec succès après ce correctif.
La version contenant ce rendu a ensuite été reconstruite et installée : le même
cours, ses réponses et le bilan **4/4** sont retrouvés après redémarrage, et les
fractions sont visibles correctement dans la fenêtre native.

Aucun test au vrai micro n'a été effectué pour cette première étape. La dictée
réutilise la capture existante et demande de relire le texte avant enregistrement.
La conversation orale continue relève de l'étape suivante, décrite ci-dessous.

L'évaluation finale est une proposition pour s'entraîner, pas une certification.
Le bilan distingue les notions à revoir et celles qui n'ont pas encore été
évaluées. La préparation reste lente, et une sortie incomplète est refusée avec
les réponses déjà enregistrées conservées. Les brouillons non enregistrés ne
sont pas garantis si l'on change de discussion ou ferme l'application.

Prochaines étapes du mode professeur complet : diagnostic adaptatif, suivi de
maîtrise sur plusieurs séances, révisions espacées, lecture des longs documents
par chapitres et évaluations pédagogiques sur plusieurs matières.

## Continuité de l'oral et du texte

Le service Étudier et l'outil `study` sont communs au chat, au WebSocket vocal et
au panneau. L'identité de la discussion vient du transport authentifié, jamais
du modèle. Les documents importés, la question courante, les réponses et les
corrections restent dans le même enregistrement. Une conversation invitée sans
historique n'hérite pas des études privées.

Les commandes simples démarrent l'épreuve, relisent la question, changent de
question, demandent un indice ou terminent le test via l'exécuteur habituel.
Leur restitution provient du résultat sauvegardé. Une réponse ouverte est
distinguée d'une demande d'aide par une interprétation locale contrainte, sans
corrigé dans ce contexte ; ses mots d'origine sont ensuite enregistrés tels
quels. Un QCM conserve à la fois le choix et la formulation de l'étudiant.
La préparation utilise également une interprétation locale de la demande,
puis le même générateur validé que le formulaire.

En entraînement, une correction peut être demandée avant de passer à la suite.
En examen, l'outil ne rend ni solution ni indice ; la conversation ne contourne
pas ce refus en répondant depuis les connaissances du modèle. Les questions
peuvent être relues et les réponses restent modifiables jusqu'à la correction.
Le bilan définitif de l'essai est demandé explicitement ; les évaluations de
réponses libres restent des propositions expliquées.

Une préparation longue émet une courte annonce et un signal d'activité pour
ne pas être confondue avec deux minutes de silence. Elle garde son propre
délai borné. Le panneau retrouve la progression orale sans rechargement, mais
n'écrase pas un brouillon en cours ni une dictée. Ses lectures périodiques ont
un budget distinct des requêtes de chat, avec l'authentification inchangée.

### Vérifications de continuité

- **275 tests Python réussis** sur le parcours, ses transports, la voix,
  l'authentification et le contrat téléphone ; les **62 tests Étudier** couvrent
  **87,34 %** des 837 instructions du nouveau code ciblé. Les fixtures historiques
  de conversations signalent encore des connexions SQLite non fermées.
  **1 946 tests frontend** et TypeScript ont passé avant installation de
  l'interface ; les derniers ajustements ne concernent que le serveur.
- Préparation depuis la chaîne vocale installée : la demande d'un cours de
  fractions débutant avec deux questions lance réellement `study prepare`,
  conserve exactement le document joint et restitue une confirmation avec
  Orion. Le même cours, ses objectifs, ses essentiels et ses deux questions
  sont ensuite retrouvés dans le panneau natif, sans reconstruire de copie.
- Parcours local avec le modèle réel et la trousse complète : démarrage oral,
  QCM oral, correction et question suivante à l'écrit, réponse ouverte à l'écrit,
  puis bilan oral **3/3**. La réponse ouverte est conservée mot pour mot.
- Même parcours dans le serveur installé, avec la vraie synthèse Orion : audio
  reçu à chaque tour et réponses retrouvées dans la fenêtre native, jusqu'au
  bilan **3/3**, à la citation du document et aux critères de correction.
- Ce banc injecte le texte dans le transport vocal : il vérifie les outils,
  les sauvegardes et le son, **pas la reconnaissance du micro de l'utilisateur**.
  Les premiers sons mesurés arrivent après **0,53 s** pour la question,
  **0,77 s** pour l'enregistrement du QCM et **2,50 s** pour une réponse ouverte,
  depuis la réception du texte. Le premier chargement de ce banc a demandé
  **67,3 s**. La correction annonce son travail avant de rendre le bilan ;
  cette annonce n'est pas la mesure de fin de correction.
- Les essais ont révélé des annonces sans écriture, des questions inventées
  après une bonne réponse et un démarrage demandé sans cours. Les actions
  explicites, l'interprétation courte et la restitution depuis les résultats
  corrigent ces cas sans prétendre assurer une compréhension universelle.
- L'interprétation réelle ne déclenche pas de préparation pour une négation,
  une question sur la méthode ni une demande mêlant création et suppression.
  Une demande distincte d'examen de biologie est interprétée avec le niveau
  lycée, cinq questions, correction finale et sans les documents, comme demandé.
  Ce dernier contrôle classe les intentions uniquement, sans écrire d'étude.

Les essais utilisent exclusivement des documents synthétiques et des
discussions de validation séparées. Les données des autres discussions ne sont
pas modifiées. L'interface installée et le serveur ont été rechargés pour ce
parcours ; les évolutions ultérieures purement serveur ne demandent pas une
nouvelle reconstruction du bureau.

### Ouverture volontaire du panneau

Le retour utilisateur a révélé deux défauts d'affichage : l'ouverture d'Étudier
survivait au changement de discussion, et le panneau était placé avant tout
l'historique. Son état est maintenant associé au fil qui l'a ouvert, puis effacé
en quittant ce fil. Une nouvelle discussion montre le chat normal. Une ouverture
explicite depuis « + » place le panneau après les messages ; le focus ne ramène
plus au début de l'historique. Les études sauvegardées ne sont pas supprimées
lorsque le panneau est fermé.

Correction reconstruite, installée et vérifiée dans la fenêtre native : panneau
après deux messages témoins, nouvelle discussion sans panneau, retour au fil
précédent sans réouverture, ouverture explicite depuis un fil vide puis fermeture.
TypeScript, les tests de logique Étudier et la compilation de l'application
passent. Une discussion de validation séparée contient les deux messages témoins.

### Préparation interrompue sur un sujet sans document

Le retour sur « Je veux comprendre le squelette humain », débutant, cinq
questions, a reproduit un dépassement du délai de **180 secondes**. Le modèle
émettait le premier texte en **0,44 s**, mais préparait encore la cinquième
question à l'arrêt : l'ouverture du formulaire et le réseau n'expliquaient pas
cet essai. Le JSON libre a été écarté : il reproduisait le schéma lui-même.

La préparation valide d'abord la leçon, puis produit les questions en imposant
les intitulés exacts des objectifs déjà préparés. Une simple reformulation
d'objectif ne doit plus déclencher la réécriture du cours entier. Les QCM
utilisent un indice explicite du bon choix ; les questions libres gardent leur
réponse attendue et leur barème. Deux groupes typés imposent les deux formes de
questions et leur nombre exact. Le serveur restitue les identifiants et les
citations originales dans le contrat `Programme` inchangé. Aucun cours
sauvegardé n'est migré.

Les indices invalides, les choix ambigus, les sources inexistantes et les
réponses ouvertes sans critères restent refusés. Une réparation par étape est
possible ; les étapes partagent le **même plafond total de 180 secondes**.
Le JSON compact évite les tokens d'indentation. Les essais ont écarté une
numérotation des objectifs (confusion de base zéro/un), un parcours ne contenant
que des QCM et l'activation du raisonnement approfondi (délai dépassé).

Le message d'échec de création n'annonce plus des réponses sauvegardées quand
l'étudiant n'a encore rien répondu. Lors d'une correction interrompue, les
réponses restent sauvegardées et aucune note n'est inventée. **75 tests Étudier**
passent après ces changements ; la vérification élargie aux conversations, à la
voix, à l'authentification et au périmètre du téléphone compte **288 tests
réussis**. Les contrôles Ruff, de formatage et `git diff --check` passent aussi.

Le modèle réel termine le même sujet sans document en **74,38 s** sur le banc :
**25,01 s** pour la leçon, puis **49,34 s** pour deux QCM et trois questions
ouvertes, sans réparation. Après rechargement du serveur, le bouton du formulaire
dans l'application installée produit le cours en **environ 90 s**, mesurées entre
le clic et la date d'enregistrement. La relecture confirme les cinq questions et
l'absence de réponses avant le début de l'exercice. Le cours puis le
questionnaire s'affichent dans la fenêtre native. Les captures de contrôle sont
limitées à Diapason. Ce changement concerne le serveur : le bureau n'a pas été
reconstruit ni redémarré. Ces mesures ne garantissent pas le même délai sous une
autre charge ou pour un autre cours.

Limite importante du diagnostic : des sorties sans document ont aussi contenu
des imprécisions factuelles et un objectif mal associé à une question. Les
contrôles de structure ne prouvent pas l'exactitude scientifique ; la validation
des exemples réels doit inclure la lecture du cours et de son corrigé.

### Plusieurs études dans le fil, repliables

Le panneau unique repoussé sous tous les messages ne conservait pas la place
d'une étude ; sa relève sélectionnait aussi la dernière étude modifiée à la
place de celle qu'on lisait. Chaque étude est maintenant un bloc indépendant
intercalé dans le fil. Le formulaire mémorise le message qui précède son
ouverture et l'instant d'ouverture ; ces repères sont sauvegardés avec le cours.
Un message envoyé pendant la préparation reste après ce bloc. Une création
orale sans repère d'interface utilise l'instant de début de la préparation.
Répondre, corriger, reprendre ou terminer ne modifie aucun de ces repères.

La relève est commune au fil ; chaque carte reçoit uniquement sa propre
révision et garde un brouillon ou une dictée en cours. Replier une réponse
modifiée l'enregistre d'abord ; un échec laisse la carte ouverte. Le bloc fermé
montre un aperçu du titre et du premier objectif, sans exposer le corrigé. Son
état replié est une préférence locale de présentation, indexée par discussion
et étude. Le cours, les réponses et le bilan restent sur le serveur. Déplier
reprend explicitement cette étude pour la suite de la conversation orale.

Les études anciennes restent lisibles : en l'absence de date de création, le
seul repère disponible est leur dernière écriture antérieure à ce changement.
Il est figé avant leur prochaine modification ; aucune ancienne date précise
n'est inventée. La liste ne coupe plus silencieusement les études après la
cinquantième. Supprimer une discussion conserve le nettoyage déjà prévu.

Validation : **291 tests Python**, **83 tests frontend ciblés** et TypeScript.
Le scénario de prévisualisation isolée vérifie deux études entre trois messages,
la sauvegarde d'un QCM et d'une réponse ouverte avant repli, le bilan, le
rechargement, une troisième étude suivie d'un message et le changement de fil.
Contrôles de largeur à **340, 375 et 1000 px**, sans débordement horizontal ni
erreur JavaScript dans cet essai. L'application a été reconstruite, installée et
relancée, le serveur rechargé. Dans la fenêtre native, l'étude sur le squelette
apparaît entre les messages antérieurs et les suivants ; déplier retrouve les
cinq questions et le bilan existant, puis replier ne garde que l'aperçu. La
capture de preuve porte uniquement sur la fenêtre Diapason.
