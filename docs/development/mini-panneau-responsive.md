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

## État

Notes, Projets, la palette ⌘K et l'EmojiPicker ont été traités ET vérifiés
dans le vrai mini-panneau le 15 septembre 2026. Tâches, Planificateur,
Finances, Tableau de bord, Habitudes, Bilan, la Discussion, la cloche
d'approbation et les toasts ont reçu leur plan le 16 : vérifiés en
compilation, en tests et par une revue de code adversaire (20 défauts
attrapés et corrigés, dont un menu « ⋯ » peint sous la carte suivante), mais
**pas encore regardés à l'écran** — l'écran était verrouillé. Le contrôle
visuel de ces neuf morceaux reste dû ; ne lis pas « traité » comme « vu ».
Un module nouveau se conforme aux cinq règles dès sa naissance.
