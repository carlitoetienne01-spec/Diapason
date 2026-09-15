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
   actions révélées au survol doivent être `max-sm:opacity-100` : un NSPanel
   non activant **ne livre pas le survol** hors focus (les clics, oui) —
   §82, rien ne devient inatteignable.

## Ce qui reste à passer au crible

Notes, Projets, la palette ⌘K et l'EmojiPicker sont traités. Tâches,
Planificateur, Finances, Tableau de bord, Habitudes, Bilan et le chat portent
un plan précis issu de l'audit (voir les rapports de la session du
15 septembre) mais leurs fichiers étaient dans le chantier « verre satiné »
non commité d'une autre session — à appliquer une fois ce chantier livré.
