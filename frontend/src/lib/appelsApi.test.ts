// Le cliquet des appels à l'API — qu'aucun écran ne reparle au serveur en direct.
//
// Un `fetch('/v1/…')` relatif marche dans le navigateur, où la page EST servie
// par le serveur. Dans la fenêtre de bureau, la page vient d'un autre schéma :
// le chemin ne désigne plus rien, et WebKit rend son erreur la plus opaque —
// « The string did not match the expected pattern. »
//
// Constaté le 1er septembre 2026 sur un écran depuis retiré : l'erreur
// s'affichait et « 0 » avec, alors que la base contenait mille trente lignes.
// Rien dans les tests ni dans le navigateur ne pouvait le montrer.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

// `import.meta.url` ne rend pas un chemin absolu utilisable ici ; vitest tourne
// depuis `frontend/`, et c'est de là qu'on part.
const RACINE = join(process.cwd(), 'src');

function fichiersSources(dossier: string): string[] {
  const sortie: string[] = [];
  for (const nom of readdirSync(dossier)) {
    const chemin = join(dossier, nom);
    if (statSync(chemin).isDirectory()) {
      sortie.push(...fichiersSources(chemin));
    } else if (/\.tsx?$/.test(nom) && !/\.test\.tsx?$/.test(nom)) {
      sortie.push(chemin);
    }
  }
  return sortie;
}

describe('Aucun écran ne parle au serveur par un chemin relatif', () => {
  it('tout appel à /v1/ passe par apiFetch ou par getBase()', () => {
    const fautifs: string[] = [];
    for (const dossier of ['features', 'pages', 'components']) {
      for (const chemin of fichiersSources(join(RACINE, dossier))) {
        // LES COMMENTAIRES D'ABORD RETIRÉS. Sans cela, ce cliquet se
        // déclenchait sur le commentaire qui EXPLIQUE le piège, en citant
        // l'appel fautif entre guillemets — un test qui punit sa propre
        // documentation finit par la faire supprimer.
        const source = readFileSync(chemin, 'utf-8')
          .replace(/\/\*[\s\S]*?\*\//g, '')
          .replace(/^[ \t]*\/\/.*$/gm, '');
        // `fetch(` suivi d'un chemin commençant par /v1/ SANS base devant :
        // c'est le cas qui casse dans la fenêtre. `apiFetch(` ne correspond
        // pas — la limite de mot exige que rien de mot ne précède « fetch ».
        const relatifs = source.match(/\bfetch\(\s*[`'"]\/v1\//g);
        if (relatifs) {
          fautifs.push(`${chemin.replace(RACINE, '')} (${relatifs.length})`);
        }
      }
    }
    expect(fautifs, [
      'Ces fichiers appellent le serveur par un chemin relatif.',
      'Dans la fenêtre de bureau, la page ne vient pas du serveur : le chemin',
      'ne désigne rien et WebKit rend « The string did not match the expected',
      'pattern. » Utilisez apiFetch, ou préfixez par getBase().',
      '',
      ...fautifs,
    ].join('\n')).toEqual([]);
  });
});
