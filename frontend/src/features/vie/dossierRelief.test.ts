import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  perspectiveDuDossier,
  profondeur,
  reliefDuDossier,
  survolDuDossier,
  transitionDeSurvol,
} from './dossierRelief';

/**
 * Les dossiers à plat au téléphone (26/09/2026, contre-épreuve de la
 * fluidité : la copie du dossier dans les Projets gardait son relief —
 * 149 calques, 16 transitions de 320 à 460 ms).
 */
describe('à plat (téléphone)', () => {
  it('ni perspective, ni preserve-3d, ni will-change, ni translateZ, ni transition', () => {
    expect(perspectiveDuDossier(true)).toBeUndefined();
    expect(reliefDuDossier(true, { x: 3, y: -2 }, true, 1.03), 'aucun style de relief').toEqual({});
    expect(profondeur(true, 22)).toBeUndefined();
    expect(transitionDeSurvol(true, 'opacity 320ms ease'), 'aucune transition de survol').toBeUndefined();
    expect(survolDuDossier(true, { onPointerEnter: () => {} }), 'aucun survol au doigt').toEqual({});
  });
});

describe('en relief (Mac, inchangé)', () => {
  it('garde la perspective, l’inclinaison et les couches', () => {
    expect(perspectiveDuDossier(false)).toBe('760px');
    const relief = reliefDuDossier(false, { x: 3, y: -2 }, true, 1.03);
    expect(relief.transform).toBe('rotateX(-2deg) rotateY(3deg) scale(1.03)');
    expect(relief.transformStyle).toBe('preserve-3d');
    expect(relief.willChange).toBe('transform');
    expect(reliefDuDossier(false, { x: 0, y: 0 }, false, 1.03).transition).toContain('460ms');
    expect(profondeur(false, 22)).toBe('translateZ(22px)');
    expect(transitionDeSurvol(false, 'opacity 320ms ease')).toBe('opacity 320ms ease');
  });
});

describe('aucun composant ne pose de relief sans passer par ici', () => {
  it('pas de preserve-3d, translateZ ni perspective de dossier en dur dans les sources', () => {
    const racine = join(__dirname, '..', '..');
    const fautifs: string[] = [];
    const parcourir = (dossier: string) => {
      for (const nom of readdirSync(dossier)) {
        const chemin = join(dossier, nom);
        if (statSync(chemin).isDirectory()) parcourir(chemin);
        else if (/\.tsx?$/.test(nom) && !/\.test\./.test(nom) && !chemin.endsWith('dossierRelief.ts')) {
          const code = readFileSync(chemin, 'utf8').replace(/\/\/[^\n]*|\/\*[\s\S]*?\*\//g, '');
          if (/preserve-3d|translateZ\(|perspective: '\d/.test(code)) fautifs.push(chemin.slice(racine.length));
        }
      }
    };
    parcourir(racine);
    expect(fautifs, 'un relief posé à côté de dossierRelief.ts oublie le téléphone').toEqual([]);
  });
});
