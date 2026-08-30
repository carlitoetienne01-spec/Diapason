import { describe, expect, it } from 'vitest';

import { sanitizeNoteHtml } from './noteSanitize';
import {
  boitePage,
  decomposeLegacyFormat,
  miseEnPageDeLaNote,
  NOTE_PAGE_FORMATS,
  NOTE_PAGE_MARGINS,
  NOTE_FONT_SIZES,
  NOTE_PAGE_SIZES,
  styleDeTaille,
} from './noteFormats';

describe('les trois axes de Word', () => {
  it('le paysage échange les DEUX dimensions', () => {
    const portrait = boitePage({ size: 'a4', orientation: 'portrait', margins: 'normales' });
    const paysage = boitePage({ size: 'a4', orientation: 'paysage', margins: 'normales' });
    expect(portrait).toMatchObject({ w: '210mm', h: '297mm' });
    expect(paysage.w).toBe('297mm');
    expect(paysage.h).toBe('210mm');
  });

  it("l'orientation ne touche pas aux marges", () => {
    const portrait = boitePage({ size: 'a4', orientation: 'portrait', margins: 'moderees' });
    const paysage = boitePage({ size: 'a4', orientation: 'paysage', margins: 'moderees' });
    expect([paysage.t, paysage.r, paysage.b, paysage.l]).toEqual([
      portrait.t,
      portrait.r,
      portrait.b,
      portrait.l,
    ]);
  });

  it('les marges Modérées sont asymétriques, comme chez Word', () => {
    // 2,54 cm en haut et en bas, 1,91 cm à gauche et à droite. L'ancienne
    // variable unique `--note-margin` rendait ce préréglage inexprimable.
    const box = boitePage({ size: 'a4', orientation: 'portrait', margins: 'moderees' });
    expect(box).toMatchObject({ t: '1in', b: '1in', l: '0.75in', r: '0.75in' });
  });

  it('les marges sont écrites en pouces, pour tomber sur des pixels entiers', () => {
    // 1, 0,5, 0,75 et 2 po donnent 96, 48, 72 et 192 px à 96 dpi. Les mêmes
    // valeurs en centimètres dérivent de 0,19 px sur « Modérées ».
    for (const marge of NOTE_PAGE_MARGINS) {
      for (const cote of [marge.t, marge.r, marge.b, marge.l]) {
        expect(cote.endsWith('in')).toBe(true);
        expect((parseFloat(cote) * 96) % 1).toBe(0);
      }
    }
  });
});

describe('les notes déjà enregistrées se relisent', () => {
  it.each([
    ['a4', 'a4', 'portrait', 'normales'],
    ['letter', 'letter', 'portrait', 'normales'],
    ['a5', 'a5', 'portrait', 'normales'],
    ['wide', 'a4', 'paysage', 'normales'],
    ['narrow', 'executive', 'portrait', 'moderees'],
    ['full', 'a4', 'portrait', 'etroites'],
    ['reading', 'a4', 'portrait', 'larges'],
  ] as const)('« %s » se relit en %s / %s / %s', (herite, size, orientation, margins) => {
    expect(decomposeLegacyFormat(herite)).toEqual({ size, orientation, margins });
  });

  it('les sept anciennes valeurs sont toutes traduites', () => {
    // Si quelqu'un ajoute une entrée à la liste héritée sans la traduire,
    // ses notes rouvriraient silencieusement en A4 marges normales.
    for (const format of NOTE_PAGE_FORMATS) {
      const mise = decomposeLegacyFormat(format.id);
      expect(NOTE_PAGE_SIZES.some((s) => s.id === mise.size)).toBe(true);
    }
  });

  it('« Marges minimales » rouvre en A4 marges étroites, pas en A4 normales', () => {
    expect(decomposeLegacyFormat('full').margins).toBe('etroites');
  });

  it('les trois nouveaux champs gagnent sur la valeur héritée', () => {
    const mise = miseEnPageDeLaNote({
      pageFormat: 'a4',
      pageSize: 'legal',
      pageOrientation: 'paysage',
      pageMargins: 'larges',
    });
    expect(mise).toEqual({ size: 'legal', orientation: 'paysage', margins: 'larges' });
  });

  it("une note qui n'a que l'ancien champ reste lisible", () => {
    expect(miseEnPageDeLaNote({ pageFormat: 'wide' })).toEqual({
      size: 'a4',
      orientation: 'paysage',
      margins: 'normales',
    });
  });
});

describe('la géométrie tombe sur les chiffres de Word', () => {
  const PX_PAR_MM = 96 / 25.4;
  const enPx = (v: string) =>
    v.endsWith('mm') ? parseFloat(v) * PX_PAR_MM : parseFloat(v) * 96;

  it('A4 portrait marges normales tient 43 lignes, comme Word', () => {
    // Contrôle de fidélité : Word donne (297 − 50,8) mm de hauteur utile,
    // divisée par une ligne de 15,9 pt (Aptos 12 pt, interligne 1,08) = 43,9,
    // donc 43 lignes pleines. Si ce test tombe à 42 ou 44, la géométrie a
    // dérivé de celle de Word.
    const box = boitePage({ size: 'a4', orientation: 'portrait', margins: 'normales' });
    const utile = enPx(box.h) - enPx(box.t) - enPx(box.b);
    expect(Math.floor(utile / 21.2)).toBe(43);
  });

  it('la colonne de texte de « Larges » reste dans le confort de lecture', () => {
    // 45 à 75 caractères par ligne. À 15 px, un caractère moyen fait ~7,5 px.
    const box = boitePage({ size: 'a4', orientation: 'portrait', margins: 'larges' });
    const colonne = enPx(box.w) - enPx(box.l) - enPx(box.r);
    const caracteres = colonne / 7.5;
    expect(caracteres).toBeGreaterThanOrEqual(45);
    expect(caracteres).toBeLessThanOrEqual(75);
  });
});

describe('les tailles de police', () => {
  it('sont celles de Word, en points', () => {
    // L'ancien menu portait les valeurs 1 à 7 de execCommand('fontSize'), qui
    // émet <font size="N"> — un attribut que noteSanitize.ts ne conserve pas.
    // Le menu était mort de bout en bout : la taille disparaissait à la
    // première sauvegarde.
    expect(NOTE_FONT_SIZES).toContain(11);
    expect(NOTE_FONT_SIZES).toContain(12);
    expect(NOTE_FONT_SIZES[0]).toBe(8);
    expect(NOTE_FONT_SIZES[NOTE_FONT_SIZES.length - 1]).toBe(72);
  });

  it('sont croissantes, sans doublon', () => {
    const trie = [...NOTE_FONT_SIZES].sort((a, b) => a - b);
    expect(NOTE_FONT_SIZES).toEqual(trie);
    expect(new Set(NOTE_FONT_SIZES).size).toBe(NOTE_FONT_SIZES.length);
  });

  it("s'expriment en style inline, que le nettoyeur conserve déjà", () => {
    // `style` est autorisé par noteSanitize.ts ; `size` ne l'est pas. C'est
    // toute la différence entre une taille qui survit et une qui s'efface.
    expect(styleDeTaille(14)).toBe('font-size:14pt');
    expect(sanitizeNoteHtml('<span style="font-size:14pt">x</span>')).toContain(
      'font-size:14pt',
    );
  });

  it("l'attribut size, lui, ne survit PAS — c'était le défaut", () => {
    expect(sanitizeNoteHtml('<font size="7">x</font>')).not.toContain('size');
  });
});
