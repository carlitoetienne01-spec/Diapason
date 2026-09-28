# Navigation du bureau — rail et panneau

Intégration du prototype approuvé le 28 septembre 2026.

- Un rail permanent de 60 px garde Discussion, Projets, Notes,
  Tâches, Planificateur, Tableau de bord, Finances, Habitudes et Bilan.
  Réglages et le changement de thème restent au pied. Démarrer, Sources de
  données, Agents, Synchronisation, Appareils, Vue d'ensemble du système et
  Journaux restent uniquement dans le panneau des Réglages.
  Le bouton « Plus » a été retiré à la demande de Carlito : le rail défile
  verticalement lorsque les icônes ne tiennent plus dans la hauteur.
- Le panneau repliable ajoute 260 px sur le bureau. Le choix ouvert/replié
  est conservé lors d'un changement de rubrique, y compris vers Réglages.
  À la demande de Carlito (28/09/2026), il n'est proposé que dans Discussion
  et Réglages. Projets, Notes, Tâches, Planificateur et Finances s'ouvrent
  directement à côté du rail, comme Tableau de bord, Habitudes et Bilan,
  sans effacer ce choix. Sous 768 px, il se superpose
  et se borne à la fenêtre ; choisir un élément dans la même rubrique le
  retire pour montrer la page. Le mini-panneau et la roue du téléphone gardent
  leurs présentations propres.
- Les discussions gardent les épingles, la recherche dans les messages,
  les menus renommer/dupliquer/supprimer et leur synchronisation existante.
  Les flèches reviennent aux pages et aux discussions visitées durant la
  session, en restaurant l'ID du fil quand plusieurs partagent la route `/`.
- « Discussions récentes » est supprimé ; les conversations restent dans
  Discussion, sans les projets. Les contrôles métier (listes, catégories,
  filtres, dates et périodes) restent accessibles dans leurs pages.
- Le décor utilise les variables du thème courant. Les flèches, le repli,
  la recherche et les rubriques restent utilisables au clavier.

Fichiers : `components/Sidebar/Sidebar.tsx`, `Navigation.css`,
`PanneauEspaces.tsx`, `navigation.ts`, `useHistoriqueNavigation.ts`.
Les décisions d'historique et de recherche sont vérifiées par
`navigation.test.ts` ; les contrôles de navigation étroite existants restent
ceux de `lib/barre.test.ts`.

Contrôle visuel du 28 septembre 2026 : le confinement de largeur CSS du
compositeur est limité à `.composer-saisie` et nommé `compositeur`. Posé sur
la classe vitrée commune, il supprimait la largeur intrinsèque du sélecteur
des Tâches et superposait ses libellés aux boutons voisins. Les actions des
Tâches se replient désormais sans comprimer les boutons ; la date du Tableau
de bord passe sous le titre lorsque la largeur manque.

Le banc navigateur, avec les vrais composants et les polices Phosphore,
a contrôlé huit rubriques à 1280 et 820 px (panneau ouvert lorsqu'utile),
puis à 340 px (panneau replié) : aucun chevauchement des contrôles d'en-tête
ni débordement horizontal des pages observé. Le compositeur a également été
contrôlé à 340 px, avec le passage du bouton vocal au bouton d'envoi.
Ces contrôles utilisent des données de démonstration et ne constituent pas
une garantie sur tous les contenus et tous les thèmes.
