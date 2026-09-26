import { describe, expect, it } from 'vitest';

import type { ReponseNatif } from '../../lib/natif';
import { ANNONCE_MENU_APP, annoncerLeMenuDeLApp, OUVRIR_MENU_APP } from './menuDeLApp';

const reponse = (ok: boolean, erreur?: string): ReponseNatif => ({ type: 'reponse', id: 'b1-1', ok, erreur });

describe('Le menu de l’app dans l’écran « Aller à » (lot 4, 26/09/2026)', () => {
  it('le bouton ne s’affiche que si la coquille a répondu ok à l’annonce', async () => {
    const envoyes: unknown[] = [];
    const affiche = await annoncerLeMenuDeLApp(async (_verbe, donnees) => {
      envoyes.push(donnees);
      return reponse(true);
    });
    expect(affiche, 'une coquille qui sait ouvrir son menu : le bouton est là').toBe(true);
    expect(envoyes, 'l’annonce n’ouvre rien : la coquille retire seulement sa barre').toEqual([{ ouvrir: false }]);
  });

  it('une coquille ancienne (verbeInconnu) garde sa barre, et le bouton n’apparaît pas', async () => {
    const affiche = await annoncerLeMenuDeLApp(async () => reponse(false, 'verbeInconnu'));
    expect(affiche, 'un bouton qui n’ouvrirait rien serait une promesse (§5)').toBe(false);
  });

  it('un délai ou un canal qui lève : pas de bouton, et aucune exception ne remonte', async () => {
    const affiche = await annoncerLeMenuDeLApp(async () => {
      throw new Error('délai');
    });
    expect(affiche).toBe(false);
  });

  it('les deux charges ne portent qu’un booléen', () => {
    expect(ANNONCE_MENU_APP).toEqual({ ouvrir: false });
    expect(OUVRIR_MENU_APP).toEqual({ ouvrir: true });
  });
});
