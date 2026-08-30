import { describe, expect, it } from 'vitest';

import {
  assurerUneEncreLisible,
  contrasteSurBlanc,
  nettoyerCouleursIllisibles,
  sanitizeNoteHtml,
} from './noteSanitize';

describe('contrasteSurBlanc', () => {
  it('rend 1 pour du blanc — le cas qui a rendu un tableau invisible', () => {
    expect(contrasteSurBlanc('rgb(255, 255, 255)')).toBeCloseTo(1, 2);
    expect(contrasteSurBlanc('#ffffff')).toBeCloseTo(1, 2);
    expect(contrasteSurBlanc('white')).toBeCloseTo(1, 2);
  });

  it('rend 21 pour du noir', () => {
    expect(contrasteSurBlanc('#000')).toBeCloseTo(21, 0);
  });

  it('reconnaît les couleurs voulues du document', () => {
    // Le bleu des titres et le rouge des avertissements, relevés dans la note.
    expect(contrasteSurBlanc('rgb(46, 116, 181)')).toBeGreaterThan(4.5);
    expect(contrasteSurBlanc('rgb(155, 28, 28)')).toBeGreaterThan(4.5);
    expect(contrasteSurBlanc('rgb(32, 55, 72)')).toBeGreaterThan(7);
  });

  it("rend null sur ce qu'il ne sait pas lire", () => {
    // Refuser ce qu'on ne comprend pas effacerait des mises en forme
    // légitimes : on conserve.
    expect(contrasteSurBlanc('currentcolor')).toBeNull();
    expect(contrasteSurBlanc('var(--x)')).toBeNull();
  });
});

describe('nettoyerCouleursIllisibles', () => {
  it('jette le blanc et garde tout le reste de la déclaration', () => {
    const nettoye = nettoyerCouleursIllisibles(
      'caret-color: rgb(255, 255, 255); color: rgb(255, 255, 255); font-weight: 700',
    );
    expect(nettoye).not.toMatch(/(^|;)\s*color\s*:/);
    expect(nettoye).toContain('font-weight: 700');
    // `caret-color` tombe AUSSI : un curseur blanc sur papier blanc est un
    // curseur qu'on ne voit pas, et le collage depuis un thème sombre en
    // pose partout.
    expect(nettoye).not.toContain('caret-color');
  });

  it('garde une couleur voulue et lisible', () => {
    const style = 'color: rgb(46, 116, 181); font-size: 8.5pt';
    expect(nettoyerCouleursIllisibles(style)).toBe(style);
  });

  it('ne touche pas un fond clair — seul le TEXTE est en cause', () => {
    const style = 'background: rgb(232, 238, 245); padding: 4pt';
    expect(nettoyerCouleursIllisibles(style)).toBe(style);
  });

  it('laisse passer un style sans couleur', () => {
    expect(nettoyerCouleursIllisibles('font-weight: 700')).toBe('font-weight: 700');
  });
});

describe('le cas réel du 30 août 2026', () => {
  it('un tableau collé depuis un thème sombre redevient lisible', () => {
    // Le div enveloppant portait `color: rgb(255,255,255)` — WebKit sérialise
    // le style CALCULÉ quand on copie, thème compris. Les cellules
    // n'déclaraient rien et héritaient donc du blanc, sur papier blanc :
    // vingt-cinq lignes de tableau s'affichaient vides.
    const colle =
      '<div style="caret-color: rgb(255, 255, 255); color: rgb(255, 255, 255);">' +
      '<table><tbody><tr><td><p><span style="font-size: 8.5pt;">Python</span></p></td>' +
      '<td><p><span style="font-size: 8.5pt;">550 à 750 h</span></p></td></tr></tbody></table>' +
      '</div>';
    const propre = sanitizeNoteHtml(colle);
    expect(propre).toContain('Python');
    expect(propre).toContain('550 à 750 h');
    expect(propre).not.toContain('rgb(255, 255, 255)');
    // La taille, elle, survit : on ne jette qu'une déclaration.
    expect(propre).toContain('font-size: 8.5pt');
  });

  it('le bloc « RÉPONSE DIRECTE » garde son fond et retrouve son encre', () => {
    const colle =
      '<div style="background: rgb(232, 238, 245); color: rgb(255, 255, 255);">' +
      '<p>Pour devenir fortement opérationnel…</p></div>';
    const propre = sanitizeNoteHtml(colle);
    expect(propre).toContain('background: rgb(232, 238, 245)');
    expect(propre).not.toMatch(/(^|;|")\s*color:\s*rgb\(255, 255, 255\)/);
    expect(propre).toContain('Pour devenir fortement opérationnel');
  });
});

describe('un fond déclaré déclare son encre', () => {
  it('un fond clair reçoit une encre sombre', () => {
    // Sans cela, le bloc hérite de l'encre du PAPIER : lisible sur le papier
    // blanc, invisible sur le papier sombre — 79 éléments à 1,00 de contraste
    // mesurés sur une vraie note.
    const nettoye = nettoyerCouleursIllisibles('background: rgb(232, 238, 245)');
    expect(assurerUneEncreLisible(nettoye)).toContain('color:#1a2232');
  });

  it('un fond sombre reçoit une encre claire', () => {
    expect(assurerUneEncreLisible('background: rgb(26, 34, 50)')).toContain(
      'color:#e8eef8',
    );
  });

  it('ne touche pas un style qui porte déjà sa couleur', () => {
    // C'est un choix de l'auteur, et il a survécu au filtre de contraste.
    const style = 'background: rgb(232, 238, 245); color: rgb(46, 116, 181)';
    expect(assurerUneEncreLisible(style)).toBe(style);
  });

  it('ne touche pas un style sans fond', () => {
    expect(assurerUneEncreLisible('font-weight: 700')).toBe('font-weight: 700');
  });

  it("le cas réel : fond clair + texte blanc redevient lisible partout", () => {
    // Dans son tableau : un <td> isolé est déballé par le nettoyeur, à juste
    // titre — le premier jet de ce test l'avait oublié.
    const propre = sanitizeNoteHtml(
      '<table><tbody><tr><td style="background: rgb(232, 238, 245); ' +
        'color: rgb(255, 255, 255);">Langage</td></tr></tbody></table>',
    );
    expect(propre).toContain('background: rgb(232, 238, 245)');
    expect(propre).toContain('color:#1a2232');
    expect(propre).not.toContain('rgb(255, 255, 255)');
  });
});
