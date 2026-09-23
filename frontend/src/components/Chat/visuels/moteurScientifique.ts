import { apiFetch } from '../../../lib/api';
import type { FigureScientifique } from './figureScientifique';
import { nettoyerSvg, type PaletteVisuel } from './svgSur';

function hex(couleur: string): string {
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d'); if (!ctx) throw new Error('canvas');
  ctx.fillStyle = couleur; ctx.fillRect(0, 0, 1, 1);
  return '#' + [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3).map(n => n.toString(16).padStart(2, '0')).join('');
}
export async function dessinerScientifique(figure: FigureScientifique, palette: PaletteVisuel, locale: string, signal: AbortSignal) {
  const controle = new AbortController();
  const annuler = () => controle.abort(); signal.addEventListener('abort', annuler, { once: true });
  if (signal.aborted) controle.abort();
  // Le premier rendu construit parfois le cache des polices (~10 s ici).
  // 30 s laisse cette marge sans garder une attente infinie si le serveur meurt.
  const delai = setTimeout(annuler, 30_000);
  try {
    const reponse = await apiFetch('/v1/visuals/matplotlib', { method: 'POST', signal: controle.signal,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ figure, locale: locale.startsWith('fr') ? 'fr' : 'en',
        palette: { background: hex(palette.fond), text: hex(palette.texte), accent: hex(palette.accent), border: hex(palette.bord), mono: palette.police === 'monospace' } }),
    });
    if (!reponse.ok) throw new Error('figure');
    const { svg } = await reponse.json();
    return nettoyerSvg(svg, palette, true);
  } finally { clearTimeout(delai); signal.removeEventListener('abort', annuler); }
}
