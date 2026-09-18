import {
  useEffect,
  useMemo,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { CirclePlus, Link2, Loader2 } from 'lucide-react';

import {
  colonnesInitiales,
  construireReseau,
  faisables,
  positionner,
  statuts,
  type StatutTache,
} from './reseau';
import type { SuccesTask, SuccesTaskEdge } from './types';

type Props = {
  tasks: SuccesTask[];
  edges: SuccesTaskEdge[];
  saving?: boolean;
  onToggle: (task: SuccesTask) => Promise<void>;
  onLink: (fromTaskId: string, toTaskId: string) => Promise<void>;
  onUnlink: (fromTaskId: string, toTaskId: string) => Promise<void>;
  onCreate: (input: { title: string }) => Promise<void>;
  onSelect?: (task: SuccesTask) => void;
};

const CARD_W = 190;
const CARD_H = 64;
const GAP_X = 72;
const GAP_Y = 26;
const PAD = 24;
const DANGER = 'var(--color-error, var(--color-text-secondary))';

// Le raisonnement (niveaux, statuts, faisables, colonnes) vit dans
// `reseau.ts`, testé sur AgriCulture (chantier réseau, 18 sept. 2026) :
// ici on ne fait que dessiner.

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

export function NetworkView({
  tasks,
  edges,
  saving = false,
  onToggle,
  onLink,
  onUnlink,
  onCreate,
  onSelect,
}: Props) {
  const [linkMode, setLinkMode] = useState(false);
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<{ from: string; to: string } | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [error, setError] = useState<string | null>(null);

  const reseau = useMemo(() => construireReseau(tasks, edges), [tasks, edges]);
  const byId = reseau.parId;
  const visibleEdges = reseau.aretes;
  const statusById = useMemo(() => statuts(reseau), [reseau]);
  const feasible = useMemo(() => faisables(reseau), [reseau]);

  const layout = useMemo(
    () =>
      positionner(colonnesInitiales(reseau), {
        largeurCarte: CARD_W,
        hauteurCarte: CARD_H,
        ecartX: GAP_X,
        ecartY: GAP_Y,
        marge: PAD,
      }),
    [reseau],
  );

  useEffect(() => {
    if (!linkMode && !selectedEdge) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        // Consommé : le mini-panneau ne se ferme qu'au second Échap (contrat du 17 sept. 2026, lib.rs lit `defaultPrevented`).
        event.preventDefault();
        setLinkMode(false);
        setLinkFrom(null);
        setSelectedEdge(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [linkMode, selectedEdge]);

  const run = async (action: () => Promise<void>) => {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const keyActivate = (action: () => void) => (event: ReactKeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      event.stopPropagation();
      action();
    }
  };

  const activateCard = (task: SuccesTask) => {
    setSelectedEdge(null);
    if (linkMode) {
      if (!linkFrom) {
        setLinkFrom(task.id);
        return;
      }
      if (linkFrom === task.id) {
        setLinkFrom(null);
        return;
      }
      const from = linkFrom;
      setLinkMode(false);
      setLinkFrom(null);
      void run(() => onLink(from, task.id));
      return;
    }
    onSelect?.(task);
  };

  const toggleTask = (task: SuccesTask) => {
    if (saving) return;
    void run(() => onToggle(task));
  };

  const unlinkSelected = () => {
    if (!selectedEdge || saving) return;
    const { from, to } = selectedEdge;
    void run(async () => {
      await onUnlink(from, to);
      setSelectedEdge(null);
    });
  };

  const addTask = () => {
    const title = newTitle.trim();
    if (!title || saving) return;
    void run(async () => {
      await onCreate({ title });
      setNewTitle('');
    });
  };

  const statusLabel = (status: StatutTache) =>
    status === 'faite' ? '✓ fait' : status === 'faisable' ? '→ faisable maintenant' : '⏳ bloquée';

  const statusColor = (status: StatutTache) =>
    status === 'faite'
      ? 'var(--color-text-secondary)'
      : status === 'faisable'
        ? 'var(--color-accent)'
        : 'var(--color-text-tertiary)';

  return (
    <div className="grid gap-4">
      <section
        className="grid gap-2 rounded-2xl p-4"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          Faisable maintenant : <span style={{ color: 'var(--color-accent)' }}>{feasible.length}</span>
        </p>
        {feasible.length === 0 ? (
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Aucune tâche débloquée pour l’instant.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {feasible.map((task) => (
              <button
                key={task.id}
                type="button"
                onClick={() => onSelect?.(task)}
                className="px-2.5 py-1 rounded-full text-xs cursor-pointer"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <span style={{ color: 'var(--color-accent)' }}>→ </span>
                {task.title}
              </button>
            ))}
          </div>
        )}
      </section>

      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          disabled={saving || tasks.length < 2}
          onClick={() => {
            setError(null);
            setSelectedEdge(null);
            setLinkFrom(null);
            setLinkMode((value) => !value);
          }}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer disabled:opacity-50"
          style={
            linkMode
              ? { background: 'var(--color-accent)', color: '#fff' }
              : { border: '1px solid var(--color-border)', color: 'var(--color-text)' }
          }
        >
          {saving ? <Loader2 size={15} className="animate-spin" /> : <Link2 size={15} />}
          {linkMode ? 'Annuler la liaison' : 'Relier'}
        </button>
        {linkMode && (
          <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {linkFrom
              ? 'Cliquez la tâche à débloquer (cible). Échap pour annuler.'
              : 'Cliquez la tâche source. Échap pour annuler.'}
          </span>
        )}
      </div>

      {error && (
        <p className="text-xs" role="alert" style={{ color: DANGER }}>
          {error}
        </p>
      )}

      {tasks.length === 0 ? (
        <div
          className="rounded-2xl py-12 text-center"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <p className="font-medium" style={{ color: 'var(--color-text)' }}>
            Aucune tâche dans le réseau
          </p>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
            Ajoutez une première tâche ci-dessous, puis reliez-les avec « Relier ».
          </p>
        </div>
      ) : (
        <div
          className="rounded-2xl p-2 overflow-x-auto"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <svg
            width="100%"
            viewBox={`0 0 ${layout.largeur} ${layout.hauteur}`}
            role="img"
            aria-label="Réseau des tâches reliées par « débloque »"
            style={{ display: 'block', width: '100%', height: 'auto' }}
            onClick={() => setSelectedEdge(null)}
          >
            <defs>
              <marker
                id="nv-arrow-border"
                viewBox="0 0 8 8"
                refX="7"
                refY="4"
                markerWidth="8"
                markerHeight="8"
                orient="auto-start-reverse"
              >
                <path d="M0,0 L8,4 L0,8 Z" fill="var(--color-border)" />
              </marker>
              <marker
                id="nv-arrow-accent"
                viewBox="0 0 8 8"
                refX="7"
                refY="4"
                markerWidth="8"
                markerHeight="8"
                orient="auto-start-reverse"
              >
                <path d="M0,0 L8,4 L0,8 Z" fill="var(--color-accent)" />
              </marker>
            </defs>

            {visibleEdges.map((edge) => {
              const from = layout.pos.get(edge.fromTaskId);
              const to = layout.pos.get(edge.toTaskId);
              const fromTask = byId.get(edge.fromTaskId);
              const toTask = byId.get(edge.toTaskId);
              if (!from || !to || !fromTask || !toTask) return null;
              const x1 = from.x + CARD_W;
              const y1 = from.y + CARD_H / 2;
              const x2 = to.x - 2;
              const y2 = to.y + CARD_H / 2;
              const dx = Math.max(28, Math.abs(x2 - x1) / 2);
              const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
              const waiting = !fromTask.done;
              const isSelected =
                selectedEdge?.from === edge.fromTaskId && selectedEdge?.to === edge.toTaskId;
              return (
                <g key={`${edge.fromTaskId}->${edge.toTaskId}`}>
                  <path
                    d={d}
                    fill="none"
                    stroke={waiting ? 'var(--color-accent)' : 'var(--color-border)'}
                    strokeWidth={isSelected ? 2.5 : 1.5}
                    markerEnd={`url(#${waiting ? 'nv-arrow-accent' : 'nv-arrow-border'})`}
                  />
                  <path
                    d={d}
                    fill="none"
                    stroke="transparent"
                    strokeWidth={14}
                    role="button"
                    tabIndex={0}
                    aria-label={`Lien : « ${fromTask.title} » débloque « ${toTask.title} ». Sélectionner pour supprimer.`}
                    style={{ cursor: 'pointer', outline: 'none' }}
                    onClick={(event: ReactMouseEvent<SVGPathElement>) => {
                      event.stopPropagation();
                      setSelectedEdge({ from: edge.fromTaskId, to: edge.toTaskId });
                    }}
                    onKeyDown={keyActivate(() =>
                      setSelectedEdge({ from: edge.fromTaskId, to: edge.toTaskId }),
                    )}
                  />
                </g>
              );
            })}

            {tasks.map((task) => {
              const p = layout.pos.get(task.id);
              if (!p) return null;
              const status = statusById.get(task.id) ?? 'faisable';
              const isLinkSource = linkFrom === task.id;
              const isFocused = focusedId === task.id;
              const highlighted = isLinkSource || isFocused;
              return (
                <g
                  key={task.id}
                  transform={`translate(${p.x} ${p.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${task.title} — ${statusLabel(status)}${
                    linkMode ? (linkFrom ? '. Choisir comme cible' : '. Choisir comme source') : ''
                  }`}
                  style={{ cursor: 'pointer', outline: 'none' }}
                  onClick={() => activateCard(task)}
                  onKeyDown={keyActivate(() => activateCard(task))}
                  onFocus={() => setFocusedId(task.id)}
                  onBlur={() => setFocusedId(null)}
                >
                  <rect
                    width={CARD_W}
                    height={CARD_H}
                    rx={14}
                    fill="var(--color-surface)"
                    stroke={
                      highlighted || status === 'faisable'
                        ? 'var(--color-accent)'
                        : 'var(--color-border)'
                    }
                    strokeWidth={highlighted ? 2 : 1}
                    strokeDasharray={isLinkSource ? '5 3' : undefined}
                    opacity={task.done ? 0.72 : 1}
                  />
                  <g
                    role="button"
                    tabIndex={0}
                    aria-label={task.done ? `Rouvrir « ${task.title} »` : `Terminer « ${task.title} »`}
                    style={{ cursor: 'pointer', outline: 'none' }}
                    onClick={(event: ReactMouseEvent<SVGGElement>) => {
                      event.stopPropagation();
                      toggleTask(task);
                    }}
                    onKeyDown={keyActivate(() => toggleTask(task))}
                  >
                    <circle
                      cx={20}
                      cy={CARD_H / 2}
                      r={9}
                      fill={task.done ? 'var(--color-accent)' : 'var(--color-surface)'}
                      stroke={task.done ? 'var(--color-accent)' : 'var(--color-border)'}
                      strokeWidth={1.5}
                    />
                    {task.done && (
                      <path
                        d={`M 16 ${CARD_H / 2 + 0.5} L 19 ${CARD_H / 2 + 3.5} L 25 ${CARD_H / 2 - 3}`}
                        fill="none"
                        stroke="#fff"
                        strokeWidth={2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    )}
                  </g>
                  <text
                    x={38}
                    y={CARD_H / 2 - 5}
                    fontSize={13}
                    fontWeight={600}
                    fill="var(--color-text)"
                    style={{ textDecoration: task.done ? 'line-through' : undefined }}
                  >
                    {truncate(task.title, 20)}
                  </text>
                  <text x={38} y={CARD_H / 2 + 14} fontSize={11} fill={statusColor(status)}>
                    {statusLabel(status)}
                  </text>
                </g>
              );
            })}

            {selectedEdge &&
              (() => {
                const from = layout.pos.get(selectedEdge.from);
                const to = layout.pos.get(selectedEdge.to);
                if (!from || !to) return null;
                const mx = (from.x + CARD_W + to.x - 2) / 2;
                const my = (from.y + CARD_H / 2 + to.y + CARD_H / 2) / 2;
                return (
                  <g
                    transform={`translate(${mx} ${my})`}
                    role="button"
                    tabIndex={0}
                    aria-label="Supprimer ce lien"
                    style={{ cursor: 'pointer', outline: 'none' }}
                    onClick={(event: ReactMouseEvent<SVGGElement>) => {
                      event.stopPropagation();
                      unlinkSelected();
                    }}
                    onKeyDown={keyActivate(unlinkSelected)}
                  >
                    <circle r={11} fill="var(--color-surface)" stroke={DANGER} strokeWidth={1.5} />
                    <text
                      textAnchor="middle"
                      dominantBaseline="central"
                      fontSize={14}
                      fontWeight={600}
                      fill={DANGER}
                    >
                      ×
                    </text>
                  </g>
                );
              })()}
          </svg>
        </div>
      )}

      <section
        className="flex gap-2 rounded-2xl p-3"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <input
          value={newTitle}
          onChange={(event) => setNewTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') addTask();
          }}
          placeholder="+ Tâche : titre…"
          maxLength={200}
          aria-label="Titre de la nouvelle tâche"
          className="flex-1 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
        />
        <button
          type="button"
          disabled={!newTitle.trim() || saving}
          onClick={addTask}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
          style={{ background: 'var(--color-accent)', color: '#fff' }}
        >
          {saving ? <Loader2 size={15} className="animate-spin" /> : <CirclePlus size={15} />}
          Ajouter
        </button>
      </section>
    </div>
  );
}
