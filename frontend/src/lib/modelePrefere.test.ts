import { describe, expect, it } from 'vitest';

import { modeleInitial } from './modelePrefere';

const MODELES = [{ id: 'qwen3.5:9b' }, { id: 'qwen3:14b' }];

describe('modeleInitial', () => {
  it('la préférence retenue gagne quand elle existe encore', () => {
    expect(modeleInitial('qwen3:14b', MODELES)).toBe('qwen3:14b');
  });

  it('une préférence disparue retombe sur la tête de liste', () => {
    expect(modeleInitial('parti:7b', MODELES)).toBe('qwen3.5:9b');
  });

  it('sans préférence, la tête de liste — le défaut du serveur', () => {
    expect(modeleInitial('', MODELES)).toBe('qwen3.5:9b');
  });

  it('liste vide : rien à choisir', () => {
    expect(modeleInitial('qwen3:14b', [])).toBeNull();
  });
});
