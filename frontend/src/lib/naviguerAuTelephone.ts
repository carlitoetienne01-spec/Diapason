// Le verbe `naviguer` du côté du bundle : lire la cible, poser la
// sélection, attendre la montée de la page, naviguer, et ne rendre le
// chemin qu'une fois la page MONTÉE.
//
// 26/09/2026, contre-épreuve de la phase 3 étape 9
// (docs/development/diapason-mobile.md). Le gestionnaire vivait dans
// l'effet de `NavigationDuTelephone`, qu'aucun test ne peut monter (aucun
// test de composant dans ce dépôt) : retirer l'attente, ou la poser APRÈS
// `navigate()` — qui manque une montée synchrone —, laissait les 1 341
// vitest verts, et la coquille acquittait SUCCESS à l'appareil émetteur
// devant un « Chargement… ».

import { readShellNavigation, type MeshNavTarget } from '../features/mesh/routes';
import { traduire } from '../i18n/translate';
import type { PagesAffichees } from './pagesAffichees';

export interface DependancesDeNavigation {
  /** `navigate()` du routeur ; la page peut monter PENDANT l'appel. */
  naviguer: (chemin: string) => void;
  /** La sélection que la page lit à sa montée (`setPendingMeshSelection`). */
  poserSelection: (selection: NonNullable<MeshNavTarget['selection']>) => void;
  pages: Pick<PagesAffichees, 'attendre'>;
  delaiMs: number;
}

/**
 * Rend `{path, selection}` une fois la page montée ; lève avec la phrase
 * à rendre à la coquille sinon.
 */
export async function naviguerAuTelephone(
  donnees: unknown,
  d: DependancesDeNavigation,
): Promise<{ path: string; selection: MeshNavTarget['selection'] | null }> {
  const cible = readShellNavigation(donnees);
  if (!cible) throw new Error(traduire('natif.naviguer.inconnu'));
  // Posée avant de naviguer : la page lit la sélection à sa montée, et la
  // montée a lieu pendant navigate() (même règle que MeshHost).
  if (cible.selection) d.poserSelection(cible.selection);
  // L'attente AVANT navigate(), pour la même raison.
  const affichee = d.pages.attendre(cible.path, d.delaiMs);
  d.naviguer(cible.path);
  if (!(await affichee)) throw new Error(traduire('natif.naviguer.pasAffichee'));
  return { path: cible.path, selection: cible.selection ?? null };
}
