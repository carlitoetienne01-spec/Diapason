# Visuels dans les discussions

Première livraison, 23 septembre 2026 : SVG, Mermaid et graphiques Recharts
(barres, courbes, aires, secteurs). Le moteur reste local ; aucun service
externe de dessin n'est appelé. Deuxième livraison, le même jour :
Matplotlib pour les figures scientifiques vectorielles et Plotly pour
l'exploration des axes. La dernière tranche ajoute les exports PDF, les vues
3D bornées et l'ouverture d'une copie dans Inkscape s'il est installé.
Aucun code Python ou JavaScript fourni par le modèle n'est exécuté.

## Conservation et génération

Le client annonce `visuals: true` sur le flux de discussion. Le serveur
ajoute le contrat des six formats au message système, sans modifier
l'historique fourni. Une demande de dessin reste sur le modèle choisi,
comme les autres demandes de production.

Les sources sont des blocs Markdown `svg`, `mermaid`, `diapason-chart`,
`diapason-matplotlib`, `diapason-plotly` ou `diapason-plotly3d` fermés. Ils vivent dans `message.content`, donc dans la même sauvegarde et
la même synchronisation que le texte (fenêtre principale et mini-panneau).
Aucun nouvel entrepôt d'images ou champ de synchronisation n'est ajouté.
Pendant le flux, un bloc incomplet affiche une attente. Un bloc mal formé
conserve son code et affiche une erreur, jamais un faux dessin réussi.

Exemple de graphique :

```diapason-chart
{"title":"Temps par activité","type":"bar","xKey":"activite","series":[{"key":"minutes","label":"Minutes"}],"data":[{"activite":"Lecture","minutes":25},{"activite":"Exercice","minutes":40}],"sample":true,"source":"Exemple fictif"}
```

Les nombres sont ceux du JSON reçu. `sample` signale un exemple ; `source`
reste une **origine indiquée**, pas une certification de ses chiffres.
Une origine absente est signalée. Le modèle doit demander les données
manquantes plutôt que les inventer ; cette consigne ne garantit pas son
exactitude factuelle.

## Rendu et limites

- Huit visuels rendus par message ; les suivants restent du code lisible.
- SVG : 60 000 caractères, 2 500 éléments, dimensions au plus 10 000,
  rapport des côtés au plus 20. Mermaid : 12 000 caractères, 160 lignes,
  200 arêtes ; rendu nettoyé au plus 500 000 caractères.
- Graphiques : 300 catégories, huit séries, nombres finis de valeur absolue
  au plus 10¹⁵. Un secteur a une série non négative, avec un total positif.
- SVG nettoyé et affiché comme **image isolée**, jamais injecté dans le DOM
  du chat. Pas de JavaScript du modèle, HTML embarqué, image distante ou
  événement. Seuls les renvois internes de dégradés/flèches subsistent.
- Mermaid : configuration et couleurs imposées par Diapason, directives,
  HTML et liens interdits ; décorations `style`, `classDef`, `linkStyle`
  écartées sans modifier les relations du diagramme. Ses rendus sont sérialisés
  pour ne pas mélanger sa configuration globale entre deux cartes.
- Chargement différé du moteur graphique et de Mermaid. Les cartes hors
  écran attendent avant de calculer leur diagramme. Les variables animées
  du thème ne provoquent pas de nouveau rendu quand la palette est identique.

L'animation de révélation est décorative (1,1 s), sans délai ajouté au
texte ni faux pourcentage. Elle respecte la réduction des mouvements.
Un historique relu ne rejoue pas ses animations. Le menu permet de rejouer.

## Commandes

Zoom 100–400 %, déplacement du visuel agrandi, recentrage, plein écran
fermé par Échap avec retour du focus. Sous 420 px les commandes restent dans
la carte ; le menu et la liste des notes se déplient dans le flux. Aucun
panneau flottant ne doit dépasser le mini-panneau.

