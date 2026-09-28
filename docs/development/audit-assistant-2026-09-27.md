# Audit de conversation et d’outils — 27 septembre 2026

Audit demandé par Carlito à partir d’une vraie recherche sur le web. Les
scénarios ont été joués avec le vrai modèle local, dans l’application, puis
sur les mêmes routes locales que le chat et la voix. Les bancs vocaux de cet
audit envoient du texte et reçoivent le vrai audio d’Orion : ils ne constituent
pas une validation de reconnaissance de la voix de Carlito au microphone.

Les corrections décrites sont chargées dans le serveur local. Les derniers
changements concernent le serveur : aucune reconstruction supplémentaire
de l'interface n'est nécessaire pour les utiliser.

## Points forts observés

- Le suivi conserve le sujet et les contraintes dans les essais de recette
  et de correction ciblée ; les tours suivants n’exigent pas de tout répéter.
- Les outils effectuent réellement les recherches, les lectures de pages,
  la création et la lecture de notes, et les calculs testés.
- Orion conserve une sortie audio exploitable sur le parcours testé. Pour
  ces échanges courts, le premier paquet arrive entre environ 2 et 5 secondes
  après le texte reçu, une fois la préparation initiale terminée.

## Constats et corrections

| Scénario | Défaut observé | Correction |
|---|---|---|
| Demander un lien officiel, puis signaler une page introuvable | Après un HTTP 404, un nouveau chemin était inventé et annoncé comme officiel. | Les adresses demandées sont confrontées aux résultats reçus avant affichage. Une adresse candidate peut être lue par le même exécuteur, avec les mêmes permissions et le même budget. Une absence de preuve est annoncée comme telle. |
| Deux lectures web dans une réponse | Deux trames natives Ollama avaient chacune l’index zéro : le chat fusionnait leurs noms et leurs JSON, puis le moteur refusait la suite. | Index distincts sur toute la génération ; test de deux trames jusqu’à leur réassemblage. |
| Créer une note explicitement dans Diapason | L’outil Apple Notes était appelé. | Consignes de destination et refus de cette écriture lorsque la demande désigne Diapason. L’outil Diapason reste autorisé normalement. |
| Relire la note créée | Une réponse issue de l’historique devenait un graphique invalide, sans lecture. | Action `read_note` dans `vie_workspace`, lecture réelle du stockage. Pour une demande explicite de relecture, contrôle avant diffusion ; si un titre est cité, recherche de ce titre sans inventer d’identifiant. Une reprise au plus, puis échec explicite si aucune lecture n’a lieu. |
| Demander le « texte actuel » de la note | Le raccourci de messagerie reconnaissait « text » au milieu de la phrase et prenait « ctuel » pour un destinataire. | Raccourci seulement en début de commande, corps du message explicitement délimité, et préposition entière. « Texte » en français n’est plus un verbe de messagerie. Aucun message n’a été envoyé pendant le diagnostic. |
| Afficher un lien reçu à la voix | Le nettoyage destiné à la synthèse supprimait aussi l’adresse du texte conservé dans le chat. | Séparation du texte affiché et du texte prononcé ; les adresses restent écrites sans être épelées. |
| Poser une question après une longue réponse vocale | Après une réponse de 93 secondes, la fenêtre d’engagement de 90 secondes était déjà expirée ; le suivi était ignoré. | La fenêtre repart après la fin estimée du son. La vérification d’identité n’est pas désactivée. |
| Reprendre les résultats d’un outil à la voix | La trace conservée s’arrêtait à 160 caractères et perdait adresses, contenu et identifiants. | Conservation bornée plus large pour recherche, notes et tâches ; métadonnées métier conservées dans ces traces. |
| Vérifier une durée | Un planning de 15 minutes contenait 3 + 5 + 8 minutes. | Calculateur local disponible à la voix et consigne de vérifier les totaux contraignants. Sa disponibilité ne garantit pas que le modèle l’appellera à chaque calcul. |
| Corriger uniquement un élément dans un suivi | La somme devenait juste, mais le modèle modifiait un autre élément que celui demandé. | Consignes écrites et vocales : identifier l’élément visé et conserver les autres contraintes. Trois scénarios réels de suivi validés ensuite ; pas de garantie universelle. |
| Préparer le chat avant une demande | Le préchauffage n’incluait pas le contrat graphique du client. Les exemples graphiques pouvaient aussi rejoindre un bloc de mémoire près du dernier message. | Contrat graphique dans le premier système ; même contrat dans le préchauffage. Cela ne prouve pas à lui seul la disparition des attentes à froid. |
| Créer et relire les tâches d’un projet | Le paramètre du projet était accepté par le schéma, puis ignoré dans `create` et `list`. | Résolution du projet avant écriture, rattachement réel et relecture limitée à ce projet. Projet absent ou ambigu : refus sans création. |
| Demande à six étapes | Le chat ne permettait que trois tours d’outils : un projet et deux tâches étaient créés, puis la suite s’arrêtait. | Plafond porté à douze tours, comme le budget vocal. Les appels identiques restent dédupliqués. Si le plafond est atteint, une consigne impose de distinguer les actions confirmées des étapes non exécutées. |

