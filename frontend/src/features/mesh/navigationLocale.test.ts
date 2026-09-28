import { describe, expect, it } from 'vitest';
import { cheminLocal } from './navigationLocale';
import { PAGES_ROUE } from '../roue/pagesRoue';

describe('navigation interne de l’assistant', () => {
  it('accepte toutes les pages réellement accessibles', () => {
    for (const page of PAGES_ROUE) expect(cheminLocal(page.chemin, 200, 100)).toBe(page.chemin);
  });
  it('refuse une navigation périmée ou hors application', () => {
    expect(cheminLocal('/vie/finances', 100, 100)).toBeNull();
    expect(cheminLocal('/vie/finances', undefined, 100)).toBeNull();
    expect(cheminLocal('https://example.com', 200, 100)).toBeNull();
    expect(cheminLocal('/inconnu', 200, 100)).toBeNull();
  });
});
