import { describe, expect, it } from 'vitest';

import { bornerZoom, fitZoom, ZOOM_MAX, ZOOM_MIN } from './noteZoom';

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

  it("l'ajustement reste plafonné à 100 %, le réglage manuel non", () => {
    // Deux gestes différents : « Largeur de page » ne doit pas gonfler le
    // papier, mais agrandir volontairement doit être possible.
    expect(fitZoom(4000, A4_PX)).toBe(1);
    expect(bornerZoom(2)).toBe(2);
  });
});

describe('bornerZoom', () => {
  it('monte jusqu’à 200 %, comme demandé', () => {
    expect(ZOOM_MAX).toBe(2);
    expect(bornerZoom(2)).toBe(2);
    expect(bornerZoom(5)).toBe(2);
  });

  it('ne descend pas sous 25 %, le même plancher que l’ajustement', () => {
    // Deux minimums différents selon le geste seraient un piège.
    expect(ZOOM_MIN).toBe(0.25);
    expect(bornerZoom(0.1)).toBe(0.25);
    expect(bornerZoom(-3)).toBe(0.25);
  });

  it('arrondit au pour cent', () => {
    expect(bornerZoom(0.666666)).toBe(0.67);
    expect((bornerZoom(1.234567) * 100) % 1).toBe(0);
  });

  it('rend 1 sur une valeur absurde plutôt que NaN', () => {
    expect(bornerZoom(NaN)).toBe(1);
    expect(bornerZoom(Infinity)).toBe(1);
  });
});
