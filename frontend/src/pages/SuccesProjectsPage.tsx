import { CadreVitre } from '../components/Glass/CadreVitre';
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type PointerEvent,
} from 'react';
import {
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  CirclePlus,
  Loader2,
  Pencil,
  Search,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  DateAmbigueError,
  DateInconnueError,
  addSuccesSubtask,
  createSuccesProject,
  createSuccesTask,
  deleteSuccesProject,
  deleteSuccesTask,
  listSuccesProjectKits,
  listSuccesProjects,
  reorderProjects,
  listSuccesTasks,
  rescheduleSuccesTask,
  setSuccesSubtaskDone,
  setSuccesTaskDone,
  createSuccesTaskEdge,
  deleteSuccesTaskEdge,
  listSuccesTaskEdges,
  resetSuccesProjectCycle,
  updateSuccesProject,
  updateSuccesTask,
} from '../features/succes/api';
import { ProjectTreeView } from '../features/succes/ProjectTreeView';
import { GenealogyView } from '../features/succes/GenealogyView';
import { LigneEtape } from '../features/succes/LigneEtape';
import { MindMapView } from '../features/succes/MindMapView';
import { PipelineBoard } from '../features/succes/PipelineBoard';
import { NetworkView } from '../features/succes/NetworkView';
import { FicheBranches } from '../features/succes/FicheBranches';
import { CycleWheel } from '../features/succes/CycleWheel';
import { PilesPhotos } from '../features/succes/PilesPhotos';
import { StructureGlyph } from '../features/succes/StructureGlyph';
import {
  progressionSequentielle,
  tachesVerrouillees,
} from '../features/succes/verrou';
import { useRefreshOnFocus } from '../features/succes/useRefreshOnFocus';
import { useChargementTemporise } from '../features/succes/useChargementTemporise';
import { clesSucces, ecrireCache, lireCache } from '../features/succes/cacheSucces';
import { dateIsoLocale } from '../features/succes/planificateur';
import { phraseReportee } from '../features/succes/report';
import { construireReseau, phraseApresBascule, type PhraseBascule } from '../features/succes/reseau';
import { TaskCard, type SuccesTaskPatch } from '../features/succes/TaskCard';
import type {
  SuccesProject,
  SuccesProjectKit,
  SuccesProjectStructure,
  SuccesSubtask,
  SuccesTask,
  SuccesTaskEdge,
} from '../features/succes/types';
import { useConfirm } from '../components/ConfirmDialog';
import { useNavigate } from 'react-router';

import { NoteFolderVisual } from '../features/succes/NoteFolderVisual';
import { listSuccesNotes } from '../features/succes/api';
import type { SuccesNote } from '../features/succes/types';
import { deplacerVers } from '../features/succes/photos';
import { useAppStore } from '../lib/store';
import { useContexteVue } from '../features/mesh/useContexteVue';

const FALLBACK_COLOR = '#6366f1';

const COLOR_PRESETS = [
  '#6366f1', '#38bdf8', '#22c55e', '#14b8a6',
  '#f59e0b', '#ef4444', '#ec4899', '#a855f7',
];

const emptyDraft = {
  name: '',
  description: '',
  icon: '',
  color: FALLBACK_COLOR,
  startDate: '',
  endDate: '',
  structure: 'flat' as SuccesProjectStructure,
  kitId: '',
  /** Arbre et carte : les tâches d'une fratrie s'ouvrent une par une. */
  sequential: false,
  /** Les étages nommés du projet, conservés tels quels pour ne pas les perdre
   *  en enregistrant un simple changement de nom. */
  levelLabels: [] as string[],
};

/** Les cinq formes + la liste, plus l'entrée Kit. Le même catalogue vit côté
 *  serveur (structures.py) ; le garder statique ici évite un aller réseau
 *  pour ouvrir un simple formulaire. */
const STRUCTURE_OPTIONS: ReadonlyArray<{
  id: SuccesProjectStructure | 'kit';
  label: string;
  hint: string;
}> = [
  { id: 'flat', label: '☰ Liste', hint: 'Des tâches, dans l’ordre.' },
  { id: 'tree', label: '🌳 Arbre', hint: 'L’objectif engendre ses livrables.' },
  { id: 'mindmap', label: '🧠 Carte', hint: 'Les idées rayonnent du centre.' },
  { id: 'pipeline', label: '🏭 Pipeline', hint: 'Chaque tâche traverse des étapes.' },
  { id: 'network', label: '🕸️ Réseau', hint: 'Qui débloque quoi, et quoi faire là.' },
  { id: 'cycle', label: '🔄 Cycle', hint: 'La roue des routines, tour après tour.' },
  { id: 'kit', label: '📦 Kit', hint: 'Démarrer depuis un modèle prêt.' },
];

