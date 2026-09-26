import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * L'état du store au lancement, sur un écran de téléphone.
 *
 * Échecs évités (26/09/2026) :
 * - la barre latérale et le panneau Système démarraient ouverts partout ;
 *   remplacer les requêtes média de store.ts par `true` laissait la suite
 *   verte, alors que les deux couvrent la Discussion à 375 px ;
 * - sans réglages enregistrés, la clé de session était ignorée, et le
 *   premier changement de thème l'effaçait : tout répondait 401 ensuite.
 */

class Stockage {
  valeurs = new Map<string, string>();
  getItem(k: string) {
    return this.valeurs.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.valeurs.set(k, v);
  }
  removeItem(k: string) {
    this.valeurs.delete(k);
  }
}

let session: Stockage;

beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal('localStorage', new Stockage());
  session = new Stockage();
  session.setItem('diapason-api-key', 'cle-de-test');
  vi.stubGlobal('sessionStorage', session);
  // Un écran de 375 px : aucune requête `min-width` ne répond.
  vi.stubGlobal('matchMedia', (requete: string) => ({ matches: false, media: requete }));
  window.matchMedia = ((requete: string) => ({ matches: false, media: requete })) as never;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Le store au lancement, sur un téléphone de 375 px', () => {
  it('la barre et le panneau Système démarrent fermés', async () => {
    const { useAppStore } = await import('./store');
    const etat = useAppStore.getState();
    expect(etat.sidebarOpen, 'la barre couvrirait deux tiers de la page').toBe(false);
    expect(etat.systemPanelOpen, 'le panneau couvrirait la Discussion').toBe(false);
  });

  it('la clé de session survit au premier changement de thème', async () => {
    const { useAppStore } = await import('./store');
    expect(useAppStore.getState().settings.apiKey).toBe('cle-de-test');
    useAppStore.getState().updateSettings({ theme: 'dark' });
    expect(session.getItem('diapason-api-key')).toBe('cle-de-test');
  });
});
