// Le calque d'annotations d'une photo — un SVG posé sur l'image.
//
// Les formes vivent en fractions de l'image affichée (0..1), donc le même
// calque tient à toute taille : l'aperçu, le plein cadre, l'export PDF (où
// `photosClient.graverAnnotations` les redessine dans un canvas avec les
// mêmes proportions — les deux doivent rester d'accord).
//
// En lecture, le SVG laisse passer les clics. En édition, il les prend :
// on pose une forme par glisser, un texte par clic ; une forme cliquée se
// sélectionne, ⌫ la supprime.

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';

import { boiteDe, idAnnotation, pointeFleche } from './photos';
import type { SuccesAnnotation, SuccesAnnotationType } from './types';

// La capture du pointeur lève `NotFoundError` quand l'événement ne vient pas
// d'un vrai pointeur (un test, un geste synthétique) : le geste doit
// s'achever quand même, capture ou pas.
function capturer(e: { currentTarget: Element; pointerId: number }) {
  try {
    e.currentTarget.setPointerCapture(e.pointerId);
  } catch {
    // Pas de pointeur actif : rien à capturer.
  }
}
function relacher(e: { currentTarget: Element; pointerId: number }) {
  try {
    e.currentTarget.releasePointerCapture(e.pointerId);
  } catch {
    // Déjà relâché.
  }
}

interface Props {
  annotations: SuccesAnnotation[];
  largeur: number;
  hauteur: number;
  edition: boolean;
  outil: SuccesAnnotationType;
  couleur: string;
  epaisseur: number;
  selection: string | null;
  onSelection: (id: string | null) => void;
  onChange: (annotations: SuccesAnnotation[]) => void;
}

/** L'échelle des traits : pensée pour ~1000 px de côté, comme au canvas. */
const unitePour = (l: number, h: number) => Math.max(l, h) / 1000;

export function AnnotationsCalque({
  annotations,
  largeur,
  hauteur,
  edition,
  outil,
  couleur,
  epaisseur,
  selection,
  onSelection,
  onChange,
}: Props) {
  const svg = useRef<SVGSVGElement>(null);
  /** La forme en cours de tracé ; null entre deux gestes. */
  const [brouillon, setBrouillon] = useState<SuccesAnnotation | null>(null);
  /** Le texte en cours de saisie, à l'endroit cliqué. */
  const [saisie, setSaisie] = useState<{ x: number; y: number; texte: string } | null>(null);
  const champ = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (saisie) champ.current?.focus();
  }, [saisie]);

  const fraction = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = svg.current?.getBoundingClientRect();
    if (!r || !r.width || !r.height) return [0, 0];
    const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    const y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
    return [Math.round(x * 100000) / 100000, Math.round(y * 100000) / 100000];
  };

  const commencer = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (!edition || e.button !== 0) return;
    const cible = e.target as Element;
    const idForme = cible.closest('[data-annotation]')?.getAttribute('data-annotation');
    if (idForme) {
      onSelection(idForme);
      return;
    }
    onSelection(null);
    const p = fraction(e);
    if (outil === 'text') {
      setSaisie({ x: p[0], y: p[1], texte: '' });
      return;
    }
    capturer(e);
    setBrouillon({
      id: idAnnotation(),
      type: outil,
      color: couleur,
      width: epaisseur,
      points: [p, p],
    });
  };

  const tracer = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (!brouillon) return;
    const p = fraction(e);
    setBrouillon((b) => {
      if (!b) return b;
      if (b.type === 'pen' || b.type === 'highlight') return { ...b, points: [...b.points, p] };
      return { ...b, points: [b.points[0], p] };
    });
  };

  const finir = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (!brouillon) return;
    relacher(e);
    const b = brouillon;
    setBrouillon(null);
    // Un clic sans mouvement n'est pas une forme : on ne garde que ce qui
    // a une taille, sauf le stylo qui peut poser un point.
    const boite = boiteDe(b.points);
    const minuscule = boite.w < 0.005 && boite.h < 0.005;
    if (minuscule && b.type !== 'pen') return;
    onChange([...annotations, b]);
    onSelection(b.id);
  };

  const validerTexte = () => {
    if (!saisie) return;
    const texte = saisie.texte.trim();
    setSaisie(null);
    if (!texte) return;
    const forme: SuccesAnnotation = {
      id: idAnnotation(),
      type: 'text',
      color: couleur,
      width: epaisseur,
      points: [[saisie.x, saisie.y]],
      text: texte,
    };
    onChange([...annotations, forme]);
    onSelection(forme.id);
  };

  const unite = unitePour(largeur, hauteur);
  const formes = brouillon ? [...annotations, brouillon] : annotations;

  return (
    <>
      <svg
        ref={svg}
        viewBox={`0 0 ${largeur} ${hauteur}`}
        width={largeur}
        height={hauteur}
        className="absolute inset-0"
        style={{
          pointerEvents: edition ? 'auto' : 'none',
          cursor: edition ? (outil === 'text' ? 'text' : 'crosshair') : undefined,
          touchAction: 'none',
        }}
        onPointerDown={commencer}
        onPointerMove={tracer}
        onPointerUp={finir}
        onPointerCancel={() => setBrouillon(null)}
        aria-hidden={!edition}
      >
        {formes.map((a) => (
          <Forme
            key={a.id}
            a={a}
            l={largeur}
            h={hauteur}
            unite={unite}
            selectionnee={edition && selection === a.id}
          />
        ))}
      </svg>
      {saisie && (
        <input
          ref={champ}
          value={saisie.texte}
          onChange={(e) => setSaisie({ ...saisie, texte: e.target.value })}
          onBlur={validerTexte}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === 'Enter') validerTexte();
            if (e.key === 'Escape') setSaisie(null);
          }}
          maxLength={300}
          placeholder="Ton texte, puis Entrée"
          aria-label="Texte de l'annotation"
          className="absolute rounded px-1.5 py-1 text-sm outline-none"
          style={{
            left: saisie.x * largeur,
            top: saisie.y * hauteur,
            background: 'rgba(0,0,0,0.8)',
            color: couleur,
            border: `1px solid ${couleur}`,
            minWidth: 160,
          }}
        />
      )}
    </>
  );
}

