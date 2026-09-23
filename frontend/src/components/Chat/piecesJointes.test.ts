import { describe, expect, it } from 'vitest';

import {
  DOCUMENTS_MAX,
  DOCUMENT_TAILLE_MAX,
  NOMBRE_MAX,
  TAILLE_MAX,
  documentsPourLeFil,
  estUnDocument,
  resumeDocument,
  separer,
  trierDocuments,
  imagesDeLEvenement,
  messagesPourLApi,
  pourLeFil,
  resume,
  trier,
} from './piecesJointes';

function fichier(nom: string, type: string, octets: number): File {
  const f = new File(['x'], nom, { type });
  Object.defineProperty(f, 'size', { value: octets });
  return f;
}

describe('trier', () => {
  it('accepte les formats que les modèles de vision lisent', () => {
    const entrants = [
      fichier('capture.png', 'image/png', 1000),
      fichier('photo.jpg', 'image/jpeg', 2000),
      fichier('anim.gif', 'image/gif', 3000),
      fichier('moderne.webp', 'image/webp', 4000),
    ];
    const { acceptees, refus } = trier(entrants, 0);
    expect(acceptees).toHaveLength(4);
    expect(refus).toEqual([]);
  });

  it('refuse un PDF, et dit pourquoi', () => {
    const { acceptees, refus } = trier([fichier('contrat.pdf', 'application/pdf', 1000)], 0);
    expect(acceptees).toEqual([]);
    expect(refus[0].fichier).toBe('contrat.pdf');
    expect(refus[0].raison).toContain('Format non pris en charge');
  });

  it('nomme les DEUX familles acceptées, sinon le refus ment', () => {
    // Un .zip tombe ici parce que `separer` y envoie ce qui n'est ni image
    // ni document ; lui répondre « PNG, JPEG, GIF, WebP » lui cache que
    // .pdf et .docx passent.
    const { refus } = trier([fichier('archive.zip', 'application/zip', 100)], 0);
    expect(refus[0].raison).toContain('.pdf');
    expect(refus[0].raison).toContain('PNG');
  });

  it("refuse un SVG : c'est du script, pas une image que le modèle regarde", () => {
    const { refus } = trier([fichier('logo.svg', 'image/svg+xml', 500)], 0);
    expect(refus).toHaveLength(1);
  });

  it('refuse ce qui dépasse quatre mégaoctets, avec le poids dans la phrase', () => {
    const { acceptees, refus } = trier(
      [fichier('photo.jpg', 'image/jpeg', TAILLE_MAX + 1)],
      0,
    );
    expect(acceptees).toEqual([]);
    expect(refus[0].raison).toMatch(/Trop lourde : 4 Mo/);
  });

  it(`s'arrête à ${NOMBRE_MAX} images`, () => {
    const entrants = Array.from({ length: NOMBRE_MAX + 2 }, (_, i) =>
      fichier(`i${i}.png`, 'image/png', 100),
    );
    const { acceptees, refus } = trier(entrants, 0);
    expect(acceptees).toHaveLength(NOMBRE_MAX);
    expect(refus).toHaveLength(2);
    expect(refus[0].raison).toContain(`Maximum ${NOMBRE_MAX}`);
  });

  it('tient compte de celles qui sont déjà jointes', () => {
    const { acceptees, refus } = trier([fichier('a.png', 'image/png', 10)], NOMBRE_MAX);
    expect(acceptees).toEqual([]);
    expect(refus).toHaveLength(1);
  });

  it('accepte les bonnes et refuse les mauvaises du même lot', () => {
    const { acceptees, refus } = trier(
      [
        fichier('ok.png', 'image/png', 10),
        fichier('trop.png', 'image/png', TAILLE_MAX + 1),
        fichier('aussi-ok.jpg', 'image/jpeg', 20),
      ],
      0,
    );
    expect(acceptees.map((f) => f.name)).toEqual(['ok.png', 'aussi-ok.jpg']);
    expect(refus.map((r) => r.fichier)).toEqual(['trop.png']);
  });
});

