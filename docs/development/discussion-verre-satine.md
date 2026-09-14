# Discussion — du verre satiné au cristal

Direction validée par Carlito le 12 septembre 2026 : reprendre **la poche
vitrée** de `NoteFolderVisual`, pas le cartable entier. Seuls le compositeur
et ses menus changent de matière. Le fond existant est prolongé derrière la
saisie ; les messages, la typographie et les autorisations restent identiques.

La première version a été refusée visuellement par Carlito : le canevas
s'arrêtait avant la saisie, 64 % de teinte et 16 px de flou effaçaient le
fond, et le quadrillage CRT passait au-dessus du verre. Les tests techniques
ne suffisaient pas à valider cette matière.

## Matière

- Une seule surface, arrondie, éclairée à 162° comme la poche des cartables.
- Cristal neutre sur le sable Ardéchine, verre fumé en sombre.
  Repères : cristal `#f8fcff`, givre `#d9e8ed`, ombre `#253239`, reflet
  `#ffffff`, sable existant `#beb3a1`. L'encre et les couleurs fonctionnelles
  viennent du thème ; typographie et alignement des deux rangées inchangés.
- Fond diffusé par `backdrop-filter`, jamais `filter` sur le contenu : texte
  et icônes restent nets. Le même canevas passe derrière le compositeur.
  Le centre passe de 3 à 1,2 px de flou. Un anneau de 7 px, flouté à 4 px,
  donne le givrage des tranches sans recouvrir le texte.
- Teinte de fond ramenée de 10 à 3 % ; menus plus opaques (78 %, flou de 8 px)
  pour garder leurs choix lisibles.
- Le quadrillage Terminal est découpé uniquement au-dessus des surfaces
  vitrées. Il reste inchangé ailleurs et revient intégralement à leur fermeture.
- Reflet du bouton d'envoi seulement quand l'envoi est possible ; l'état
  désactivé dépend toujours du texte, du modèle et de son chargement.
- Contour au focus, pression brève ; aucun nouveau moteur d'animation,
  aucune animation de flou ou boucle permanente.
- Reflet elliptique lié à la position de la souris, regroupé à une mise à
  jour par image, arrêté en sortie et désactivé avec les mouvements réduits.
- Réfraction géométrique simulée **des glyphes du canevas** : déplacement
  maximal de 2,8 px et étirement maximal de 14 % dans une bande de 16 px
  près du contour arrondi. Le centre et le fond hors de la vitre sont intacts.
  Ce n'est pas une déformation de l'interface ni une capture du bureau.

## Périmètre pour les sessions parallèles

- `frontend/src/components/Chat/ComposerGlass.css` : matière et états visuels,
  y compris les menus rendus dans un portail, le focus clavier et les replis.
- `InputArea.tsx` : classes du compositeur, deux groupes de contrôles qui
  passent à la ligne sur une fenêtre étroite. Aucun changement de l'envoi,
  de la dictée ni de la recherche.
- `ComposerBar.tsx` : matière des boutons et menus. Leur largeur est bornée
  à celle de la fenêtre ; le mode d'autorisation et le modèle utilisent
  toujours les mêmes fonctions et les mêmes routes.
- `ChatArea.tsx` : un seul canevas derrière les messages et le compositeur,
  indépendant du défilement ; pas de nouvelle boucle d'animation.
- `useSurfaceVitree.ts` / `verreTexture.ts` : masque alpha du quadrillage
  supérieur, recalculé sur changement de géométrie. Les trous des menus et
  du panneau se réunissent, même en cas de chevauchement. Observateurs et
  masque sont retirés lorsque leurs surfaces se démontent.
- `cristal.ts` / `cristal.test.ts` : réfraction bornée du biseau et reflet
  sans React à chaque mouvement. `MatrixRain.tsx` applique la déformation
  lors du dessin existant, en lisant la géométrie mise en cache par
  `verreTexture.ts` ; aucune lecture du DOM ajoutée à chaque image.

