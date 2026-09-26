import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Le visuel de la Discussion et le PDF d'une pile, exportés dans le
 * téléphone : rien ne s'annonce sur un renoncement.
 *
 * Échec évité (26/09/2026) : seul l'assistant commun était éprouvé. Faire
 * rendre `true` au visuel, ou faire rendre au PDF le nom proposé sans
 * passer par la coquille, laissait toute la suite verte — et « enregistré »
 * se serait affiché sur un sélecteur d'Android refermé sans rien choisir.
 */

const banc = vi.hoisted(() => ({
  envoyes: [] as Array<Record<string, unknown>>,
  reponse: { ok: false, erreur: 'annule' } as Record<string, unknown>,
}));

vi.mock('../../../lib/natif', async (importOriginal) => {
  const vrai = await importOriginal<typeof import('../../../lib/natif')>();
  let pont: InstanceType<typeof vrai.PontNatif>;
  pont = new vrai.PontNatif({
    postMessage(texte: string) {
      const m = JSON.parse(texte) as Record<string, unknown>;
      banc.envoyes.push(m);
      queueMicrotask(() => pont.recevoir({ type: 'reponse', id: m.id, ...banc.reponse }));
    },
  });
  return { ...vrai, estMobile: true, pontNatif: pont };
});

import { exporterPdf } from '../../../features/vie/photosExport';
import { enregistrerVisuel } from './exportVisuel';

const rendu = { svg: '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>', width: 10, height: 10 };

beforeEach(() => {
  banc.envoyes.length = 0;
  banc.reponse = { ok: false, erreur: 'annule' };
});

describe('Hors de l’app de bureau, dans le téléphone', () => {
  it('le visuel rend false quand la personne renonce', async () => {
    expect(await enregistrerVisuel(rendu as never, 'svg', 'Courbe', '#fff')).toBe(false);
    expect(banc.envoyes[0]).toMatchObject({ verbe: 'enregistrer' });
  });

  it('le visuel rend true quand la coquille a écrit', async () => {
    banc.reponse = { ok: true, donnees: { nom: 'Courbe.svg' } };
    expect(await enregistrerVisuel(rendu as never, 'svg', 'Courbe', '#fff')).toBe(true);
  });

  it('le PDF d’une pile rend null quand la personne renonce', async () => {
    expect(await exporterPdf([], 'Pile', 'pile.pdf')).toBeNull();
    expect(banc.envoyes[0]).toMatchObject({ verbe: 'enregistrer', donnees: { nom: 'pile.pdf' } });
  });

  it('le PDF rend le nom de la coquille, pas celui proposé', async () => {
    banc.reponse = { ok: true, donnees: { nom: 'Téléchargements/pile (1).pdf' } };
    expect(await exporterPdf([], 'Pile', 'pile.pdf')).toBe('Téléchargements/pile (1).pdf');
  });
});