describe('imagesDeLEvenement', () => {
  const faux = (items: unknown[], files: unknown[]) =>
    ({ items, files } as unknown as DataTransfer);

  it("prend les images collées, qui arrivent dans `items` sans nom de fichier", () => {
    const capture = fichier('image.png', 'image/png', 1234);
    const dt = faux([{ kind: 'file', getAsFile: () => capture }], []);
    expect(imagesDeLEvenement(dt)).toEqual([capture]);
  });

  it('ignore le texte collé à côté de l’image', () => {
    const capture = fichier('image.png', 'image/png', 10);
    const dt = faux(
      [
        { kind: 'string', getAsFile: () => null },
        { kind: 'file', getAsFile: () => capture },
      ],
      [],
    );
    expect(imagesDeLEvenement(dt)).toEqual([capture]);
  });

  it('prend les fichiers déposés quand `items` est vide', () => {
    const photo = fichier('photo.jpg', 'image/jpeg', 99);
    expect(imagesDeLEvenement(faux([], [photo]))).toEqual([photo]);
  });

  it('écarte un fichier déposé qui n’est pas une image', () => {
    expect(imagesDeLEvenement(faux([], [fichier('notes.txt', 'text/plain', 5)]))).toEqual([]);
  });

  it('ne casse pas sur un événement sans données', () => {
    expect(imagesDeLEvenement(null)).toEqual([]);
  });
});

describe('pourLeFil', () => {
  it("rend undefined sans image : un champ vide sur chaque message coûterait pour rien", () => {
    expect(pourLeFil([])).toBeUndefined();
  });

  it("garde l'en-tête data:, que le serveur retire lui-même", () => {
    const p = [{ id: '1', nom: 'a.png', donnees: 'data:image/png;base64,AAA', octets: 3 }];
    expect(pourLeFil(p)).toEqual(['data:image/png;base64,AAA']);
  });
});

describe('resume', () => {
  it('ne dit rien quand il n’y a rien', () => {
    expect(resume([])).toBe('');
  });

  it('accorde le pluriel et pèse en kilo-octets', () => {
    const p = (n: number, o: number) =>
      Array.from({ length: n }, (_, i) => ({ id: `${i}`, nom: 'x', donnees: '', octets: o }));
    expect(resume(p(1, 2048))).toBe('1 image · 2 Ko');
    expect(resume(p(3, 2048))).toBe('3 images · 6 Ko');
  });

  it('passe aux mégaoctets, avec la virgule française', () => {
    const p = [{ id: '1', nom: 'x', donnees: '', octets: 1_572_864 }];
    expect(resume(p)).toBe('1 image · 1,5 Mo');
  });
});

describe('messagesPourLApi', () => {
  const texte = (m: { content: string }) => m.content;

  it("fait voyager les images AVEC leur message, et nulle part ailleurs", () => {
    const sortie = messagesPourLApi(
      [
        { role: 'user', content: 'bonjour' },
        { role: 'assistant', content: 'salut' },
        { role: 'user', content: 'que vois-tu ?', images: ['data:image/png;base64,AAA'] },
      ],
      texte,
    );
    expect(sortie[0]).toEqual({ role: 'user', content: 'bonjour' });
    expect(sortie[1]).toEqual({ role: 'assistant', content: 'salut' });
    expect(sortie[2]).toEqual({
      role: 'user',
      content: 'que vois-tu ?',
      images: ['data:image/png;base64,AAA'],
    });
  });

  it("n'ajoute pas de champ vide à un message de texte", () => {
    const [m] = messagesPourLApi([{ role: 'user', content: 'x', images: [] }], texte);
    expect('images' in m).toBe(false);
  });

  it('laisse le texte être réécrit sans toucher aux images', () => {
    const [m] = messagesPourLApi(
      [{ role: 'assistant', content: 'brut', images: ['data:image/png;base64,B'] }],
      () => 'réécrit',
    );
    expect(m).toEqual({ role: 'assistant', content: 'réécrit', images: ['data:image/png;base64,B'] });
  });

  it("garde les sept images d'un même message", () => {
    const images = Array.from({ length: 7 }, (_, i) => `data:image/png;base64,${i}`);
    const [m] = messagesPourLApi([{ role: 'user', content: 'planche', images }], texte);
    expect(m.images).toHaveLength(7);
  });
});

