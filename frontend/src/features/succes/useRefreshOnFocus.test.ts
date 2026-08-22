import { describe, expect, it, vi } from 'vitest';

import { brancherRafraichissement } from './useRefreshOnFocus';

/**
 * Constaté le 22 août 2026 dans l'application de bureau : une page ouverte
 * gardait son état indéfiniment. Des tâches créées ailleurs n'apparaissaient
 * pas, et un projet supprimé restait affiché — l'écran vieillissait sans rien
 * dire, ce qui se lit comme un bogue.
 *
 * Doublures maison plutôt que jsdom : c'est la convention de ce dépôt, les
 * tests tournent sous node.
 */
class CibleFactice {
  private handlers = new Map<string, Set<() => void>>();

  addEventListener(type: string, handler: () => void): void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type)?.add(handler);
  }

  removeEventListener(type: string, handler: () => void): void {
    this.handlers.get(type)?.delete(handler);
  }

  emettre(type: string): void {
    for (const h of [...(this.handlers.get(type) ?? [])]) h();
  }

  /** Combien d'écouteurs restent — pour prouver le nettoyage. */
  get total(): number {
    let n = 0;
    for (const set of this.handlers.values()) n += set.size;
    return n;
  }
}

function monter(
  refresh: () => void,
  { minIntervalMs = 2000, visible = true }: { minIntervalMs?: number; visible?: boolean } = {},
) {
  const fenetre = new CibleFactice();
  const document = new CibleFactice();
  let horloge = 1_000_000;
  let estVisible = visible;
  let courante = refresh;
  const detacher = brancherRafraichissement({
    getRefresh: () => courante,
    minIntervalMs,
    estVisible: () => estVisible,
    maintenant: () => horloge,
    fenetre,
    document,
  });
  return {
    fenetre,
    document,
    detacher,
    avancer: (ms: number) => {
      horloge += ms;
    },
    cacher: () => {
      estVisible = false;
    },
    remplacer: (fn: () => void) => {
      courante = fn;
    },
  };
}

describe('brancherRafraichissement', () => {
  it('relit quand la fenêtre reprend le focus', () => {
    const relire = vi.fn();
    const h = monter(relire);
    h.fenetre.emettre('focus');
    expect(relire).toHaveBeenCalledTimes(1);
  });

  it('relit quand la page redevient visible', () => {
    const relire = vi.fn();
    const h = monter(relire);
    h.document.emettre('visibilitychange');
    expect(relire).toHaveBeenCalledTimes(1);
  });

  it('ne relit pas quand la page PASSE en arrière-plan', () => {
    const relire = vi.fn();
    const h = monter(relire, { visible: false });
    h.document.emettre('visibilitychange');
    expect(relire).not.toHaveBeenCalled();
  });

  it('étouffe la rafale de focus de macOS', () => {
    const relire = vi.fn();
    const h = monter(relire);
    h.fenetre.emettre('focus');
    h.fenetre.emettre('focus');
    h.fenetre.emettre('focus');
    expect(relire).toHaveBeenCalledTimes(1);
  });

  it('relit de nouveau une fois le délai écoulé', () => {
    const relire = vi.fn();
    const h = monter(relire, { minIntervalMs: 2000 });
    h.fenetre.emettre('focus');
    h.avancer(2500);
    h.fenetre.emettre('focus');
    expect(relire).toHaveBeenCalledTimes(2);
  });

  it('appelle la DERNIÈRE fonction, pas une fermeture périmée', () => {
    const premiere = vi.fn();
    const seconde = vi.fn();
    const h = monter(premiere);
    h.remplacer(seconde);
    h.fenetre.emettre('focus');
    expect(premiere).not.toHaveBeenCalled();
    expect(seconde).toHaveBeenCalledTimes(1);
  });

  it('retire ses deux écouteurs au démontage', () => {
    const relire = vi.fn();
    const h = monter(relire);
    expect(h.fenetre.total + h.document.total).toBe(2);
    h.detacher();
    expect(h.fenetre.total + h.document.total).toBe(0);
    h.fenetre.emettre('focus');
    expect(relire).not.toHaveBeenCalled();
  });
});
