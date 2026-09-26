import { jsPDF } from 'jspdf';
import 'svg2pdf.js';
import { octetsEnBase64 } from '../../../features/vie/pdfPhotos';
import type { SvgPret } from './svgSur';

const polices = new Map<string, Promise<string>>();
const familleExport = (mono: boolean) => mono ? 'DiapasonVisuelMono' : 'DiapasonVisuelSans';
function chargerPolice(mono: boolean) {
  const nom = mono ? 'DejaVuSansMono' : 'DejaVuSans';
  if (!polices.has(nom)) polices.set(nom, fetch(`/fonts/visuels/${nom}.ttf`).then(async r => {
    if (!r.ok) throw new Error('font');
    const contenu = await r.arrayBuffer();
    // Le 24/09/2026, le PDF utilisait DejaVu mais svg2pdf mesurait une police
    // de repli : chaque texte centré glissait vers la droite. Charger la
    // même police pour mesurer dans le navigateur et pour écrire le PDF.
    document.fonts.add(await new FontFace(familleExport(mono), contenu).load());
    return octetsEnBase64(new Uint8Array(contenu));
  }).catch(e => { polices.delete(nom); throw e; }));
  return polices.get(nom)!;
}
export async function pdfDuVisuel(rendu: SvgPret, mono: boolean): Promise<Blob> {
  const largeur = 842, marge = 24, hauteur = Math.max(160, Math.min(2400, rendu.height / rendu.width * (largeur - marge * 2) + marge * 2));
  const doc = new jsPDF({ orientation: largeur > hauteur ? 'landscape' : 'portrait', unit: 'pt', format: [largeur, hauteur], compress: true });
  doc.setProperties({ title: rendu.title, creator: 'Diapason' });
  if (rendu.png) {
    const facteur = Math.min((largeur - 2 * marge) / rendu.width, (hauteur - 2 * marge) / rendu.height);
    doc.addImage(rendu.png, 'PNG', marge, marge, rendu.width * facteur, rendu.height * facteur);
    return doc.output('blob');
  }
  const police = await chargerPolice(mono);
  const famille = familleExport(mono);
  doc.addFileToVFS('Diapason.ttf', police);
  doc.addFont('Diapason.ttf', famille, 'normal');
  const svg = new DOMParser().parseFromString(rendu.svg, 'image/svg+xml').documentElement;
  svg.setAttribute('font-family', famille);
  for (const t of svg.querySelectorAll('text,tspan')) { t.setAttribute('font-family', famille); t.setAttribute('font-weight', 'normal'); }
  const facteur = Math.min((largeur - 2 * marge) / rendu.width, (hauteur - 2 * marge) / rendu.height);
  await doc.svg(svg, { x: marge, y: marge, width: rendu.width * facteur, height: rendu.height * facteur });
  return doc.output('blob');
}