describe('les documents', () => {
  const doc = (nom: string, type = '', octets = 1000) => fichier(nom, type, octets);

  it('reconnaît un document à son extension, pas à son type MIME', () => {
    // Un .docx glissé depuis le Finder arrive parfois sans type.
    expect(estUnDocument(doc('rapport.docx'))).toBe(true);
    expect(estUnDocument(doc('bail.pdf'))).toBe(true);
    expect(estUnDocument(doc('notes.md'))).toBe(true);
    expect(estUnDocument(doc('photo.png', 'image/png'))).toBe(false);
  });

  it('sépare un lot mêlé : la capture d’un côté, le PDF de l’autre', () => {
    const { images, documents } = separer([
      doc('capture.png', 'image/png'),
      doc('bail.pdf'),
      doc('photo.jpg', 'image/jpeg'),
    ]);
    expect(images.map((f) => f.name)).toEqual(['capture.png', 'photo.jpg']);
    expect(documents.map((f) => f.name)).toEqual(['bail.pdf']);
  });

  it('envoie vers les images ce qui n’est ni l’un ni l’autre, pour qu’il soit refusé avec sa raison', () => {
    const { images, documents } = separer([doc('archive.zip', 'application/zip')]);
    expect(documents).toEqual([]);
    expect(images).toHaveLength(1);
  });

  it(`s'arrête à ${DOCUMENTS_MAX} documents`, () => {
    const { acceptees, refus } = trierDocuments(
      [doc('a.pdf'), doc('b.pdf'), doc('c.pdf')],
      0,
    );
    expect(acceptees).toHaveLength(DOCUMENTS_MAX);
    expect(refus[0].raison).toContain(`Maximum ${DOCUMENTS_MAX}`);
  });

  it('refuse au-delà de dix mégaoctets', () => {
    const { refus } = trierDocuments([doc('these.pdf', '', DOCUMENT_TAILLE_MAX + 1)], 0);
    expect(refus[0].raison).toMatch(/Trop lourd : 10 Mo/);
  });

  it('ne fait voyager que le texte extrait, jamais le fichier', () => {
    const fil = documentsPourLeFil([
      { id: '1', nom: 'bail.pdf', texte: 'Le loyer…', pages: 3, caracteres: 9, tronque: false },
    ]);
    expect(fil).toEqual([{ nom: 'bail.pdf', texte: 'Le loyer…', pages: 3 }]);
  });

  it('fait voyager la coupure, sans quoi le modèle conclurait sur un extrait', () => {
    const fil = documentsPourLeFil([
      { id: '1', nom: 'these.pdf', texte: 'début', pages: 200, caracteres: 5, tronque: true },
    ]);
    expect(fil![0].tronque).toBe(true);
  });

  it('rend undefined sans document', () => {
    expect(documentsPourLeFil([])).toBeUndefined();
  });

  it('dit la coupure à l’usager AVANT qu’il pose sa question', () => {
    const coupe = { id: '1', nom: 't.pdf', texte: 'x', pages: 200, caracteres: 1, tronque: true };
    expect(resumeDocument(coupe)).toBe('t.pdf · 200 pages · extrait seulement');
    expect(resumeDocument({ ...coupe, tronque: false })).toBe('t.pdf · 200 pages');
  });

  it('compte les caractères quand il n’y a pas de pages', () => {
    const d = { id: '1', nom: 'n.docx', texte: 'x', caracteres: 3200, tronque: false };
    expect(resumeDocument(d)).toMatch(/n\.docx · 3\s?200 caractères/);
  });
});

describe('messagesPourLApi, avec documents', () => {
  it('fait voyager les documents avec leur message', () => {
    const [m] = messagesPourLApi(
      [{ role: 'user', content: 'Combien ?', documents: [{ nom: 'f.pdf', texte: '42 $' }] }],
      (x) => x.content,
    );
    expect(m.documents).toEqual([{ nom: 'f.pdf', texte: '42 $' }]);
  });

  it("n'ajoute pas de champ vide", () => {
    const [m] = messagesPourLApi([{ role: 'user', content: 'x', documents: [] }], (x) => x.content);
    expect('documents' in m).toBe(false);
  });
});