Pas de dépendance nouvelle. Sans flou disponible ou si la transparence est
réduite, le panneau redevient opaque. Le contraste forcé garde un fond
système et des contours ; la réduction des mouvements supprime les nouveaux
déplacements et transitions. Les indicateurs vocaux existants ne changent pas.

## Vérifier sans agir sur le compte

Lancer TypeScript et Vitest, puis vérifier Discussion en Ardéchine et en
sombre, au repos, avec un brouillon **non envoyé**, menu ouvert puis fermé
avec Échap. Vérifier aussi une fenêtre étroite. Ne pas choisir Auto, changer
le modèle ni ouvrir le micro pour tester la matière. Une compilation Tauri
est nécessaire pour que l'application installée embarque le nouveau style ;
aucun redémarrage du serveur Python n'est nécessaire pour ce changement.

Validation technique de la première version, avant le retour visuel : TypeScript et 398 tests frontend passent dans
l'arbre partagé ; 373 tests passent dans le paquet isolé, qui exclut le
chantier Succès parallèle. Compilation Tauri réussie, application Mac
installée et signature vérifiée. Rendu vérifié dans la WebView macOS avec
le vrai modèle sélectionné, et dans le navigateur en Ardéchine/sombre,
avec menus, puis à 390 et 320 pixels. Aucun message d'essai envoyé, aucun
modèle ni mode d'autorisation changé. Le serveur a conservé son processus.
L'app précédente reste dans `~/.diapason/backups/Diapason.app.precedente`.
Cette installation locale ne met pas à jour le binaire Windows.

Seconde version après ce refus : 404 tests frontend passent dans l'arbre
partagé, 379 dans le paquet isolé ; TypeScript et compilation Tauri passent.
Vérification visuelle sur le Mac installé : les caractères du canevas
continuent sous la vitre, diffusés, et le quadrillage ne recouvre plus sa
surface. Dans le navigateur : découpes réunies avec un menu ouvert, suivi
à 320 px et masque retiré après navigation hors de Discussion. Aucun message
envoyé, aucune permission changée, aucun redémarrage du serveur ni push.

Troisième version, cristal : 411 tests frontend passent dans l'arbre
partagé, 386 dans le paquet isolé ; TypeScript, compilation Tauri et
vérification de signature passent. Le reflet a été vérifié dans le
navigateur : actif au passage de la souris, arrêté en sortie. Le rendu
de l'application Mac installée a été inspecté : centre plus clair,
caractères visibles derrière le verre, tranches givrées et contrôles nets.
Le premier essai de tranche, trop blanc, a été atténué avant installation.
Aucun message envoyé, aucune permission changée ; le serveur a conservé
son processus. L'ancienne application est conservée dans la sauvegarde
indiquée ci-dessus. Aucun commit ni push ; Windows n'est pas mis à jour.

## Extension aux cartes du panneau système

Demandée par Carlito le 12 septembre 2026 après le compositeur : même
matière sur chacune des cartes Session, Appareil et Comparatif des coûts.
Le fond du panneau, les titres et leur typographie restent inchangés ; les
deux colonnes de statistiques et les quatre lignes de coûts restent en place.
La palette cristal/givre/encre décrite plus haut est réutilisée, sans ajouter
une nouvelle couleur ni animer les chiffres.

- `SystemPanel.tsx` utilise `CarteSysteme` pour les huit cartes visibles et
  les températures CPU/GPU lorsqu'elles sont disponibles. Aucune modification
  des calculs, tarifs, valeurs ou appels de télémétrie.
- `SystemPanelGlass.css` ne change que l'échelle du matériau : rayon de
  12 px, biseau de 2,5 px et reflet de 120 × 60 px pour des cartes de 36 à
  60 px de haut. Le premier essai à 4 px donnait un cadre trop épais.
- Le même motif CRT est placé sous la vitre de chaque carte et retiré
  au-dessus par le masque partagé. Contrairement au compositeur, ces cartes
  n'ont pas de caractères animés derrière elles : aucune réfraction de
  glyphes ni nouvelle boucle de canevas n'est prétendue ici.
