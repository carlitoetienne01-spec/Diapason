import { describe, expect, it } from 'vitest';

import { composantInitial } from './pageParesseuse';
import { memoiserChargeur } from './prechargerPages';

/**
 * Une page préchargée se rend sans suspendre (lot 2 de la fluidité,
 * 26/09/2026 ; mutant A5 de la contre-épreuve).
 */
describe('composantInitial', () => {
  it('rend le module déjà arrivé, pas la version paresseuse qui suspendrait', async () => {
    const Page = () => null;
    const Paresseuse = () => null;
    const memo = memoiserChargeur(async () => Page);
    expect(composantInitial(memo, Paresseuse), 'rien d’arrivé : la version paresseuse').toBe(Paresseuse);
    await memo.charger();
    expect(composantInitial(memo, Paresseuse), 'arrivé : la page elle-même, sans « Chargement… »').toBe(Page);
  });
});
