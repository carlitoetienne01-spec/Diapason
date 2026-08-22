import { useEffect, useMemo, useRef, useState } from 'react';
import { CirclePlus, Loader2, RotateCcw, X, ZoomIn, ZoomOut } from 'lucide-react';

import type { SuccesTask } from './types';
import { buildProjectTaskTree, type ProjectTreeNode } from './ProjectTreeView';

const RING_GAP = 110;
const NODE_R = 9;
const CENTER_R = 46;
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 4;

type LaidNode = {
  node: ProjectTreeNode;
  x: number;
  y: number;
  depth: number;
  parentX: number;
  parentY: number;
};

function truncate(text: string, max = 18): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** Layout radial : chaque sous-arbre reçoit un secteur proportionnel à son nombre de feuilles. */
function layoutRadial(roots: ProjectTreeNode[]): LaidNode[] {
  const leafCounts = new Map<string, number>();
  const countLeaves = (node: ProjectTreeNode): number => {
    const cached = leafCounts.get(node.id);
    if (cached !== undefined) return cached;
    const count =
      node.children.length === 0
        ? 1
        : node.children.reduce((sum, child) => sum + countLeaves(child), 0);
    leafCounts.set(node.id, count);
    return count;
  };

  const laid: LaidNode[] = [];
  const walk = (
    node: ProjectTreeNode,
    a0: number,
    a1: number,
    depth: number,
    parentX: number,
    parentY: number,
  ) => {
    const angle = (a0 + a1) / 2;
    const radius = depth * RING_GAP;
    const x = radius * Math.cos(angle);
    const y = radius * Math.sin(angle);
    laid.push({ node, x, y, depth, parentX, parentY });
    const leaves = countLeaves(node);
    let childStart = a0;
    for (const child of node.children) {
      const span = (a1 - a0) * (countLeaves(child) / leaves);
      walk(child, childStart, childStart + span, depth + 1, x, y);
      childStart += span;
    }
  };

  const total = roots.reduce((sum, root) => sum + countLeaves(root), 0) || 1;
  let start = -Math.PI / 2;
  for (const root of roots) {
    const span = (Math.PI * 2 * countLeaves(root)) / total;
    walk(root, start, start + span, 1, 0, 0);
    start += span;
  }
  return laid;
}

type Props = {
  tasks: SuccesTask[];
  projectName: string;
  saving?: boolean;
  onToggle: (task: SuccesTask) => Promise<void>;
  onCreate: (input: { title: string; parentTaskId?: string }) => Promise<void>;
  onSelect?: (task: SuccesTask) => void;
};