function Forme({
  a,
  l,
  h,
  unite,
  selectionnee,
}: {
  a: SuccesAnnotation;
  l: number;
  h: number;
  unite: number;
  selectionnee: boolean;
}) {
  const pts = a.points.map(([x, y]) => ({ x: x * l, y: y * h }));
  const ep = Math.max(1, a.width * unite);
  const commun = {
    'data-annotation': a.id,
    stroke: a.color,
    strokeWidth: ep,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    fill: 'none',
    style: { cursor: 'pointer' },
  };
  const halo = selectionnee ? (
    <HaloSelection pts={pts} ep={ep} />
  ) : null;

  if (a.type === 'arrow' && pts.length >= 2) {
    const p = pts[0];
    const q = pts[pts.length - 1];
    const [t, u, v] = pointeFleche(p, q, ep);
    return (
      <g>
        {halo}
        <line x1={p.x} y1={p.y} x2={q.x} y2={q.y} {...commun} />
        <polygon
          points={`${t.x},${t.y} ${u.x},${u.y} ${v.x},${v.y}`}
          data-annotation={a.id}
          fill={a.color}
          stroke="none"
        />
      </g>
    );
  }
  if ((a.type === 'rect' || a.type === 'ellipse') && pts.length >= 2) {
    const x = Math.min(pts[0].x, pts[1].x);
    const y = Math.min(pts[0].y, pts[1].y);
    const w = Math.abs(pts[1].x - pts[0].x);
    const hh = Math.abs(pts[1].y - pts[0].y);
    return (
      <g>
        {halo}
        {a.type === 'rect' ? (
          <rect x={x} y={y} width={w} height={hh} rx={ep} {...commun} />
        ) : (
          <ellipse cx={x + w / 2} cy={y + hh / 2} rx={w / 2} ry={hh / 2} {...commun} />
        )}
      </g>
    );
  }
  if ((a.type === 'pen' || a.type === 'highlight') && pts.length >= 1) {
    const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x} ${p.y}`).join(' ');
    return (
      <g>
        {halo}
        <path
          d={pts.length === 1 ? `${d} l0.01 0` : d}
          {...commun}
          strokeWidth={a.type === 'highlight' ? ep * 5 : ep}
          opacity={a.type === 'highlight' ? 0.35 : 1}
        />
      </g>
    );
  }
  if (a.type === 'text' && pts.length >= 1 && a.text) {
    const taille = Math.max(12, 22 * unite + a.width * unite);
    const largeurTexte = a.text.length * taille * 0.58;
    return (
      <g data-annotation={a.id} style={{ cursor: 'pointer' }}>
        {halo}
        <rect
          x={pts[0].x - 4 * unite}
          y={pts[0].y - 3 * unite}
          width={largeurTexte + 8 * unite}
          height={taille + 6 * unite}
          fill="#000"
          opacity={0.75}
          rx={3 * unite}
        />
        <text
          x={pts[0].x}
          y={pts[0].y + taille * 0.82}
          fill={a.color}
          fontSize={taille}
          fontWeight={600}
          fontFamily='-apple-system, "Helvetica Neue", Arial, sans-serif'
        >
          {a.text}
        </text>
      </g>
    );
  }
  return null;
}

/** Un contour pointillé autour de la forme sélectionnée. */
function HaloSelection({ pts, ep }: { pts: Array<{ x: number; y: number }>; ep: number }) {
  const xs = pts.map((p) => p.x);
  const ys = pts.map((p) => p.y);
  const marge = ep * 2 + 6;
  const x = Math.min(...xs) - marge;
  const y = Math.min(...ys) - marge;
  return (
    <rect
      x={x}
      y={y}
      width={Math.max(...xs) - Math.min(...xs) + marge * 2}
      height={Math.max(...ys) - Math.min(...ys) + marge * 2}
      fill="none"
      stroke="#fff"
      strokeWidth={1.5}
      strokeDasharray="6 4"
      rx={6}
      pointerEvents="none"
    />
  );
}
