import { describe, expect, it } from 'vitest';

import { clavierOuvert, estUneSaisie, PART_CLAVIER, suivreHauteurMax } from './clavier';

/**
 * Clavier ouvert, le bouton de la roue se retire (26/09/2026, contre-épreuve
 * de la fluidité) : la Discussion gardait 97 px morts sous le compositeur.
 */
describe('clavierOuvert', () => {
  it('ouvert quand une saisie a le focus ET que l’écran a perdu un quart de sa hauteur', () => {
    expect(clavierOuvert({ hauteur: 482, hauteurMax: 812, saisie: true }), '482 px au banc').toBe(true);
    expect(clavierOuvert({ hauteur: 482, hauteurMax: 812, saisie: false }), 'sans saisie, un redimensionnement').toBe(false);
    expect(
      clavierOuvert({ hauteur: 812, hauteurMax: 812, saisie: true }),
      'le retour d’Android ferme le clavier sans rendre le focus : le bouton revient',
    ).toBe(false);
    expect(clavierOuvert({ hauteur: 760, hauteurMax: 812, saisie: true }), 'une barre qui apparaît').toBe(false);
    expect(PART_CLAVIER).toBe(0.75);
  });
});

describe('estUneSaisie', () => {
  it('un champ de texte, pas une case ni un bouton', () => {
    const texte = document.createElement('textarea');
    const champ = document.createElement('input');
    const case_ = document.createElement('input');
    case_.type = 'checkbox';
    const lecture = document.createElement('input');
    lecture.readOnly = true;
    const editable = document.createElement('div');
    editable.setAttribute('contenteditable', 'true');
    expect(estUneSaisie(texte)).toBe(true);
    expect(estUneSaisie(champ)).toBe(true);
    expect(estUneSaisie(editable), 'le carnet des Notes').toBe(true);
    expect(estUneSaisie(case_)).toBe(false);
    expect(estUneSaisie(lecture), 'en lecture seule : pas de clavier').toBe(false);
    expect(estUneSaisie(document.createElement('button'))).toBe(false);
    expect(estUneSaisie(null)).toBe(false);
  });
});

describe('suivreHauteurMax', () => {
  it('retient la plus grande hauteur par largeur', () => {
    const memo = new Map<number, number>();
    expect(suivreHauteurMax(memo, 375, 812)).toBe(812);
    expect(suivreHauteurMax(memo, 375, 482), 'le clavier ne baisse pas le maximum').toBe(812);
    expect(suivreHauteurMax(memo, 812, 375), 'l’écran tourné a son propre maximum').toBe(375);
  });
});
