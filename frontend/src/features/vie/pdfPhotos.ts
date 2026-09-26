// Un PDF de photos, écrit à la main — une page par photo, sa légende dessous.
//
// Aucune bibliothèque : le dépôt n'en a pas pour ça, et un PDF fait d'images
// JPEG tient en une centaine de lignes. Les JPEG entrent tels quels
// (`/DCTDecode`), donc le fichier pèse le poids des images, pas plus.
// Les légendes sont en Helvetica avec l'encodage WinAnsi : les accents du
// français y sont ; ce qui n'y est pas (emoji) devient « ? ».
//
// Pur : rend des octets à partir d'octets. Testable sous node.

export interface PagePhoto {
  /** Les octets JPEG de l'image. */
  jpeg: Uint8Array;
  largeur: number;
  hauteur: number;
  legende: string;
}

/** A4 en points PDF (1/72 de pouce). */
const A4 = { largeur: 595.28, hauteur: 841.89 };
const MARGE = 36;
const HAUTEUR_LEGENDE = 40;
const TAILLE_TEXTE = 11;

const encodeur = new TextEncoder();

/** Une chaîne PDF entre parenthèses, en WinAnsi, échappée. */
export function chainePdf(texte: string): string {
  let sortie = '';
  for (const caractere of texte) {
    const code = caractere.codePointAt(0) ?? 63;
    let octet: number;
    if (code < 128) octet = code;
    else if (code >= 160 && code <= 255) octet = code;
    else octet = 63;
    if (octet === 0x28 || octet === 0x29 || octet === 0x5c) sortie += `\\${String.fromCharCode(octet)}`;
    else if (octet < 32 || octet > 126) sortie += `\\${octet.toString(8).padStart(3, '0')}`;
    else sortie += String.fromCharCode(octet);
  }
  return `(${sortie})`;
}

/** Le rectangle où l'image tient dans la page, centré, marge et légende comprises. */
export function cadreImage(
  largeur: number,
  hauteur: number,
  page: { largeur: number; hauteur: number } = A4,
): { x: number; y: number; w: number; h: number } {
  const zoneL = page.largeur - MARGE * 2;
  const zoneH = page.hauteur - MARGE * 2 - HAUTEUR_LEGENDE;
  const facteur = Math.min(zoneL / Math.max(1, largeur), zoneH / Math.max(1, hauteur));
  const w = largeur * facteur;
  const h = hauteur * facteur;
  return {
    x: MARGE + (zoneL - w) / 2,
    // L'origine PDF est en bas à gauche ; la légende prend le bas.
    y: MARGE + HAUTEUR_LEGENDE + (zoneH - h) / 2,
    w,
    h,
  };
}

/** Une page en paysage si l'image est plus large que haute. */
export function orientationPour(largeur: number, hauteur: number): { largeur: number; hauteur: number } {
  return largeur > hauteur ? { largeur: A4.hauteur, hauteur: A4.largeur } : A4;
}

/**
 * Le PDF complet. Objets : 1 catalogue, 2 pages, 3 police, puis par photo :
 * page, contenu, image.
 */
export function construirePdf(pages: PagePhoto[], titre = 'Photos'): Uint8Array {
  const morceaux: Uint8Array[] = [];
  const offsets: number[] = [];
  let position = 0;
  const pousser = (data: Uint8Array | string) => {
    const octets = typeof data === 'string' ? encodeur.encode(data) : data;
    morceaux.push(octets);
    position += octets.length;
  };
  const objet = (numero: number, corps: string, flux?: Uint8Array) => {
    offsets[numero] = position;
    pousser(`${numero} 0 obj\n${corps}\n`);
    if (flux) {
      pousser('stream\n');
      pousser(flux);
      pousser('\nendstream\n');
    }
    pousser('endobj\n');
  };

  pousser('%PDF-1.4\n%âãÏÓ\n');
  const total = pages.length;
  const idsPages = pages.map((_, i) => 4 + i * 3);
  objet(1, '<< /Type /Catalog /Pages 2 0 R >>');
  objet(2, `<< /Type /Pages /Kids [${idsPages.map((id) => `${id} 0 R`).join(' ')}] /Count ${total} >>`);
  objet(3, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>');

  pages.forEach((page, i) => {
    const idPage = 4 + i * 3;
    const idContenu = idPage + 1;
    const idImage = idPage + 2;
    const format = orientationPour(page.largeur, page.hauteur);
    const cadre = cadreImage(page.largeur, page.hauteur, format);
    const legende = page.legende.trim();
    const numero = `${i + 1} / ${total}`;
    const contenu =
      `q ${cadre.w.toFixed(2)} 0 0 ${cadre.h.toFixed(2)} ${cadre.x.toFixed(2)} ${cadre.y.toFixed(2)} cm /Im${i} Do Q\n` +
      `BT /F1 ${TAILLE_TEXTE} Tf ${MARGE} ${MARGE + 14} Td ${chainePdf(legende)} Tj ET\n` +
      `BT /F1 9 Tf ${(format.largeur - MARGE - 40).toFixed(2)} ${MARGE + 14} Td ${chainePdf(numero)} Tj ET\n`;
    const octetsContenu = encodeur.encode(contenu);
    objet(
      idPage,
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${format.largeur} ${format.hauteur}] ` +
        `/Resources << /Font << /F1 3 0 R >> /XObject << /Im${i} ${idImage} 0 R >> >> ` +
        `/Contents ${idContenu} 0 R >>`,
    );
    objet(idContenu, `<< /Length ${octetsContenu.length} >>`, octetsContenu);
    objet(
      idImage,
      `<< /Type /XObject /Subtype /Image /Width ${page.largeur} /Height ${page.hauteur} ` +
        `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${page.jpeg.length} >>`,
      page.jpeg,
    );
  });

  const nombreObjets = 4 + total * 3;
  const debutXref = position;
  let xref = `xref\n0 ${nombreObjets}\n0000000000 65535 f \n`;
  for (let n = 1; n < nombreObjets; n += 1) {
    xref += `${String(offsets[n] ?? 0).padStart(10, '0')} 00000 n \n`;
  }
  pousser(xref);
  pousser(
    `trailer\n<< /Size ${nombreObjets} /Root 1 0 R /Info << /Title ${chainePdf(titre)} /Producer (Diapason) >> >>\n` +
      `startxref\n${debutXref}\n%%EOF\n`,
  );

  const sortie = new Uint8Array(position);
  let curseur = 0;
  for (const m of morceaux) {
    sortie.set(m, curseur);
    curseur += m.length;
  }
  return sortie;
}

/** Les octets → base64, par tranches : `btoa` sur 40 Mo d'un coup fait sauter la pile d'appels. */
export function octetsEnBase64(octets: Uint8Array): string {
  let binaire = '';
  const tranche = 0x8000;
  for (let i = 0; i < octets.length; i += tranche) {
    binaire += String.fromCharCode(...octets.subarray(i, i + tranche));
  }
  return btoa(binaire);
}
