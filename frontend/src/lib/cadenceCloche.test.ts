// La relève de la cloche (chantier de la fluidité, lot 2, 26/09/2026) : au
// repos, le téléphone relisait les approbations toutes les 5 s en 4G.

import { describe, expect, it } from 'vitest';

import {
  CLOCHE_EN_ATTENTE_MS,
  CLOCHE_REPOS_BUREAU_MS,
  CLOCHE_REPOS_TELEPHONE_MS,
  intervalleCloche,
} from './cadenceCloche';

describe('intervalleCloche', () => {
  it('suit de près une décision qui attend, au téléphone comme au Mac', () => {
    expect(intervalleCloche(1, true), 'au téléphone').toBe(CLOCHE_EN_ATTENTE_MS);
    expect(intervalleCloche(2, false), 'au Mac').toBe(CLOCHE_EN_ATTENTE_MS);
  });

  it('ne change rien au Mac, où la boucle locale ne coûte rien', () => {
    expect(intervalleCloche(0, false)).toBe(5_000);
    expect(CLOCHE_REPOS_BUREAU_MS).toBe(5_000);
  });

  it('espace la relève au repos au téléphone, où chaque requête réveille la radio', () => {
    expect(intervalleCloche(0, true), 'six fois moins souvent qu’au Mac').toBe(CLOCHE_REPOS_TELEPHONE_MS);
    expect(CLOCHE_REPOS_TELEPHONE_MS / CLOCHE_REPOS_BUREAU_MS).toBe(6);
  });
});
