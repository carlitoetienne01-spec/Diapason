import { describe, expect, it } from 'vitest';

import { champsNonReprisParAmorce } from './RecurrencesPanel';

describe('Ce qu’une amorce de récurrence laisse derrière elle (revue du 17 sept. 2026, défaut 21)', () => {
  it('ne nomme rien quand heure, notes et catégorie sont vides : rien à confirmer', () => {
    expect(champsNonReprisParAmorce({ time: '', notes: '', category: '' })).toEqual([]);
  });

  it('nomme chaque champ rempli qu’une règle ne porte pas, dans l’ordre du formulaire', () => {
    // « Répéter… » jetait ces trois champs en silence : une récurrence n'a
    // ni heure, ni notes, ni catégorie (`SuccesTemplate`).
    expect(champsNonReprisParAmorce({ time: '09:30', notes: 'appeler avant', category: 'Santé' })).toEqual([
      'l’heure',
      'les notes',
      'la catégorie',
    ]);
    expect(champsNonReprisParAmorce({ time: '', notes: 'appeler avant', category: '' })).toEqual(['les notes']);
  });

  it('ignore des notes ou une catégorie faites d’espaces — rien de saisi, rien de perdu', () => {
    expect(champsNonReprisParAmorce({ time: '', notes: '   ', category: ' \n' })).toEqual([]);
  });
});