- Chaque reflet répond au pointeur ; les cartes restent informatives,
  sans faux bouton ni étape de tabulation ajoutée. Mouvements réduits,
  transparence réduite et contraste forcé gardent les replis du compositeur.
- `verreTexture.ts` borne la découpe d'une carte à la fenêtre de défilement
  marquée `data-verre-defilement`. Les arrondis ne se déplacent pas lorsque
  le bord d'une carte sort du panneau. Quatre tests couvrent la coupe
  partielle, les cartes sorties, la réunion de huit cartes et le scroll.

Vérifications avant compilation : TypeScript et 415 tests frontend passent
dans l'arbre partagé. Navigateur : huit cartes en Ardéchine et Oxblood,
reflet sur Requêtes seulement puis arrêt en sortie, défilement du panneau
dans une fenêtre de 900 × 400 px. Aucun message ni changement d'autorisation.

Installation Mac vérifiée : 390 tests passent dans le paquet isolé sans les
modifications Succès parallèles ; compilation Tauri et signature Apple
Development valides. Les huit cartes ont été inspectées dans la WebView
installée avec les vraies valeurs (4 requêtes, 8 jetons), inchangées après
le test. Interface web actualisée, processus serveur conservé, ancienne app
sauvegardée. Aucun commit ni push ; le binaire Windows reste inchangé.

### Cartes plus transparentes — retour visuel de 13 h 14

Carlito trouve les cartes encore pleines, et demande davantage de verre
clair. La validation technique précédente ne valait pas acceptation de la
matière. Ajustement limité à `SystemPanelGlass.css` : aucun changement du
compositeur, du panneau, de sa géométrie ni des données.

- Centre sans teinte de fond, seulement un reflet neutre de 5,5 % à un coin
  et 2,5 % à l'autre. Palette et typographie existantes conservées.
- Flou central abaissé de 1,2 à 0,18 px : le motif de 3 px doit rester
  visible, pas devenir un aplat uniforme. Saturation ramenée à 104 %.
- Biseau réduit de 2,5 à 1 px et flou de tranche de 4 à 1,2 px. Ombres et
  double trait lumineux atténués pour éviter le cadre de plastique.
- Motif sous la vitre ancré à la fenêtre, comme la texture du reste de
  l'écran ; il ne change plus de phase d'une carte à l'autre.
- Les replis de transparence réduite et contraste forcé sont explicitement
  conservés malgré la priorité des nouveaux sélecteurs CSS.

L'aperçu Ardéchine montre la grille à travers les huit cartes, avec du texte
net. Le centre de la saisie garde son flou antérieur : il n'est pas retouché.

Vérification de cette révision : TypeScript passe dans l'arbre partagé et
dans le paquet isolé ; les 390 tests de ce paquet passent. Compilation et
signature Mac valides. Après installation, la WebView Ardéchine laisse bien
voir la grille dans chaque carte ; les huit valeurs, la saisie vide et le
modèle sélectionné sont inchangés. Aperçu sombre vérifié également. Ancienne
app sauvegardée, serveur non redémarré, aucun commit ni push.

## Habitudes — même verre clair, après validation des cartes système

Carlito valide les cartes plus transparentes puis demande la même matière
sur Habitudes. Le fond et les couleurs actuels sont conservés (verre clair,
pas un changement de thème vers le vert). Les états colorés des jours,
la carte annuelle et les compteurs restent fondés sur les données existantes.

Le matériau est désormais partagé par `components/Glass/CarteVitree.tsx`
et `CarteVitree.css` : ce dernier reprend `Chat/SystemPanelGlass.css`,
sans changer ses valeurs validées. Le panneau système utilise le même
composant, et non une deuxième copie du style. Les chemins des sections
précédentes racontent donc l'historique, pas une autre feuille à modifier.

- `SuccesHabitsPage.tsx` : trois compteurs, carte annuelle, cartes mensuelles
  de chaque habitude, état vide et contenant du formulaire. Balises section
  et article conservées ; les fonctions métier et leurs appels sont inchangés.
