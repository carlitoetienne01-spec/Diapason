import { describe, expect, it } from 'vitest';

import { FENETRE_FRAPPE_MS, Historique, type Instantane } from './noteHistorique';

const etat = (html: string): Instantane => ({ html, place: null });

describe('Historique', () => {
  it('regroupe la frappe rapide en un seul pas, et sépare après une pause', () => {
    const h = new Historique();
    h.noterFrappe(etat('<p></p>'), 1000);
    h.noterFrappe(etat('<p>a</p>'), 1100);
    h.noterFrappe(etat('<p>ab</p>'), 1200);
    // Pause, puis « c ».
    h.noterFrappe(etat('<p>ab</p>'), 1200 + FENETRE_FRAPPE_MS + 1);
    expect(h.annuler(etat('<p>abc</p>'))?.html).toBe('<p>ab</p>');
    expect(h.annuler(etat('<p>ab</p>'))?.html).toBe('<p></p>');
    expect(h.annuler(etat('<p></p>'))).toBeNull();
  });

  it('un geste fait toujours un pas, même au milieu d’une frappe', () => {
    const h = new Historique();
    h.noterFrappe(etat('<p></p>'), 1000);
    h.noterGeste(etat('<p>ab</p>'));
    expect(h.annuler(etat('<ol><li>ab</li></ol>'))?.html).toBe('<p>ab</p>');
    expect(h.annuler(etat('<p>ab</p>'))?.html).toBe('<p></p>');
  });

  it('rétablit ce qu’on vient d’annuler, et un nouveau pas efface le futur', () => {
    const h = new Historique();
    h.noterGeste(etat('A'));
    const b = etat('B');
    expect(h.annuler(b)?.html).toBe('A');
    expect(h.peutRetablir).toBe(true);
    expect(h.retablir(etat('A'))?.html).toBe('B');
    expect(h.peutRetablir).toBe(false);
    h.annuler(b);
    h.noterGeste(etat('A'));
    expect(h.peutRetablir).toBe(false);
  });

  it('saute un pas identique au présent, et n’empile pas deux fois le même état', () => {
    const h = new Historique();
    h.noterGeste(etat('A'));
    h.noterGeste(etat('A'));
    h.noterGeste(etat('B'));
    expect(h.annuler(etat('B'))?.html).toBe('A');
    expect(h.peutAnnuler).toBe(false);
  });

  it('après un geste, la frappe qui suit est un pas à part, même immédiate', () => {
    const h = new Historique();
    h.noterGeste(etat('<p>un</p>'));
    // Le geste a publié « liste » ; la frappe « deux » arrive 50 ms après.
    h.couper();
    h.noterFrappe(etat('<ol><li>un</li></ol>'), 1050);
    expect(h.annuler(etat('<ol><li>un deux</li></ol>'))?.html).toBe('<ol><li>un</li></ol>');
    expect(h.annuler(etat('<ol><li>un</li></ol>'))?.html).toBe('<p>un</p>');
  });

  it('borne la profondeur', () => {
    const h = new Historique(3);
    for (let i = 0; i < 10; i += 1) h.noterGeste(etat(String(i)));
    expect(h.annuler(etat('x'))?.html).toBe('9');
    expect(h.annuler(etat('9'))?.html).toBe('8');
    expect(h.annuler(etat('8'))?.html).toBe('7');
    expect(h.annuler(etat('7'))).toBeNull();
  });

  it('vider repart de zéro (changement de note)', () => {
    const h = new Historique();
    h.noterGeste(etat('A'));
    h.vider();
    expect(h.peutAnnuler).toBe(false);
  });
});
