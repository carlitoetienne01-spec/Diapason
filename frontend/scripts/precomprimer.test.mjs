// @vitest-environment node
// La précompression du bundle servi par le serveur (lot 1 de la fluidité,
// 26/09/2026). Ce que chaque test évite : une variante qui ne décomprime pas
// à l'identique (le téléphone exécuterait autre chose que le Mac), ou une
// variante périmée laissée à côté d'un original qui a changé.
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { precomprimer, SEUIL_OCTETS } from './precomprimer.mjs';

let dossier;

beforeEach(async () => {
  dossier = await fs.mkdtemp(path.join(os.tmpdir(), 'precomprimer-'));
  await fs.mkdir(path.join(dossier, 'assets'));
});

afterEach(async () => {
  vi.restoreAllMocks();
  await fs.rm(dossier, { recursive: true, force: true });
});

const js = "export const tache = { titre: 'Réviser le chapitre', fait: false };\n".repeat(400);

describe('precomprimer', () => {
  it('pose des variantes br et gz qui redonnent le fichier à l’octet près', async () => {
    const chemin = path.join(dossier, 'assets', 'index-Ab1_cD-2.js');
    await fs.writeFile(chemin, js);
    const bilan = await precomprimer(dossier);
    expect(bilan.fichiers, 'un seul fichier candidat').toBe(1);
    const br = zlib.brotliDecompressSync(await fs.readFile(`${chemin}.br`));
    const gz = zlib.gunzipSync(await fs.readFile(`${chemin}.gz`));
    expect(br.toString(), 'le brotli décomprimé est le fichier').toBe(js);
    expect(gz.toString(), 'le gzip décomprimé est le fichier').toBe(js);
    expect(bilan.br, 'brotli doit gagner franchement').toBeLessThan(bilan.brut / 5);
  });

  it('ignore les petits fichiers et les formats déjà comprimés', async () => {
    await fs.writeFile(path.join(dossier, 'index.html'), 'x'.repeat(SEUIL_OCTETS - 1));
    await fs.writeFile(path.join(dossier, 'assets', 'police-Ab1_cD-2.woff2'), js);
    await fs.writeFile(path.join(dossier, 'icone.png'), js);
    const bilan = await precomprimer(dossier);
    expect(bilan.fichiers).toBe(0);
    const noms = (await fs.readdir(dossier, { recursive: true })).map(String);
    expect(noms.filter((n) => n.endsWith('.br') || n.endsWith('.gz'))).toEqual([]);
  });

  it('retire une variante périmée quand le fichier ne se comprime plus', async () => {
    const chemin = path.join(dossier, 'sw.js');
    await fs.writeFile(chemin, js);
    await precomprimer(dossier);
    // Le même nom, un contenu qui ne se comprime pas (octets aléatoires) :
    // l'ancien .br décrirait un fichier qui n'existe plus.
    const hasard = Buffer.alloc(8192);
    for (let i = 0; i < hasard.length; i++) hasard[i] = Math.floor(Math.random() * 256);
    await fs.writeFile(chemin, hasard);
    await precomprimer(dossier);
    await expect(fs.stat(`${chemin}.br`), 'plus de .br périmé').rejects.toThrow();
    await expect(fs.stat(`${chemin}.gz`), 'plus de .gz périmé').rejects.toThrow();
  });

  // 26/09/2026, contre-épreuve : ces deux règles survivaient à leur retrait,
  // 1 580 tests verts.
  it('retire les variantes d’un fichier devenu plus petit que le seuil', async () => {
    const chemin = path.join(dossier, 'sw.js');
    await fs.writeFile(chemin, js);
    await precomprimer(dossier);
    await fs.stat(`${chemin}.br`);
    // Réécrit sous 1 Ko : l'ancien .br décrirait 27 Ko qui n'existent plus,
    // et le serveur le servirait tant qu'il est plus récent que l'original.
    await fs.writeFile(chemin, 'self.skipWaiting();');
    await precomprimer(dossier);
    await expect(fs.stat(`${chemin}.br`), 'plus de .br d’un autre contenu').rejects.toThrow();
    await expect(fs.stat(`${chemin}.gz`), 'plus de .gz d’un autre contenu').rejects.toThrow();
  });

  it('n’écrit jamais une variante en place : un fichier provisoire, puis un renommage', async () => {
    const chemin = path.join(dossier, 'assets', 'index-Ab1_cD-2.js');
    await fs.writeFile(chemin, js);
    const ecrits = [];
    const renommes = [];
    const ecrire = fs.writeFile.bind(fs);
    const renommer = fs.rename.bind(fs);
    vi.spyOn(fs, 'writeFile').mockImplementation((cible, ...reste) => {
      ecrits.push(String(cible));
      return ecrire(cible, ...reste);
    });
    vi.spyOn(fs, 'rename').mockImplementation((de, vers) => {
      renommes.push(String(vers));
      return renommer(de, vers);
    });
    await precomprimer(dossier);
    // Le serveur tourne pendant qu'install-desktop.sh recopie le bundle : une
    // variante écrite en place part au téléphone à moitié écrite.
    expect(ecrits.length, 'deux variantes écrites').toBe(2);
    for (const cible of ecrits) {
      expect(cible.endsWith('.tmp'), `${cible} écrit en place`).toBe(true);
    }
    expect(renommes.sort()).toEqual([`${chemin}.br`, `${chemin}.gz`]);
    const noms = (await fs.readdir(dossier, { recursive: true })).map(String);
    expect(noms.filter((n) => n.endsWith('.tmp')), 'aucun provisoire ne reste').toEqual([]);
  });
});