- `SuccesHabitsGlass.css` : arrondis existants de 16 px et reflet de
  180 × 85 px adapté aux surfaces plus grandes. Même centre clair à 0,18 px
  de flou, sans teinte beige ; biseau toujours de 1 px.
- La fenêtre de défilement porte le même marqueur de découpe CRT que le
  panneau système. La texture reste derrière la vitre et ne recouvre pas
  le texte. Les couleurs des cases, les boutons, les champs et les réglages
  internes de récurrence ne sont pas remaquillés.
- Pas de nouveau canevas, dépendance, appel réseau ou boucle d'animation.
  Les autres modifications Succès de la session parallèle restent exclues
  de la construction locale isolée.

Vérification de développement : TypeScript et 415 tests frontend passent.
L'aperçu sans autorisation API sert uniquement à vérifier les surfaces,
l'état vide et l'ouverture/annulation du formulaire vide. À 390 px, les
cartes restent dans la fenêtre sans débordement horizontal. Les véritables
habitudes doivent être inspectées dans l'application Mac, sans cocher,
créer, modifier ou supprimer une habitude ni activer de rappel.

Installation vérifiée : 390 tests passent dans le paquet isolé, compilation
Tauri et signature Apple Development valides. Dans l'app Mac, les trois
compteurs (27, 0/2, 27), la carte annuelle et les quatre cartes mensuelles
ont été inspectés avant/après, puis après défilement. Les jours cochés,
manqués et futurs gardent leurs couleurs et leur état. Aucun clic sur un
jour, aucune écriture d'habitude, aucun rappel activé. Discussion conserve
la matière validée. La page Habitudes est laissée ouverte ; ancien bundle
sauvegardé, serveur conservé, aucun commit ni push.

## Parler à Diapason — même verre, 12 septembre après 14 h 40

Le panneau vocal demandé reprend le centre à 0,18 px, le biseau de 1 px
et les reflets de `CarteVitree.css`. Pas de copie du matériau, ni de
modification des cartes précédemment validées. La silhouette, Geist,
l'orbe violet/cyan, les textes et les actions vocales sont conservés.
Les encres s'adaptent au thème pour rester lisibles sur une vitre claire.
Le bouton de démarrage devient vitré également.

Trois obstacles à la transparence ont été traités :

- Le panneau n'est plus rempli de noir. Le rideau n'applique plus un flou
  de 14 px et un noir à 76 % : une atténuation de 76 % dans la couleur du
  thème garde l'arrière-plan perceptible sans lui donner le premier plan.
- Le canevas n'est plus opaque. Le premier essai `mix-blend-mode: screen`
  laissait un ovale noir dans le contexte de composition de la vitre :
  cette tentative a été retirée. Le rendu WebGL accepte l'alpha et une
  passe après le bloom rétablit un alpha prémultiplié à partir du maximum
  RGB. Le noir devient transparent ; la lumière sur fond noir reste la
  même. Aucun changement de la mesure audio, des profils ou des permissions.
- La découpe CRT et le reflet s'inscrivent à chaque ouverture du panneau,
  même lorsque `TalkOrb` reste monté sans DOM à l'état fermé. Le paramètre
  `visible` du hook vaut `true` par défaut pour préserver les autres cartes.

Le fil de transcription possède une diffusion locale de 6 px, distincte
du centre clair, pour séparer ses textes de ceux de la page sous-jacente.
Transparence réduite, mouvement réduit et contraste forcé restent pris en
compte. Le banc DEV est ajusté à la spécificité des nouveaux sélecteurs ;
ses états simulés ne constituent pas un test d'appel vocal réel.

Vérifications : 415 tests frontend de l'arbre partagé passent ; TypeScript
et les 390 tests du paquet isolé passent, compilation Tauri réussie.
Navigateur : Ardéchine et Oxblood, fermeture/réouverture, retrait du canevas,
retour du focus au bouton Parler, boucle de tabulation et Détails vérifiés.
Le banc avec conversation simulée reste dans 390 × 760 px, sans débordement
horizontal ; les commandes et le fil restent atteignables par défilement.
L'erreur d'authentification de l'aperçu de développement est préexistante :
elle n'est pas masquée ni présentée comme une panne de l'application installée.

