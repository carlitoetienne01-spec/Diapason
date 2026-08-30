import { describe, expect, it } from 'vitest';

import { fitZoom, NOTE_ZOOMS } from './noteZoom';

const A4_PX = 793.7;

describe('fitZoom', () => {
  it('laisse la page à 100 % quand elle tient', () => {
    expect(fitZoom(940, A4_PX)).toBe(1);
  });

  it("ne gonfle jamais le papier sur un grand écran", () => {
    // Word ne le fait pas non plus en « Largeur de page » : une A4 affichée à
    // 150 % sur un 4K n'est plus une A4 pour l'œil.
    expect(fitZoom(2000, A4_PX)).toBe(1);
    expect(fitZoom(4000, A4_PX)).toBe(1);
  });

  it('met à l’échelle au lieu de comprimer quand la fenêtre est étroite', () => {
    // Le cas mesuré : 398 px de feuille pour une A4 de 794. Au lieu de
    // rétrécir la largeur SEULE — ce qui reflue le texte et fausse la
    // pagination — on réduit toute la page.
    expect(fitZoom(560, A4_PX)).toBe(0.67);
    expect(fitZoom(430, A4_PX)).toBe(0.5);
  });

  it('garde le rapport de la page : les deux dimensions suivent', () => {
    const zoom = fitZoom(560, A4_PX);
    const largeur = A4_PX * zoom;
    const hauteur = 1122.52 * zoom;
    expect(hauteur / largeur).toBeCloseTo(1122.52 / A4_PX, 5);
  });

  it('plancher à 25 % : sous cette taille, mieux vaut faire défiler', () => {
    expect(fitZoom(100, A4_PX)).toBe(0.25);
    expect(fitZoom(1, A4_PX)).toBe(0.25);
  });

  it('arrondit au pour cent', () => {
    // Un ResizeObserver qui écrirait 0,6613756613756614 à chaque pixel
    // relancerait une pagination complète à chaque image.
    for (const largeur of [500, 561, 623, 777, 888]) {
      expect((fitZoom(largeur, A4_PX) * 100) % 1).toBe(0);
    }
  });

  it('rend 1 plutôt que NaN sur une mesure absente', () => {
    // Une mesure prise avant le layout donne 0 : refuser de diviser vaut
    // mieux que d’écrire NaN dans une variable CSS.
    expect(fitZoom(0, A4_PX)).toBe(1);
    expect(fitZoom(940, 0)).toBe(1);
  });

  it('le menu propose « Largeur de page » en premier', () => {
    expect(NOTE_ZOOMS[0].valeur).toBeNull();
    expect(NOTE_ZOOMS.map((z) => z.valeur)).toEqual([null, 0.5, 0.75, 1]);
  });
});