Les vérifications de liens établissent une **provenance technique** de
l’adresse, pas la vérité de toutes les affirmations d’une page ni sa qualité.
Une page lue n’est pas automatiquement une bonne recommandation. En dernier
recours, les sources sont explicitement présentées comme encore à évaluer.

## Résultats établis

- Avant correction, une recherche de jeux a proposé un lien absent des
  résultats ; après une lecture en échec, une seconde adresse a été inventée.
- La note de diagnostic a été créée dans Diapason avec son contenu exact.
  Après correction, le scénario de relecture a exécuté `read_note` et rendu
  ce contenu en texte, sans graphique ni identifiant dans la réponse.
  Le dernier contrôle dans l’application installée confirme aussi que
  « texte actuel » ne déclenche plus le raccourci de messagerie.
- Le suivi du calcul a correctement identifié 16 minutes et proposé une
  révision de 7 minutes pour obtenir 15. Sur cet essai écrit, le modèle a
  toutefois calculé sans appeler le calculateur.
- Les essais de recette ont produit les cinq étapes et gardé les contraintes
  du tour suivant. Les listes coupées présentes dans l’ancien historique
  n’ont pas été reproduites de façon suffisamment stable pour en annoncer
  la cause ou prétendre les avoir corrigées.
- Le contrôle automatique du périmètre modifié passe : **1 292 tests**,
  7 ignorés et 3 exclus selon leurs marqueurs ; lint ciblé sans erreur.
  Ce dernier passage inclut les ajustements des liens, des destinations,
  des projets et du plafond d'appels d'outils.
  Cela ne constitue pas la validation complète du dépôt exigée avant push.

## Parcours vocal réel, sans microphone

Le banc utilise le serveur installé, son modèle local, ses outils normaux,
la mémoire activée et l’audio réellement produit par Orion. Il ne joue pas
le son et n’évalue donc ni la reconnaissance au micro ni le naturel à l’écoute.

| Demande | Résultat | Premier paquet audio / fin serveur |
|---|---|---|
| Additionner 3, 5 et 8 avec le calculateur | Outil exécuté ; 16 minutes, donc dépassement de 15. | 3,92 s / 6,13 s |
| Corriger le dernier nombre | Total corrigé, mais mauvais élément : 3 + 4 + 8 au lieu de 3 + 5 + 7. Consigne de correction ciblée renforcée ensuite. | 2,99 s / 5,27 s |
| Lire Code.org et donner son lien dans le chat | `web_read` réussi ; lien reçu après redirection, conservé dans la transcription. | 3,96 s / 8,61 s |
| Redonner seulement l’adresse précédente | Adresse exacte conservée ; aucun son pour une adresse seule, conformément au nettoyage oral. | Aucun audio / 3,56 s |

La préparation initiale de cette séance a pris 39,7 secondes. Ces temps
partent d’une entrée **texte**, pas de la fin d’une phrase au microphone.
Le premier son d’une recherche peut être l’annonce de consultation ; il
ne faut pas le présenter comme le délai de la réponse finale.

Après renforcement des consignes, trois nouveaux essais avec contexte fourni
au parcours vocal normal donnent :

| Suivi demandé | Réponse vérifiée | Premier audio |
|---|---|---|
| Corriger le dernier de 3, 5 et 8 pour totaliser 15 | Troisième étape de 7 minutes ; calculateur appelé. | 4,38 s |
| Remplacer seulement le deuxième fruit | Pommes, fraises, bananes ; premier et dernier préservés. | 1,98 s |
| Réduire seulement les loisirs pour passer de 65 à 60 dollars | Transport 20, repas 30, loisirs 10 ; calculateur appelé. | 4,70 s |

Le démarrage à froid de cette seconde série prend 56,27 secondes ; les deux
réouvertures prennent 0,68 et 0,59 seconde. Les réponses ne sont donc pas
précédées d’une attente identique selon l’état des moteurs et du contexte.

Dans le chat chargé, le nouvel essai de vérification d’adresse a exécuté
`web_search` puis `web_read`, sans la fusion invalide des appels. La page
demandée a été reçue. Le résultat de secours a ensuite été resserré sur
l’adresse de ce domaine, plutôt que de présenter toutes les pages tierces.
Le dernier échange de l’application contient bien l’adresse de la page lue,
sans nouveau chemin inventé ; il a pris 81,9 secondes, dont 13 secondes
derrière le préchauffage et 42 secondes de premier préremplissage.

