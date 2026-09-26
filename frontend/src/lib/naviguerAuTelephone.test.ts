import { afterEach, describe, expect, it, vi } from 'vitest';

import { traduire } from '../i18n/translate';
import { naviguerAuTelephone } from './naviguerAuTelephone';
import { PagesAffichees } from './pagesAffichees';

/**
 * 26/09/2026, contre-épreuve de la phase 3 étape 9 : la coquille acquitte
 * SUCCESS à l'appareil qui a demandé l'écran sur la seule réponse du
 * bundle. Trois mutants survivaient dans `NavigationDuTelephone` : l'attente
 * retirée (NDT1), l'attente posée après `navigate()` (NDT2), et
 * `attendre` qui répondait pour n'importe quelle page montée (PA3).
 */
describe('Le bundle ne rend le chemin qu’une fois la page montée', () => {
  afterEach(() => vi.useRealTimers());

  it('une page jamais montée rend « pas affichée », jamais le chemin', async () => {
    vi.useFakeTimers();
    const pages = new PagesAffichees();
    const reponse = naviguerAuTelephone(
      { path: '/vie/notes' },
      { naviguer: () => {}, poserSelection: () => {}, pages, delaiMs: 8000 },
    );
    const verdict = expect(reponse).rejects.toThrow(traduire('natif.naviguer.pasAffichee'));
    await vi.advanceTimersByTimeAsync(8000);
    await verdict;
  });

  it('une montée faite PENDANT navigate() est vue', async () => {
    const pages = new PagesAffichees();
    const reponse = await naviguerAuTelephone(
      { path: '/vie/notes' },
      {
        // Une page déjà chargée monte dans l'appel même.
        naviguer: (chemin) => {
          pages.signalerMontee(chemin);
        },
        poserSelection: () => {},
        pages,
        delaiMs: 8000,
      },
    );
    expect(reponse).toEqual({ path: '/vie/notes', selection: null });
  });

  it('le chemin n’est rendu qu’après la montée', async () => {
    const pages = new PagesAffichees();
    let rendu: unknown = null;
    void naviguerAuTelephone(
      { path: '/vie/tasks' },
      { naviguer: () => {}, poserSelection: () => {}, pages, delaiMs: 8000 },
    ).then((r) => (rendu = r));
    await Promise.resolve();
    await Promise.resolve();
    expect(rendu, 'rien avant la montée : « Chargement… » n’est pas ouvert').toBeNull();
    pages.signalerMontee('/vie/tasks');
    await vi.waitFor(() => expect(rendu).toEqual({ path: '/vie/tasks', selection: null }));
  });

  it('une AUTRE page déjà affichée ne compte pas', async () => {
    vi.useFakeTimers();
    const pages = new PagesAffichees();
    pages.signalerMontee('/chat');
    const reponse = naviguerAuTelephone(
      { path: '/vie/notes' },
      { naviguer: () => {}, poserSelection: () => {}, pages, delaiMs: 8000 },
    );
    const verdict = expect(reponse).rejects.toThrow(traduire('natif.naviguer.pasAffichee'));
    await vi.advanceTimersByTimeAsync(8000);
    await verdict;
  });

  it('la sélection est posée AVANT de naviguer, et un chemin inconnu ne navigue pas', async () => {
    const pages = new PagesAffichees();
    const ordre: string[] = [];
    await naviguerAuTelephone(
      { path: '/vie/notes', selection: { kind: 'note', id: 'n-1' } },
      {
        naviguer: (chemin) => {
          ordre.push(`naviguer ${chemin}`);
          pages.signalerMontee(chemin);
        },
        poserSelection: (s) => ordre.push(`selection ${s.id}`),
        pages,
        delaiMs: 8000,
      },
    );
    expect(ordre).toEqual(['selection n-1', 'naviguer /vie/notes']);

    // L'attente aussi, avant navigate() : c'est le contrat écrit de
    // `attendre`. Avec les `PagesAffichees` d'aujourd'hui, une attente
    // posée après une montée synchrone la voit encore (la page courante est
    // retenue) ; l'ordre tient pour un registre qui ne la retiendrait pas.
    const appels: string[] = [];
    await naviguerAuTelephone(
      { path: '/vie/tasks' },
      {
        naviguer: () => appels.push('naviguer'),
        poserSelection: () => {},
        pages: {
          attendre: () => {
            appels.push('attendre');
            return Promise.resolve(true);
          },
        },
        delaiMs: 8000,
      },
    );
    expect(appels).toEqual(['attendre', 'naviguer']);

    const naviguer = vi.fn();
    await expect(
      naviguerAuTelephone(
        { path: '/settings' },
        { naviguer, poserSelection: () => {}, pages, delaiMs: 8000 },
      ),
    ).rejects.toThrow(traduire('natif.naviguer.inconnu'));
    expect(naviguer).not.toHaveBeenCalled();
  });
});
