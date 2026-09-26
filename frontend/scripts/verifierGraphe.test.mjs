// @vitest-environment node
// Le graphe du bundle (contre-épreuve de la fluidité, 26/09/2026). Ce que
// chaque test évite : recharts sur le chemin critique de la Discussion (il y
// était, 432 Ko bruts, par un morceau manuel qui emportait React), ou une
// page lourde glissée dans le préchargement du téléphone sans test rouge.
import { promises as fs, readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { importsStatiques, LOURDS, pagesPrechargees, verifier } from './verifierGraphe.mjs';

const APP = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'App.tsx'), 'utf8');

let dossier;

beforeEach(async () => {
  dossier = await fs.mkdtemp(path.join(os.tmpdir(), 'graphe-'));
  await fs.mkdir(path.join(dossier, 'assets'));
});

afterEach(async () => {
  await fs.rm(dossier, { recursive: true, force: true });
});

/** Un faux build : { nom: code }, et l'index qui nomme `entree`. */
async function construire(morceaux, entree = 'index-Ab1cD2e3.js') {
  for (const [nom, code] of Object.entries(morceaux)) {
    await fs.writeFile(path.join(dossier, 'assets', nom), code);
  }
  await fs.writeFile(
    path.join(dossier, 'index.html'),
    `<script type="module" crossorigin src="/assets/${entree}"></script>`,
  );
}

/** Toutes les pages préchargées, avec un morceau propre chacune. */
function pagesPropres() {
  return Object.fromEntries(pagesPrechargees(APP).map((p) => [`${p}-Zz9Yy8Xx.js`, 'export{}']));
}

describe('importsStatiques', () => {
  it('suit les import et from statiques, jamais les import() dynamiques', () => {
    const code = 'import{a as b}from"./react-Ab1cD2e3.js";import"./x-Ab1cD2e3.js";const p=()=>import("./lourd-Ab1cD2e3.js");';
    expect(importsStatiques(code).sort()).toEqual(['react-Ab1cD2e3.js', 'x-Ab1cD2e3.js']);
  });
});

describe('pagesPrechargees', () => {
  it('lit les pages de App.tsx, toutes déclarées par pageParesseuse', () => {
    const pages = pagesPrechargees(APP);
    expect(pages.slice(0, 3), 'les pages les plus visitées d’abord').toEqual([
      'VieTasksPage',
      'ViePlannerPage',
      'VieNotesPage',
    ]);
    expect(pages.length).toBeGreaterThanOrEqual(10);
  });

  it('refuse une entrée qui n’est pas une page', () => {
    const glisse = APP.replace('VieTasksPage, ViePlannerPage,', "VieTasksPage, () => import('plotly.js'), ViePlannerPage,");
    expect(glisse).not.toBe(APP);
    expect(() => pagesPrechargees(glisse)).toThrow(/n'est pas une page/);
  });
});

describe('verifier', () => {
  it('refuse recharts atteint depuis l’entrée, même par un morceau partagé', async () => {
    await construire({
      'index-Ab1cD2e3.js': 'import{K}from"./charts-Ab1cD2e3.js";',
      'charts-Ab1cD2e3.js': `const c="${LOURDS.recharts}";export{c as K}`,
      ...pagesPropres(),
    });
    expect(verifier({ dossier, sourceApp: APP })).toEqual([
      'l’ouverture de l’app charge recharts (charts-Ab1cD2e3.js)',
    ]);
  });

  it('laisse passer recharts chargé à la demande', async () => {
    await construire({
      'index-Ab1cD2e3.js': 'const f=()=>import("./CartesianChart-Ab1cD2e3.js");',
      'CartesianChart-Ab1cD2e3.js': `const c="${LOURDS.recharts}";`,
      ...pagesPropres(),
    });
    expect(verifier({ dossier, sourceApp: APP })).toEqual([]);
  });

  it('refuse une page préchargée qui emporte Plotly, Mermaid ou Three', async () => {
    const [premiere] = pagesPrechargees(APP);
    await construire({
      'index-Ab1cD2e3.js': 'export{}',
      ...pagesPropres(),
      [`${premiere}-Zz9Yy8Xx.js`]: 'import"./visuel-Ab1cD2e3.js";',
      'visuel-Ab1cD2e3.js': `const p="${LOURDS.plotly}";const m="${LOURDS.mermaid}";`,
    });
    expect(verifier({ dossier, sourceApp: APP })).toEqual([
      `le préchargement de ${premiere} charge plotly (visuel-Ab1cD2e3.js)`,
      `le préchargement de ${premiere} charge mermaid (visuel-Ab1cD2e3.js)`,
    ]);
  });
});
