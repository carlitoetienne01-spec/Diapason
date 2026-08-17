import { useCallback, useEffect, useId, useState, type PointerEvent } from 'react';
import {
  BriefcaseBusiness,
  ChevronLeft,
  CirclePlus,
  Loader2,
  Pencil,
  Search,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  addSuccesSubtask,
  createSuccesProject,
  createSuccesTask,
  deleteSuccesProject,
  deleteSuccesTask,
  listSuccesProjects,
  listSuccesTasks,
  rescheduleSuccesTask,
  setSuccesSubtaskDone,
  setSuccesTaskDone,
  updateSuccesProject,
  updateSuccesTask,
} from '../features/succes/api';
import { TaskCard, type SuccesTaskPatch } from '../features/succes/TaskCard';
import type { SuccesProject, SuccesSubtask, SuccesTask } from '../features/succes/types';
import { useConfirm } from '../components/ConfirmDialog';
import { useAppStore } from '../lib/store';

const FALLBACK_COLOR = '#6366f1';

const COLOR_PRESETS = [
  '#6366f1', '#38bdf8', '#22c55e', '#14b8a6',
  '#f59e0b', '#ef4444', '#ec4899', '#a855f7',
];

const emptyDraft = {
  name: '', description: '', icon: '', color: FALLBACK_COLOR, startDate: '', endDate: '',
};

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
function ProjectFolderVisual({ color, height = 'h-72' }: { color: string; height?: string }) {
  const isLight = useIsLightTheme();
  const tone = readableColor(color || FALLBACK_COLOR, isLight);
  const palette = folderPalette(tone, isLight);
  const rawId = useId();
  const uid = rawId.replace(/[^a-zA-Z0-9]/g, '');
  const ref = (name: string) => `${uid}-${name}`;
  const [tilt, setTilt] = useState({ x: 0, y: 0, glareX: 50, glareY: 42 });
  const [active, setActive] = useState(false);

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
      </div>
    </div>
  );
}

