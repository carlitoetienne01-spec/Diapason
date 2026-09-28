# L'assistant accède aux données de Diapason

27 septembre 2026. La consultation d'une semaine ne filtrait que son lundi ;
une demande annuelle comptait toutes les tâches. Les outils de finances ne
portaient que cinq actions, alors que l'interface en proposait beaucoup plus.

## Périmètre

- `vie_tasks` : `count`, `list` paginé, `read`, plus les actions existantes.
  `date` pour un jour, `period` avec une date d'ancrage pour une semaine
  (lundi–dimanche), un mois ou une année ; `startDate`/`endDate` inclusifs
  pour un intervalle libre. Les totaux précèdent la pagination et séparent
  terminé/non terminé. Ils comptent les tâches enregistrées, pas les
  occurrences futures non matérialisées des modèles récurrents.
  Une période redondante avec ses bornes exactes est acceptée ; des bornes
  contradictoires restent refusées.
- `diapason_app` : catalogue fermé de 60 opérations métier des tâches,
  projets, habitudes, notes, planificateur et finances. Le schéma détaillé
  de chaque opération vient des modèles Pydantic des handlers existants.
  Les écritures et lectures utilisent exactement les mêmes magasins que
  les écrans ; aucun SQL ni chemin HTTP libre n'est exposé au modèle.
- `diapason_app_delete` : 13 suppressions nommées, avec la cloche commune.
  Les identifiants doivent provenir d'une lecture. Les écritures des finances
  sont celles du registre local en CAD, pas des opérations bancaires.
- Navigation locale : les 17 destinations de la roue sont accessibles via
  `navigate`. `current_view` décrit la vue publiée par l'interface. Une mise
  en file n'est pas un affichage : la réussite attend le chemin réellement
  rendu. L'événement expire après quatre secondes. Le protocole signé et
  les routes interappareils ne changent pas.
  Une commande explicite comme « Ouvre la page Finances de Diapason » passe
  directement par l'exécuteur d'outils, sans inférence : l'ancien raccourci
  lançait simplement l'application. « Ouvre Notes » garde son sens d'ouverture
  d'Apple Notes ; une commande composite revient au modèle.

Le catalogue n'accorde aucun accès aux identifiants, aux clés, à
l'administration réseau ou aux mutations de réglages. Le plafond du téléphone
reste inchangé : les nouveaux outils du Mac y sont refusés par défaut.
Ce plafond se décide nom par nom, alors que `diapason_app` porte aussi
`navigate` et `current_view`, qui pilotent et lisent la fenêtre du Mac.
Depuis le 28 septembre 2026, l'outil les refuse lui-même au téléphone,
en résultat d'outil : si la phase 6 ouvre `diapason_app` pour ses données,
ces deux opérations ne suivent pas sans décision. Le catalogue rendu au
téléphone ne liste pas non plus les pages que `navigate` ouvrirait.
Les conversations, le web, les documents et les autres fonctions conservent
leurs outils déjà présents.

## Forme des appels

`operation=describe, name=upsert_budget` donne le schéma ; l'exécution emploie
`operation=upsert_budget, params={body:{scope:"global",yearMonth:"2026-10",limit:650}}`.
`upsert_budget` crée ou modifie le même mois/périmètre. Pour le relire,
`operation=list_budgets, params={yearMonth:"2026-10"}`. Le mois effectif
figure dans le résultat, même si la liste est vide.

Les champs inconnus sont refusés, y compris les filtres mis au mauvais
niveau. Une erreur de validation rend le schéma réel pour permettre une
reprise. Aucun succès n'est produit pour une validation échouée.

## Cache et vérification

Les deux schémas d'outils restent fixes dans les trousses texte et voix ;
les schémas détaillés sont des résultats d'outils. Le préfixe ne change donc
pas à chaque domaine consulté. Le chat compte maintenant 49 outils par défaut.

Une lecture peut se répéter après une écriture métier réussie. La protection
contre la répétition des écritures reste active, indépendamment de l'ordre
des clés JSON. Une note créée/modifiée dont la relecture a été demandée peut
être relue par son identifiant retourné, même sans titre cité entre guillemets.

