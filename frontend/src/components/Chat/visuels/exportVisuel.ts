import { apiFetch, isTauri } from '../../../lib/api';
import { exporterSuccesFichier, updateSuccesNote } from '../../../features/succes/api';
import { octetsEnBase64 } from '../../../features/succes/pdfPhotos';
import { urlSvg, type PaletteVisuel, type SvgPret } from './svgSur';

/** Copier les styles calculés de Recharts/Mermaid en attributs SVG : le
 * fichier doit rester lisible hors de Diapason et de ses feuilles CSS. */
export function svgDuGraphique(element: SVGSVGElement, palette: PaletteVisuel, titre = '', origine = ''): SvgPret {
  const copie = element.cloneNode(true) as SVGSVGElement;
  const originaux = [element, ...element.querySelectorAll('*')];
  const copies = [copie, ...copie.querySelectorAll('*')];
  originaux.forEach((el, i) => {
    const style = getComputedStyle(el);
    for (const propriete of ['fill', 'stroke', 'stroke-width', 'font-size', 'font-family', 'font-weight', 'text-anchor', 'opacity']) {
      copies[i].setAttribute(propriete, style.getPropertyValue(propriete));
    }
    copies[i].removeAttribute('style'); copies[i].removeAttribute('tabindex');
  });
  const width = element.viewBox.baseVal.width || element.getBoundingClientRect().width;
  const height = element.viewBox.baseVal.height || element.getBoundingClientRect().height;
  copie.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  copie.setAttribute('viewBox', `0 0 ${width} ${height}`);
  copie.setAttribute('width', String(width)); copie.setAttribute('height', String(height));
  copie.setAttribute('color', palette.texte);
  copie.querySelectorAll('.recharts-tooltip-cursor').forEach(el => el.remove());
  const espace = 'http://www.w3.org/2000/svg';
  const sortie = document.createElementNS(espace, 'svg');
  sortie.setAttribute('xmlns', espace);
  const ajouterTexte = (texte: string, y: number, couleur: string, taille = 12) => {
    const t = document.createElementNS(espace, 'text');
    t.setAttribute('x', '14'); t.setAttribute('y', String(y));
    t.setAttribute('fill', couleur); t.setAttribute('font-size', String(taille));
    t.textContent = texte; sortie.append(t);
  };
  // La légende Recharts est en HTML, hors du SVG ; sans cette copie, un
  // export multi-séries perd le sens de ses couleurs (23/09/2026).
  const legendes = Array.from(element.parentElement?.querySelectorAll('.recharts-legend-item-text') ?? []);
  const longueur = Math.max(12, Math.floor((width - 28) / 7.5));
  const lignes = (texte: string) => texte.match(new RegExp(`.{1,${longueur}}`, 'gu')) ?? [];
  const titreLignes = lignes(titre);
  const haut = 18 + titreLignes.length * 20;
  const groupe = document.createElementNS(espace, 'g');
  groupe.setAttribute('transform', `translate(0 ${haut})`);
  groupe.append(...Array.from(copie.childNodes)); sortie.append(groupe);
  titreLignes.forEach((t, i) => ajouterTexte(t, 20 + i * 20, palette.texte, 15));
  let bas = haut + height + 16;
  for (const legende of legendes) for (const ligne of lignes(legende.textContent || '')) {
    ajouterTexte(ligne, bas, getComputedStyle(legende).color); bas += 18;
  }
  for (const ligne of lignes(origine)) { ajouterTexte(ligne, bas, palette.secondaire); bas += 18; }
  const hauteur = bas + 12;
  const fond = document.createElementNS(espace, 'rect');
  fond.setAttribute('width', String(width)); fond.setAttribute('height', String(hauteur)); fond.setAttribute('fill', palette.fond);
  sortie.prepend(fond);
  sortie.setAttribute('viewBox', `0 0 ${width} ${hauteur}`);
  sortie.setAttribute('width', String(width)); sortie.setAttribute('height', String(hauteur));
  sortie.setAttribute('font-family', palette.police);
  return { svg: new XMLSerializer().serializeToString(sortie), width, height: hauteur, title: titre };
}

export async function pngDuVisuel(rendu: SvgPret, fond: string): Promise<Blob> {
  const image = new Image();
  await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error('export')); image.src = rendu.png || urlSvg(rendu.svg); });
  const facteur = Math.min(2, 2400 / Math.max(rendu.width, rendu.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(rendu.width * facteur)); canvas.height = Math.max(1, Math.round(rendu.height * facteur));
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('export');
  ctx.fillStyle = fond; ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => canvas.toBlob(b => b ? resolve(b) : reject(new Error('export')), 'image/png'));
}

export async function enregistrerVisuel(rendu: SvgPret, format: 'svg' | 'png' | 'pdf', titre: string, fond: string, mono = false) {
  if (format === 'svg' && rendu.png) throw new Error('raster');
  const blob = format === 'pdf' ? await (await import('./pdfVisuel')).pdfDuVisuel(rendu, mono)
    : format === 'png' ? await pngDuVisuel(rendu, fond) : new Blob([rendu.svg], { type: 'image/svg+xml' });
  const nom = `${titre.replace(/[^\p{L}\p{N} _-]/gu, '').trim().slice(0, 80) || 'Diapason'}.${format}`;
  if (isTauri()) {
    const { save } = await import('@tauri-apps/plugin-dialog');
    const path = await save({ defaultPath: nom, filters: [{ name: format.toUpperCase(), extensions: [format] }] });
    if (!path) return false;
    await exporterSuccesFichier(path, octetsEnBase64(new Uint8Array(await blob.arrayBuffer())));
  } else {
    const url = URL.createObjectURL(blob); const a = document.createElement('a');
    a.href = url; a.download = nom; document.body.appendChild(a); a.click(); a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }
  return true;
}

export async function ajouterVisuelDansNote(id: string, rendu: SvgPret, fond: string, titre: string) {
  const blob = await pngDuVisuel(rendu, fond);
  const base64 = octetsEnBase64(new Uint8Array(await blob.arrayBuffer()));
  const alt = titre.replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const content = `<p><img src="data:image/png;base64,${base64}" alt="${alt}"></p>`;
  if (new TextEncoder().encode(content).length > 1_000_000) throw new Error('noteFull');
  await updateSuccesNote(id, { appendContent: content, opId: crypto.randomUUID() });
}

export async function ouvrirDansInkscape(rendu: SvgPret): Promise<boolean> {
  if (rendu.png) throw new Error('raster');
  const etat = await apiFetch('/v1/visuals/inkscape');
  if (!etat.ok) throw new Error('inkscape');
  if (!(await etat.json()).available) return false;
  const reponse = await apiFetch('/v1/visuals/inkscape', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ svg: rendu.svg }) });
  if (!reponse.ok || (await reponse.json()).status !== 'openingRequested') throw new Error('inkscape');
  return true;
}