## Tâche à plusieurs étapes, stockage isolé

Le vrai modèle local a reçu cette consigne : créer un projet, y ajouter
trois tâches pour le lendemain, terminer uniquement la première, relire les
tâches et donner leurs états. La boucle du chat et les deux vrais outils
de projets/tâches ont été utilisés avec leurs écritures dans une base
temporaire. Les projets personnels de Carlito ne sont pas concernés par ce banc.

Avant correction du plafond, le scénario s’arrêtait après le projet et deux
tâches. Après correction, les six appels réussissent en 47 secondes :

| Tâche | Résultat effectivement relu dans la base |
|---|---|
| Choisir un jeu | Terminée |
| Tester quinze minutes | Non terminée |
| Noter le bilan | Non terminée |

Les trois tâches ont le même identifiant de projet réel et la date demandée.
Il n’y a ni quatrième tâche ni deuxième projet. Ce banc présente seulement
les deux outils métier concernés au modèle ; il ne mesure pas la difficulté
de sélection parmi toute la trousse de l’application.

## Limites de l’audit

Les délais écrits ont atteint environ 40 à 80 secondes sur plusieurs essais
chargés. Les métriques isolent surtout le préremplissage du modèle, parfois
32 à 52 secondes, alors qu’une lecture de note prend environ 24 millisecondes
et une recherche web 1 à 2 secondes. Ne pas confondre ces essais avec les
mesures antérieures d’échanges vocaux courts et chauds.

Les permissions, le contrôle d’identité et les validations des actions
sensibles sont conservés. Aucun message n’a été envoyé à un tiers pour
l’audit. Deux notes portant le titre de diagnostic existent : une dans
Apple Notes, créée lors de la reproduction du défaut, et une dans Diapason.
Elles n’ont pas été mélangées avec des notes ordinaires ni supprimées
silencieusement.

Cet audit couvre la conversation, le suivi, les liens, les notes, le
calcul et un projet à six étapes. Il ne valide pas tous les outils,
tous les projets longs, ni toutes
les conditions de bruit et de charge. Les changements restent locaux,
sans commit ni push de l’ensemble des travaux partagés.

## Priorités encore ouvertes

1. Réduire le coût du premier échange et des changements de contexte lourds,
   avec des comparaisons qui séparent préparation, modèle, outils et audio.
2. Étendre le scénario de projet validé à toute la trousse, aux tâches plus
   longues, aux interruptions et aux reprises après une erreur d’outil.
3. Rejouer avec la vraie voix les formulations courtes et les suivis ambigus.
   La réussite du banc texte-vers-audio ne remplace pas cette vérification.

## Complément : pourquoi le chat écrit attendait presque une minute

Trois échanges courts, envoyés au serveur avec la trousse complète, les
visuels, les questions interactives et les contrôles habituels, ont donné
40,28 / 43,94 / 57,41 secondes avant le premier texte. Les journaux natifs
montrent 93 à 94 % de préfixe commun, mais aucun point de reprise assez tôt :
le préchauffage incluait l'horloge et une demande factice. L'heure suivante
invalidait le calcul, puis le modèle relisait environ 13 000 jetons.

La correction place les règles de questions dans l'identité stable et
prépare uniquement ce préfixe, avec les mêmes 47 schémas. Le vrai échange
conserve son heure actuelle, ses perceptions, sa mémoire et son historique.
Après cette seule correction, les trois premiers textes arrivent en
7,98 / 6,98 / 8,44 secondes. Le journal confirme la restauration effective
du cache ; le modèle ne relit plus tout le préfixe.

Un deuxième délai de 3 secondes environ séparait les premiers mots produits
de leur affichage : le contrôle de confidentialité gardait 128 caractères
en réserve. La réserve devient 48 caractères pour les motifs de longueur
bornée (au plus 36), avec un contrôle tous les 16 caractères. Les clés,
adresses et valeurs non bornées restent retenues jusqu'à leur frontière ;
le mode de blocage complet et les scanners personnalisés restent atomiques.
Les 617 tests des contrôles de confidentialité et du parcours concerné
passent, dont les découpes des motifs dans les versions Rust et Python.

Après chargement de ces deux corrections dans le serveur, les mêmes trois
demandes produisent les mesures suivantes. Les réponses sont complètes,
le suivi conserve l'exemple anglais et sa traduction, et les 47 schémas
d'outils sont présents à chaque tour.

| Demande | Premier texte avant | Premier texte après | Réponse entière après |
|---|---:|---:|---:|
| Intérêt d'une pratique quotidienne | 40,28 s | 4,35 s | 7,77 s |
| Exemple anglais et traduction | 43,94 s | 3,57 s | 5,18 s |
| Remplacer l'exemple par une commande de café | 57,41 s | 4,65 s | 5,24 s |

