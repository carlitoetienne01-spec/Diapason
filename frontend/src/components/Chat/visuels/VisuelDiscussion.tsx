import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, useReducedMotion } from 'motion/react';
import { Maximize2, X, MoreHorizontal, RotateCcw, ZoomIn, ZoomOut, ScanLine, Image as ImageIcon } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from '../../../i18n/useTranslation';
import { listSuccesNoteResumes } from '../../../features/succes/api';
import type { SuccesNoteResume } from '../../../features/succes/types';
import { lireGraphique, type GenreVisuel, type Graphique } from './formatVisuel';
import { nettoyerSvg, urlSvg, type PaletteVisuel, type SvgPret } from './svgSur';
import { dessinerMermaid } from './moteurMermaid';
import { lireFigure3D, type Figure3D } from './figure3D';
import { lireFigureScientifique, type FigureScientifique } from './figureScientifique';
import { dessinerScientifique } from './moteurScientifique';
import type { CommandesPlotly } from './PlotlyDiscussion';
import { ajouterVisuelDansNote, enregistrerVisuel, ouvrirDansInkscape, svgDuGraphique } from './exportVisuel';
import { libellesVisuel } from './libelles';
import './VisuelDiscussion.css';

const chargerGraphiques = () => import('./GraphiqueDiscussion');
const GraphiqueDiscussion = lazy(chargerGraphiques);
const chargerPlotly = () => import('./PlotlyDiscussion');
const PlotlyDiscussion = lazy(chargerPlotly);

function paletteCourante(): PaletteVisuel {
  const style = getComputedStyle(document.documentElement);
  const couleur = (cle: string, repli: string) => style.getPropertyValue(cle).trim() || repli;
  return { fond: couleur('--color-bg-secondary', '#ffffff'), texte: couleur('--color-text', '#222222'),
    accent: couleur('--color-accent', '#4477aa'), bord: couleur('--color-border', '#888888'),
    secondaire: couleur('--color-text-secondary', '#666666'), police: document.documentElement.classList.contains('terminal') ? 'monospace' : style.fontFamily || 'sans-serif' };
}

