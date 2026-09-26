#!/usr/bin/env node
// Ce que l'ouverture de l'app et le préchargement des pages chargent vraiment.
//
//   node scripts/verifierGraphe.mjs [dossier]   (défaut : ../src/diapason/server/static)
//
// 26/09/2026, contre-épreuve de la fluidité. Deux défauts que rien ne voyait :
//
// 1. L'index préchargeait `charts-*.js` — recharts, 432 Ko bruts, 104 Ko en
//    brotli — sur le chemin critique de la Discussion, qui n'en affiche
//    aucun. La cause n'était pas un import : `manualChunks: { charts:
//    ['recharts'] }` rangeait React lui-même dans ce morceau (le morceau
//    `react-*.js` pesait 1 octet), et l'entrée devait donc le charger.
// 2. Une page lourde (Plotly, Mermaid, Three) ajoutée au préchargement du
//    téléphone serait partie à chaque ouverture en 4G sans qu'un test rougisse.
//
// Le contrôle lit le build lui-même (les `import … from "./x.js"` statiques des
// morceaux) : c'est le graphe que le navigateur suit, pas celui des sources.
// Branché sur `npm run build`, après `vite build`.

import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

/** Une signature propre à chaque bibliothèque lourde, relevée dans le build. */
export const LOURDS = {
  recharts: 'recharts-surface',
  plotly: 'plotly.js',
  mermaid: 'mermaidAPI',
  three: 'WebGLRenderer',
};

/** Les imports STATIQUES d'un morceau (jamais les `import("./x.js")`). */
export function importsStatiques(code) {
  const vus = new Set();
  for (const m of code.matchAll(/(?:\bfrom|\bimport)\s*["']\.\/([^"']+\.js)["']/g)) vus.add(m[1]);
  return [...vus];
}

/** Tout ce que charger `depart` fait charger, lui compris. */
export function atteignables(lire, depart) {
  const vus = new Set();
  const pile = [depart];
  while (pile.length) {
    const nom = pile.pop();
    if (vus.has(nom)) continue;
    vus.add(nom);
    for (const suivant of importsStatiques(lire(nom))) pile.push(suivant);
  }
  return vus;
}

/** Les bibliothèques lourdes présentes dans un ensemble de morceaux. */
export function lourdsDans(lire, morceaux, interdits = Object.keys(LOURDS)) {
  const trouves = [];
  for (const nom of morceaux) {
    const code = lire(nom);
    for (const lib of interdits) if (code.includes(LOURDS[lib])) trouves.push(`${lib} (${nom})`);
  }
  return trouves;
}

/**
 * Les pages que App.tsx précharge, par le nom de leur module : chaque entrée
 * de `PAGES_A_PRECHARGER` doit être une page déclarée par `pageParesseuse`.
 */
export function pagesPrechargees(sourceApp) {
  const modules = new Map();
  for (const m of sourceApp.matchAll(/const (\w+) = pageParesseuse\(\(\) => import\('\.\/pages\/(\w+)'\)/g)) {
    modules.set(m[1], m[2]);
  }
  const bloc = sourceApp.split('const PAGES_A_PRECHARGER')[1]?.split('].map(')[0];
  if (!bloc) throw new Error('PAGES_A_PRECHARGER introuvable dans App.tsx');
  const corps = bloc.slice(bloc.indexOf('= [') + 3);
  const pages = [];
  for (const brut of corps.split(',')) {
    const nom = brut.replace(/\/\/[^\n]*/g, '').trim();
    if (!nom) continue;
    if (!modules.has(nom)) throw new Error(`« ${nom} » préchargé n'est pas une page de pageParesseuse`);
    pages.push(modules.get(nom));
  }
  return pages;
}

/** Le contrôle entier ; rend la liste des défauts (vide = conforme). */
export function verifier({ dossier, sourceApp }) {
  const assets = path.join(dossier, 'assets');
  const fichiers = readdirSync(assets).filter((f) => f.endsWith('.js'));
  const cache = new Map();
  const lire = (nom) => {
    if (!cache.has(nom)) cache.set(nom, readFileSync(path.join(assets, nom), 'utf8'));
    return cache.get(nom);
  };
  const html = readFileSync(path.join(dossier, 'index.html'), 'utf8');
  const entree = html.match(/<script[^>]*type="module"[^>]*src="\/assets\/([^"]+\.js)"/)?.[1];
  if (!entree) return ['index.html ne nomme aucun script d’entrée'];
  const defauts = [];
  const ouverture = atteignables(lire, entree);
  for (const lourd of lourdsDans(lire, ouverture)) {
    defauts.push(`l’ouverture de l’app charge ${lourd}`);
  }
  for (const page of pagesPrechargees(sourceApp)) {
    const morceau = fichiers.find((f) => new RegExp(`^${page}-[A-Za-z0-9_-]{8}\\.js$`).test(f));
    if (!morceau) {
      defauts.push(`page préchargée ${page} : aucun morceau ${page}-*.js`);
      continue;
    }
    // recharts est permis : les Finances en ont besoin, et il ne pèse que
    // 104 Ko en brotli. Plotly, Mermaid et Three dépassent chacun le Mo.
    for (const lourd of lourdsDans(lire, atteignables(lire, morceau), ['plotly', 'mermaid', 'three'])) {
      defauts.push(`le préchargement de ${page} charge ${lourd}`);
    }
  }
  return defauts;
}

const ICI = path.dirname(fileURLToPath(import.meta.url));

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const dossier = path.resolve(
    process.argv[2] ?? path.join(ICI, '..', '..', 'src', 'diapason', 'server', 'static'),
  );
  const sourceApp = readFileSync(path.join(ICI, '..', 'src', 'App.tsx'), 'utf8');
  const defauts = verifier({ dossier, sourceApp });
  if (defauts.length) {
    console.error(`graphe du bundle : ${defauts.length} défaut(s)\n  - ${defauts.join('\n  - ')}`);
    process.exit(1);
  }
  console.log(`graphe du bundle : ouverture et préchargement sans morceau lourd — ${dossier}`);
}