Export SVG, PNG ou PDF, dialogue natif dans Tauri et téléchargement navigateur.
Les exports de graphiques incluent titre, légendes et provenance. Le PNG
est limité à 2 400 pixels sur son plus grand côté. La route existante
`POST /v1/succes/photos/exporter` accepte désormais PDF, PNG et SVG validés,
toujours dans le dossier personnel, avec refus des liens symboliques.

L'ajout dans Notes propose les résumés, puis envoie uniquement le fragment
PNG en `appendContent`, avec un `opId`. Le serveur lit et ajoute dans la
même transaction `BEGIN IMMEDIATE` ; une répétition du même opId ne double
pas l'image. Le contenu fusionné respecte la limite de 1 Mo.

L'éditeur transmet `expectedContentHash` lors du remplacement du contenu.
Une autre écriture entre-temps rend HTTP 409 `note_conflict` ; le brouillon
reste ouvert, avec « Enregistrer une copie ». La copie ne remplace aucune
version. Le hash porte uniquement sur le contenu : changer une catégorie
ne crée pas un faux conflit. Les anciens clients omettant ce champ restent
compatibles, mais leurs remplacements ne bénéficient pas de cette protection.

## Vérification

Tests purs Vitest : clôture des blocs, limites, conservation des données,
SVG actif/externe, palette, couleurs Mermaid et directives refusées.
Tests Python : consigne jusqu'au moteur, compatibilité client texte,
routage du dessin, exports et refus d'un lien symbolique.

Banc navigateur avec le vrai `MessageBubble` : SVG, Mermaid, graphique,
changement de thème, petit format 340 px, zoom conservé pendant la suite du
message, Échap/focus, erreur de syntaxe, export SVG/PNG et ajout dans une
note de contrôle sans écraser son texte. Le banc temporaire ne fait pas
partie du produit. Ces contrôles ne constituent pas un essai sur Windows.

Essai réel : Qwen 3.5 9b déjà chargé a produit un bloc Mermaid complet en
8,2 s. Ses instructions de couleur inattendues ont révélé le besoin de
normaliser la décoration avant validation, couvert par un test de régression.

## Figures scientifiques et exploration

Les deux nouveaux formats prennent du JSON strict, jamais un script :

```diapason-plotly
{"title":"Distance mesurée","type":"scatter","xLabel":"Temps (s)","yLabel":"Distance (m)","series":[{"name":"Essai","x":[1,2,3],"y":[2,4,5],"errorY":[0.1,0.2,0.1]}],"sample":true,"source":"Données fictives"}
```

Types communs : `line`, `scatter`, `histogram`. Pour l'histogramme,
`series[].x` contient les observations, sans `y` ni `errorY` ; `bins`
choisit 2 à 60 intervalles (12 par défaut), communs à toutes les séries.
Matplotlib ajoute `heatmap` : `matrix` rectangulaire, `xLabels` et
`yLabels` facultatifs, sans séries. Plotly ne reçoit pas de matrice dans
cette version : ses cartes de chaleur raster ne respecteraient pas la
promesse d'export vectoriel de ce cadre.

Limites : 6 séries, 300 observations au total, matrices de 20×20,
nombres finis entre −10¹² et 10¹². Les coordonnées et incertitudes ont
les mêmes longueurs ; les incertitudes sont non négatives. Aucun
paramètre de bibliothèque arbitraire (fonction, URL, image, HTML) n'est
transmis. Les données restent consultables sous « Voir les données ».

Matplotlib est une dépendance des installations `server` et `desktop`.
`POST /v1/visuals/matplotlib` est protégé par l'authentification générale
et valide de nouveau les données côté Python. La route synchrone travaille
hors de la boucle du chat, avec un verrou autour de Matplotlib et un cache
LRU de 16 figures (8 Mo de SVG maximum). FigureCanvasSVG n'ouvre aucune
fenêtre native ; le rendu désactive TeX et les expressions mathématiques.
La couleur vient de la palette du client, contrôlée comme hexadécimal.

Plotly utilise le bundle cartésien chargé uniquement lorsqu'un visuel
Plotly devient visible. Survol des valeurs, zoom par sélection de zone,
boutons de zoom accessibles et recentrage ; la molette reste réservée au
défilement de la discussion. Une observation du conteneur redimensionne
les axes, y compris en plein écran et dans le mini-panneau. L'export
reprend la plage de données visible et ajoute titre et provenance.

