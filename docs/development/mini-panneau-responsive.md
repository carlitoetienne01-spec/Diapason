# Le mini-panneau et le responsive — la convention

Le mini-panneau de la réglette (l'onglet de bord d'écran) charge le vrai
bundle React dans une WKWebView de ~460×620, redimensionnable en continu
(minimum 340×380). **Le viewport EST le panneau** : les breakpoints Tailwind
(sm 640, md 768…) et les container queries y réagissent déjà, sans JS.

Audit complet du 15 septembre 2026 ; le mécanisme tient en trois morceaux,
tous en place :

- `frontend/src/lib/compact.ts` — lit le drapeau une fois (WKUserScript natif,
  globale, `?compact` en navigateur) et le **normalise sur `<html>`**
  (`data-diapason-compact="1"`), LE sélecteur CSS unique.
- `frontend/src/index.css` — le variant `@custom-variant compact` (à côté de
  `dark`) et la réserve `--surplomb-panneau` (la barre de glissement injectée
  par le panneau natif recouvre ~24 px en haut ; `Layout.tsx` les réserve).
- Les pages n'importent **jamais** `estCompact` : seule `Layout.tsx` le lit.

## Les cinq règles

1. **Le style de base est celui du panneau minimal (340 px).** Un préfixe
   (`sm:`, `md:`, `@sm:`) ne fait qu'AJOUTER — colonnes, étiquettes, chrome.
   Jamais de layout de base qui exige plus de 340 px.
