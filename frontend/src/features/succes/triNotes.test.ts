import { describe, expect, it } from 'vitest';

import { estTriNotes, triInitialDesNotes, unArrangementExiste } from './triNotes';

describe('le tri des cartables à l’ouverture de Notes', () => {
  it('montre « Mon ordre » dès qu’un cartable a été rangé, sans rien avoir à choisir', () => {
    // 17 sept. 2026 : l’arrangement existait côté serveur mais la page
    // rouvrait toujours en « Récent » — le dernier édité passait devant.
    const notes = [{ order: 0 }, { order: 2 }, { order: 1 }];
    expect(unArrangementExiste(notes)).toBe(true);
    expect(triInitialDesNotes(undefined, notes)).toBe('manuel');
  });

  it('reste en « Récent » pour qui n’a jamais rien rangé', () => {
    const jamaisRangees = [{ order: 0 }, {}, { order: 0 }];
    expect(unArrangementExiste(jamaisRangees)).toBe(false);
    expect(triInitialDesNotes(undefined, jamaisRangees)).toBe('recent');
    expect(triInitialDesNotes(undefined, [])).toBe('recent');
  });

  it('respecte un choix mémorisé, même quand un arrangement existe', () => {
    const rangees = [{ order: 3 }];
    expect(triInitialDesNotes('name-asc', rangees)).toBe('name-asc');
    expect(triInitialDesNotes('recent', rangees)).toBe('recent');
  });

  it('ignore une valeur mémorisée qui n’est pas un tri', () => {
    expect(estTriNotes('manuel')).toBe(true);
    expect(estTriNotes('aleatoire')).toBe(false);
    expect(estTriNotes(42)).toBe(false);
    expect(triInitialDesNotes('aleatoire', [{ order: 1 }]), 'une valeur inconnue ne casse rien').toBe(
      'manuel',
    );
  });
});
