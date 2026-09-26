#!/usr/bin/env node
// Pose à côté de chaque fichier texte du bundle ses variantes .br et .gz.
//
//   node scripts/precomprimer.mjs [dossier]   (défaut : ../src/diapason/server/static)
//
// 26/09/2026, chantier de la fluidité : le serveur envoyait le bundle BRUT au
// téléphone — 2 517 936 octets pour ouvrir l'app, 625 575 en brotli 11. Le
// serveur Python ne comprime pas les fichiers lui-même : brotli 11 sur les
// 1,4 Mo d'index-*.js prendrait plus d'une seconde sur sa boucle, à chaque
// build. On le fait donc ici, une fois, et server/bundle_statique.py choisit
// la variante selon Accept-Encoding.
//
// Sans dépendance : node:zlib fait brotli et gzip. Branché sur `npm run build`
// et sur scripts/install-desktop.sh (qui recopie frontend/dist dans
// server/static — sans lui, le serveur de Carlito n'aurait jamais de variante).
// JAMAIS sur `build:tauri` : l'app de bureau embarque dist/ et le comprime
// déjà elle-même ; des .br et .gz y alourdiraient le binaire pour rien.

import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { promisify } from 'node:util';
import zlib from 'node:zlib';

const brotli = promisify(zlib.brotliCompress);
const gzip = promisify(zlib.gzip);

// La même liste que COMPRESSIBLES dans src/diapason/server/bundle_statique.py
// (tests/server/test_bundle_statique.py les compare). Les woff2, png, webp…
// sont déjà comprimés : les recomprimer ne gagne rien.
export const EXTENSIONS = new Set([
  '.js',
  '.mjs',
  '.css',
  '.html',
  '.svg',
  '.json',
  '.webmanifest',
  '.txt',
  '.xml',
  '.map',
  '.ttf',
  '.otf',
  '.ico',
  '.wasm',
]);

// Sous ~1 Ko, le fichier tient dans un paquet du tailnet (MTU 1 280) : une
// variante ne gagnerait ni un paquet ni un aller-retour.
export const SEUIL_OCTETS = 1024;

// Une variante qui ne gagne pas 10 % n'est pas posée : le serveur servirait
// alors l'original, et le navigateur n'aurait rien à décomprimer pour rien.
export const GAIN_MIN = 0.9;

/** Les deux variantes d'un contenu : brotli 11 (texte) et gzip 9. */
export async function comprimer(contenu) {
  const [br, gz] = await Promise.all([
    brotli(contenu, {
      params: {
        [zlib.constants.BROTLI_PARAM_QUALITY]: zlib.constants.BROTLI_MAX_QUALITY,
        [zlib.constants.BROTLI_PARAM_SIZE_HINT]: contenu.length,
        [zlib.constants.BROTLI_PARAM_MODE]: zlib.constants.BROTLI_MODE_TEXT,
      },
    }),
    gzip(contenu, { level: 9 }),
  ]);
  return { br, gz };
}

async function* fichiers(dossier) {
  for (const entree of await fs.readdir(dossier, { withFileTypes: true })) {
    const chemin = path.join(dossier, entree.name);
    if (entree.isDirectory()) yield* fichiers(chemin);
    else if (entree.isFile()) yield chemin;
  }
}

// Écrire puis renommer : le serveur tourne pendant qu'install-desktop.sh
// recopie le bundle, et une variante à moitié écrite partirait au téléphone
// comme un fichier corrompu.
async function ecrire(chemin, contenu) {
  const provisoire = `${chemin}.${process.pid}.tmp`;
  await fs.writeFile(provisoire, contenu);
  await fs.rename(provisoire, chemin);
}

async function retirer(chemin) {
  await fs.rm(chemin, { force: true });
}

/** Précomprime un fichier ; rend ce qui a été posé, ou null s'il est écarté. */
export async function precomprimerFichier(chemin) {
  if (!EXTENSIONS.has(path.extname(chemin).toLowerCase())) return null;
  const contenu = await fs.readFile(chemin);
  if (contenu.length < SEUIL_OCTETS) {
    await Promise.all([retirer(`${chemin}.br`), retirer(`${chemin}.gz`)]);
    return null;
  }
  const { br, gz } = await comprimer(contenu);
  const pose = { brut: contenu.length, br: 0, gz: 0 };
  for (const [suffixe, variante] of [
    ['.br', br],
    ['.gz', gz],
  ]) {
    if (variante.length <= contenu.length * GAIN_MIN) {
      await ecrire(chemin + suffixe, variante);
      pose[suffixe.slice(1)] = variante.length;
    } else {
      // Une variante d'un build précédent, restée là, serait servie à la
      // place d'un original qui a changé.
      await retirer(chemin + suffixe);
    }
  }
  return pose;
}

/** Précomprime tout un dossier ; rend le bilan (octets bruts, br, gz). */
export async function precomprimer(dossier) {
  const chemins = [];
  for await (const chemin of fichiers(dossier)) chemins.push(chemin);
  const bilan = { fichiers: 0, brut: 0, br: 0, gz: 0 };
  // Quatre à la fois : le fil de libuv en compte quatre par défaut, et
  // davantage ne ferait qu'attendre en mémoire.
  let suivant = 0;
  async function ouvrier() {
    while (suivant < chemins.length) {
      const pose = await precomprimerFichier(chemins[suivant++]);
      if (!pose) continue;
      bilan.fichiers += 1;
      bilan.brut += pose.brut;
      bilan.br += pose.br || pose.brut;
      bilan.gz += pose.gz || pose.brut;
    }
  }
  await Promise.all([ouvrier(), ouvrier(), ouvrier(), ouvrier()]);
  return bilan;
}

const ICI = path.dirname(fileURLToPath(import.meta.url));

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const dossier = path.resolve(
    process.argv[2] ?? path.join(ICI, '..', '..', 'src', 'diapason', 'server', 'static'),
  );
  const debut = Date.now();
  const bilan = await precomprimer(dossier);
  const ko = (n) => `${Math.round(n / 1024).toLocaleString('fr-FR')} Ko`;
  console.log(
    `précompression : ${bilan.fichiers} fichiers, ${ko(bilan.brut)} → ` +
      `${ko(bilan.br)} en brotli, ${ko(bilan.gz)} en gzip ` +
      `(${((Date.now() - debut) / 1000).toFixed(1)} s) — ${dossier}`,
  );
}