2. **La largeur se lit en CSS, jamais en JS.** Largeur du panneau →
   `sm:`/`md:`. Largeur propre d'un composant réutilisé → `@container` +
   `@sm:`… (avec `min-w-0` sur l'enfant flex). Jamais `window.innerWidth`,
   jamais de `useMediaQuery` — le CSS fait ce travail gratuitement, sans
   re-render.
3. **`compact` = mode, pas largeur.** `estCompact` (TS) et `compact:` (CSS) ne
   gouvernent que le chrome, les sondes et la réserve du haut. Un panneau
   étiré à 900 px reste compact ; une fenêtre navigateur de 500 px ne l'est
   pas.
4. **Jamais de largeur fixe posée au-delà de 320 px.** Toujours un plafond qui
   cède : `w-full max-w-*` (+ `min-w-0` chez les enfants flex). Un pop-up
   ancré doit **retourner et se borner** : flip haut/bas mesuré à l'ouverture,
   ancre `right-0` en fin de barre, `max-height` avec défilement, et
   fermeture sur `resize` (le panneau se redimensionne en continu — une ancre
   figée devient fausse). Modèles : `EmojiPicker.tsx`, `MenuBarre`
   (RichNoteEditor), `ChipMenu` (ComposerBar).
5. **Sous `sm` : cacher le secondaire, condenser le reste.** Descriptifs
   `hidden sm:block`, libellés de boutons `hidden sm:inline` (avec
   `aria-label`), outils secondaires derrière un « ⋯ » ancré à droite. Les
   actions révélées au survol portent `compact:opacity-100` (et
   `max-sm:opacity-100` pour le tactile et les fenêtres étroites) : un
   NSPanel non activant **ne livre plus le survol** dès qu'une autre app est
   devant (les clics, oui), et c'est un MODE, pas une largeur — le
   préréglage L du panneau fait exactement 640 px, où `max-sm:` s'éteint
   (revue du 16 sept. 2026). §82, rien ne devient inatteignable. Un menu
   ouvert DANS une carte vitrée (`backdrop-filter` = contexte
   d'empilement) est peint sous la carte suivante : un menu est un portail
   `fixed` sur `body` (modèles : `ChipMenu`, `MenuActions` de TaskCard).

## Le cas téléphone (26 septembre 2026)

Le même bundle tourne aussi dans la WebView de la coquille Flutter du
téléphone (`docs/development/diapason-mobile.md`, phase 3). Le téléphone
n'est pas une largeur : c'est un **mode**, comme `compact`, reconnu au pont
natif et à lui seul (`lib/natif.ts` : le canal `DiapasonNatif`, normalisé en
`data-diapason-mobile="1"` sur `<html>`). Un navigateur de 375 px n'est pas
un téléphone ; un téléphone tenu à l'horizontale (740 à 915 px) en reste un.
Les cinq règles valent telles quelles ; le téléphone en ajoute quatre.

6. **Le doigt : 40 px de côté au moins.** Posé une fois, hors des couches,
   dans `index.css` (`html[data-diapason-mobile='1'] :is(button, a[href],
   select, [role=…], label:has(case)…)`) — une règle par composant en
   oublierait. Le bureau et le mini-panneau, à la souris, n'en voient rien.
   Un contrôle **dessiné** (interrupteur, case, pastille) ne peut pas
   grandir sans se déformer : il porte `data-cible-libre` et
   `cible-etendue` (plus `relative` s'il n'est pas positionné), et sa
   surface de toucher déborde par un pseudo-élément réglé par
   `--cible-marge` (8 px par défaut). Modèles : les interrupteurs des
   Réglages, les cases de `TaskCard`. Un point qu'on tire (la poignée de
   lien du réseau) garde sa taille si un autre chemin fait la même chose au
   doigt (§82).
7. **Rien n'existe qu'au survol — `mobile:` avec `max-sm:` et `compact:`.**
   Le variant `mobile:` (index.css) s'ajoute aux deux autres sur toute
   action révélée au survol : `max-sm:` s'éteint à 640 px, et un doigt ne
   survole rien, même à 900 px.
8. **La barre latérale est un tiroir sous `md`.** Elle démarre fermée là
   où elle couvrirait la page, se retire après une navigation choisie dans
   le tiroir, et le bouton retour d'Android la ferme d'abord
   (`lib/barre.ts`, fonctions pures testées ; la requête média est lue à
   l'amorçage et au moment de naviguer, jamais `innerWidth`). Ce qui flotte
   au-dessus des pages — le bouton qui rouvre la barre, la cloche — a sa
   réserve : `--bande-barre-fermee` au-dessus des pages et de
   `.voile-modal`, `--degagement-barre-fermee` à gauche de l'en-tête de la
   Discussion. Toute nouvelle page reçoit la bande par `Layout.tsx` ; toute
   nouvelle surface plein écran la respecte.
9. **Ce qui se superpose sous `sm` ne s'ouvre pas tout seul.** Le panneau
   Système de la Discussion ne s'ouvre au premier lancement que là où il
   est une colonne (`lib/panneauSysteme.ts`). Un choix mémorisé reste un
   choix.

Pour vérifier une page au téléphone sans téléphone, le banc injecte un faux
canal `DiapasonNatif` avant le bundle (une page de la même origine qui
réécrit le document) ; ce qu'il ne dit pas, et que seule la vraie WebView
d'Android dira (étape 7) : le survol réel, le clavier virtuel, la barre
d'état.

## État

Notes, Projets, la palette ⌘K et l'EmojiPicker ont été traités ET vérifiés
dans le vrai mini-panneau le 15 septembre 2026. Tâches, Planificateur,
Finances, Tableau de bord, Habitudes, Bilan, la Discussion, la cloche
d'approbation et les toasts ont reçu leur plan le 16 : vérifiés en
compilation, en tests et par une revue de code adversaire (20 défauts
attrapés et corrigés, dont un menu « ⋯ » peint sous la carte suivante), mais
**pas encore regardés à l'écran** — l'écran était verrouillé. Le contrôle
visuel de ces neuf morceaux reste dû ; ne lis pas « traité » comme « vu ».
Le 26 septembre 2026, toutes les pages ont été mesurées et regardées à
340 px en `?compact` dans un navigateur Chromium (aucun débordement
horizontal, 17 pages sur 17) : c'est le rendu du bundle, pas encore la
vraie WKWebView non activante du mini-panneau, qui reste due pour les neuf.
Le même jour, les mêmes pages ont été vues à 375 px avec le pont simulé
(`diapason-mobile.md`, étape 5).
Un module nouveau se conforme aux neuf règles dès sa naissance.