Ce sont des requêtes réelles au serveur installé, après préparation du
préfixe, pas une mesure du navigateur ni une garantie pour toute demande.
Le premier recalcul complet du nouveau préfixe a encore coûté 48,5 secondes ;
le rechargement suivant, avec le préfixe déjà en mémoire, n'a demandé que
0,58 seconde de préparation. Le passage à la voix, un autre modèle, une trousse
différente ou un historique lourd peuvent de nouveau allonger l'attente.

La relecture de la note du diagnostic a ensuite rendu son contenu exact en
8,39 secondes, après une vraie recherche par son titre dans le stockage.
Ce contrôle conserve l'historique chargé des essais précédents. Il confirme
que le gain sur la conversation simple ne supprime pas les étapes utiles
d'une demande outillée. Le contrôle final élargi du chat, du moteur et de
la confidentialité passe : **785 tests**, sans échec.

La durée indiquée dans le pied du message correspond à la réponse entière.
Elle ne doit pas être comparée au premier son d'Orion, ni au premier mot
visible. La préparation initiale reste distincte des échanges une fois prêts.

## Complément : recettes refusées puis réponse répétée

Des captures d'écran montrent un cas absent des premiers essais de recette :
dans le fil chargé de l'audit, « Donne moi des recettes pour faire des pâtes »,
puis « oui » et « Oui tu peux me les donner » produisent le même refus
d'accéder aux « recettes de mes outils ». Aucun échec d'outil ne justifie ce
refus. La reproduction sur le serveur, avec une copie en lecture seule de
l'historique, retrouve exactement cette réponse. Une conversation neuve
donne seulement des idées de plats : elle ne reproduit pas la boucle.

Une première correction des consignes permet de répondre à la demande
initiale, mais ne suffit pas à sortir des refus déjà présents dans le fil.
La version retenue rattache aussi les accords courts à la dernière demande
substantielle, sans retirer de messages ni transformer l'accord en permission
d'action. Le rappel reste unique quand le routeur et la boucle d'outils le
préparent tous les deux. Les règles du canal écrit suivent désormais la
persona : la préférence pour la concision reste compatible avec une recette
qui donne ingrédients et préparation. Le préchauffage garde exactement le
même assemblage que le chat.

Après rechargement du serveur, les trois premiers essais avec le modèle local
et les 47 outils donnent :

| Cas rejoué | Résultat | Premier texte / réponse entière |
|---|---|---:|
| Demande initiale, nouveau fil | Quatre recettes avec ingrédients et préparation. | 3,77 s / 24,51 s |
| Même demande, historique de l'audit | Deux recettes, sans refus d'accès inventé. | 4,77 s / 18,13 s |
| « Oui tu peux me les donner », avec les refus antérieurs | Deux recettes au lieu de la réponse répétée. | 5,67 s / 16,04 s |

Les réponses ne sont pas des textes prédéfinis. La dernière reste succincte
et propose encore un développement ; le défaut de refus répété est corrigé
sur ces cas, ce qui ne garantit pas la complétude de toute recette générée.

Le suivi « Garde seulement la recette la plus simple, sans crème, pour deux
personnes » conserve ces contraintes et donne ingrédients et cinq étapes
(premier texte à 5,64 s, réponse entière à 19,06 s). Sur la version finale
rechargée, un simple « oui » ajouté après les **trois** refus des captures
donne deux recettes : premier texte à 4,81 s, fin à 19,56 s. Aucune conversation
enregistrée n'a été réécrite pour ces essais.

Le contrôle d'un accord à une offre de relecture a révélé un défaut voisin :
le modèle utilisait un identifiant inventé, puis demandait toute la liste des
notes sans filtrer. Le résultat tronqué ne contenait pas la note du diagnostic,
pourtant présente dans la base. Une offre de lecture acceptée conserve
désormais le contrôle de lecture du tour ; si `list_notes` omet son filtre,
le titre cité par l'utilisateur est utilisé. Un filtre déjà fourni, une action
d'écriture et un simple acquiescement après lecture terminée ne sont pas
modifiés. L'exécuteur et ses permissions restent identiques.

L'essai final appelle effectivement `list_notes` avec le titre exact et
restitue « Objectif : apprendre la programmation. Durée : 15 minutes par
jour. », conforme à la base lue séparément (6,36 s avant le texte, 8,31 s au
total). Le contrôle ciblé passe : **183 tests en 6,64 s**, lint et formatage
des fichiers concernés sans erreur. Le serveur est rechargé ; aucune
reconstruction du bureau n'est nécessaire pour ces corrections côté serveur.
