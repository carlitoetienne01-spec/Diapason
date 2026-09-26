import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Le câblage réel de l'enregistrement dans le téléphone, sans environnement
 * injecté.
 *
 * Échec évité (26/09/2026) : tous les tests passaient leur propre
 * environnement. Remplacer `mobile: estMobile && pont !== null` par
 * `mobile: false` dans l'environnement par défaut laissait la suite verte —
 * et le téléphone retombait sur le clic `blob:` qui ne fait RIEN dans la
 * WebView d'Android, exactement le défaut de 70ba5de.
 */

const banc = vi.hoisted(() => ({
  envoyes: [] as Array<Record<string, unknown>>,
  reponse: { ok: true, donnees: { nom: 'Téléchargements/a.json' } } as Record<string, unknown>,
}));

vi.mock('./natif', async (importOriginal) => {
  const vrai = await importOriginal<typeof import('./natif')>();
  let pont: InstanceType<typeof vrai.PontNatif>;
  const canal = {
    postMessage(texte: string) {
      const m = JSON.parse(texte) as Record<string, unknown>;
      banc.envoyes.push(m);
      queueMicrotask(() => pont.recevoir({ type: 'reponse', id: m.id, ...banc.reponse }));
    },
  };
  pont = new vrai.PontNatif(canal);
  return {
    ...vrai,
    estMobile: true,
    pontNatif: pont,
    demanderAuTelephone: (verbe: 'ouvrirExterne', donnees: unknown) => pont.demander(verbe, donnees),
  };
});

import { enregistrerHorsBureau } from './enregistrerFichier';
import { ouvrirLienExterne } from './lienExterne';

beforeEach(() => {
  banc.envoyes.length = 0;
  banc.reponse = { ok: true, donnees: { nom: 'Téléchargements/a.json' } };
});

describe('Dans le téléphone, sans environnement injecté', () => {
  it('enregistrer part à la coquille, et le nom est le sien', async () => {
    const clic = vi.spyOn(HTMLAnchorElement.prototype, 'click');
    const nom = await enregistrerHorsBureau(new Blob(['{}'], { type: 'application/json' }), 'a.json');
    expect(banc.envoyes[0]).toMatchObject({ verbe: 'enregistrer', donnees: { nom: 'a.json' } });
    expect(clic, 'aucun clic blob: dans le téléphone').not.toHaveBeenCalled();
    expect(nom).toBe('Téléchargements/a.json');
    clic.mockRestore();
  });

  it('un renoncement rend null', async () => {
    banc.reponse = { ok: false, erreur: 'annule' };
    expect(await enregistrerHorsBureau(new Blob(['{}']), 'a.json')).toBeNull();
  });

  it('un lien externe part à la coquille, pas à window.open', async () => {
    const ouvrir = vi.spyOn(window, 'open').mockImplementation(() => null);
    expect(await ouvrirLienExterne('https://exemple.org/')).toBe(true);
    expect(banc.envoyes[0]).toMatchObject({
      verbe: 'ouvrirExterne',
      donnees: { url: 'https://exemple.org/' },
    });
    expect(ouvrir).not.toHaveBeenCalled();
    ouvrir.mockRestore();
  });
});