Construction isolée : `/private/tmp/diapason-voix-verre.mAjmDR`, depuis le
paquet Habitudes, sans les changements Succès parallèles. Mise à jour Mac
signée avec la même identité Apple Development, signature vérifiée.
SHA-256 du binaire :
`b89a75e42e81fdfa76c7dd8441f98b414c97991efa2c49e3a3d95d2239af2ded`.
Statique web actualisé avec les mêmes assets. Ancien bundle dans
`/Users/carlito.e/.diapason/backups/Diapason.app.precedente`, ancien statique
dans `static-precedent` sous la copie isolée. Serveur PID 67047 conservé,
health `ok`. Aucun commit, push, changement Windows ou ouverture du micro
par cette vérification.

Dans la WebView Mac installée, le verre, les pages en arrière-plan, l'orbe
sans disque noir et les commandes sont visibles. Une conversation active
avec transcription était déjà présente après la relance : elle a été
observée sans interrompre la session ni agir sur ses commandes. Cette
observation ne certifie pas la réponse audio de bout en bout.

## Cadres des cinq pages — 12 septembre, après 15 h

Bilan, Tableau de bord, Finances, Planificateur et Tâches utilisent
`CadreVitre`. Le centre conserve la transparence validée et son flou de
0,18 px. Le volume vient du biseau porté à 1,5 px, d'une tranche inférieure
de 3 px et d'une ombre courte ; aucun nouvel aplat laiteux, aucune animation
permanente. Les variantes compactes gardent les calendriers et les petites
cartes à leur taille. Le motif du thème reste visible derrière le contenu.

Le composant conserve la balise et les événements d'origine, sans wrapper
intermédiaire sur les éléments déplaçables. `styleCadreVitre` retire seulement
les fonds et bordures neutres : couleurs d'alerte, de dépôt, de sélection,
opacité et hauteur restent prioritaires. Cinq tests protègent ce contrat.
`TaskCard` n'active ce matériau que sur demande explicite de son appelant :
Projets, chantier parallèle, garde son apparence. Aucun changement des
valeurs financières, des actions, des graphiques ou des permissions.

Vérifications : TypeScript valide ; 420 tests de l'arbre partagé et 395
tests du paquet isolé passent. Comparaison statique des 209 gestionnaires
d'événements des huit fichiers concernés : conservés. Ce n'est pas un test
réel de glisser-déposer : aucune tâche ni donnée financière n'a été modifiée
pour tester le rendu. `git diff --check` passe, compilation Tauri réussie.

Dans le navigateur : Bilan, Finances, Planificateur et Tâches inspectés,
y compris Finances et le calendrier en 390 × 760 px. Les 35 cases du mois
gardent leur hauteur de 200 px, sans débordement horizontal ; les états du
calendrier restent distincts. Le Tableau de bord de l'aperçu ne dispose pas
de données authentifiées : son rendu avec données après mise à jour n'est
pas certifié. Dans l'app Mac installée, Bilan est inspecté en Sauge puis en
Sombre : transparence, tranche et compteurs inchangés (42, 31, 27, 3, 0).
Carlito a repris la navigation pendant les contrôles : aucune nouvelle
action native après ces interruptions. Les préférences temporaires de
l'aperçu et son viewport sont rétablis, puis l'onglet de test est fermé.

Construction isolée : `/private/tmp/diapason-cadres-volume.btWGJN`, depuis
le paquet vocal précédent, sans les changements Succès parallèles. App
Mac installée avec la même signature Apple Development, vérifiée :
SHA-256 `051078d4cad03c2444243445c22b40e704d715b4484e5e72c7da20996d3af44f`.
Les assets web correspondent au même build. L'ancien bundle est dans
`/Users/carlito.e/.diapason/backups/Diapason.app.precedente`, l'ancien statique
dans `static-precedent` sous la copie isolée. Serveur PID 67047 conservé,
health `ok`. Aucun commit, push ni déploiement Windows.