export function SuccesProjectsPage() {
  const confirm = useConfirm();
  const [projects, setProjects] = useState<SuccesProject[]>([]);
  const [tasks, setTasks] = useState<SuccesTask[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState(emptyDraft);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [quickTitle, setQuickTitle] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextProjects, nextTasks] = await Promise.all([
        listSuccesProjects(search),
        listSuccesTasks({ includeDone: true }),
      ]);
      setProjects(nextProjects);
      setTasks(nextTasks);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `Projets : ${message}` });
      toast.error('Les projets ne peuvent pas être chargés.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load]);

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
  const projectTasks = selected
    ? tasks.filter((task) => task.projectId === selected.id)
    : [];
  const openCount = projectTasks.filter((task) => !task.done).length;
  const doneCount = projectTasks.filter((task) => task.done).length;
  const progress = projectTasks.length
    ? Math.round((doneCount / projectTasks.length) * 100)
    : 0;

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
        draft.endDate,
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
    });
    setEditingId(project.id);
    setShowForm(true);
  };

  const save = async () => {
    if (!draft.name.trim()) return;
    setSaving(true);
    try {
      if (editingId) await updateSuccesProject(editingId, draft);
      else await createSuccesProject(draft);
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

  const loadTasks = useCallback(async () => {
    try {
      setTasks(await listSuccesTasks({ includeDone: true }));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error('Les tâches ne peuvent pas être chargées.', { description: message });
    }
  }, []);

  const refreshAfter = async (action: () => Promise<unknown>, success: string) => {
    setSaving(true);
    try {
      await action();
      await loadTasks();
      toast.success(success, { description: 'Enregistré localement sur ce Mac.' });
    } catch (error) {
      toast.error("L'action n'a pas été enregistrée.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const createTaskForProject = async () => {
    if (!selected || !quickTitle.trim()) return;
    await refreshAfter(
      () => createSuccesTask({ title: quickTitle.trim(), projectId: selected.id }),
      `Tâche ajoutée à « ${selected.name} »`,
    );
    setQuickTitle('');
  };

  if (selected) {
    return (
      <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
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
            <ProjectFolderVisual color={selected.color || FALLBACK_COLOR} height="h-44" />
            <div>
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
                {selected.startDate && <span>Début {selected.startDate}</span>}
                {selected.endDate && <span>Fin {selected.endDate}</span>}
                <span>{doneCount}/{projectTasks.length || selected.taskTotal} terminée(s)</span>
                <span>{openCount} ouverte(s)</span>
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
          ) : projectTasks.length === 0 ? (
            <div className="rounded-2xl py-14 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
              <BriefcaseBusiness size={28} className="mx-auto mb-3" style={{ color: selected.color || 'var(--color-accent)' }} />
              <p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucune tâche dans ce projet</p>
              <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Ajoutez-en une ci-dessus, ou assignez-en une depuis Tâches.</p>
            </div>
          ) : (
            <div className="grid gap-3">
              {projectTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  projects={projects}
                  onToggleTask={(item) => refreshAfter(() => setSuccesTaskDone(item.id, !item.done), item.done ? 'Tâche rouverte' : 'Tâche terminée')}
                  onToggleSubtask={(item, subtask: SuccesSubtask) =>
                    refreshAfter(() => setSuccesSubtaskDone(item.id, subtask.id, !subtask.done), 'Sous-tâche mise à jour')
                  }
                  onAddSubtask={(item, title, parentId) =>
                    refreshAfter(() => addSuccesSubtask(item.id, title, parentId), 'Sous-tâche ajoutée')
                  }
                  onAssignProject={(item, projectId) =>
                    refreshAfter(() => updateSuccesTask(item.id, { projectId }), projectId ? 'Tâche réassignée' : 'Tâche retirée du projet')
                  }
                  onUpdate={(item, patch: SuccesTaskPatch) =>
                    refreshAfter(() => updateSuccesTask(item.id, patch), 'Tâche mise à jour')
                  }
                  onReschedule={async (item, date) => {
                    setSaving(true);
                    try {
                      const result = await rescheduleSuccesTask(item.id, date);
                      await load();
                      toast.success(`Reportée au ${date}`, {
                        description: result.warning || 'Enregistré localement sur ce Mac.',
                      });
                    } catch (error) {
                      toast.error('Le report a échoué.', {
                        description: error instanceof Error ? error.message : String(error),
                      });
                    } finally {
                      setSaving(false);
                    }
                  }}
                  onDelete={async (item) => {
                    const ok = await confirm({
                      title: `Supprimer « ${item.title} » ?`,
                      confirmLabel: 'Supprimer',
                      keepLabel: 'Garder',
                      tone: 'danger',
                    });
                    if (!ok) return;
                    return refreshAfter(() => deleteSuccesTask(item.id), `Tâche supprimée : ${item.title}`);
                  }}
                />
              ))}
            </div>
          )}
        </main>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
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

        <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 mb-5" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <Search size={15} style={{ color: 'var(--color-text-tertiary)' }} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher un projet…" className="w-full bg-transparent outline-none text-sm" style={{ color: 'var(--color-text)' }} />
        </div>

        {showForm && (
          <section className="grid gap-3 rounded-2xl p-4 mb-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}>
            <div className="grid gap-4 sm:grid-cols-[240px_1fr]">
              <ProjectFolderVisual color={draft.color} height="h-48" />
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
            <div className="grid sm:grid-cols-2 gap-3">
              <label className="grid gap-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Début<input type="date" value={draft.startDate} onChange={(event) => setDraft({ ...draft, startDate: event.target.value })} className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} /></label>
              <label className="grid gap-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Fin<input type="date" value={draft.endDate} onChange={(event) => setDraft({ ...draft, endDate: event.target.value })} className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} /></label>
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => void closeForm()} className="px-3 py-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>Annuler</button>
              <button type="button" disabled={!draft.name.trim() || saving} onClick={() => void save()} className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>{editingId ? 'Mettre à jour' : 'Créer le projet'}</button>
            </div>
          </section>
        )}

        {loading ? (
          <div className="flex justify-center gap-2 py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}><Loader2 size={17} className="animate-spin" /> Chargement des projets…</div>
        ) : projects.length === 0 ? (
          <div className="rounded-2xl py-16 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}><BriefcaseBusiness size={28} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} /><p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucun projet</p><p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Créez votre premier projet ou demandez-le à DIA.</p></div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-4 gap-y-2">
            {projects.map((project) => (
              <article key={project.id} className="group relative flex flex-col items-center">
                <button
                  type="button"
                  onClick={() => setSelectedId(project.id)}
                  className="w-full cursor-pointer bg-transparent border-0 p-0 text-inherit"
                  aria-label={`Ouvrir ${project.name}`}
                >
                  <ProjectFolderVisual color={project.color || FALLBACK_COLOR} height="h-[188px]" />
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

                <div className="absolute right-1 top-1 flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
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
