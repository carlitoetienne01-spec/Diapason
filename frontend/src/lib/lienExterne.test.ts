import { describe, expect, it } from 'vitest';

import { estLienOuvrable, ouvrirLienExterne } from './lienExterne';

describe('Un lien de note n’est pas ouvrable parce qu’il ressemble à un lien', () => {
  it('accepte http et https', () => {
    expect(estLienOuvrable('https://openclassrooms.com/fr/courses/4312781')).toBe(true);
    expect(estLienOuvrable('http://127.0.0.1:8000/vie/notes')).toBe(true);
  });

  it('refuse javascript:, qui exécuterait du code dans la page', () => {
    expect(estLienOuvrable('javascript:alert(1)')).toBe(false);
  });

  it('refuse file:, qui ouvrirait le disque', () => {
    expect(estLienOuvrable('file:///Users/carlito.e/.diapason/auth')).toBe(false);
  });

  it('refuse data:, qui embarque son propre contenu', () => {
    expect(estLienOuvrable('data:text/html,<script>1</script>')).toBe(false);
  });

  it('refuse ce qui n’est pas une URL du tout', () => {
    for (const brut of ['', '   ', 'openclassrooms.com', 'https://', '://x']) {
      expect(estLienOuvrable(brut)).toBe(false);
    }
  });
});

describe('Dans le téléphone, un lien part à la coquille', () => {
  it('passe par ouvrirExterne et ne dit « ouvert » que sur sa réponse', async () => {
    // Échec évité (26/09/2026) : window.open ne fait rien dans la WebView
    // d'Android, et la fonction rendait `true` quand même.
    const demandes: unknown[] = [];
    const env = (ok: boolean) => ({
      tauri: false,
      mobile: true,
      demander: async (_verbe: 'ouvrirExterne', donnees: { url: string }) => {
        demandes.push(donnees);
        return { type: 'reponse' as const, id: 'b1', ok };
      },
    });
    expect(await ouvrirLienExterne('https://exemple.org/a', env(true))).toBe(true);
    expect(await ouvrirLienExterne('https://exemple.org/b', env(false))).toBe(false);
    expect(demandes).toEqual([{ url: 'https://exemple.org/a' }, { url: 'https://exemple.org/b' }]);
  });

  it('rend faux quand le pont se tait, au lieu de lever', async () => {
    const env = {
      tauri: false,
      mobile: true,
      demander: async () => {
        throw new Error('délai');
      },
    };
    expect(await ouvrirLienExterne('https://exemple.org', env)).toBe(false);
  });

  it('ne transmet jamais un lien refusé', async () => {
    let appele = false;
    const env = {
      tauri: false,
      mobile: true,
      demander: async () => {
        appele = true;
        return { type: 'reponse' as const, id: 'b1', ok: true };
      },
    };
    expect(await ouvrirLienExterne('javascript:alert(1)', env)).toBe(false);
    expect(appele).toBe(false);
  });
});
