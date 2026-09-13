import { describe, expect, it } from 'vitest';

import { cadreImage, chainePdf, construirePdf, octetsEnBase64, orientationPour } from './pdfPhotos';

const decodeur = new TextDecoder('latin1');
const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 0xff, 0xd9]);

describe('chainePdf', () => {
  it('garde les accents du français et échappe les parenthèses', () => {
    expect(chainePdf('été (test) \\ fin')).toBe('(\\351t\\351 \\(test\\) \\\\ fin)');
  });

  it('remplace ce que WinAnsi ne connaît pas par un point d’interrogation', () => {
    expect(chainePdf('ok 🙂')).toBe('(ok ?)');
  });
});

describe('cadreImage', () => {
  it('centre l’image dans la zone au-dessus de la légende, proportions gardées', () => {
    const c = cadreImage(1600, 1000);
    expect(c.w).toBeCloseTo(595.28 - 72, 1);
    expect(c.h).toBeCloseTo(c.w * (1000 / 1600), 1);
    expect(c.x).toBeCloseTo(36, 1);
    expect(c.y).toBeGreaterThan(36 + 40);
  });

  it('bascule en paysage pour une image large', () => {
    expect(orientationPour(1600, 1000).largeur).toBeGreaterThan(orientationPour(1600, 1000).hauteur);
    expect(orientationPour(1000, 1600).largeur).toBeLessThan(orientationPour(1000, 1600).hauteur);
  });
});

describe('construirePdf', () => {
  it('produit un PDF cohérent : en-tête, une page par photo, xref juste', () => {
    const pdf = construirePdf(
      [
        { jpeg: JPEG, largeur: 1600, hauteur: 1000, legende: 'Première' },
        { jpeg: JPEG, largeur: 800, hauteur: 1200, legende: '' },
      ],
      'Python',
    );
    const texte = decodeur.decode(pdf);
    expect(texte.startsWith('%PDF-1.4')).toBe(true);
    expect(texte.endsWith('%%EOF\n')).toBe(true);
    expect(texte).toContain('/Count 2');
    expect(texte).toContain('/Filter /DCTDecode /Length 9');
    expect(texte).toContain('(Premi\\350re)');
    expect(texte).toContain('/Title (Python)');
    // Chaque décalage de la table xref pointe bien sur « n 0 obj ».
    const debut = Number(/startxref\n(\d+)\n/.exec(texte)![1]);
    expect(texte.slice(debut, debut + 4)).toBe('xref');
    const lignes = texte.slice(debut).split('\n').slice(2, 2 + 10);
    lignes.forEach((ligne, n) => {
      if (n === 0) return;
      const offset = Number(ligne.slice(0, 10));
      expect(texte.slice(offset, offset + `${n} 0 obj`.length)).toBe(`${n} 0 obj`);
    });
  });

  it('les octets JPEG entrent tels quels', () => {
    const pdf = construirePdf([{ jpeg: JPEG, largeur: 2, hauteur: 2, legende: 'x' }]);
    const texte = decodeur.decode(pdf);
    const debut = texte.indexOf('stream\n', texte.indexOf('/DCTDecode')) + 'stream\n'.length;
    expect(Array.from(pdf.subarray(debut, debut + JPEG.length))).toEqual(Array.from(JPEG));
  });
});

describe('octetsEnBase64', () => {
  it('encode par tranches sans perdre un octet', () => {
    const gros = new Uint8Array(70000).map((_, i) => i % 251);
    expect(atob(octetsEnBase64(gros)).length).toBe(70000);
    expect(octetsEnBase64(new Uint8Array([37, 80, 68, 70]))).toBe('JVBERg==');
  });
});
