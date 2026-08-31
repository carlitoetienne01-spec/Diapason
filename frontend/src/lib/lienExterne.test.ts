import { describe, expect, it } from 'vitest';

import { estLienOuvrable } from './lienExterne';

describe('Un lien de note n’est pas ouvrable parce qu’il ressemble à un lien', () => {
  it('accepte http et https', () => {
    expect(estLienOuvrable('https://openclassrooms.com/fr/courses/4312781')).toBe(true);
    expect(estLienOuvrable('http://127.0.0.1:8000/succes/notes')).toBe(true);
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
