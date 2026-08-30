import { describe, expect, it } from 'vitest';

import { aideDroitAccessibilite } from './accessibilite';

describe('l’aide Accessibilité', () => {
  it('se tait si l’erreur parle d’autre chose', () => {
    expect(aideDroitAccessibilite('Le micro s’est fermé tout seul')).toBeNull();
    expect(aideDroitAccessibilite(null)).toBeNull();
  });

  it('nomme le retrait de l’entrée fantôme, pas seulement la case', () => {
    const aide = aideDroitAccessibilite(
      'Le pointeur n’a pas pu agir : Autorise Diapason dans Accessibilité',
    );
    expect(aide).toContain('bouton −');
    expect(aide).toContain('/Applications/Diapason.app');
  });
});
