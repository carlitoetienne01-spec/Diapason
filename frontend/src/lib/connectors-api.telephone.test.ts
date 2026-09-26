import { describe, expect, it, vi } from 'vitest';

/**
 * Dans le téléphone, une connexion OAuth se dit « depuis le Mac » au lieu
 * d'ouvrir une attente sans issue.
 *
 * Échec évité (26/09/2026) : `window.open` est muet dans la WebView
 * d'Android, et le rappel OAuth vise 127.0.0.1:8789 sur le Mac ; la roue
 * « en attente » tournait trois minutes puis s'éteignait sans un mot.
 */

vi.mock('./natif', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./natif')>()),
  estMobile: true,
}));

import { startServerOAuth } from './connectors-api';

describe('OAuth dans le téléphone', () => {
  it('refuse tout de suite, lisiblement, sans ouvrir de fenêtre', async () => {
    const ouvrir = vi.spyOn(window, 'open').mockImplementation(() => null);
    document.documentElement.setAttribute('lang', 'fr');
    try {
      await expect(startServerOAuth('google')).rejects.toThrow(/depuis l’app Diapason du Mac/);
      expect(ouvrir).not.toHaveBeenCalled();
    } finally {
      document.documentElement.removeAttribute('lang');
      ouvrir.mockRestore();
    }
  });
});