export function MindMapView({
  tasks,
  projectName,
  saving = false,
  onToggle,
  onCreate,
  onSelect,
}: Props) {
  const roots = useMemo(() => buildProjectTaskTree(tasks), [tasks]);
  const laid = useMemo(() => layoutRadial(roots), [roots]);
  const maxDepth = useMemo(
    () => laid.reduce((max, item) => Math.max(max, item.depth), 1),
    [laid],
  );
  const half = maxDepth * RING_GAP + 120;

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [panning, setPanning] = useState(false);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [pendingParent, setPendingParent] = useState<ProjectTreeNode | null>(null);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const clickTimer = useRef<number | null>(null);
  const panState = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    baseX: number;
    baseY: number;
  } | null>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * 0.0015);
      setZoom((value) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value * factor)));
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, []);

  useEffect(
    () => () => {
      if (clickTimer.current !== null) window.clearTimeout(clickTimer.current);
    },
    [],
  );

  const zoomBy = (factor: number) => {
    setZoom((value) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value * factor)));
  };

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  const handlePointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    panState.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      baseX: pan.x,
      baseY: pan.y,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setPanning(true);
  };

  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const state = panState.current;
    if (!state || state.pointerId !== event.pointerId) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const scale = (half * 2) / rect.width;
    setPan({
      x: state.baseX + (event.clientX - state.startX) * scale,
      y: state.baseY + (event.clientY - state.startY) * scale,
    });
  };

  const handlePointerEnd = (event: React.PointerEvent<SVGSVGElement>) => {
    if (panState.current?.pointerId !== event.pointerId) return;
    panState.current = null;
    setPanning(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const handleNodeClick = (node: ProjectTreeNode) => {
    if (clickTimer.current !== null) window.clearTimeout(clickTimer.current);
    clickTimer.current = window.setTimeout(() => {
      clickTimer.current = null;
      onSelect?.(node);
    }, 220);
  };

  const handleNodeDoubleClick = (node: ProjectTreeNode) => {
    if (clickTimer.current !== null) {
      window.clearTimeout(clickTimer.current);
      clickTimer.current = null;
    }
    if (!saving) void onToggle(node);
  };

  const startChildBranch = (node: ProjectTreeNode) => {
    setPendingParent(node);
    inputRef.current?.focus();
  };

  const addBranch = async () => {
    const trimmed = title.trim();
    if (!trimmed || saving) return;
    await onCreate({
      title: trimmed,
      parentTaskId: pendingParent ? pendingParent.id : undefined,
    });
    setTitle('');
    setPendingParent(null);
  };

  const edgePath = (item: LaidNode): string => {
    const midX = (item.parentX + item.x) / 2;
    const midY = (item.parentY + item.y) / 2;
    const ctrlX = midX * 0.8;
    const ctrlY = midY * 0.8;
    return `M ${item.parentX} ${item.parentY} Q ${ctrlX} ${ctrlY} ${item.x} ${item.y}`;
  };

  return (
    <div className="grid gap-3">
      <div
        className="relative rounded-2xl overflow-hidden"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <svg
          ref={svgRef}
          viewBox={`${-half} ${-half} ${half * 2} ${half * 2}`}
          width="100%"
          role="application"
          aria-label={`Carte mentale du projet ${projectName}`}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerEnd}
          onPointerCancel={handlePointerEnd}
          style={{
            display: 'block',
            cursor: panning ? 'grabbing' : 'grab',
            touchAction: 'none',
            userSelect: 'none',
          }}
        >
          <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
            {laid.map((item) => (
              <path
                key={`edge-${item.node.id}`}
                d={edgePath(item)}
                fill="none"
                stroke="var(--color-border)"
                strokeWidth={1.5}
              />
            ))}

            <g>
              <circle cx={0} cy={0} r={CENTER_R} fill="var(--color-accent)" />
              <text
                x={0}
                y={0}
                dy={4}
                textAnchor="middle"
                fill="#fff"
                fontSize={13}
                fontWeight={600}
              >
                {truncate(projectName, 14)}
              </text>
              <title>{projectName}</title>
            </g>

            {roots.length === 0 && (
              <text
                x={0}
                y={CENTER_R + 28}
                textAnchor="middle"
                fontSize={11}
                fill="var(--color-text-tertiary)"
              >
                Aucune branche — ajoutez-en une ci-dessous.
              </text>
            )}

            {laid.map((item) => {
              const { node, x, y } = item;
              const showPlus = hoveredId === node.id || focusedId === node.id;
              const horizontal = Math.abs(x) > 20;
              const labelAnchor = horizontal ? (x > 0 ? 'start' : 'end') : 'middle';
              const labelX = horizontal ? x + (x > 0 ? NODE_R + 6 : -(NODE_R + 6)) : x;
              const labelY = horizontal ? y + 4 : y + (y >= 0 ? NODE_R + 16 : -(NODE_R + 8));
              return (
                <g
                  key={node.id}
                  tabIndex={0}
                  role="button"
                  aria-label={`${node.title}${node.done ? ' (terminée)' : ''}`}
                  onPointerDown={(event) => event.stopPropagation()}
                  onMouseEnter={() => setHoveredId(node.id)}
                  onMouseLeave={() =>
                    setHoveredId((current) => (current === node.id ? null : current))
                  }
                  onFocus={() => setFocusedId(node.id)}
                  onBlur={() =>
                    setFocusedId((current) => (current === node.id ? null : current))
                  }
                  onClick={() => handleNodeClick(node)}
                  onDoubleClick={() => handleNodeDoubleClick(node)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      onSelect?.(node);
                    } else if (event.key === ' ') {
                      event.preventDefault();
                      if (!saving) void onToggle(node);
                    } else if (event.key === '+') {
                      event.preventDefault();
                      startChildBranch(node);
                    }
                  }}
                  style={{ cursor: 'pointer', outline: 'none' }}
                >
                  <title>{node.title}</title>
                  {focusedId === node.id && (
                    <circle
                      cx={x}
                      cy={y}
                      r={NODE_R + 5}
                      fill="none"
                      stroke="var(--color-accent)"
                      strokeWidth={1.5}
                      strokeDasharray="3 3"
                    />
                  )}
                  <circle
                    cx={x}
                    cy={y}
                    r={NODE_R}
                    fill={node.done ? 'var(--color-accent)' : 'var(--color-surface)'}
                    stroke={node.done ? 'var(--color-accent)' : 'var(--color-border)'}
                    strokeWidth={1.5}
                  />
                  <text
                    x={labelX}
                    y={labelY}
                    textAnchor={labelAnchor}
                    fontSize={11}
                    fill={node.done ? 'var(--color-text-tertiary)' : 'var(--color-text)'}
                    style={{
                      textDecoration: node.done ? 'line-through' : undefined,
                      pointerEvents: 'none',
                    }}
                  >
                    {truncate(node.title)}
                  </text>
                  {showPlus && (
                    <g
                      transform={`translate(${x + NODE_R + 8}, ${y - NODE_R - 8})`}
                      role="button"
                      aria-label={`Ajouter un enfant à ${node.title}`}
                      onPointerDown={(event) => event.stopPropagation()}
                      onClick={(event) => {
                        event.stopPropagation();
                        startChildBranch(node);
                      }}
                      onDoubleClick={(event) => event.stopPropagation()}
                      style={{ cursor: 'pointer' }}
                    >
                      <circle r={8} fill="var(--color-accent)" />
                      <line x1={-3.5} y1={0} x2={3.5} y2={0} stroke="#fff" strokeWidth={1.6} />
                      <line x1={0} y1={-3.5} x2={0} y2={3.5} stroke="#fff" strokeWidth={1.6} />
                      <title>Ajouter un enfant</title>
                    </g>
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        <div className="absolute top-3 right-3 flex gap-1">
          <button
            type="button"
            onClick={() => zoomBy(1.25)}
            className="rounded-lg p-1.5 cursor-pointer"
            style={{
              color: 'var(--color-text-secondary)',
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
            }}
            aria-label="Zoomer"
            title="Zoomer"
          >
            <ZoomIn size={14} />
          </button>
          <button
            type="button"
            onClick={() => zoomBy(1 / 1.25)}
            className="rounded-lg p-1.5 cursor-pointer"
            style={{
              color: 'var(--color-text-secondary)',
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
            }}
            aria-label="Dézoomer"
            title="Dézoomer"
          >
            <ZoomOut size={14} />
          </button>
          <button
            type="button"
            onClick={resetView}
            className="rounded-lg p-1.5 cursor-pointer"
            style={{
              color: 'var(--color-text-secondary)',
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
            }}
            aria-label="Recentrer la carte"
            title="Recentrer la carte"
          >
            <RotateCcw size={14} />
          </button>
        </div>
      </div>

      <section
        className="grid gap-2 rounded-2xl p-4"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        {pendingParent && (
          <div
            className="flex items-center gap-1.5 text-xs"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <span>Nouvelle branche sous</span>
            <span className="font-medium" style={{ color: 'var(--color-text)' }}>
              « {truncate(pendingParent.title)} »
            </span>
            <button
              type="button"
              onClick={() => setPendingParent(null)}
              className="rounded p-0.5 cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
              aria-label="Revenir à la racine"
              title="Revenir à la racine"
            >
              <X size={12} />
            </button>
          </div>
        )}
        <div className="flex gap-2">
          <input
            ref={inputRef}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void addBranch();
              else if (event.key === 'Escape') setPendingParent(null);
            }}
            placeholder={
              pendingParent
                ? `Titre de la branche sous « ${truncate(pendingParent.title, 14)} »…`
                : 'Ajouter une branche…'
            }
            maxLength={200}
            aria-label="Ajouter une branche"
            className="flex-1 min-w-0 rounded-xl px-3 py-2.5 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
          />
          <button
            type="button"
            disabled={!title.trim() || saving}
            onClick={() => void addBranch()}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer shrink-0"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <CirclePlus size={15} />}
            Ajouter
          </button>
        </div>
      </section>
    </div>
  );
}