Un essai natif disait avoir changé le budget de 650 à 720 sans aucun appel.
Les demandes explicites de mutation retiennent donc la confirmation tant
qu'aucune écriture interne n'a réussi ; une reprise réclame l'exécution,
puis rend un échec explicite si elle manque. Une cible imprécise peut encore
être demandée. Une relecture expressément demandée doit suivre l'écriture.
Ce contrôle lexical du chat complète les résultats des outils ; il ne
prétend pas démontrer l'exécution de toute paraphrase ni de chaque étape
d'une demande composite, et ne change pas la boucle vocale.

Les comptes simples et explicites (aujourd'hui, semaine/mois/année relatifs,
année donnée, date ou intervalle complètement daté) empruntent un chemin
direct, au clavier comme à la voix : même outil `vie_tasks`, même exécuteur,
même période, mêmes totaux. La phrase est composée depuis le résultat reçu.
Une grammaire fermée refuse ce raccourci pour un projet, une comparaison ou
une commande composite : le modèle reçoit alors la demande entière. Le
plafond d'outils vocaux et le refus des commandes Mac depuis le téléphone
restent actifs. Le chemin évite les deux inférences constatées à 22,6 s
avant l'audio alors que la lecture prenait 15 ms.

## Vérifications

- 532 tests métier, outils et chat ; 211 contrôles complémentaires comprenant
  les parcours vocaux ; 146 contrôles ciblés après les corrections de relecture
  et de confirmation des écritures.
  Ces groupes se recouvrent, leurs nombres ne s'additionnent pas.
- TypeScript et 55 tests de navigation ; construction et installation Tauri.
- 102 tests des commandes du bureau, actions rapides, périodes et navigation
  après les deux défauts révélés dans l'application installée.
- 156 tests couvrant le comptage direct, puis 112 contrôles vocaux et de
  filtrage, dont le respect du plafond d'outils dans le nouveau raccourci.
- Mutations éprouvées dans une base isolée : notes, comptes, transactions,
  budgets, objectifs et abonnements. Aucune donnée financière personnelle
  n'a été créée, modifiée ou supprimée pour ces essais.
- Modèle local réel, base isolée : budget d'octobre créé à 650 puis modifié
  à 720, relu avec l'outil après chaque écriture ; note créée, complétée et
  relue, puis supprimée avec la confirmation du banc. Les assertions
  contrôlent le magasin après chaque échange, pas seulement le texte rendu.
  Ces demandes composites prennent 30 à 46 secondes sur ce banc ; ce n'est
  pas une validation de latence inférieure à cinq secondes pour les actions.
- Serveur installé, lectures seules : les consultations du 27 septembre,
  de la semaine du 28 septembre au 4 octobre et de l'année 2026 correspondent
  aux comptes SQLite indépendants. L'année rend 19 tâches, dont 12 terminées
  et 7 restantes, au moment du contrôle. La navigation explicite vers Finances
  prend 0,6 à 0,9 s ; le chemin affiché est vérifié dans la fenêtre Tauri.
  Le dernier compte annuel prend 10,7 s avant le texte, les deux premiers
  comptes 18 à 21 s : ne pas présenter ces appels d'outils comme des réponses
  systématiquement sous cinq secondes.
- Après ajout du chemin direct, mêmes questions jour/semaine/année dans
  le serveur installé : réponse complète en 0,01 à 0,03 s, sans inférence.
  Banc WebSocket vocal (texte injecté, pas une capture micro) : compte de
  la semaine puis de l'année, même outil réussi et même texte exact ; premier
  audio à 0,58 puis 0,54 s après réception du texte. Préparation de séance
  mesurée séparément : 7,58 s sur cet essai. Ces chiffres n'incluent pas
  la reconnaissance de la voix de l'utilisateur et ne s'étendent pas aux
  demandes composites traitées par le modèle.

L'application de bureau est reconstruite et installée ; le serveur a été
rechargé après les derniers correctifs. Le micro n'a pas été ouvert pour
les contrôles WebSocket ; la page Notes a été rétablie après navigation.

Les opérations décrites sont celles réellement proposées par les écrans.
Un futur domaine ou une future route nécessite un ajout explicite au catalogue
et ses vérifications ; ce n'est pas une permission universelle sur le serveur.
