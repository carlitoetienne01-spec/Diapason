import { lazy, useState, type ComponentType } from 'react';

import { memoiserChargeur, type ChargeurMemoise } from './prechargerPages';

/**
 * Ce que la page rend à son montage : le module s'il est déjà arrivé, sinon
 * la version paresseuse. 26/09/2026, contre-épreuve : le mutant qui ignorait
 * le module arrivé (la page suspendait toujours, « Chargement… » une image
 * de trop après chaque préchargement) laissait les 1 580 tests verts.
 */
export function composantInitial<C>(memo: ChargeurMemoise<C>, paresseux: C): C {
  return memo.module() ?? paresseux;
}

/**
 * Une page chargée à la demande qui sait aussi se PRÉcharger.
 *
 * 26/09/2026, chantier de la fluidité (lot 2) : `React.lazy` seul suspend
 * au premier rendu même quand le morceau est déjà arrivé — son `import()`
 * rend un `Promise` que React ne sait pas déjà résolu, et la page affichait
 * « Chargement… » une image de trop. Une fois le module là (préchargé
 * pendant un creux, ou visité), la page le rend directement.
 *
 * Le choix est figé au MONTAGE (`useState`) : passer de la version
 * paresseuse à la directe pendant que la page vit la remonterait, et
 * emporterait son état (un brouillon, un carnet ouvert).
 */
export function pageParesseuse<P extends object>(charger: () => Promise<ComponentType<P>>) {
  const memo = memoiserChargeur(charger);
  const Paresseuse = lazy(() => memo.charger().then((Composant) => ({ default: Composant })));
  function Page(props: P) {
    const [Composant] = useState(() => composantInitial<ComponentType<P>>(memo, Paresseuse));
    return <Composant {...props} />;
  }
  return Object.assign(Page, { precharger: memo.charger });
}
