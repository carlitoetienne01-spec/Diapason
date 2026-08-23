import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Check, CirclePlus, Loader2, Plus } from 'lucide-react';

import { buildProjectTaskTree, type ProjectTreeNode } from './ProjectTreeView';
import { planifierRafale, type Impulsion } from './synapses';
import type { SuccesTask } from './types';

/** Nombre maximal d'étages affichés ; au-delà, un compteur « +N » sur le dernier étage. */
const MAX_VISIBLE_LEVELS = 6;
const DEFAULT_LEVEL_LABELS = ['Objectif', 'Livrables', 'Actions', 'Micro-pas'];

type GenealogyViewProps = {
  tasks: SuccesTask[];
  levelLabels: string[];
  saving?: boolean;
  onToggle: (task: SuccesTask) => Promise<void>;
  onCreate: (input: { title: string; parentTaskId?: string }) => Promise<void>;
  onSelect?: (task: SuccesTask) => void;
};

type SubtreeStats = { total: number; done: number };

type LevelItem = {
  node: ProjectTreeNode;
  parentId: string | null;
  stats: SubtreeStats;
  hiddenCount: number;
  /** Au dernier étage affiché : un enfant créé ici serait invisible. */
  atDepthLimit: boolean;
};

type Edge = {
  id: string;
  parentId: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

/** La courbe en S d'une arête — inversée quand l'information remonte. */
function cheminArete(edge: Edge, descend: boolean): string {
  const midY = (edge.y1 + edge.y2) / 2;
  return descend
    ? `M ${edge.x1} ${edge.y1} C ${edge.x1} ${midY}, ${edge.x2} ${midY}, ${edge.x2} ${edge.y2}`
    : `M ${edge.x2} ${edge.y2} C ${edge.x2} ${midY}, ${edge.x1} ${midY}, ${edge.x1} ${edge.y1}`;
}

/** Compte les descendants (tous niveaux confondus) de chaque nœud du sous-arbre. */
function collectStats(node: ProjectTreeNode, into: Map<string, SubtreeStats>): SubtreeStats {
  let total = 0;
  let done = 0;
  for (const child of node.children) {
    const childStats = collectStats(child, into);
    total += 1 + childStats.total;
    done += (child.done ? 1 : 0) + childStats.done;
  }
  const stats: SubtreeStats = { total, done };
  into.set(node.id, stats);
  return stats;
}

function levelLabelFor(depth: number, levelLabels: string[]): string {
  const custom = levelLabels[depth];
  if (custom && custom.trim()) return custom.trim();
  const fallback = DEFAULT_LEVEL_LABELS[depth];
  return fallback ?? `Niveau ${depth + 1}`;
}

export function GenealogyView({
  tasks,
  levelLabels,
  saving = false,
  onToggle,
  onCreate,
  onSelect,
}: GenealogyViewProps) {
  const rows = useMemo<LevelItem[][]>(() => {
    const roots = buildProjectTaskTree(tasks);
    const stats = new Map<string, SubtreeStats>();
    for (const root of roots) collectStats(root, stats);

    const built: LevelItem[][] = [];
    let current: Array<{ node: ProjectTreeNode; parentId: string | null }> = roots.map(
      (node) => ({ node, parentId: null }),
    );
    let depth = 0;
    while (current.length > 0 && depth < MAX_VISIBLE_LEVELS) {
      const lastVisible = depth === MAX_VISIBLE_LEVELS - 1;
      built.push(
        current.map(({ node, parentId }) => ({
          node,
          parentId,
          stats: stats.get(node.id) ?? { total: 0, done: 0 },
          hiddenCount: lastVisible ? (stats.get(node.id)?.total ?? 0) : 0,
          atDepthLimit: lastVisible,
        })),
      );
      const next: Array<{ node: ProjectTreeNode; parentId: string | null }> = [];
      for (const { node } of current) {
        for (const child of node.children) next.push({ node: child, parentId: node.id });
      }
      current = next;
      depth += 1;
    }
    return built;
  }, [tasks]);

  const [addingFor, setAddingFor] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState('');
  const [edges, setEdges] = useState<Edge[]>([]);
  const [canvasSize, setCanvasSize] = useState({ width: 1, height: 1 });

  const canvasRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef(new Map<string, HTMLDivElement>());

  const setCardRef = useCallback(
    (id: string) => (el: HTMLDivElement | null) => {
      if (el) cardRefs.current.set(id, el);
      else cardRefs.current.delete(id);
    },
    [],
  );

  /** Mesure les cartes et retrace les traits parent → enfant. */
  const recompute = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const canvasRect = canvas.getBoundingClientRect();
    const next: Edge[] = [];
    for (const row of rows) {
      for (const item of row) {
        if (!item.parentId) continue;
        const childEl = cardRefs.current.get(item.node.id);
        const parentEl = cardRefs.current.get(item.parentId);
        if (!childEl || !parentEl) continue;
        const childRect = childEl.getBoundingClientRect();
        const parentRect = parentEl.getBoundingClientRect();
        next.push({
          id: item.node.id,
          parentId: item.parentId,
          x1: parentRect.left + parentRect.width / 2 - canvasRect.left,
          y1: parentRect.bottom - canvasRect.top,
          x2: childRect.left + childRect.width / 2 - canvasRect.left,
          y2: childRect.top - canvasRect.top,
        });
      }
    }
    setEdges(next);
    setCanvasSize({
      width: Math.max(1, Math.round(canvasRect.width)),
      height: Math.max(1, Math.round(canvasRect.height)),
    });
  }, [rows]);

  useLayoutEffect(() => {
    recompute();
  }, [recompute, addingFor]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => recompute());
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [recompute]);

  // ── les synapses ─────────────────────────────────────────────────────────
  // L'arbre pense : par moments, une impulsion lumineuse part d'une branche
  // au hasard et se propage aux branches voisines — voir synapses.ts pour la
  // planification. Ici on ne fait que JOUER les rafales : monter les comètes,
  // allumer les halos à l'arrivée, et se taire quand l'onglet est caché ou
  // que la personne préfère les interfaces immobiles.
  const [rafale, setRafale] = useState<Array<Impulsion & { cle: string }>>([]);
  const [halos, setHalos] = useState<Set<string>>(new Set());
  const edgesRef = useRef<Edge[]>([]);
  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      return undefined;
    }
    let vivant = true;
    const minuteries = new Set<number>();
    const poser = (fn: () => void, delai: number) => {
      const t = window.setTimeout(() => {
        minuteries.delete(t);
        fn();
      }, delai);
      minuteries.add(t);
    };
    const feu = () => {
      if (!vivant) return;
      const aretes = edgesRef.current;
      if (document.hidden || aretes.length === 0) {
        poser(feu, 4000);
        return;
      }
      const naissance = Date.now();
      const pensee = planifierRafale(aretes).map((imp, i) => ({
        ...imp,
        cle: `${naissance}-${i}`,
      }));
      setRafale(pensee);
      let fin = 0;
      for (const imp of pensee) {
        const arrivee = imp.departMs + imp.dureeMs;
        fin = Math.max(fin, arrivee);
        poser(() => {
          setHalos((h) => new Set(h).add(imp.arriveeId));
          poser(
            () =>
              setHalos((h) => {
                const suivant = new Set(h);
                suivant.delete(imp.arriveeId);
                return suivant;
              }),
            550,
          );
        }, arrivee);
      }
      poser(() => setRafale([]), fin + 700);
      poser(feu, 3500 + Math.random() * 4500);
    };
    poser(feu, 1200 + Math.random() * 1500);
    return () => {
      vivant = false;
      for (const t of minuteries) window.clearTimeout(t);
    };
  }, []);

  const submitCreate = async (parentTaskId?: string) => {
    const title = draftTitle.trim();
    if (!title || saving) return;
    await onCreate(parentTaskId ? { title, parentTaskId } : { title });
    setDraftTitle('');
    setAddingFor(null);
  };

  if (rows.length === 0) {
    return (
      <div
        className="rounded-2xl py-10 px-6 text-center grid gap-3 justify-items-center"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <p className="font-medium" style={{ color: 'var(--color-text)' }}>
          Aucun étage dans cette généalogie
        </p>
        <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          Créez la racine — {levelLabelFor(0, levelLabels)} — puis descendez étage par étage avec
          les boutons +.
        </p>
        <div className="flex w-full max-w-sm gap-2">
          <input
            value={draftTitle}
            onChange={(event) => setDraftTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void submitCreate();
            }}
            placeholder="Titre de la racine…"
            maxLength={200}
            className="flex-1 min-w-0 rounded-xl px-3 py-2.5 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
          />
          <button
            type="button"
            disabled={!draftTitle.trim() || saving}
            onClick={() => void submitCreate()}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer shrink-0"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <CirclePlus size={15} />}
            Créer
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto pb-2">
      <div ref={canvasRef} className="relative isolate min-w-fit grid gap-10 py-2">
        <svg
          className="absolute inset-0 -z-10 pointer-events-none"
          width="100%"
          height="100%"
          viewBox={`0 0 ${canvasSize.width} ${canvasSize.height}`}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {edges.map((edge) => (
            <path
              key={edge.id}
              d={cheminArete(edge, true)}
              fill="none"
              stroke="var(--color-border)"
              strokeWidth={1.5}
            />
          ))}
          {rafale.map((imp) => {
            // La comète relit l'arête au rendu : si l'arbre se réagence en
            // plein vol, elle suit la branche au lieu de flotter dans le vide.
            const arete = edges.find((e) => e.id === imp.areteId);
            if (!arete) return null;
            return (
              <path
                key={imp.cle}
                d={cheminArete(arete, imp.descend)}
                pathLength={100}
                fill="none"
                stroke="var(--color-accent)"
                strokeWidth={2}
                strokeLinecap="round"
                style={{
                  strokeDasharray: '12 100',
                  strokeDashoffset: 12,
                  animation: `synapse-file ${imp.dureeMs}ms linear ${imp.departMs}ms forwards`,
                  filter: 'drop-shadow(0 0 3px var(--color-accent))',
                  opacity: 0.9,
                }}
              />
            );
          })}
        </svg>
        {rows.map((row, depth) => (
          <div key={depth} className="flex items-stretch gap-3">
            <div className="w-24 shrink-0 flex items-center">
              <p
                className="text-xs font-medium uppercase tracking-wide break-words"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                {levelLabelFor(depth, levelLabels)}
              </p>
            </div>
            <div className="flex-1 flex flex-wrap justify-center items-start gap-x-4 gap-y-6">
              {row.map((item) => (
                <GenealogyNodeCard
                  key={item.node.id}
                  item={item}
                  halo={halos.has(item.node.id)}
                  saving={saving}
                  adding={addingFor === item.node.id}
                  draftTitle={addingFor === item.node.id ? draftTitle : ''}
                  cardRef={setCardRef(item.node.id)}
                  onToggle={onToggle}
                  onSelect={onSelect}
                  onStartAdd={() => {
                    setAddingFor(item.node.id);
                    setDraftTitle('');
                  }}
                  onCancelAdd={() => {
                    setAddingFor(null);
                    setDraftTitle('');
                  }}
                  onDraftChange={setDraftTitle}
                  onSubmitAdd={() => void submitCreate(item.node.id)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

type NodeCardProps = {
  item: LevelItem;
  /** La carte vient de recevoir une impulsion — elle s'illumine un instant. */
  halo: boolean;
  saving: boolean;
  adding: boolean;
  draftTitle: string;
  cardRef: (el: HTMLDivElement | null) => void;
  onToggle: (task: SuccesTask) => Promise<void>;
  onSelect: ((task: SuccesTask) => void) | undefined;
  onStartAdd: () => void;
  onCancelAdd: () => void;
  onDraftChange: (value: string) => void;
  onSubmitAdd: () => void;
};

function GenealogyNodeCard({
  item,
  halo,
  saving,
  adding,
  draftTitle,
  cardRef,
  onToggle,
  onSelect,
  onStartAdd,
  onCancelAdd,
  onDraftChange,
  onSubmitAdd,
}: NodeCardProps) {
  const { node, stats, hiddenCount, atDepthLimit } = item;
  const hasDescendants = stats.total > 0;
  const pct = hasDescendants ? Math.round((stats.done / stats.total) * 100) : 0;

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div
        ref={cardRef}
        className="w-44 rounded-xl p-3 grid gap-2"
        style={{
          background: 'var(--color-surface)',
          border: `1px solid ${halo ? 'var(--color-accent)' : 'var(--color-border)'}`,
          boxShadow: halo
            ? '0 0 14px color-mix(in srgb, var(--color-accent) 30%, transparent)'
            : '0 0 0 transparent',
          transition: 'box-shadow 320ms ease, border-color 320ms ease',
          opacity: node.done ? 0.72 : 1,
        }}
      >
        <div className="flex items-start gap-2">
          <button
            type="button"
            onClick={() => void onToggle(node)}
            disabled={saving}
            className="mt-0.5 size-5 rounded-full border flex items-center justify-center cursor-pointer shrink-0 disabled:opacity-50"
            style={{
              borderColor: node.done ? 'var(--color-accent)' : 'var(--color-border)',
              background: node.done ? 'var(--color-accent)' : 'transparent',
              color: '#fff',
            }}
            aria-label={node.done ? `Rouvrir « ${node.title} »` : `Terminer « ${node.title} »`}
          >
            {node.done ? <Check size={12} /> : null}
          </button>
          <button
            type="button"
            onClick={() => onSelect?.(node)}
            className="flex-1 min-w-0 text-left text-sm font-medium cursor-pointer break-words"
            style={{
              color: 'var(--color-text)',
              textDecoration: node.done ? 'line-through' : undefined,
            }}
          >
            {node.title}
          </button>
        </div>
        {hasDescendants && (
          <div className="grid gap-1">
            <div
              className="h-1.5 rounded-full overflow-hidden"
              style={{ background: 'var(--color-border)' }}
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={stats.total}
              aria-valuenow={stats.done}
              aria-label={`${stats.done} descendant(s) sur ${stats.total} terminé(s)`}
            >
              <div
                className="h-full rounded-full"
                style={{ width: `${pct}%`, background: 'var(--color-accent)' }}
              />
            </div>
            <div className="flex items-center justify-between gap-1">
              <p className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
                {stats.done}/{stats.total} descendants
              </p>
              {hiddenCount > 0 && (
                <span
                  className="text-[10px] font-medium px-1.5 py-0.5 rounded-full shrink-0"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                  title={`${hiddenCount} descendant(s) au-delà de la profondeur affichée`}
                >
                  +{hiddenCount}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
      {adding ? (
        <div
          className="w-44 grid gap-1.5 rounded-xl p-2"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <input
            autoFocus
            value={draftTitle}
            onChange={(event) => onDraftChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') onSubmitAdd();
              if (event.key === 'Escape') onCancelAdd();
            }}
            placeholder="Titre de l'enfant…"
            maxLength={200}
            className="rounded-lg px-2 py-1.5 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onCancelAdd}
              className="text-xs cursor-pointer"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              Annuler
            </button>
            <button
              type="button"
              disabled={!draftTitle.trim() || saving}
              onClick={onSubmitAdd}
              className="text-xs font-medium cursor-pointer disabled:opacity-50 flex items-center gap-1"
              style={{ color: 'var(--color-accent)' }}
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : null}
              Ajouter
            </button>
          </div>
        </div>
      ) : atDepthLimit ? (
        // Au dernier étage affiché, ce bouton créait un enfant au niveau
        // suivant — que la vue ne dessine pas. L'utilisateur voyait sa saisie
        // acceptée puis rien apparaître, et sa tâche existait pourtant, hors
        // de portée. Mieux vaut ne rien proposer que proposer en vain.
        <span
          className="rounded-full px-2 py-0.5 text-[10px] select-none"
          style={{
            color: 'var(--color-text-tertiary)',
            border: '1px dashed var(--color-border)',
          }}
          title={`Dernier étage affiché (${MAX_VISIBLE_LEVELS}). Un enfant créé ici ne serait pas visible : passez par « Éditer les branches » pour aller plus profond.`}
        >
          fond de l'arbre
        </span>
      ) : (
        <button
          type="button"
          onClick={onStartAdd}
          disabled={saving}
          className="rounded-full p-1 cursor-pointer disabled:opacity-50"
          style={{
            color: 'var(--color-text-tertiary)',
            border: '1px solid var(--color-border)',
            background: 'var(--color-surface)',
          }}
          aria-label={`Ajouter un enfant sous « ${node.title} »`}
          title="Ajouter un enfant"
        >
          <Plus size={13} />
        </button>
      )}
    </div>
  );
}
