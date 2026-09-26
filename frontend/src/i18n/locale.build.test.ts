// @vitest-environment node
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { transformSync } from 'esbuild';
import { describe, expect, it } from 'vitest';

// La cible par défaut de `vite build` (modules) : ce que le bundle servi au
// Mac et au téléphone exécute réellement.
const CIBLE_VITE = ['es2020', 'edge88', 'firefox78', 'chrome87', 'safari14'];

describe('localeDuDocument survit à la construction', () => {
  it('rend la langue de <html> une fois abaissé par esbuild', () => {
    // Échec évité (26/09/2026) : un `?.()` dans une valeur par défaut de
    // paramètre, abaissé pour safari14, référençait une variable hors de
    // portée — « n is not defined » dans le bundle, vitest restant vert
    // parce qu'il n'abaisse rien. On construit donc le vrai fichier.
    const source = readFileSync(join(process.cwd(), 'src/i18n/locale.ts'), 'utf8');
    const { code } = transformSync(source, { loader: 'ts', format: 'cjs', target: CIBLE_VITE });
    const module = { exports: {} as Record<string, unknown> };
    const faux = {
      document: { documentElement: { getAttribute: (nom: string) => (nom === 'lang' ? 'fr' : null) } },
      navigator: { languages: ['en'] },
    };
    new Function('module', 'exports', 'document', 'navigator', code)(
      module,
      module.exports,
      faux.document,
      faux.navigator,
    );
    const localeDuDocument = module.exports.localeDuDocument as () => string;
    expect(localeDuDocument()).toBe('fr');
  });
});