function parseHex(hex: string): [number, number, number] {
  const raw = (hex || '').trim().replace('#', '');
  const full = raw.length === 3 ? raw.split('').map((channel) => channel + channel).join('') : raw;
  if (!/^[0-9a-f]{6}$/i.test(full)) return [99, 102, 241];
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

/** Positive amounts lighten toward white, negative ones deepen toward black. */
function shade(hex: string, amount: number) {
  const target = amount > 0 ? 255 : 0;
  const ratio = Math.abs(amount);
  const [r, g, b] = parseHex(hex).map((channel) => Math.round(channel + (target - channel) * ratio));
  return `rgb(${r}, ${g}, ${b})`;
}

function alpha(hex: string, opacity: number) {
  const [r, g, b] = parseHex(hex);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

/** Same ramp as `shade`, but hex out so the result can feed `shade`/`alpha` again. */
function shadeHex(hex: string, amount: number) {
  const target = amount > 0 ? 255 : 0;
  const ratio = Math.abs(amount);
  const channels = parseHex(hex).map((channel) =>
    Math.round(channel + (target - channel) * ratio),
  );
  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}

/** WCAG relative luminance — used to spot colors too pale for a white page. */
function luminance(hex: string) {
  const [r, g, b] = parseHex(hex).map((channel) => {
    const scaled = channel / 255;
    return scaled <= 0.03928
      ? scaled / 12.92
      : ((scaled + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * On a light page a pale project color (yellow, light cyan) would melt into the
 * background, so deepen it just enough to keep the folder readable. Dark themes
 * keep the author's color untouched.
 */
function readableColor(hex: string, isLight: boolean) {
  if (!isLight) return hex;
  const level = luminance(hex);
  if (level <= 0.3) return hex;
  return shadeHex(hex, -Math.min(0.42, (level - 0.3) * 0.8));
}

function resolveIsLight() {
  if (typeof document === 'undefined') return false;
  const root = document.documentElement;
  if (root.classList.contains('light')) return true;
  if (root.classList.contains('dark')) return false;
  // 'system' adds no class, so fall back to the OS preference.
  return !window.matchMedia('(prefers-color-scheme: dark)').matches;
}

/** Tracks the resolved theme, including the 'system' case and live switches. */
function useIsLightTheme() {
  const [isLight, setIsLight] = useState(resolveIsLight);

  useEffect(() => {
    const update = () => setIsLight(resolveIsLight());
    update();
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });
    return () => {
      media.removeEventListener('change', update);
      observer.disconnect();
    };
  }, []);

  return isLight;
}

/*
 * Icon geometry, traced from the reference render on a 240x180 canvas.
 * The folder is deliberately WIDER than the sheet, its tab sits on the left,
 * and roughly a third of the sheet rises above the flap.
 */
/* Cropped to the artwork's own bounds (folder + sheet + shadows) so the icon
 * fills its box as tightly as the Notes folder does at the same height. */
const ART_VIEWBOX = '55 34 135 138';
const FOLDER_PATH =
  'M 78 66 H 108 L 128 82 H 165 A 7 7 0 0 1 172 89 V 137 A 7 7 0 0 1 165 144 H 78 A 7 7 0 0 1 71 137 V 73 A 7 7 0 0 1 78 66 Z';
const SHEET_PATH =
  'M 96 40 H 144 L 155 51 V 121 A 5 5 0 0 1 150 126 H 96 A 5 5 0 0 1 91 121 V 45 A 5 5 0 0 1 96 40 Z';
const FOLD_PATH = 'M 144 40 L 155 51 H 149 A 5 5 0 0 1 144 46 Z';

const FOLDER_MASK = `url("data:image/svg+xml,${encodeURIComponent(
  `<svg xmlns='http://www.w3.org/2000/svg' viewBox='${ART_VIEWBOX}'><path fill='white' d='${FOLDER_PATH}'/></svg>`,
)}")`;

/**
 * Two lighting rigs for the same glass folder.
 *
 * On a dark page the silhouette is drawn by white rim light and specular
 * sweeps. Those same whites vanish on a light page, leaving only a blurry
 * colored blob, so the light rig inverts the logic: highlights shrink, and the
 * shape is carried by a dark contour plus color-derived bevels. The colored
 * halo is also toned right down, since bloom reads as smudge on white.
 */
function folderPalette(tone: string, isLight: boolean) {
  if (isLight) {
    return {
      // Denser body: the sheet rides a touch deeper so it holds its own on white
      // without any drawn contour.
      sheetTop: shade(tone, 0.2),
      sheetMid: shade(tone, -0.06),
      sheetBottom: shade(tone, -0.34),
      sheetOutline: null,
      sheenTop: 'rgba(255,255,255,0.24)',
      sheenMid: 'rgba(255,255,255,0.03)',
      // Soft elevation shadow instead of a line — reads clean like a macOS icon.
      shadowColor: '#0f172a',
      shadowOpacity: 0.28,
      glowOpacity: 0.22,
      glowDeviation: 16,
      bloomIdle: 0.2,
      bloomActive: 0.3,
      aoFill: 'rgba(15,23,42,0.18)',
      foldLight: shade(tone, 0.28),
      foldSheen: 'rgba(255,255,255,0.16)',
      // Slightly more tinted glass so the slab has weight on a light page.
      glass: `linear-gradient(158deg,
        rgba(255,255,255,0.34) 0%,
        ${alpha(tone, 0.10)} 32%,
        ${alpha(tone, 0.18)} 58%,
        ${alpha(tone, 0.30)} 84%,
        ${alpha(tone, 0.42)} 100%)`,
      glassFilter: 'blur(3px) saturate(135%) brightness(1)',
      bevelHighlight: alpha(shadeHex(tone, -0.4), 0.28),
      bevelColor: alpha(tone, 0.42),
      specularPeak: 'rgba(255,255,255,0.28)',
      specularSoft: 'rgba(255,255,255,0.06)',
      baseEdge: alpha(shadeHex(tone, -0.4), 0.5),
      baseEdgeIdle: 0.5,
      baseEdgeActive: 0.7,
      rimStops: [
        alpha(shadeHex(tone, -0.1), 0.55),
        alpha(shadeHex(tone, -0.3), 0.5),
        alpha(tone, 0.4),
        shade(tone, -0.4),
      ],
      outline: null,
      outlineWidth: 0,
      rimWidth: 1.4,
      hotspotIdle: 0.04,
      hotspotActive: 0.14,
      hotspotBlend: 'soft-light',
    };
  }
  return {
    sheetTop: shade(tone, 0.46),
    sheetMid: shade(tone, 0.16),
    sheetBottom: shade(tone, -0.12),
    sheetOutline: null,
    sheenTop: 'rgba(255,255,255,0.34)',
    sheenMid: 'rgba(255,255,255,0.04)',
    shadowColor: '#000',
    shadowOpacity: 0.45,
    // No colored halo around the folder in dark mode.
    glowOpacity: 0,
    glowDeviation: 14,
    bloomIdle: 0,
    bloomActive: 0,
    aoFill: 'rgba(0,0,0,0.3)',
    foldLight: shade(tone, 0.66),
    foldSheen: 'rgba(255,255,255,0.24)',
    glass: `linear-gradient(158deg,
      rgba(255,255,255,0.20) 0%,
      rgba(255,255,255,0.07) 30%,
      rgba(255,255,255,0.03) 55%,
      ${alpha(tone, 0.10)} 82%,
      ${alpha(tone, 0.20)} 100%)`,
    glassFilter: 'blur(3px) saturate(150%) brightness(1.06)',
    bevelHighlight: 'rgba(255,255,255,0.28)',
    bevelColor: alpha(tone, 0.25),
    specularPeak: 'rgba(255,255,255,0.22)',
    specularSoft: 'rgba(255,255,255,0.05)',
    baseEdge: shade(tone, 0.4),
    baseEdgeIdle: 0.75,
    baseEdgeActive: 0.95,
    rimStops: [
      'rgba(255,255,255,0.75)',
      'rgba(255,255,255,0.28)',
      alpha(tone, 0.45),
      shade(tone, 0.45),
    ],
    outline: null,
    outlineWidth: 0,
    rimWidth: 1.4,
    hotspotIdle: 0.05,
    hotspotActive: 0.2,
    hotspotBlend: 'screen',
  };
}

/**
 * Layered glass folder: an opaque colored sheet, a real backdrop-filtered pane
 * masked to the folder silhouette, then vector bevels, rim light and specular
 * passes on top. Every colored layer derives from the project color, so the
 * sheet, the light bleeding under the flap and the tint inside the glass stay
 * physically consistent.
 */
function ProjectFolderVisual({
  color,
  height = 'h-72',
  structure,
}: {
  color: string;
  height?: string;
  /** Pictogramme au survol — grille seulement. */
  structure?: SuccesProjectStructure;
}) {
  const isLight = useIsLightTheme();
  const tone = readableColor(color || FALLBACK_COLOR, isLight);
  const palette = folderPalette(tone, isLight);
  const rawId = useId();
  const uid = rawId.replace(/[^a-zA-Z0-9]/g, '');
  const ref = (name: string) => `${uid}-${name}`;
  const [tilt, setTilt] = useState({ x: 0, y: 0, glareX: 50, glareY: 42 });
  const [active, setActive] = useState(false);
  const showGlyph = Boolean(structure) && active;
  const glyphInk = luminance(tone) > 0.42 ? 'rgba(15,23,42,0.78)' : 'rgba(255,255,255,0.92)';

  const followPointer = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const glareX = ((event.clientX - bounds.left) / bounds.width) * 100;
    const glareY = ((event.clientY - bounds.top) / bounds.height) * 100;
    // Subtle motion: enough parallax to read as 3D, never enough to distort.
    setTilt({
      x: (glareX / 100 - 0.5) * 7,
      y: -(glareY / 100 - 0.5) * 5,
      glareX,
      glareY,
    });
  };

  const reset = () => {
    setActive(false);
    setTilt({ x: 0, y: 0, glareX: 50, glareY: 42 });
  };

  return (
    <div
      aria-hidden="true"
      className={`relative grid w-full place-items-center ${height}`}
      onPointerEnter={() => setActive(true)}
      onPointerMove={followPointer}
      onPointerLeave={reset}
      style={{ perspective: '760px', background: 'transparent' }}
    >
      <div
        className="relative h-full"
        style={{
          aspectRatio: '135 / 138',
          maxWidth: '100%',
          transform: `rotateX(${tilt.y}deg) rotateY(${tilt.x}deg) scale(${active ? 1.02 : 1})`,
          transformStyle: 'preserve-3d',
          transition: active ? 'transform 90ms linear' : 'transform 460ms cubic-bezier(.2,.8,.2,1)',
          willChange: 'transform',
        }}
      >
        {/* Sheet: the only opaque colored body, sitting behind the glass */}
        <svg viewBox={ART_VIEWBOX} className="absolute inset-0 h-full w-full">
          <defs>
            <linearGradient id={ref('sheet')} x1="0.1" y1="0" x2="0.55" y2="1">
              <stop offset="0%" stopColor={palette.sheetTop} />
              <stop offset="38%" stopColor={palette.sheetMid} />
              <stop offset="100%" stopColor={palette.sheetBottom} />
            </linearGradient>
            <linearGradient id={ref('sheetSheen')} x1="0" y1="0" x2="0.7" y2="1">
              <stop offset="0%" stopColor={palette.sheenTop} />
              <stop offset="45%" stopColor={palette.sheenMid} />
              <stop offset="100%" stopColor="rgba(255,255,255,0)" />
            </linearGradient>
            <filter id={ref('sheetShadow')} x="-40%" y="-25%" width="180%" height="170%">
              <feDropShadow
                dx="0"
                dy="4"
                stdDeviation="5"
                floodColor={palette.shadowColor}
                floodOpacity={palette.shadowOpacity}
              />
              <feDropShadow
                dx="0"
                dy="10"
                stdDeviation={palette.glowDeviation}
                floodColor={tone}
                floodOpacity={palette.glowOpacity}
              />
            </filter>
            <filter id={ref('ao')} x="-20%" y="-60%" width="140%" height="220%">
              <feGaussianBlur stdDeviation="3.5" />
            </filter>
            {/* Kept in user space so the halo scales with the icon instead of
                hardening into a tight ring when the card grows. */}
            <filter id={ref('bloom')} x="-60%" y="-90%" width="220%" height="280%">
              <feGaussianBlur stdDeviation="13" />
            </filter>
            <clipPath id={ref('sheetClip')}>
              <path d={SHEET_PATH} />
            </clipPath>
          </defs>

          {/* Light theme: a soft contact shadow gives elevation without a line. */}
          {isLight && (
            <ellipse
              cx="122"
              cy="150"
              rx="60"
              ry="16"
              fill="rgba(15,23,42,0.22)"
              filter={`url(#${ref('bloom')})`}
              opacity={active ? 0.9 : 0.7}
              style={{ transition: 'opacity 320ms ease' }}
            />
          )}

          {/* Colored light spilling out from under the flap */}
          <ellipse
            cx="121"
            cy="132"
            rx="56"
            ry="22"
            fill={alpha(tone, palette.glowOpacity)}
            filter={`url(#${ref('bloom')})`}
            opacity={active ? palette.bloomActive : palette.bloomIdle}
            style={{ transition: 'opacity 320ms ease' }}
          />

          <g filter={`url(#${ref('sheetShadow')})`}>
            <path d={SHEET_PATH} fill={`url(#${ref('sheet')})`} />
          </g>
          <g clipPath={`url(#${ref('sheetClip')})`}>
            <path d={SHEET_PATH} fill={`url(#${ref('sheetSheen')})`} />
            {/* Ambient occlusion where the flap presses against the sheet */}
            <rect x="60" y="74" width="120" height="12" fill={palette.aoFill} filter={`url(#${ref('ao')})`} />
          </g>
          {/* On a light page the paper needs its own edge or it bleeds into white */}
          {palette.sheetOutline && (
            <path d={SHEET_PATH} fill="none" stroke={palette.sheetOutline} strokeWidth="0.9" />
          )}
          {/* Dog-ear: back of the paper catches more light */}
          <path d={FOLD_PATH} fill={palette.foldLight} />
          <path d={FOLD_PATH} fill={palette.foldSheen} />
          <path
            d="M 144 40 L 155 51"
            stroke="rgba(0,0,0,0.18)"
            strokeWidth="0.8"
            fill="none"
          />
        </svg>

        {/* Real glass: backdrop-filter masked to the folder silhouette */}
        <div
          className="absolute inset-0"
          style={{
            backdropFilter: palette.glassFilter,
            WebkitBackdropFilter: palette.glassFilter,
            background: palette.glass,
            maskImage: FOLDER_MASK,
            WebkitMaskImage: FOLDER_MASK,
            maskSize: '100% 100%',
            WebkitMaskSize: '100% 100%',
            maskRepeat: 'no-repeat',
            WebkitMaskRepeat: 'no-repeat',
            transform: 'translateZ(16px)',
          }}
        />

        {/* Glass finishing: bevels, rim light, specular, frost */}
        <svg
          viewBox={ART_VIEWBOX}
          className="pointer-events-none absolute inset-0 h-full w-full"
          style={{ transform: 'translateZ(18px)' }}
        >
          <defs>
            <linearGradient id={ref('rim')} x1="0.2" y1="0" x2="0.6" y2="1">
              <stop offset="0%" stopColor={palette.rimStops[0]} />
              <stop offset="35%" stopColor={palette.rimStops[1]} />
              <stop offset="72%" stopColor={palette.rimStops[2]} />
              <stop offset="100%" stopColor={palette.rimStops[3]} />
            </linearGradient>
            <linearGradient id={ref('specular')} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="rgba(255,255,255,0)" />
              <stop offset="42%" stopColor={palette.specularPeak} />
              <stop offset="58%" stopColor={palette.specularSoft} />
              <stop offset="100%" stopColor="rgba(255,255,255,0)" />
            </linearGradient>
            <filter id={ref('rimGlow')} x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="3" />
            </filter>
            <filter id={ref('frost')} x="0%" y="0%" width="100%" height="100%">
              <feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" result="noise" />
              <feColorMatrix in="noise" type="saturate" values="0" />
            </filter>
            <clipPath id={ref('folderClip')}>
              <path d={FOLDER_PATH} />
            </clipPath>
          </defs>

          {/* Light bleeding through the bottom edge of the slab */}
          <path
            d="M 78 143 H 165"
            stroke={palette.baseEdge}
            strokeWidth="4"
            strokeLinecap="round"
            filter={`url(#${ref('rimGlow')})`}
            opacity={active ? palette.baseEdgeActive : palette.baseEdgeIdle}
          />

          <g clipPath={`url(#${ref('folderClip')})`}>
            {/* Frosted micro-texture */}
            <rect x="0" y="0" width="240" height="180" filter={`url(#${ref('frost')})`} opacity="0.04" />
            {/* Broad specular sweep across the slab */}
            <rect x="-40" y="40" width="150" height="180" fill={`url(#${ref('specular')})`} transform="rotate(-18 120 110)" />
            {/* Inner bevel: bright just under the top edges, dark at the base */}
            <path
              d={FOLDER_PATH}
              fill="none"
              stroke={palette.bevelHighlight}
              strokeWidth="2.4"
              transform="translate(0, 1.2)"
            />
            <path
              d={FOLDER_PATH}
              fill="none"
              stroke={palette.bevelColor}
              strokeWidth="6"
              transform="translate(0, -3)"
            />
          </g>

          {/* Light theme only: a dark contour so the silhouette never dissolves
              into a pale background. */}
          {palette.outline && (
            <path
              d={FOLDER_PATH}
              fill="none"
              stroke={palette.outline}
              strokeWidth={palette.outlineWidth}
              strokeLinejoin="round"
            />
          )}

          {/* Outer rim: crisp edge that defines the slab thickness */}
          <path
            d={FOLDER_PATH}
            fill="none"
            stroke={`url(#${ref('rim')})`}
            strokeWidth={palette.rimWidth}
          />
        </svg>

        {/* Pointer-driven specular hotspot */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background: `radial-gradient(circle at ${tilt.glareX}% ${tilt.glareY}%, rgba(255,255,255,${active ? palette.hotspotActive : palette.hotspotIdle}) 0%, transparent 30%)`,
            mixBlendMode: palette.hotspotBlend as 'screen' | 'soft-light',
            maskImage: FOLDER_MASK,
            WebkitMaskImage: FOLDER_MASK,
            maskSize: '100% 100%',
            WebkitMaskSize: '100% 100%',
            maskRepeat: 'no-repeat',
            WebkitMaskRepeat: 'no-repeat',
            transform: 'translateZ(22px)',
            transition: active ? 'none' : 'background 300ms ease',
          }}
        />

        {structure && (
          <svg
            viewBox={ART_VIEWBOX}
            className="pointer-events-none absolute inset-0 h-full w-full"
            style={{
              transform: 'translateZ(24px)',
              opacity: showGlyph ? 1 : 0,
              transition: 'opacity 220ms ease',
            }}
            aria-hidden="true"
          >
            <defs>
              <clipPath id={ref('glyphClip')}>
                <path d={FOLDER_PATH} />
              </clipPath>
            </defs>
            <g clipPath={`url(#${ref('glyphClip')})`}>
              <svg x="98" y="86" width="48" height="50" viewBox="0 0 48 48">
                <StructureGlyph structure={structure} stroke={glyphInk} />
              </svg>
            </g>
          </svg>
        )}
      </div>
    </div>
  );
}

/**
 * Les notes rattachées au projet — de petits cartables, même langage visuel
 * que le dossier. Un clic ouvre la note dans le module Notes (le chemin
 * qu'emprunte déjà « montre-moi cette note » du maillage). Demandé le
 * 15 septembre 2026.
 *
 * En LIGNE, pleine largeur, sous l'en-tête — plus dans la colonne de 200 px
 * du dossier, où six cartables s'empilaient sur trois rangées de deux
 * pendant que tout l'espace à droite restait vide (Carlito, 17 sept. 2026 :
 * « mets les notes en horizontal, le plus ergonomique possible »). L'ordre
 * est celui fixé dans Notes (le serveur sert le rang manuel).
 */
function NotesDuProjet({ projectId }: { projectId: string }) {
  const [notes, setNotes] = useState<SuccesNote[]>([]);
  const navigate = useNavigate();
  const setPendingMeshSelection = useAppStore((s) => s.setPendingMeshSelection);

  useEffect(() => {
    let visible = true;
    listSuccesNotes('')
      .then((toutes) => {
        if (visible) setNotes(toutes.filter((note) => note.projectId === projectId));
      })
      .catch(() => {
        // La section reste simplement vide : la page projet vaut mieux
        // sans ses notes qu'en erreur.
      });
    return () => {
      visible = false;
    };
  }, [projectId]);

  if (!notes.length) return null;
  return (
    <section className="mb-6" aria-label="Notes du projet">
      <div className="flex items-center gap-2 mb-2">
        <h3
          className="text-[11px] font-semibold tracking-[0.14em] uppercase shrink-0"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          Notes
        </h3>
        <span
          className="text-[11px] tabular-nums shrink-0"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          {notes.length}
        </span>
        <span aria-hidden="true" className="flex-1 h-px" style={{ background: 'var(--color-border)' }} />
      </div>
      {/* Une rangée qui ne revient à la ligne que si les cartables ne
          tiennent pas : tout est visible d'un regard, rien à faire défiler. */}
      <div className="flex flex-wrap gap-x-3 gap-y-4">
        {notes.map((note) => (
          <button
            key={note.id}
            type="button"
            onClick={() => {
              setPendingMeshSelection({ kind: 'note', id: note.id });
              void navigate('/succes/notes');
            }}
            className="w-24 sm:w-28 shrink-0 cursor-pointer bg-transparent border-0 p-0 text-inherit"
            aria-label={`Ouvrir la note ${note.title}`}
            title={note.title}
          >
            <NoteFolderVisual color={note.color || '#6366f1'} sheets={2} height="h-20" />
            <p
              className="max-w-full truncate text-[11px] text-center px-1 pt-0.5"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {note.title}
            </p>
          </button>
        ))}
      </div>
    </section>
  );
}

export function SuccesProjectsPage() {
  const confirm = useConfirm();
  // L'état initial vient du cache — la dernière réponse du serveur, en
  // mémoire depuis la visite précédente ou relue du disque au lancement.
  // Chaque retour sur la page repartait d'un écran vide et d'un spinner
  // pour un serveur qui répond en 3-8 ms (Carlito, 18 sept. 2026).
  const [projects, setProjects] = useState<SuccesProject[]>(
    () => lireCache<SuccesProject[]>(clesSucces.projets()) ?? [],
  );
  const [tasks, setTasks] = useState<SuccesTask[]>(() => lireCache<SuccesTask[]>(clesSucces.taches()) ?? []);
  const [search, setSearch] = useState('');
  // Le spinner n'existe qu'au premier chargement sans cache : ensuite la
  // liste reste montée pendant qu'on relit derrière (retour de focus,
  // recherche, réordonnancement) — `saving` tient le voyant discret.
  // Les DEUX caches : le détail d'un projet dépend des tâches, et Notes
  // remplit celui des projets sans toucher à celui des tâches — « Notes,
  // puis Projets » montait avec les projets et zéro tâche, et le détail
  // disait « Aucune tâche dans ce projet » et « 0/12 terminée(s) » pendant
  // tout le premier chargement (revue du cache, 18 sept. 2026).
  const [loading, setLoading] = useState(
    () => lireCache(clesSucces.projets()) === null || lireCache(clesSucces.taches()) === null,
  );
  /**
   * Vrai dès que le serveur a rendu projets ET tâches pendant ce montage —
   * le cache n'y suffit pas. Un état, pas une ref : le rendu s'en sert pour
   * ne montrer l'état vide et les comptes d'un projet que sur une liste de
   * tâches que le serveur a rendue.
   */
  const [chargeReussi, setChargeReussi] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState(emptyDraft);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  /** Le projet survolé pendant un glisser de réordonnancement. */
  const [cibleProjet, setCibleProjet] = useState<string | null>(null);
  const [quickTitle, setQuickTitle] = useState('');
  const [kits, setKits] = useState<SuccesProjectKit[]>(
    () => lireCache<SuccesProjectKit[]>(clesSucces.kitsProjets()) ?? [],
  );
  const [edges, setEdges] = useState<SuccesTaskEdge[]>([]);
  const [edgesFailed, setEdgesFailed] = useState(false);
  // Les cinq vues exposent onSelect ; sans destinataire, chips « faisable »,
  // titres de cartes et clics simples étaient des boutons morts.
  const [inspected, setInspected] = useState<SuccesTask | null>(null);
  // Le réseau (18 sept. 2026) garde l'ID, pas l'objet : la fiche « Branches »
  // se relit dans `projectTasks` et `edges` à chaque rendu. L'aside générique
  // ci-dessus affichait encore « Ouverte » après une coche sur la carte du
  // graphe, parce qu'il tenait une photo prise au clic.
  const [inspectedId, setInspectedId] = useState<string | null>(null);
  /** « Relier depuis ici » : la source demandée au graphe, avec un jeton par demande. */
  const [liaisonDemandee, setLiaisonDemandee] = useState<{ sourceId: string; jeton: number } | null>(null);
  // La Ligne (23 août 2026) : cliquer une étape RACINE de l'arbre déroule ses
  // cours en stations de métro. On garde l'id, pas l'objet — après chaque
  // enregistrement, l'étape affichée se relit dans les tâches fraîches.
  const [etapeLigneId, setEtapeLigneId] = useState<string | null>(null);
  // Les piles de photos : la tâche dont la Ligne veut voir les photos, et
  // combien de photos pointent vers chaque tâche (pour le repère en Ligne).
  const [photosDeTache, setPhotosDeTache] = useState<string | null>(null);
  const [photosParTache, setPhotosParTache] = useState<Record<string, number>>({});
  const surPhotosParTache = useCallback((parTache: Record<string, number>) => {
    setPhotosParTache(parTache);
  }, []);
  const surTacheOuverte = useCallback(() => setPhotosDeTache(null), []);
  // La famille arbre (arbre, carte) garde un onglet « Édition » : la vue
  // spécialisée montre et crée, l'édition renomme et supprime.
  const [treeEditMode, setTreeEditMode] = useState(false);

  const load = useCallback(async () => {
    try {
      const [nextProjects, nextTasks, nextKits] = await Promise.all([
        listSuccesProjects(search),
        listSuccesTasks({ includeDone: true }),
        listSuccesProjectKits().catch(() => null),
      ]);
      // Une recherche tapée reste en mémoire seule : le disque ne garde que
      // la liste complète, celle qu'un retour sur la page redemande.
      ecrireCache(clesSucces.projets(search), nextProjects, { memoireSeule: Boolean(search) });
      ecrireCache(clesSucces.taches(), nextTasks);
      setProjects(nextProjects);
      setTasks(nextTasks);
      setChargeReussi(true);
      if (nextKits) {
        ecrireCache(clesSucces.kitsProjets(), nextKits);
        setKits(nextKits);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `Projets : ${message}` });
      toast.error('Les projets ne peuvent pas être chargés.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [search]);

  useChargementTemporise(load, search);

  // Une page ouverte gardait son état indéfiniment : dans l'application de
  // bureau, des tâches créées ailleurs n'apparaissaient pas et un projet
  // supprimé restait affiché. On relit au retour du focus, avec les arêtes du
  // projet ouvert s'il y en a.
  useRefreshOnFocus(() => {
    void load();
    void loadEdges();
  });

  // Une autre appareil peut demander « montre-moi ce projet ». La sélection
  // arrive par le magasin parce que le routeur ne la transporte pas ; elle est
  // consommée une fois, sinon revenir sur l'écran la rouvrirait sans raison.
  const pendingMeshSelection = useAppStore((s) => s.pendingMeshSelection);
  const setPendingMeshSelection = useAppStore((s) => s.setPendingMeshSelection);
  useEffect(() => {
    if (pendingMeshSelection?.kind !== 'project') return;
    setSelectedId(pendingMeshSelection.id);
    setPendingMeshSelection(null);
  }, [pendingMeshSelection, setPendingMeshSelection]);

  const selected = projects.find((project) => project.id === selectedId) ?? null;
  // Le référent de « ce projet » (handoff, 25/08/2026) : sans ce cliché,
  // « continue ça sur mon téléphone » ne désigne rien.
  useContexteVue(
    selected ? { type: 'project', id: selected.id, title: selected.name } : null,
  );

  // Un projet ouvert peut disparaître sous nos pieds : supprimé depuis le
  // téléphone, une autre fenêtre, ou l'assistant. La page retombait alors sur
  // la liste sans un mot, ce qui se lit comme un bogue. On le DIT, et on
  // referme la sélection pour qu'un rechargement ne la rouvre pas.
  useEffect(() => {
    if (!selectedId || loading || selected) return;
    // On n'annonce une disparition que sur une liste que le SERVEUR a rendue
    // pendant ce montage : la liste du cache peut dater d'avant la création
    // du projet qu'un autre appareil demande d'ouvrir (18 sept. 2026), et
    // « n'existe plus » aurait été un faux (§100). D'où `projects` entier en
    // dépendance, pas sa longueur : la relecture qui suit rend un nouveau
    // tableau de même taille.
    if (!chargeReussi || projects.length === 0) return;
    setSelectedId(null);
    setEdges([]);
    setInspected(null);
    setEtapeLigneId(null);
    toast.info('Ce projet n’existe plus.', {
      description: 'Il a été supprimé ailleurs — retour à la liste.',
    });
  }, [selectedId, selected, projects, loading, chargeReussi]);

  const loadEdges = useCallback(async () => {
    if (!selected || selected.structure !== 'network') {
      setEdges([]);
      return;
    }
    try {
      setEdges(await listSuccesTaskEdges(selected.id));
      setEdgesFailed(false);
    } catch (error) {
      // Avaler cet échec était pire que la panne : sans arêtes, TOUTES les
      // tâches paraissent « faisables maintenant », y compris celles qui
      // attendent. Un réseau muet qui ment est plus dangereux qu'un réseau
      // qui dit ne pas savoir.
      setEdges([]);
      setEdgesFailed(true);
      toast.error('Les dépendances de ce projet ne peuvent pas être chargées.', {
        description:
          (error instanceof Error ? error.message : String(error)) +
          " — les tâches affichées comme faisables ne le sont peut-être pas.",
      });
    }
  }, [selected]);

  useEffect(() => {
    void loadEdges();
    setTreeEditMode(false);
    // Sinon la fiche du projet précédent se rouvrait d'elle-même en revenant
    // sur lui : l'id restait posé, et ses tâches réapparaissaient.
    setInspectedId(null);
    setLiaisonDemandee(null);
  }, [selectedId, selected?.structure]); // eslint-disable-line react-hooks/exhaustive-deps
  // Trié par RANG, pas par priorité. La liste globale place la priorité avant
  // order_index — juste pour la page Tâches, faux pour un arbre : un jalon
  // « high » sautait en tête de son étape et les cours « low » coulaient au
  // fond, à rebours de l'ordre chronologique voulu. Dans une généalogie,
  // l'ordre EST l'information.
  const projectTasks = selected
    ? tasks
        .filter((task) => task.projectId === selected.id)
        .slice()
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    : [];
  const openCount = projectTasks.filter((task) => !task.done).length;
  const doneCount = projectTasks.filter((task) => task.done).length;
  const progress = projectTasks.length
    ? Math.round((doneCount / projectTasks.length) * 100)
    : 0;
  // Un projet sans tâche connue n'est « vide » que si le serveur l'a dit
  // pendant ce montage ; des tâches du cache, elles, sont une réponse du
  // serveur et se montrent. Sinon : le voyant discret, pas « Aucune tâche »
  // ni « 0/N terminée(s) » (§100, revue du cache, 18 sept. 2026).
  // Une liste de tâches du cache est une réponse du serveur au même titre
  // qu'une relecture : un projet qui n'y a aucune tâche est « connu » vide.
  // Tester `projectTasks` laissait « Chargement des tâches… » sans fin sur
  // un projet vide quand la relecture échouait (contre-revue, 18 sept. 2026).
  const tachesConnues = chargeReussi || tasks.length > 0;

  const closeFormNow = () => {
    setShowForm(false);
    setEditingId(null);
    setDraft(emptyDraft);
  };

  const closeForm = async () => {
    const dirty = Boolean(
      draft.name.trim() ||
        draft.description.trim() ||
        draft.icon.trim() ||
        (draft.color && draft.color !== emptyDraft.color) ||
        draft.startDate ||
        draft.endDate ||
        draft.structure !== 'flat' ||
        draft.kitId ||
        draft.sequential,
    );
    if (dirty || editingId) {
      const confirmed = await confirm({
        title: editingId ? 'Annuler les modifications ?' : 'Annuler la création ?',
        description: 'Les changements non enregistrés seront perdus.',
        confirmLabel: 'Annuler',
        keepLabel: 'Garder',
        tone: 'warning',
      });
      if (!confirmed) return;
    }
    closeFormNow();
  };

  const edit = (project: SuccesProject) => {
    setDraft({
      name: project.name,
      description: project.description,
      icon: project.icon,
      color: project.color,
      startDate: project.startDate,
      endDate: project.endDate,
      structure: project.structure || 'flat',
      kitId: '',
      sequential: project.structureConfig?.sequential === true,
      // Sans cette reprise, enregistrer le formulaire écraserait les étages
      // nommés du projet : `structureConfig` part en entier, pas en morceaux.
      levelLabels: project.structureConfig?.levelLabels ?? [],
    });
    setEditingId(project.id);
    setShowForm(true);
  };

  const save = async () => {
    if (!draft.name.trim()) return;
    setSaving(true);
    try {
      if (editingId) {
        await updateSuccesProject(editingId, {
          name: draft.name,
          description: draft.description,
          icon: draft.icon,
          color: draft.color,
          startDate: draft.startDate,
          endDate: draft.endDate,
          structure: draft.structure,
          structureConfig:
            draft.structure === 'tree' || draft.structure === 'mindmap'
              ? {
                  ...(draft.levelLabels.length
                    ? { levelLabels: draft.levelLabels }
                    : {}),
                  ...(draft.sequential ? { sequential: true } : {}),
                }
              : undefined,
        });
      } else {
        await createSuccesProject({
          name: draft.name,
          description: draft.description,
          icon: draft.icon,
          color: draft.color,
          startDate: draft.startDate,
          endDate: draft.endDate,
          // Avec un kit, la forme vient du kit (un kit pipeline crée un
          // pipeline) : on n'envoie pas celle du brouillon par-dessus.
          structure: draft.kitId ? undefined : draft.structure,
          // Le kit apporte sa propre configuration : la nôtre l'écraserait.
          structureConfig:
            !draft.kitId &&
            draft.sequential &&
            (draft.structure === 'tree' || draft.structure === 'mindmap')
              ? { sequential: true }
              : undefined,
          kitId: draft.kitId || undefined,
        });
      }
      toast.success(editingId ? 'Projet mis à jour' : 'Projet créé', { description: 'Enregistré localement sur ce Mac.' });
      closeFormNow();
      await load();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error("Le projet n'a pas été enregistré.", { description: message });
    } finally {
      setSaving(false);
    }
  };

  /**
   * Placer un projet avant un autre. Réordonnancement 1D d'une grille plate
   * (deplacerVers, la logique pure des photos). Optimiste puis serveur ; en
   * cas d'échec on recharge, l'ordre affiché venant toujours de la base
   * (§100). Désactivé pendant une recherche : la liste y est partielle.
   */
  const placerProjetAvant = async (projetId: string, cibleId: string) => {
    if (search.trim() || projetId === cibleId) return;
    const ordonnes = deplacerVers(projects.map((p) => p.id), projetId, cibleId);
    if (ordonnes.join('\u0000') === projects.map((p) => p.id).join('\u0000')) return;
    const rang = new Map(ordonnes.map((id, i) => [id, i]));
    setProjects((prev) => [...prev].sort((a, b) => (rang.get(a.id) ?? 0) - (rang.get(b.id) ?? 0)));
    setSaving(true);
    try {
      await reorderProjects(ordonnes);
      await load();
    } catch (error) {
      toast.error("L'ordre n'a pas été enregistré.", {
        description: error instanceof Error ? error.message : String(error),
      });
      await load();
    } finally {
      setSaving(false);
    }
  };

  /** Déplacer un projet d'un cran (clavier/clic — §82). */
  const decalerProjet = async (project: SuccesProject, sens: 'avant' | 'apres') => {
    if (search.trim()) return;
    const ids = projects.map((p) => p.id);
    const i = ids.indexOf(project.id);
    const j = sens === 'avant' ? i - 1 : i + 1;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    const rang = new Map(ids.map((id, k) => [id, k]));
    setProjects((prev) => [...prev].sort((a, b) => (rang.get(a.id) ?? 0) - (rang.get(b.id) ?? 0)));
    setSaving(true);
    try {
      await reorderProjects(ids);
      await load();
    } catch (error) {
      toast.error("L'ordre n'a pas été enregistré.", {
        description: error instanceof Error ? error.message : String(error),
      });
      await load();
    } finally {
      setSaving(false);
    }
  };

  const remove = async (project: SuccesProject) => {
    const confirmed = await confirm({
      title: `Supprimer le projet « ${project.name} » ?`,
      description: 'Ses tâches ne seront pas supprimées.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    setSaving(true);
    try {
      await deleteSuccesProject(project.id);
      toast.success('Projet supprimé');
      if (selectedId === project.id) setSelectedId(null);
      await load();
    } catch (error) {
      toast.error('La suppression a échoué.', { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setSaving(false);
    }
  };

  // Rend la liste rechargée, ou null si le serveur n'a pas répondu : le
  // réseau (18 sept. 2026) en tire la phrase du toast après une coche —
  // « débloque « … » » se calcule sur ce qui est revenu, pas sur le clic.
  const loadTasks = useCallback(async (): Promise<SuccesTask[] | null> => {
    try {
      const nextTasks = await listSuccesTasks({ includeDone: true });
      ecrireCache(clesSucces.taches(), nextTasks);
      setTasks(nextTasks);
      return nextTasks;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error('Les tâches ne peuvent pas être chargées.', { description: message });
      return null;
    }
  }, []);

  /**
  * `success` à `null` : on ne dit rien QUAND ÇA MARCHE.
  *
  * Le carnet d'une tâche s'enregistre tout seul pendant qu'on écrit. Une bulle
  * par sauvegarde ferait défiler « Étape mise à jour » toutes les secondes.
  * L'échec, lui, garde sa bulle : une sauvegarde qui rate en silence est
  * exactement ce qu'il ne faut pas.
  */
  /**
   * Rend vrai si l'action ET le rechargement ont abouti. Un appelant qui
   * annonce lui-même le succès (le carnet d'une étape) doit le savoir :
   * avaler l'échec en rendant `undefined` lui faisait afficher « Enregistré »
   * sur un PATCH refusé, pendant qu'un toast rouge disait l'inverse
   * (contre-revue du 17 sept. 2026, §100).
   */
  const refreshAfter = async (
    action: () => Promise<unknown>,
    // Une phrase fixe, rien, ou une phrase ÉCRITE D'APRÈS L'ÉTAT RECHARGÉ
    // (le réseau : « Tâche terminée — débloque « … » », §100). Elle reçoit
    // null quand le rechargement a échoué, et doit alors le dire.
    success: string | null | ((fraiches: SuccesTask[] | null) => PhraseBascule),
  ): Promise<boolean> => {
    setSaving(true);
    try {
      await action();
      const fraiches = await loadTasks();
      if (typeof success === 'function') {
        const phrase = success(fraiches);
        toast.success(phrase.titre, { description: phrase.description });
      } else if (success) {
        toast.success(success, { description: 'Enregistré localement sur ce Mac.' });
      }
      return true;
    } catch (error) {
      toast.error("L'action n'a pas été enregistrée.", {
        description: error instanceof Error ? error.message : String(error),
      });
      return false;
    } finally {
      setSaving(false);
    }
  };

  /**
   * La phrase d'une coche dans le réseau, écrite d'après les tâches
   * RECHARGÉES et les arêtes du projet : « débloque « Discuter du contrat » »
   * ou « rien de nouveau : … attend encore … ». Quand le rechargement a
   * échoué, on ne devine pas ce qui s'est ouvert — on dit qu'on ne sait pas.
   */
  const phraseBasculeReseau =
    (task: SuccesTask) =>
    (fraiches: SuccesTask[] | null): PhraseBascule =>
      fraiches
        ? phraseApresBascule(construireReseau(fraiches, edges), task.id)
        : {
            titre: task.done ? 'Tâche rouverte' : 'Tâche terminée',
            description: 'L’état rechargé n’a pas pu être lu : ce qui s’ouvre reste inconnu.',
          };

  const createTaskForProject = async () => {
    if (!selected || !quickTitle.trim()) return;
    await refreshAfter(
      () => createSuccesTask({ title: quickTitle.trim(), projectId: selected.id }),
      `Tâche ajoutée à « ${selected.name} »`,
    );
    setQuickTitle('');
  };

  /**
   * Le report d'une carte, hors `refreshAfter` : `date` peut être
   * l'expression tapée dans le champ libre de la carte (« lundi prochain »),
   * et les deux refus du serveur — deux jours possibles, date non reconnue
   * — doivent lui REVENIR pour qu'elle montre ses chips ou son message.
   * Avalés par `refreshAfter`, ils fermaient la boîte comme un succès et la
   * question du 409 restait sans bouton (§34, revue du 17 sept. 2026,
   * défaut 6). Le toast dit la date que le SERVEUR a rendue (§100).
   */
  const rescheduleTask = async (task: SuccesTask, date: string) => {
    setSaving(true);
    try {
      const result = await rescheduleSuccesTask(task.id, date);
      await loadTasks();
      toast.success(phraseReportee(result.task.date, dateIsoLocale()), {
        description: result.warning || 'Enregistré localement sur ce Mac.',
      });
    } catch (error) {
      if (error instanceof DateAmbigueError || error instanceof DateInconnueError) throw error;
      toast.error("L'action n'a pas été enregistrée.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const structure: SuccesProjectStructure = selected?.structure || 'flat';
  const isTreeFamily = structure === 'tree' || structure === 'mindmap';
  const structureLabel =
    STRUCTURE_OPTIONS.find((option) => option.id === structure)?.label ?? '☰ Liste';
  const projectStages: string[] =
    selected?.structureConfig?.stages && selected.structureConfig.stages.length >= 2
      ? selected.structureConfig.stages
      : ['À faire', 'En cours', 'Fait'];
  const levelLabels: string[] = selected?.structureConfig?.levelLabels ?? [];
  // Les branches encore fermées, recalculées à chaque coche. Le magasin
  // refuse déjà de les terminer ; ceci ne fait que le dire AVANT le clic,
  // au lieu d'envoyer une requête dont on connaît la réponse.
  const sequentiel = progressionSequentielle(
    selected?.structure,
    selected?.structureConfig,
  );
  const verrous = useMemo(
    () => tachesVerrouillees(projectTasks, sequentiel),
    [projectTasks, sequentiel],
  );

  if (selected) {
    return (
      <div className="flex-1 overflow-y-auto px-3 py-5 sm:px-5 sm:py-8 md:px-8 md:py-10">
        <main className="max-w-5xl mx-auto w-full">
          <button
            type="button"
            onClick={() => setSelectedId(null)}
            className="mb-5 flex items-center gap-2 text-sm cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <ChevronLeft size={16} style={{ color: 'var(--color-accent)' }} />
            Retour aux projets
          </button>

          <header className="grid gap-5 sm:grid-cols-[200px_1fr] mb-7 items-start">
            {/* Sous sm : le texte (titre, progression) d'abord, le décor après. */}
            <div className="order-2 sm:order-none">
              <ProjectFolderVisual color={selected.color || FALLBACK_COLOR} height="h-28 sm:h-44" />
              {/* Les photos, sous le dossier : une seule pile, toutes les
                  catégories empilées derrière. Choix du 13 septembre 2026,
                  contre une section pleine largeur avant l'arbre. */}
              <PilesPhotos
                projectId={selected.id}
                tasks={projectTasks}
                tacheAOuvrir={photosDeTache}
                onTacheOuverte={surTacheOuverte}
                onParTache={surPhotosParTache}
              />
            </div>
            <div className="order-1 sm:order-none">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>Succès</span>
                {saving && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}
              </div>
              <div className="flex flex-wrap items-start gap-3">
                <h1 className="text-2xl font-semibold flex-1 min-w-0" style={{ color: 'var(--color-text)' }}>{selected.name}</h1>
                <div className="flex gap-1">
                  <button type="button" onClick={() => edit(selected)} className="rounded-lg p-2 cursor-pointer" style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-bg-secondary)' }} aria-label="Modifier">
                    <Pencil size={14} />
                  </button>
                  <button type="button" onClick={() => void remove(selected)} className="rounded-lg p-2 cursor-pointer" style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-bg-secondary)' }} aria-label="Supprimer">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {selected.description && (
                <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>{selected.description}</p>
              )}
              <div className="flex flex-wrap gap-3 mt-3 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                <span>{structureLabel}</span>
                {isTreeFamily && (
                  <button
                    type="button"
                    onClick={() => setTreeEditMode((mode) => !mode)}
                    className="cursor-pointer underline-offset-2 hover:underline"
                    style={{ color: 'var(--color-accent)' }}
                  >
                    {treeEditMode
                      ? structure === 'mindmap'
                        ? 'Voir la carte'
                        : 'Voir la généalogie'
                      : 'Éditer les branches'}
                  </button>
                )}
                {selected.startDate && <span>Début {selected.startDate}</span>}
                {selected.endDate && <span>Fin {selected.endDate}</span>}
                {tachesConnues ? (
                  <>
                    <span>{doneCount}/{projectTasks.length || selected.taskTotal} terminée(s)</span>
                    <span>{openCount} ouverte(s)</span>
                  </>
                ) : (
                  <Loader2 size={12} className="animate-spin" aria-label="Chargement des tâches" />
                )}
              </div>
              <div className="mt-4 h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-secondary)' }}>
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${progress}%`,
                    background: selected.color || 'var(--color-accent)',
                  }}
                />
              </div>
              <p className="text-xs mt-1.5" style={{ color: 'var(--color-text-tertiary)' }}>{progress}% d’avancement</p>
            </div>
          </header>

          <NotesDuProjet projectId={selected.id} />

          {showForm && editingId === selected.id && (
            <section className="grid gap-3 rounded-2xl p-4 mb-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}>
              <input autoFocus value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} maxLength={200} placeholder="Nom du projet" className="rounded-xl px-3 py-2.5 bg-transparent outline-none" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
              <div className="flex flex-wrap items-center gap-2">
                {COLOR_PRESETS.map((preset) => (
                  <button key={preset} type="button" onClick={() => setDraft({ ...draft, color: preset })} aria-label={`Couleur ${preset}`} className="size-6 rounded-full cursor-pointer" style={{ background: preset, boxShadow: draft.color.toLowerCase() === preset ? `0 0 0 2px var(--color-surface), 0 0 0 4px ${preset}` : undefined }} />
                ))}
                <input type="color" value={draft.color} onChange={(event) => setDraft({ ...draft, color: event.target.value })} className="size-8 rounded-lg bg-transparent cursor-pointer" style={{ border: '1px solid var(--color-border)' }} />
              </div>
              <textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={3} maxLength={4000} placeholder="Description…" className="rounded-xl px-3 py-2 bg-transparent outline-none resize-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="grid gap-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Début<input type="date" value={draft.startDate} onChange={(event) => setDraft({ ...draft, startDate: event.target.value })} className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} /></label>
                <label className="grid gap-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Fin<input type="date" value={draft.endDate} onChange={(event) => setDraft({ ...draft, endDate: event.target.value })} className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} /></label>
              </div>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => void closeForm()} className="px-3 py-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>Annuler</button>
                <button type="button" disabled={!draft.name.trim() || saving} onClick={() => void save()} className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>Mettre à jour</button>
              </div>
            </section>
          )}

          {structure === 'tree' && !treeEditMode ? (
            <GenealogyView
              onSelect={(task) => {
                // Une racine s'ouvre en Ligne ; une branche garde l'aperçu.
                if (!task.parentTaskId) setEtapeLigneId(task.id);
                else setInspected(task);
              }}
              tasks={projectTasks}
              levelLabels={levelLabels}
              verrous={verrous}
              saving={saving}
              onToggle={async (task) => {
                await refreshAfter(
                  () => setSuccesTaskDone(task.id, !task.done),
                  task.done ? 'Branche rouverte' : 'Branche terminée',
                );
              }}
              onCreate={async ({ title, parentTaskId }) => {
                await refreshAfter(
                  () =>
                    createSuccesTask({
                      title,
                      projectId: selected.id,
                      parentTaskId: parentTaskId || '',
                    }),
                  parentTaskId ? 'Branche ajoutée' : 'Racine ajoutée',
                );
              }}
            />
          ) : structure === 'mindmap' && !treeEditMode ? (
            <MindMapView
              onSelect={setInspected}
              tasks={projectTasks}
              projectName={selected.name}
              saving={saving}
              onToggle={async (task) => {
                await refreshAfter(
                  () => setSuccesTaskDone(task.id, !task.done),
                  task.done ? 'Idée rouverte' : 'Idée accomplie',
                );
              }}
              onCreate={async ({ title, parentTaskId }) => {
                await refreshAfter(
                  () =>
                    createSuccesTask({
                      title,
                      projectId: selected.id,
                      parentTaskId: parentTaskId || '',
                    }),
                  'Branche ajoutée',
                );
              }}
            />
          ) : structure === 'pipeline' ? (
            <PipelineBoard
              onSelect={setInspected}
              tasks={projectTasks}
              stages={projectStages}
              saving={saving}
              onMove={async (task, stage) => {
                await refreshAfter(
                  () => updateSuccesTask(task.id, { stage }),
                  `Déplacée vers « ${stage} »`,
                );
              }}
              onCreate={async ({ title, stage }) => {
                await refreshAfter(
                  () =>
                    createSuccesTask({
                      title,
                      projectId: selected.id,
                      stage: stage || projectStages[0],
                    }),
                  'Carte ajoutée',
                );
              }}
            />
          ) : structure === 'network' ? (
            <NetworkView
              onSelect={(task) => setInspectedId(task.id)}
              miseEnAvantId={inspectedId}
              liaisonDemandee={liaisonDemandee}
              // Sans les arêtes, le raisonnement « faisable / bloquée » n'a
              // plus de fondement : on n'affiche aucune tâche plutôt que de
              // toutes les déclarer faisables.
              tasks={edgesFailed ? [] : projectTasks}
              edges={edges}
              saving={saving}
              onToggle={async (task) => {
                await refreshAfter(
                  () => setSuccesTaskDone(task.id, !task.done),
                  phraseBasculeReseau(task),
                );
              }}
              onLink={async (fromTaskId, toTaskId) => {
                await refreshAfter(async () => {
                  await createSuccesTaskEdge(selected.id, fromTaskId, toTaskId);
                  await loadEdges();
                }, 'Dépendance ajoutée');
              }}
              onUnlink={async (fromTaskId, toTaskId) => {
                await refreshAfter(async () => {
                  await deleteSuccesTaskEdge(selected.id, fromTaskId, toTaskId);
                  await loadEdges();
                }, 'Dépendance retirée');
              }}
              onCreate={async ({ title }) => {
                await refreshAfter(
                  () => createSuccesTask({ title, projectId: selected.id }),
                  'Tâche ajoutée',
                );
              }}
            />
          ) : structure === 'cycle' ? (
            <CycleWheel
              onSelect={setInspected}
              tasks={projectTasks}
              saving={saving}
              onToggle={async (task) => {
                await refreshAfter(
                  () => setSuccesTaskDone(task.id, !task.done),
                  task.done ? 'Routine rouverte' : 'Routine faite',
                );
              }}
              onReset={async () => {
                await refreshAfter(async () => {
                  const { reopened } = await resetSuccesProjectCycle(selected.id);
                  return reopened;
                }, 'Nouveau tour — tout est décoché');
              }}
              onCreate={async ({ title, cadence }) => {
                await refreshAfter(
                  () =>
                    createSuccesTask({
                      title,
                      projectId: selected.id,
                      cadence: cadence ?? null,
                    }),
                  'Routine ajoutée',
                );
              }}
            />
          ) : isTreeFamily ? (
            <ProjectTreeView
              tasks={projectTasks}
              saving={saving}
              verrous={verrous}
              onCreate={async ({ title, notes, parentTaskId }) => {
                await refreshAfter(
                  () =>
                    createSuccesTask({
                      title,
                      notes,
                      projectId: selected.id,
                      parentTaskId: parentTaskId || '',
                    }),
                  parentTaskId ? 'Branche ajoutée' : 'Racine ajoutée',
                );
              }}
              onToggle={async (task) => {
                await refreshAfter(
                  () => setSuccesTaskDone(task.id, !task.done),
                  task.done ? 'Branche rouverte' : 'Branche terminée',
                );
              }}
              onUpdate={async (task, patch) => {
                const clean = Object.fromEntries(
                  Object.entries(patch).filter(([, value]) => value !== undefined),
                );
                if (Object.keys(clean).length === 0) return;
                await refreshAfter(() => updateSuccesTask(task.id, clean), 'Branche mise à jour');
              }}
              onDelete={async (task) => {
                const confirmed = await confirm({
                  title: `Supprimer « ${task.title} » ?`,
                  description: 'Les sous-branches restent sauf si vous les supprimez aussi.',
                  confirmLabel: 'Supprimer',
                  keepLabel: 'Garder',
                  tone: 'danger',
                });
                if (!confirmed) return;
                await refreshAfter(() => deleteSuccesTask(task.id), 'Branche supprimée');
              }}
            />
          ) : (
            <>
              <section className="flex gap-2 mb-5">
                <input
                  value={quickTitle}
                  onChange={(event) => setQuickTitle(event.target.value)}
                  onKeyDown={(event) => { if (event.key === 'Enter') void createTaskForProject(); }}
                  placeholder="Ajouter une tâche à ce projet…"
                  maxLength={200}
                  className="flex-1 rounded-xl px-3 py-2.5 text-sm bg-transparent outline-none"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
                <button
                  type="button"
                  disabled={!quickTitle.trim() || saving}
                  onClick={() => void createTaskForProject()}
                  className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
                  style={{ background: 'var(--color-accent)', color: '#fff' }}
                >
                  <CirclePlus size={16} /> Ajouter
                </button>
              </section>

              {loading ? (
                <div className="flex justify-center gap-2 py-16 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                  <Loader2 size={17} className="animate-spin" /> Chargement…
                </div>
              ) : !tachesConnues ? (
                <div className="flex justify-center gap-2 py-16 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                  <Loader2 size={17} className="animate-spin" /> Chargement des tâches…
                </div>
              ) : projectTasks.length === 0 ? (
                <CadreVitre className="rounded-2xl py-14 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
                  <BriefcaseBusiness size={28} className="mx-auto mb-3" style={{ color: selected.color || 'var(--color-accent)' }} />
                  <p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucune tâche dans ce projet</p>
                  <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Ajoutez-en une ci-dessus, ou assignez-en une depuis Tâches.</p>
                </CadreVitre>
              ) : (
                <div className="grid gap-3">
                  {projectTasks.map((task) => (
                    <TaskCard
                      key={task.id}
                      task={task}
                      projects={projects}
                      onToggleTask={async (item) => {
                        await refreshAfter(() => setSuccesTaskDone(item.id, !item.done), item.done ? 'Tâche rouverte' : 'Tâche terminée');
                      }}
                      onToggleSubtask={async (item, subtask: SuccesSubtask) => {
                        await refreshAfter(() => setSuccesSubtaskDone(item.id, subtask.id, !subtask.done), 'Sous-tâche mise à jour');
                      }}
                      // `null` sur un échec : la carte garde alors son brouillon
                      // au lieu de le vider comme après un succès.
                      onAddSubtask={async (item, title, parentId) =>
                        (await refreshAfter(() => addSuccesSubtask(item.id, title, parentId), 'Sous-tâche ajoutée')) ? undefined : null
                      }
                      onAssignProject={async (item, projectId) => {
                        await refreshAfter(() => updateSuccesTask(item.id, { projectId }), projectId ? 'Tâche réassignée' : 'Tâche retirée du projet');
                      }}
                      onUpdate={async (item, patch: SuccesTaskPatch) =>
                        (await refreshAfter(() => updateSuccesTask(item.id, patch), 'Tâche mise à jour')) ? undefined : null
                      }
                      onReschedule={rescheduleTask}
                      onDelete={async (item) => {
                        await refreshAfter(() => deleteSuccesTask(item.id), 'Tâche supprimée');
                      }}
                    />
                  ))}
                </div>
              )}
            </>
          )}
          {(() => {
            // L'étape se RELIT à chaque rendu : après un enregistrement, la
            // superposition reflète les tâches fraîches, pas une photo figée.
            const etapeLigne = etapeLigneId
              ? projectTasks.find((t) => t.id === etapeLigneId) ?? null
              : null;
            return etapeLigne ? (
              <LigneEtape
                etape={etapeLigne}
                tasks={projectTasks}
                saving={saving}
                verrous={verrous}
                photosParTache={photosParTache}
                onVoirPhotos={(taskId) => {
                  // La Ligne se referme : la pile s'ouvre par-dessus la
                  // fiche, pas par-dessus la Ligne.
                  setEtapeLigneId(null);
                  setPhotosDeTache(taskId);
                }}
                onClose={() => setEtapeLigneId(null)}
                onNavigate={setEtapeLigneId}
                onToggle={async (task) => {
                  await refreshAfter(
                    () => setSuccesTaskDone(task.id, !task.done),
                    task.done ? 'Station rouverte' : 'Station franchie',
                  );
                }}
                onUpdate={async (taskId, patch, options) => {
                  const ok = await refreshAfter(
                    () => updateSuccesTask(taskId, patch),
                    options?.silencieux ? null : 'Étape mise à jour',
                  );
                  // Le carnet (silencieux) ne doit jamais croire enregistré
                  // ce que le serveur a refusé : l'échec lui est relancé.
                  if (!ok) throw new Error("L'étape n'a pas été enregistrée.");
                }}
                onCreate={async ({ title, parentTaskId }) => {
                  await refreshAfter(
                    () =>
                      createSuccesTask({
                        title,
                        projectId: selected.id,
                        parentTaskId,
                      }),
                    'Sous-étape ajoutée',
                  );
                }}
              />
            ) : null;
          })()}
          {(() => {
            // La fiche « Branches » du réseau, relue dans les tâches fraîches
            // (§100). Les autres structures gardent l'aside ci-dessous.
            if (structure !== 'network' || !inspectedId || edgesFailed) return null;
            if (!projectTasks.some((t) => t.id === inspectedId)) return null;
            return (
              <FicheBranches
                tacheId={inspectedId}
                tasks={projectTasks}
                edges={edges}
                saving={saving}
                onFermer={() => setInspectedId(null)}
                onNaviguer={setInspectedId}
                onToggle={async (task) => {
                  await refreshAfter(
                    () => setSuccesTaskDone(task.id, !task.done),
                    phraseBasculeReseau(task),
                  );
                }}
                onRelierDepuis={(task) => {
                  setInspectedId(null);
                  setLiaisonDemandee({ sourceId: task.id, jeton: Date.now() });
                }}
                onSupprimer={async (task) => {
                  const confirme = await confirm({
                    title: `Supprimer « ${task.title} » ?`,
                    description: 'Cette tâche et ses liens disparaîtront.',
                    confirmLabel: 'Supprimer',
                    keepLabel: 'Garder',
                    tone: 'danger',
                  });
                  if (!confirme) return;
                  const ok = await refreshAfter(() => deleteSuccesTask(task.id), 'Tâche supprimée');
                  if (ok) setInspectedId(null);
                  await loadEdges();
                }}
                onEnregistrerCarnet={async (taskId, journal) => {
                  const ok = await refreshAfter(() => updateSuccesTask(taskId, { journal }), null);
                  // Le carnet ne doit jamais croire enregistré ce que le
                  // serveur a refusé : l'échec lui est relancé.
                  if (!ok) throw new Error("Le carnet n'a pas été enregistré.");
                }}
                onChangerCategorie={async (taskId, category) => {
                  // Le couloir du réseau : la fiche relit la catégorie dans
                  // les tâches rechargées, le toast ne dit rien de plus.
                  await refreshAfter(
                    () => updateSuccesTask(taskId, { category }),
                    category ? 'Couloir mis à jour' : 'Couloir retiré',
                  );
                }}
              />
            );
          })()}
          {inspected && (
            <aside
              className="fixed bottom-3 inset-x-3 w-auto sm:inset-x-auto sm:right-6 sm:bottom-6 sm:w-80 max-w-full max-h-[min(60vh,420px)] overflow-y-auto z-30 rounded-2xl p-4 shadow-xl"
              style={{
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <p className="font-medium text-sm" style={{ color: 'var(--color-text)' }}>
                  {inspected.title}
                </p>
                <button
                  type="button"
                  onClick={() => setInspected(null)}
                  aria-label="Fermer"
                  className="cursor-pointer text-xs"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  ✕
                </button>
              </div>
              {inspected.notes && (
                <p className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>
                  {inspected.notes}
                </p>
              )}
              <div className="flex flex-wrap gap-2 mt-3 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                <span>{inspected.done ? 'Terminée' : 'Ouverte'}</span>
                {inspected.stage && <span>Étape : {inspected.stage}</span>}
                {inspected.date && <span>Le {inspected.date}</span>}
              </div>
              <div className="flex gap-2 mt-4">
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => {
                    const cible = inspected;
                    setInspected(null);
                    void refreshAfter(
                      () => setSuccesTaskDone(cible.id, !cible.done),
                      cible.done ? 'Tâche rouverte' : 'Tâche terminée',
                    );
                  }}
                  className="flex-1 rounded-xl px-3 py-2 text-xs font-medium disabled:opacity-50 cursor-pointer"
                  style={{ background: 'var(--color-accent)', color: '#fff' }}
                >
                  {inspected.done ? 'Rouvrir' : 'Terminer'}
                </button>
                <button
                  type="button"
                  disabled={saving}
                  onClick={async () => {
                    const cible = inspected;
                    const confirme = await confirm({
                      title: `Supprimer « ${cible.title} » ?`,
                      description: 'Cette tâche et ses liens disparaîtront.',
                      confirmLabel: 'Supprimer',
                      keepLabel: 'Garder',
                      tone: 'danger',
                    });
                    if (!confirme) return;
                    setInspected(null);
                    await refreshAfter(() => deleteSuccesTask(cible.id), 'Tâche supprimée');
                    await loadEdges();
                  }}
                  className="rounded-xl px-3 py-2 text-xs disabled:opacity-50 cursor-pointer"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                >
                  Supprimer
                </button>
              </div>
            </aside>
          )}
        </main>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-3 py-5 sm:px-5 sm:py-8 md:px-8 md:py-10">
      <main className="max-w-5xl mx-auto w-full">
        <header className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between mb-7">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>Succès</span>
              {saving && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}
            </div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>Projets</h1>
            <p className="text-sm mt-2 max-w-xl" style={{ color: 'var(--color-text-secondary)' }}>Transformez vos objectifs en ensembles d’actions clairs, suivis localement.</p>
          </div>
          <button type="button" onClick={() => { if (showForm) void closeForm(); else setShowForm(true); }} className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>
            <CirclePlus size={16} /> Nouveau projet
          </button>
        </header>

        {/* La même vitre que la rangée de filtres de Tâches (17 sept. 2026). */}
        <CadreVitre as="section"
          className="flex items-center gap-2 rounded-2xl p-2 mb-5"
          style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          aria-label="Recherche de projets"
        >
          <div className="flex items-center gap-2 flex-1 min-w-0 px-2 h-7">
            <Search size={15} className="shrink-0" style={{ color: 'var(--color-text-tertiary)' }} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher un projet…" className="w-full min-w-0 bg-transparent outline-none text-sm" style={{ color: 'var(--color-text)' }} />
          </div>
        </CadreVitre>

        {showForm && (
          <section className="grid gap-3 rounded-2xl p-4 mb-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}>
            <div className="grid gap-4 sm:grid-cols-[240px_1fr]">
              <ProjectFolderVisual color={draft.color} height="h-24 sm:h-48" />
              <div className="grid content-start gap-3">
                <input autoFocus value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} maxLength={200} placeholder="Nom du projet" className="rounded-xl px-3 py-2.5 bg-transparent outline-none" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                <div className="flex flex-wrap items-center gap-2">
                  {COLOR_PRESETS.map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => setDraft({ ...draft, color: preset })}
                      aria-label={`Couleur ${preset}`}
                      aria-pressed={draft.color.toLowerCase() === preset}
                      className="size-6 rounded-full cursor-pointer transition-transform hover:scale-110"
                      style={{
                        background: preset,
                        boxShadow: draft.color.toLowerCase() === preset
                          ? `0 0 0 2px var(--color-surface), 0 0 0 4px ${preset}`
                          : `0 0 10px ${alpha(preset, 0.5)}`,
                      }}
                    />
                  ))}
                  <input type="color" value={draft.color} onChange={(event) => setDraft({ ...draft, color: event.target.value })} aria-label="Couleur personnalisée" className="size-8 rounded-lg bg-transparent cursor-pointer" style={{ border: '1px solid var(--color-border)' }} />
                </div>
              </div>
            </div>
            <textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={3} maxLength={4000} placeholder="Description et résultat attendu…" className="rounded-xl px-3 py-2 bg-transparent outline-none resize-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
            {!editingId && (
              <div className="grid gap-2">
                <p className="text-xs font-medium uppercase tracking-wide" style={{ color: 'var(--color-text-tertiary)' }}>
                  Comment structurer ce projet ?
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {STRUCTURE_OPTIONS.map((option) => {
                    const selectedMode =
                      option.id === 'kit'
                        ? Boolean(draft.kitId)
                        : !draft.kitId && draft.structure === option.id;
                    return (
                      <button
                        key={option.id}
                        type="button"
                        onClick={() => {
                          if (option.id === 'kit') {
                            setDraft({
                              ...draft,
                              kitId: draft.kitId || kits[0]?.id || '',
                            });
                          } else {
                            setDraft({ ...draft, structure: option.id, kitId: '' });
                          }
                        }}
                        className="rounded-xl px-3 py-2.5 text-left cursor-pointer"
                        style={{
                          border: `1px solid ${selectedMode ? 'var(--color-accent)' : 'var(--color-border)'}`,
                          background: selectedMode ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)' : 'transparent',
                        }}
                      >
                        <span className="block text-sm font-medium" style={{ color: 'var(--color-text)' }}>{option.label}</span>
                        <span className="block text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>{option.hint}</span>
                      </button>
                    );
                  })}
                </div>
                {Boolean(draft.kitId) && (
                  <div className="grid gap-2 sm:grid-cols-3">
                    {kits.map((kit) => {
                      const active = draft.kitId === kit.id;
                      return (
                        <button
                          key={kit.id}
                          type="button"
                          onClick={() => setDraft({ ...draft, kitId: kit.id })}
                          className="rounded-xl px-3 py-2.5 text-left cursor-pointer"
                          style={{
                            border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-border)'}`,
                            background: active ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)' : 'transparent',
                          }}
                        >
                          <span className="block text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                            {kit.icon ? `${kit.icon} ` : ''}{kit.name}
                          </span>
                          <span className="block text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                            {kit.description}
                          </span>
                          <span className="block text-[11px] mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                            {kit.nodeCount} branches
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
                {/* Demandé le 6 septembre 2026 : « si je n'ai pas accédé à la
                    tâche avant, je ne peux pas accéder aux autres ». Le
                    réglage vit sur le PROJET et pas dans les préférences de
                    l'application : un parcours d'apprentissage se fait pas à
                    pas, un projet de déménagement non. Et il s'éteint — un
                    verrou dont on ne peut pas sortir enferme au premier faux
                    pas, par exemple en attendant une réponse qui ne vient
                    pas. */}
                {(draft.structure === 'tree' || draft.structure === 'mindmap') &&
                  !draft.kitId && (
                    <label
                      className="flex items-start gap-3 rounded-xl px-3 py-2.5 cursor-pointer"
                      style={{ border: '1px solid var(--color-border)' }}
                    >
                      <input
                        type="checkbox"
                        checked={draft.sequential}
                        onChange={(event) =>
                          setDraft({ ...draft, sequential: event.target.checked })
                        }
                        className="mt-0.5 cursor-pointer"
                      />
                      <span className="grid gap-0.5">
                        <span
                          className="text-sm font-medium"
                          style={{ color: 'var(--color-text)' }}
                        >
                          Progression séquentielle
                        </span>
                        <span
                          className="text-xs"
                          style={{ color: 'var(--color-text-tertiary)' }}
                        >
                          Dans une même liste, une tâche attend que celle qui la
                          précède soit cochée ; son contenu reste fermé jusque-là.
                          Les branches racines, elles, restent toutes ouvertes.
                        </span>
                      </span>
                    </label>
                  )}
              </div>
            )}
            <div className="grid sm:grid-cols-2 gap-3">
              <label className="grid gap-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Début<input type="date" value={draft.startDate} onChange={(event) => setDraft({ ...draft, startDate: event.target.value })} className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} /></label>
              <label className="grid gap-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Fin<input type="date" value={draft.endDate} onChange={(event) => setDraft({ ...draft, endDate: event.target.value })} className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} /></label>
            </div>
            {/* Barre ancrée au bas du formulaire. Le sélecteur de forme a
                fait passer ce panneau de 3 tuiles sur une ligne à 7 sur
                quatre : le bouton se retrouvait à 782 px dans une fenêtre de
                720, donc hors d'atteinte sans faire défiler — et personne ne
                devine qu'il faut faire défiler un formulaire qui a l'air
                entier. Le formulaire grandira encore ; la barre reste. */}
            <div
              className="flex justify-end gap-2 sticky bottom-0 -mx-5 px-5 py-3 mt-1"
              style={{
                background: 'var(--color-surface)',
                borderTop: '1px solid var(--color-border)',
              }}
            >
              <button type="button" onClick={() => void closeForm()} className="px-3 py-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>Annuler</button>
              <button type="button" disabled={!draft.name.trim() || saving} onClick={() => void save()} className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>{editingId ? 'Mettre à jour' : 'Créer le projet'}</button>
            </div>
          </section>
        )}

        {loading ? (
          <div className="flex justify-center gap-2 py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}><Loader2 size={17} className="animate-spin" /> Chargement des projets…</div>
        ) : projects.length === 0 ? (
          <CadreVitre className="rounded-2xl py-16 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}><BriefcaseBusiness size={28} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} /><p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucun projet</p><p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Créez votre premier projet ou demandez-le à DIA.</p></CadreVitre>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-4 gap-y-2">
            {projects.map((project) => (
              <article
                key={project.id}
                draggable={!search.trim()}
                onDragStart={(event) => {
                  event.dataTransfer.setData('application/x-diapason-projet', project.id);
                  event.dataTransfer.setData('text/plain', project.id);
                  event.dataTransfer.effectAllowed = 'move';
                }}
                onDragOver={(event) => {
                  if (search.trim()) return;
                  event.preventDefault();
                  setCibleProjet(project.id);
                }}
                onDragLeave={() => setCibleProjet((c) => (c === project.id ? null : c))}
                onDrop={(event) => {
                  const id =
                    event.dataTransfer.getData('application/x-diapason-projet') ||
                    event.dataTransfer.getData('text/plain');
                  setCibleProjet(null);
                  if (!id || id === project.id) return;
                  event.preventDefault();
                  void placerProjetAvant(id, project.id);
                }}
                className="group relative flex flex-col items-center rounded-2xl transition-shadow"
                style={{
                  WebkitUserDrag: search.trim() ? 'none' : 'element',
                  boxShadow: cibleProjet === project.id ? 'inset 0 0 0 2px var(--color-accent)' : undefined,
                } as React.CSSProperties}
              >
                <button
                  type="button"
                  onClick={() => setSelectedId(project.id)}
                  className="w-full cursor-pointer bg-transparent border-0 p-0 text-inherit"
                  aria-label={`Ouvrir ${project.name}`}
                >
                  <ProjectFolderVisual
                    color={project.color || FALLBACK_COLOR}
                    height="h-[188px]"
                    structure={project.structure || 'flat'}
                  />
                  <h2
                    className="max-w-full truncate text-sm font-medium text-center px-2 pb-1"
                    title={project.name}
                    style={{ color: 'var(--color-text)' }}
                  >
                    {project.name}
                  </h2>
                  <p className="text-[11px] pb-4" style={{ color: 'var(--color-text-tertiary)' }}>
                    {project.taskCompleted}/{project.taskTotal} · {project.taskTotal ? Math.round((project.taskCompleted / project.taskTotal) * 100) : 0}%
                  </p>
                </button>

                {!search.trim() && (
                  <div className="absolute left-1 top-1 flex gap-0.5 max-sm:opacity-100 compact:opacity-100 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                    <button
                      type="button"
                      onClick={(event) => { event.stopPropagation(); void decalerProjet(project, 'avant'); }}
                      aria-label={`Déplacer ${project.name} avant`}
                      title="Déplacer avant"
                      className="rounded-lg p-1.5 cursor-pointer"
                      style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-surface)' }}
                    >
                      <ChevronLeft size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={(event) => { event.stopPropagation(); void decalerProjet(project, 'apres'); }}
                      aria-label={`Déplacer ${project.name} après`}
                      title="Déplacer après"
                      className="rounded-lg p-1.5 cursor-pointer"
                      style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-surface)' }}
                    >
                      <ChevronRight size={13} />
                    </button>
                  </div>
                )}
                <div className="absolute right-1 top-1 flex gap-0.5 max-sm:opacity-100 compact:opacity-100 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                  <button
                    type="button"
                    onClick={(event) => { event.stopPropagation(); edit(project); }}
                    aria-label={`Modifier ${project.name}`}
                    className="rounded-lg p-1.5 cursor-pointer"
                    style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-surface)' }}
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={(event) => { event.stopPropagation(); void remove(project); }}
                    aria-label={`Supprimer ${project.name}`}
                    className="rounded-lg p-1.5 cursor-pointer"
                    style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-surface)' }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
