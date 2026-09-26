import { describe, expect, it, vi } from 'vitest';

import { PagesAffichees } from './pagesAffichees';

/**
 * 26/09/2026, phase 3 étape 9 : une navigation demandée par la coquille du
 * téléphone n'est acquittée qu'une fois la page MONTÉE. Répondre dès
 * `navigate()` faisait lire « L'écran est ouvert » à l'appareil qui avait
 * demandé, devant un « Chargement… » qui pouvait ne jamais finir.
 */
describe('Une page n’est « affichée » qu’une fois montée', () => {
  it('attend la montée du bon chemin, pas d’un autre', async () => {
    const pages = new PagesAffichees();
    let fini: boolean | null = null;
    void pages.attendre('/vie/notes', 8000).then((v) => (fini = v));
    pages.signalerMontee('/vie/tasks');
    await Promise.resolve();
    expect(fini, 'une autre page ne compte pas').toBeNull();
    pages.signalerMontee('/vie/notes');
    await Promise.resolve();
    expect(fini).toBe(true);
  });

  it('répond tout de suite si la page est déjà là', async () => {
    const pages = new PagesAffichees();
    pages.signalerMontee('/vie/notes');
    await expect(pages.attendre('/vie/notes', 8000)).resolves.toBe(true);
  });

  it('un démontage efface la page affichée', async () => {
    const pages = new PagesAffichees();
    const demonter = pages.signalerMontee('/vie/notes');
    demonter();
    expect(pages.affichee).toBeNull();
    vi.useFakeTimers();
    const attente = pages.attendre('/vie/notes', 8000);
    vi.advanceTimersByTime(8000);
    await expect(attente, 'démontée, elle n’est plus affichée').resolves.toBe(false);
    vi.useRealTimers();
  });

  it('un démontage tardif n’efface pas la page montée depuis', () => {
    const pages = new PagesAffichees();
    const demonterA = pages.signalerMontee('/vie/tasks');
    pages.signalerMontee('/vie/notes');
    demonterA();
    expect(pages.affichee).toBe('/vie/notes');
  });

  it('dit « pas affichée » au délai', async () => {
    vi.useFakeTimers();
    const pages = new PagesAffichees();
    const attente = pages.attendre('/vie/projects', 8000);
    vi.advanceTimersByTime(7999);
    pages.signalerMontee('/vie/tasks');
    vi.advanceTimersByTime(1);
    await expect(attente).resolves.toBe(false);
    // Une montée après le délai ne résout plus rien.
    pages.signalerMontee('/vie/projects');
    vi.useRealTimers();
  });
});