export default function VisuelDiscussion({ genre, source, complet, enDirect }: {
  genre: GenreVisuel; source: string; complet: boolean; enDirect: boolean;
}) {
  const { locale } = useTranslation(); const l = libellesVisuel(locale);
  const [palette, setPalette] = useState(paletteCourante);
  const [actif, setActif] = useState(false);
  const cadre = useRef<HTMLElement>(null); const zone = useRef<HTMLDivElement>(null);
  const dessin = useRef<HTMLDivElement>(null); const dialogue = useRef<HTMLDialogElement>(null);
  const boutonPlein = useRef<HTMLButtonElement>(null);
  const [rendu, setRendu] = useState<SvgPret | null>(null);
  const [graphique, setGraphique] = useState<Graphique | null>(null);
  const [figure, setFigure] = useState<FigureScientifique | Figure3D | null>(null);
  const commandesPlotly = useRef<CommandesPlotly | null>(null);
  const [plotlyPret, setPlotlyPret] = useState(false);
  const erreurPlotly = useCallback(() => { setErreur(true); setFigure(null); setPlotlyPret(false); }, []);
  const est3D = genre === 'diapason-plotly3d';
  const estPlotly = genre === 'diapason-plotly' || est3D;
  const [erreur, setErreur] = useState(false); const [zoom, setZoom] = useState(1);
  const [plein, setPlein] = useState(false); const [menu, setMenu] = useState(false);
  const [code, setCode] = useState(false); const [donnees, setDonnees] = useState(false);
  const [rejeu, setRejeu] = useState(0); const [occupe, setOccupe] = useState(false);
  const [tentative, setTentative] = useState(0);
  const [notes, setNotes] = useState<SuccesNoteResume[] | null>(null);
  const reduireMouvement = useReducedMotion();
  const animerAuDepart = useRef(enDirect);
  const animationVue = useRef({ source: '', rejeu: 0 });
  const doitAnimer = !reduireMouvement && ((animerAuDepart.current && animationVue.current.source !== source) || animationVue.current.rejeu < rejeu);
  const affichable = !!rendu || !!graphique || estPlotly && !!figure;
  const pret = affichable && (!estPlotly || plotlyPret);
  const titre = graphique?.title || figure?.title || rendu?.title || l[genre];
  const valeurs = graphique || figure;
  const origine = `${valeurs?.sample ? l.sample + ' · ' : ''}${valeurs?.source ? l.source + ' : ' + valeurs.source : l.noSource}`;
  const url = useMemo(() => rendu ? urlSvg(rendu.svg) : '', [rendu]);

  useEffect(() => {
    const observer = new MutationObserver(() => {
      const prochaine = paletteCourante();
      // Le thème anime aussi des variables de position sur <html>. Cela
      // n'est pas un changement de palette : ne pas redessiner le schéma.
      setPalette(ancienne => JSON.stringify(ancienne) === JSON.stringify(prochaine) ? ancienne : prochaine);
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style', 'data-terminal-skin'] });
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const el = cadre.current; if (!el) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) { setActif(true); observer.disconnect(); }
    }, { rootMargin: '300px' });
    observer.observe(el); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!actif) return;
    if (!complet) { setRendu(null); setGraphique(null); setFigure(null); setErreur(false); return; }
    let annule = false;
    const controle = new AbortController();
    setErreur(false); setRendu(null); setGraphique(null); setFigure(null); setPlotlyPret(false);
    const generer = async () => {
      try {
        if (genre === 'diapason-matplotlib' || estPlotly) {
          const f = est3D ? lireFigure3D(source) : lireFigureScientifique(source, estPlotly);
          if (estPlotly) {
            await chargerPlotly();
          } else {
            const r = await dessinerScientifique(f as FigureScientifique, palette, locale, controle.signal);
            if (!annule) setRendu(r);
          }
          if (!annule) setFigure(f);
        } else if (genre === 'diapason-chart') {
          const g = lireGraphique(source);
          await chargerGraphiques();
          if (!annule) setGraphique(g);
        } else {
          const r = genre === 'svg' ? nettoyerSvg(source, palette) : await dessinerMermaid(source, palette);
          if (!annule) setRendu(r);
        }
      } catch { if (!annule) setErreur(true); }
    };
    void generer(); return () => { annule = true; controle.abort(); };
  }, [actif, complet, genre, source, palette, locale, tentative, estPlotly, est3D]);
  useEffect(() => {
    if (plein) dialogue.current?.showModal();
    else if (dialogue.current?.open) dialogue.current.close();
  }, [plein]);
  useEffect(() => {
    if (!menu) return;
    const fermer = (e: PointerEvent) => { if (!cadre.current?.contains(e.target as Node) && !dialogue.current?.contains(e.target as Node)) setMenu(false); };
    const clavier = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(false); };
    document.addEventListener('pointerdown', fermer); document.addEventListener('keydown', clavier);
    return () => { document.removeEventListener('pointerdown', fermer); document.removeEventListener('keydown', clavier); };
  }, [menu]);

  const recentrer = () => { setZoom(1); zone.current?.scrollTo({ left: 0, top: 0 }); commandesPlotly.current?.recentrer(); };
  const obtenir = async () => {
    if (estPlotly && commandesPlotly.current) return commandesPlotly.current.exporter();
    if (rendu) return rendu;
    const svg = dessin.current?.querySelector<SVGSVGElement>('.recharts-wrapper > svg.recharts-surface');
    if (!svg) throw new Error('export');
    return svgDuGraphique(svg, palette, titre, `${graphique?.sample ? l.sample + ' · ' : ''}${graphique?.source ? l.source + ' : ' + graphique.source : l.noSource}`);
  };
  const action = async (faire: () => Promise<void>, erreurOperation = l.operationError) => {
    setOccupe(true);
    try { await faire(); } catch (e) { toast.error(e instanceof Error && e.message === 'noteFull' ? l.noteFull : erreurOperation); }
    finally { setOccupe(false); }
  };
  const exporter = (format: 'svg' | 'png' | 'pdf') => action(async () => {
    if (await enregistrerVisuel(await obtenir(), format, titre, palette.fond, palette.police === 'monospace')) toast.success(l.saved);
  }, l.exportError);
  const choisirNote = () => action(async () => { setNotes(await listSuccesNoteResumes()); setMenu(false); });
  const ajouter = (id: string) => action(async () => {
    await ajouterVisuelDansNote(id, await obtenir(), palette.fond, titre); setNotes(null); toast.success(l.noteDone);
  });
  const glisser = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const contenu = <>
    <header className="visuel-entete">
      <ImageIcon size={16} aria-hidden="true" /><span className="visuel-titre">{titre}</span>
      <div className="visuel-outils" aria-label={l.more}>
        <button disabled={!pret} title={l.zoomOut} aria-label={l.zoomOut} onClick={() => estPlotly ? commandesPlotly.current?.zoomer(.8) : setZoom(z => Math.max(1, z - .25))}><ZoomOut size={16} /></button>
        <button disabled={!pret} title={l.zoomIn} aria-label={l.zoomIn} onClick={() => estPlotly ? commandesPlotly.current?.zoomer(1.25) : setZoom(z => Math.min(4, z + .25))}><ZoomIn size={16} /></button>
        <button disabled={!pret} title={l.reset} aria-label={l.reset} onClick={recentrer}><ScanLine size={16} /></button>
        {plein ? <button title={l.close} aria-label={l.close} onClick={() => setPlein(false)}><X size={16} /></button>
          : <button ref={boutonPlein} disabled={!pret} title={l.full} aria-label={l.full} onClick={() => { setPlein(true); setMenu(false); }}><Maximize2 size={16} /></button>}
        <button title={l.more} aria-label={l.more} aria-expanded={menu} onClick={() => setMenu(!menu)}><MoreHorizontal size={18} /></button>
      </div>
    </header>
    {menu && <div className="visuel-options visuel-secondaire">
      <button disabled={!pret || occupe} onClick={() => { setRejeu(n => n + 1); setMenu(false); }}><RotateCcw size={14} />{l.replay}</button>
      {!est3D && <button disabled={!pret || occupe} onClick={() => void exporter('svg')}>{l.svgExport}</button>}
      <button disabled={!pret || occupe} onClick={() => void exporter('png')}>{l.pngExport}</button>
      <button disabled={!pret || occupe} onClick={() => void exporter('pdf')}>{l.pdfExport}</button>
      {!est3D && <button disabled={!pret || occupe} onClick={() => void action(async () => {
        if (await ouvrirDansInkscape(await obtenir())) toast.success(l.inkscapeStarted); else toast.info(l.inkscapeMissing);
      })}>{l.inkscape}</button>}
      <button disabled={!pret || occupe} onClick={() => void choisirNote()}>{l.note}</button>
      <button onClick={() => { setCode(!code); setMenu(false); }}>{code ? l.hideCode : l.code}</button>
      {valeurs && <button onClick={() => { setDonnees(!donnees); setMenu(false); }}>{donnees ? l.hideData : l.data}</button>}
    </div>}
    {notes && <div className="visuel-notes visuel-secondaire" aria-label={l.chooseNote}>
      <div>{l.chooseNote}<button aria-label={l.close} onClick={() => setNotes(null)}><X size={14} /></button></div>
      {notes.length ? notes.map(n => <button key={n.id} disabled={occupe} onClick={() => void ajouter(n.id)}>{n.title}</button>) : <p>{l.noNotes}</p>}
    </div>}
    {!pret && <div className="visuel-statut" role="status">{erreur ? l.error : !complet && !enDirect ? l.incomplete : l.waiting}
      {erreur && <button onClick={() => setTentative(n => n + 1)}>{l.retry}</button>}
      {(erreur || !enDirect && !complet) && <button onClick={() => setCode(!code)}>{l.code}</button>}</div>}
    {affichable && <div ref={zone} className="visuel-fenetre" tabIndex={0} aria-label={titre} data-zoom={zoom > 1}
      onPointerDown={e => {
        if (zoom <= 1 || e.button !== 0 || (e.target as Element).closest('button')) return;
        glisser.current = { x: e.clientX, y: e.clientY, left: e.currentTarget.scrollLeft, top: e.currentTarget.scrollTop };
        e.currentTarget.setPointerCapture(e.pointerId);
      }} onPointerMove={e => {
        const g = glisser.current; if (g) { e.currentTarget.scrollLeft = g.left - e.clientX + g.x; e.currentTarget.scrollTop = g.top - e.clientY + g.y; }
      }} onPointerUp={() => { glisser.current = null; }} onPointerCancel={() => { glisser.current = null; }}>
      <div className="visuel-plan" style={{ width: `${zoom * 100}%`, background: palette.fond }}>
        <motion.div ref={dessin} key={rejeu} className="visuel-dessin"
          initial={doitAnimer ? { clipPath: 'inset(0 100% 0 0)' } : false}
          onAnimationComplete={() => { if (pret) animationVue.current = { source, rejeu }; }}
          animate={{ clipPath: pret ? 'inset(0 0% 0 0)' : 'inset(0 100% 0 0)' }} transition={{ duration: doitAnimer ? 1.1 : 0, ease: 'easeInOut' }}>
          {rendu ? <img src={url} alt={titre} width={rendu.width} height={rendu.height} style={{ maxWidth: `calc((var(--visuel-hauteur) - 2rem) * ${rendu.width / rendu.height} * ${zoom})`, marginInline: 'auto' }} draggable={false} onError={() => { setRendu(null); setErreur(true); }} />
            : estPlotly && figure ? <Suspense fallback={<p>{l.waiting}</p>}><PlotlyDiscussion figure={figure} palette={palette} origine={origine} commandes={commandesPlotly} onReady={setPlotlyPret} onError={erreurPlotly} /></Suspense>
            : graphique && <Suspense fallback={<p>{l.waiting}</p>}><GraphiqueDiscussion graphique={graphique} palette={palette} /></Suspense>}
        </motion.div>
        {doitAnimer && pret && <motion.i key={`laser-${rejeu}`} aria-hidden="true" className="visuel-laser"
          initial={{ left: '0%', opacity: 0 }} animate={{ left: ['0%', '100%'], opacity: [0, 1, 1, 0] }} transition={{ duration: 1.1 }} />}
      </div>
    </div>}
    {valeurs && <p className="visuel-provenance">{origine}{estPlotly && <><br />{est3D ? l.interactive3D : l.interactive}</>}</p>}
    {donnees && figure && <div className="visuel-code visuel-secondaire"><pre>{JSON.stringify(figure, null, 2)}</pre></div>}
    {donnees && graphique && <div className="visuel-donnees visuel-secondaire"><table><thead><tr><th>{graphique.xKey}</th>{graphique.series.map(s => <th key={s.key}>{s.label}</th>)}</tr></thead>
      <tbody>{graphique.data.map((d, i) => <tr key={i}><td>{d[graphique.xKey]}</td>{graphique.series.map(s => <td key={s.key}>{d[s.key]}</td>)}</tr>)}</tbody></table></div>}
    {code && <div className="visuel-code visuel-secondaire"><button onClick={() => void action(async () => { await navigator.clipboard.writeText(source); toast.success(l.copied); })}>{l.copy}</button><pre>{source}</pre></div>}
  </>;
  return <section ref={cadre} className="visuel-discussion" aria-label={l[genre]}>
    {!plein && contenu}
    {plein && <p className="visuel-statut">{titre}</p>}
    {createPortal(<dialog ref={dialogue} className="visuel-dialogue visuel-discussion"
      aria-label={titre} onClose={() => { setPlein(false); requestAnimationFrame(() => boutonPlein.current?.focus()); }}
      onClick={e => { if (e.target === e.currentTarget) setPlein(false); }}>
      {plein && <div className="visuel-dialogue-contenu">{contenu}</div>}
    </dialog>, document.body)}
  </section>;
}
