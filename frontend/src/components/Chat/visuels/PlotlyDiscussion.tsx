import { useEffect, useRef, type MutableRefObject } from 'react';
import type PlotlyType from 'plotly.js-cartesian-dist-min';
import { estFigure3D, traces3D, type Figure3D } from './figure3D';
import { tracesPlotly, textePlotly, type FigureScientifique } from './figureScientifique';
import { nettoyerSvg, type PaletteVisuel, type SvgPret } from './svgSur';

export interface CommandesPlotly { exporter: () => Promise<SvgPret>; recentrer: () => void; zoomer: (facteur: number) => void }
export default function PlotlyDiscussion({ figure, palette, origine, commandes, onReady, onError }: {
  figure: FigureScientifique | Figure3D; palette: PaletteVisuel; origine: string;
  commandes: MutableRefObject<CommandesPlotly | null>; onReady: (pret: boolean) => void; onError: () => void;
}) {
  const hote = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const conteneur = hote.current; if (!conteneur) return;
    const el = document.createElement('div'); el.style.height = '100%'; conteneur.append(el);
    let annule = false, timer: ReturnType<typeof setTimeout>;
    onReady(false);
    const axe = { color: palette.texte, gridcolor: palette.bord, zerolinecolor: palette.bord, automargin: true };
    const largeur = el.clientWidth;
    const trois = estFigure3D(figure);
    let Plotly: typeof PlotlyType;
    const cameraInitiale = { eye: { x: 1.25, y: 1.25, z: 1.25 } };
    const layout = { autosize: true, height: conteneur.clientHeight, margin: { l: 48, r: 18, t: 20, b: 75 },
      paper_bgcolor: palette.fond, plot_bgcolor: palette.fond, font: { family: palette.police, color: palette.texte, size: 11 },
      xaxis: { ...axe, title: { text: textePlotly(figure.xLabel) }, nticks: largeur < 400 ? 4 : 7 },
      yaxis: { ...axe, title: { text: textePlotly(figure.yLabel) } },
      legend: { orientation: 'h', y: -.2 }, barmode: 'overlay', dragmode: trois ? 'orbit' : 'zoom', showlegend: true,
      ...(trois ? { scene: { bgcolor: palette.fond, camera: cameraInitiale,
        xaxis: { ...axe, title: { text: textePlotly(figure.xLabel) } },
        yaxis: { ...axe, title: { text: textePlotly(figure.yLabel) } },
        zaxis: { ...axe, title: { text: textePlotly(figure.zLabel) } } } } : {}) };
    const preparation = (async () => {
      Plotly = (await (trois ? import('plotly.js-gl3d-dist-min') : import('plotly.js-cartesian-dist-min'))).default;
      if (annule) return;
      if (trois) {
        const test = document.createElement('canvas');
        const gl = test.getContext('webgl2') || test.getContext('webgl');
        if (!gl) throw new Error('webgl');
        gl.getExtension('WEBGL_lose_context')?.loseContext();
      }
      return Plotly.newPlot(el, trois ? traces3D(figure, palette) : tracesPlotly(figure, palette), layout,
        { displayModeBar: false, scrollZoom: false, responsive: false, displaylogo: false, doubleClick: 'reset' });
    })();
    void preparation.then(() => {
      if (annule) return;
      commandes.current = {
        recentrer: () => { void Plotly.relayout(el, trois ? { 'scene.camera': cameraInitiale } : { 'xaxis.autorange': true, 'yaxis.autorange': true }).catch(onError); },
        zoomer: facteur => {
          if (trois) {
            const eye = (el as HTMLElement & { _fullLayout?: { scene?: { camera?: { eye?: { x: number; y: number; z: number } } } } })._fullLayout?.scene?.camera?.eye || cameraInitiale.eye;
            const norme = Math.hypot(eye.x, eye.y, eye.z);
            const rapport = Math.max(.2, Math.min(20, norme / facteur)) / (norme || 1);
            void Plotly.relayout(el, { 'scene.camera.eye': { x: eye.x * rapport, y: eye.y * rapport, z: eye.z * rapport } }).catch(onError);
            return;
          }
          const axes = (el as HTMLElement & { _fullLayout?: Record<string, { range?: number[] }> })._fullLayout;
          const ajustement: Record<string, unknown> = {};
          for (const nom of ['xaxis', 'yaxis']) {
            const plage = axes?.[nom]?.range; if (!plage) continue;
            const centre = (plage[0] + plage[1]) / 2, demi = (plage[1] - plage[0]) / 2 / facteur;
            ajustement[`${nom}.range`] = [centre - demi, centre + demi]; ajustement[`${nom}.autorange`] = false;
          }
          void Plotly.relayout(el, ajustement).catch(onError);
        },
        exporter: async () => {
          if (trois) {
            const png = await Plotly.toImage(el, { format: 'png', width: 900, height: 540 });
            const img = new Image();
            await new Promise<void>((resolve, reject) => { img.onload = () => resolve(); img.onerror = reject; img.src = png; });
            const canvas = document.createElement('canvas'); canvas.width = 900; canvas.height = 720;
            const ctx = canvas.getContext('2d'); if (!ctx) throw new Error('export');
            ctx.fillStyle = palette.fond; ctx.fillRect(0, 0, 900, 720); ctx.fillStyle = palette.texte;
            ctx.font = `16px ${palette.police}`;
            (figure.title.match(/.{1,80}/gu) ?? []).forEach((ligne, i) => ctx.fillText(ligne, 22, 24 + i * 20));
            ctx.drawImage(img, 0, 75); ctx.font = `11px ${palette.police}`;
            (origine.match(/.{1,120}/gu) ?? []).forEach((ligne, i) => ctx.fillText(ligne, 22, 640 + i * 14));
            return { svg: '', png: canvas.toDataURL('image/png'), width: 900, height: 720, title: figure.title };
          }
          const url = await Plotly.toImage(el, { format: 'svg', width: 900, height: 540 });
          const svg = new DOMParser().parseFromString(decodeURIComponent(url.slice(url.indexOf(',') + 1)), 'image/svg+xml').documentElement;
          // L'export garde la plage affichée et ajoute titre/origine hors des
          // axes : leur présence dans le chrome HTML ne les exportait pas.
          const ns = 'http://www.w3.org/2000/svg';
          const racine = document.createElementNS(ns, 'svg'); racine.setAttribute('viewBox', '0 0 900 690');
          const fond = document.createElementNS(ns, 'rect'); fond.setAttribute('width', '900'); fond.setAttribute('height', '690'); fond.setAttribute('fill', palette.fond); racine.append(fond);
          const titre = document.createElementNS(ns, 'title'); titre.textContent = figure.title; racine.append(titre);
          const texte = (valeur: string, y: number, taille: number, limite: number) => {
            const lignes = valeur.match(new RegExp(`.{1,${limite}}(?:\\s|$)|.{1,${limite}}`, 'g')) ?? [];
            lignes.forEach((ligne, i) => { const t = document.createElementNS(ns, 'text'); t.setAttribute('x', '22'); t.setAttribute('y', String(y + i * (taille + 3))); t.setAttribute('font-size', String(taille)); t.setAttribute('fill', palette.texte); t.textContent = ligne; racine.append(t); });
          };
          texte(figure.title, 25, 16, 80); svg.setAttribute('y', '65'); racine.append(svg); texte(origine, 630, 10, 140);
          return nettoyerSvg(new XMLSerializer().serializeToString(racine), palette, true);
        },
      };
      onReady(true);
    }).catch(() => { if (!annule) onError(); });
    const observer = new ResizeObserver(() => {
      clearTimeout(timer); timer = setTimeout(() => { if (!annule && commandes.current && conteneur.clientWidth) void Plotly.relayout(el,
        { width: conteneur.clientWidth, height: conteneur.clientHeight, ...(trois ? {} : { 'xaxis.nticks': conteneur.clientWidth < 400 ? 4 : 7 }) }).catch(() => { if (!annule) onError(); }); }, 80);
    });
    observer.observe(conteneur);
    return () => {
      annule = true; clearTimeout(timer); observer.disconnect(); commandes.current = null; el.remove();
      // StrictMode peut démonter avant la fin de newPlot : ne jamais purger
      // pendant son écriture, ni réutiliser le même nœud pour deux rendus.
      void preparation.catch(() => {}).then(() => Plotly?.purge(el));
    };
  }, [figure, palette, origine, commandes, onReady, onError]);
  return <div ref={hote} className="visuel-plotly" role="img" aria-label={figure.title} />;
}