Références des choix d'intégration : [Matplotlib et les fils d'exécution](https://matplotlib.org/stable/users/faq.html#work-with-threads),
[API JavaScript Plotly](https://plotly.com/javascript/plotlyjs-function-reference/).

Vérifications de cette tranche : figures réelles dans les tests Python
(dont 300 incertitudes et rendus concurrents), blocage des formes invalides,
conservation des valeurs et cache. Navigateur avec le vrai MessageBubble :
nuage de points, carte de chaleur, histogramme, thèmes, largeur de 340 px,
plein écran et exports SVG/PNG. Une requête directe à Qwen 3.5 9b a produit
le format Plotly en 4,4 s avec les coordonnées fournies intactes et
sample=false. Son premier essai employait un bloc json générique : un
exemple complet de la clôture attendue a été ajouté à la consigne. Cela
ne garantit pas que chaque modèle suivra toujours le format.

## Fiabilité, PDF, 3D et édition externe

La normalisation reconnaît les alias de clôture et un bloc `json` qui
respecte exactement un schéma visuel. Elle retire un BOM et les virgules
finales hors chaînes seulement si le résultat se parse. Elle ne complète
jamais une donnée manquante ou un bloc tronqué. Le texte original reste
conservé dans la conversation. « Réessayer le rendu » relance le moteur,
sans modifier les valeurs et sans nouvel appel au modèle.

Le PDF 2D est vectoriel via svg2pdf.js/jsPDF, avec polices DejaVu embarquées
(licence dans `frontend/public/fonts/visuels`). Les accents, légendes et
origines suivent le dessin. Ces polices sont aussi mises en cache par la
PWA. Les dépendances PDF ne sont chargées qu'au clic sur l'export.

`diapason-plotly3d` accepte `scatter3d` avec 6 séries et 300 points maximum
(x/y/z de même longueur) ou `surface` avec une matrice de hauteurs 2×2 à
20×20. Les coordonnées horizontales d'une surface sont les indices de sa
grille ; aucune formule n'est évaluée. Le bundle WebGL séparé se charge
uniquement pour la 3D. Rotation au glisser, zoom/recentrage aux boutons,
plein écran, adaptation du conteneur et du thème. L'absence de WebGL rend
une erreur explicite. **La 3D s'exporte en image PNG/PDF**, selon l'angle
visible, avec titre et origine ; aucun faux export vectoriel n'est proposé.
La liste blanche SVG continue d'interdire les images embarquées.

« Modifier dans Inkscape » interroge sa présence puis, au clic seulement,
valide le SVG et crée une copie indépendante dans `~/.diapason/visuals`.
L'éditeur reçoit ce seul chemin, sans shell ni argument fourni par le
modèle. Le succès dit « Ouverture demandée », pas « fichier modifié ».
L'original du chat reste intact. Si Inkscape manque, rien n'est installé ni
lancé et l'interface le signale. Routes authentifiées :
`GET/POST /v1/visuals/inkscape`.

Contrôles du 23 septembre : 10 766 tests Python réussis, 1 110 tests Vitest,
TypeScript, build/PWA, lint/format, audit Python, Rust workspace et Tauri.
Banc navigateur : vrai MessageBubble, surface et nuage 3D, rotation/zoom,
thème phosphore, format 340×620, plein écran/Échap, export PDF 3D et PDF
vectoriel 2D relus après rasterisation (accents, axes, valeurs, provenance).
Le PC Windows était hors ligne : ces preuves ne valident pas son WebView.

Installation locale : app Mac 1.0.5 reconstruite, signée et relancée ;
serveur rechargé, santé HTTP 200 et détection Inkscape « absent » vérifiées.
L'automatisation de la fenêtre native s'est bloquée avant le contrôle
complet principal/mini-panneau ; ce contrôle ne peut donc pas être annoncé
comme réussi. La discussion temporaire de test a été retirée. Le test HTTP
supplémentaire confirme 409 sur conflit et un ajout unique après rejeu.
