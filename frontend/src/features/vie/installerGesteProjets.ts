import { installerGesteCartables, type OptionsGesteCartables } from './installerGesteCartables';
export type { FantomeCartable as FantomeProjet } from './installerGesteCartables';

export function installerGesteProjets(grille: HTMLElement, o: Omit<OptionsGesteCartables, 'attributCarte' | 'attributActions' | 'attributZone' | 'classer' | 'ranger'> & { ranger: (ids: string[]) => void }) {
  return installerGesteCartables(grille, {
    ...o, attributCarte: 'data-projet-mobile', attributActions: 'data-actions-projet',
    poserOrdre: ids => o.poserOrdre(ids),
    ranger: ids => o.ranger(ids),
  });
}
