import { CadreVitre } from '../../components/Glass/CadreVitre';
import { useEffect, useMemo, useState } from 'react';
import { Check, ChevronDown, ChevronLeft, ChevronRight, Plus, X } from 'lucide-react';
import { libelleIntervalle } from './libelleSemaine';
import type { SuccesSubtask, SuccesTask } from './types';

export type BoardMode = 'week' | 'month';

function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function parseIso(iso: string) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(year, month - 1, day, 12);
}

/** Monday-start week — aligned with planner / French week conventions. */
function startOfWeekMonday(anchor: string) {
  const date = parseIso(anchor);
  const day = (date.getDay() + 6) % 7;
  date.setDate(date.getDate() - day);
  return localIsoDate(date);
}

function addDays(iso: string, days: number) {
  const date = parseIso(iso);
  date.setDate(date.getDate() + days);
  return localIsoDate(date);
}

function monthMatrix(anchor: string) {
  const date = parseIso(anchor);
  const year = date.getFullYear();
  const month = date.getMonth();
  const first = localIsoDate(new Date(year, month, 1, 12));
  const start = startOfWeekMonday(first);
  const lastDay = new Date(year, month + 1, 0).getDate();
  const end = localIsoDate(new Date(year, month, lastDay, 12));
  const endWeekStart = startOfWeekMonday(end);
  const last = addDays(endWeekStart, 6);
  const days: string[] = [];
  let cursor = start;
  while (cursor <= last) {
    days.push(cursor);
    cursor = addDays(cursor, 1);
  }
  return { year, month, days };
}

const DAY_LABELS = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.'];
const MIME = 'application/x-diapason-task';
/** Day cells keep a constant height; extra tasks are reachable via the footer count. */
const MAX_VISIBLE_TASKS = 2;
/**
 * La hauteur fixe (200 px) aligne les colonnes d'une même rangée. En une
 * seule colonne — la Semaine sous sm — cette raison disparaît, et sept
 * cellules de 200 px faisaient ~1 450 px de défilement pour des jours vides
 * (audit du mini-panneau, 16 sept. 2026). `souple` laisse la cellule
 * retomber à son contenu tant que la grille n'a qu'une colonne.
 */
const HAUTEUR_CELLULE = {
  fixe: 'h-[200px]',
  souple: 'min-h-24 sm:h-[200px]',
} as const;

function sortColumn(tasks: SuccesTask[]) {
  return [...tasks].sort((left, right) => {
    if (left.done !== right.done) return left.done ? 1 : -1;
    return left.title.localeCompare(right.title, 'fr', { sensitivity: 'base' });
  });
}

function countSubtasks(nodes: SuccesSubtask[]): number {
  return nodes.reduce((total, node) => total + 1 + countSubtasks(node.children), 0);
}

function BoardSubtaskRow({
  task,
  subtask,
  depth,
  onToggle,
}: {
  task: SuccesTask;
  subtask: SuccesSubtask;
  depth: number;
  onToggle: (task: SuccesTask, subtask: SuccesSubtask) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = subtask.children.length > 0;

  return (
    <div style={{ marginLeft: depth ? 12 : 0 }}>
      <div className="flex items-center gap-1.5 min-h-7 py-0.5">
        {hasChildren ? (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setExpanded((value) => !value);
            }}
            onPointerDown={(event) => event.stopPropagation()}
            className="p-0.5 rounded cursor-pointer shrink-0"
            style={{ color: 'var(--color-text-tertiary)' }}
            aria-label={expanded ? 'Réduire' : 'Développer'}
            aria-expanded={expanded}
          >
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
        ) : (
          <span className="w-3.5 shrink-0" />
        )}
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onToggle(task, subtask);
          }}
          onPointerDown={(event) => event.stopPropagation()}
          className="size-4 rounded flex items-center justify-center shrink-0 cursor-pointer"
          style={{
            border: `1px solid ${subtask.done ? 'var(--color-accent)' : 'var(--color-border)'}`,
            background: subtask.done ? 'var(--color-accent)' : 'transparent',
            color: '#fff',
          }}
          aria-label={subtask.done ? 'Rouvrir la sous-tâche' : 'Terminer la sous-tâche'}
        >
          {subtask.done && <Check size={10} />}
        </button>
        <span
          className="flex-1 text-xs leading-4 break-words"
          style={{
            color: subtask.done ? 'var(--color-text-tertiary)' : 'var(--color-text-secondary)',
            textDecoration: subtask.done ? 'line-through' : 'none',
          }}
        >
          {subtask.title || 'Sous-tâche'}
        </span>
      </div>
      {expanded &&
        subtask.children.map((child) => (
          <BoardSubtaskRow
            key={child.id}
            task={task}
            subtask={child}
            depth={depth + 1}
            onToggle={onToggle}
          />
        ))}
    </div>
  );
}

function BoardCard({
  task,
  today,
  onToggle,
  onOpenDay,
}: {
  task: SuccesTask;
  today: string;
  onToggle: (task: SuccesTask) => void;
  onOpenDay: () => void;
}) {
  const overdue = !task.done && !!task.date && task.date < today;
  const lateDays = overdue
    ? Math.max(1, Math.round((parseIso(today).getTime() - parseIso(task.date).getTime()) / 86_400_000))
    : 0;
  const hasSubtasks = countSubtasks(task.subtasks) > 0;

  return (
    <CadreVitre compact
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData(MIME, task.id);
        event.dataTransfer.setData('text/plain', task.id);
        event.dataTransfer.effectAllowed = 'move';
        event.currentTarget.style.opacity = '0.55';
      }}
      onDragEnd={(event) => {
        event.currentTarget.style.opacity = '1';
      }}
      onClick={onOpenDay}
      title="Voir les tâches de ce jour"
      className="rounded-xl p-2 cursor-grab active:cursor-grabbing overflow-hidden"
      style={{
        background: 'var(--color-surface)',
        border: `1px solid ${task.done ? 'var(--color-border)' : overdue ? 'color-mix(in srgb, var(--color-error) 45%, var(--color-border))' : 'var(--color-border)'}`,
      }}
    >
      <div className="flex items-start gap-1">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onToggle(task);
          }}
          onPointerDown={(event) => event.stopPropagation()}
          className="mt-px size-4 rounded flex items-center justify-center shrink-0 cursor-pointer"
          style={{
            border: `1px solid ${task.done ? 'var(--color-accent)' : 'var(--color-border)'}`,
            background: task.done ? 'var(--color-accent)' : 'transparent',
            color: '#fff',
          }}
          aria-label={task.done ? 'Rouvrir' : 'Terminer'}
        >
          {task.done && <Check size={10} />}
        </button>
        <div className="min-w-0 flex-1">
          <p
            className="text-sm font-medium leading-5 truncate"
            title={task.title}
            style={{
              color: task.done ? 'var(--color-text-tertiary)' : 'var(--color-text)',
              textDecoration: task.done ? 'line-through' : 'none',
            }}
          >
            {task.emoji ? `${task.emoji} ` : ''}{task.title}
          </p>
          {task.done ? (
            <span className="block text-[10px] leading-4 truncate" style={{ color: 'var(--color-accent)' }}>
              Bien joué !
            </span>
          ) : overdue ? (
            <span
              className="block text-[10px] leading-4 truncate"
              style={{ color: 'var(--color-error)' }}
              title={`En retard de ${lateDays} jour${lateDays > 1 ? 's' : ''}`}
            >
              Retard {lateDays} j
            </span>
          ) : null}
        </div>
        {hasSubtasks && (
          <span
            className="mt-px shrink-0"
            style={{ color: 'var(--color-text-tertiary)' }}
            title="Cette tâche a des sous-tâches — ouvrir le jour pour les cocher"
            aria-hidden
          >
            <ChevronRight size={12} />
          </span>
        )}
      </div>
    </CadreVitre>
  );
}

function formatDayTitle(date: string) {
  if (!date) return 'Tâches sans date';
  const label = new Intl.DateTimeFormat('fr-CA', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(parseIso(date));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function DayTasksModal({
  date,
  tasks,
  onClose,
  onToggleTask,
  onToggleSubtask,
  onQuickAdd,
}: {
  date: string;
  tasks: SuccesTask[];
  onClose: () => void;
  onToggleTask: (task: SuccesTask) => void;
  onToggleSubtask: (task: SuccesTask, subtask: SuccesSubtask) => void;
  onQuickAdd?: (date: string) => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const open = tasks.filter((task) => !task.done).length;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={formatDayTitle(date)}
      onClick={onClose}
      className="voile-modal z-50 flex items-center justify-center p-5 backdrop-blur-md"
      style={{ background: 'color-mix(in srgb, #000 55%, transparent)' }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-2xl p-5"
        style={{
          background: 'color-mix(in srgb, var(--color-surface) 92%, transparent)',
          border: '1px solid var(--color-border)',
          boxShadow: '0 24px 60px rgba(0,0,0,0.45)',
        }}
      >
        <header className="flex items-start gap-3 mb-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold capitalize" style={{ color: 'var(--color-text)' }}>
              {formatDayTitle(date)}
            </h2>
            <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
              {tasks.length} tâche{tasks.length > 1 ? 's' : ''} · {open} en cours
            </p>
          </div>
          {date && onQuickAdd && (
            <button
              type="button"
              onClick={() => {
                onQuickAdd(date);
                onClose();
              }}
              className="p-1.5 rounded-lg cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
              title="Ajouter une tâche ce jour"
              aria-label="Ajouter une tâche ce jour"
            >
              <Plus size={16} />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)' }}
            aria-label="Fermer"
          >
            <X size={16} />
          </button>
        </header>

        <div className="grid gap-3">
          {tasks.map((task) => (
            <CadreVitre as="article" compact
              key={task.id}
              className="rounded-xl p-3"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-start gap-2">
                <button
                  type="button"
                  onClick={() => onToggleTask(task)}
                  className="mt-0.5 size-5 rounded-md flex items-center justify-center shrink-0 cursor-pointer"
                  style={{
                    border: `1px solid ${task.done ? 'var(--color-accent)' : 'var(--color-border)'}`,
                    background: task.done ? 'var(--color-accent)' : 'transparent',
                    color: '#fff',
                  }}
                  aria-label={task.done ? 'Rouvrir la tâche' : 'Terminer la tâche'}
                >
                  {task.done && <Check size={11} />}
                </button>
                <p
                  className="flex-1 text-sm font-medium leading-5 break-words"
                  style={{
                    color: task.done ? 'var(--color-text-tertiary)' : 'var(--color-text)',
                    textDecoration: task.done ? 'line-through' : 'none',
                  }}
                >
                  {task.emoji ? `${task.emoji} ` : ''}{task.title}
                </p>
              </div>
              {task.subtasks.length > 0 && (
                <div
                  className="mt-2 pt-2 grid gap-0.5"
                  style={{ borderTop: '1px solid var(--color-border)' }}
                >
                  {task.subtasks.map((subtask) => (
                    <BoardSubtaskRow
                      key={subtask.id}
                      task={task}
                      subtask={subtask}
                      depth={0}
                      onToggle={onToggleSubtask}
                    />
                  ))}
                </div>
              )}
            </CadreVitre>
          ))}
          {!tasks.length && (
            <p className="text-sm py-6 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
              Aucune tâche ce jour.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function DayColumn({
  date,
  today,
  tasks,
  onDropTask,
  onToggleTask,
  onQuickAdd,
  onOpenDay,
  dimmed,
  hauteur = 'fixe',
}: {
  date: string;
  today: string;
  tasks: SuccesTask[];
  onDropTask: (taskId: string, date: string) => void;
  onToggleTask: (task: SuccesTask) => void;
  onQuickAdd: (date: string) => void;
  onOpenDay: (date: string) => void;
  dimmed?: boolean;
  hauteur?: keyof typeof HAUTEUR_CELLULE;
}) {
  const [over, setOver] = useState(false);
  const weekday = (parseIso(date).getDay() + 6) % 7;
  const label = DAY_LABELS[weekday];
  const isToday = date === today;
  const visible = tasks.slice(0, MAX_VISIBLE_TASKS);
  const hidden = tasks.length - visible.length;

  return (
    <CadreVitre as="section"
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        const id = event.dataTransfer.getData(MIME) || event.dataTransfer.getData('text/plain');
        if (id) onDropTask(id, date);
      }}
      className={`min-w-0 rounded-2xl p-2.5 flex flex-col gap-2 overflow-hidden ${HAUTEUR_CELLULE[hauteur]}`}
      style={{
        background: over
          ? 'color-mix(in srgb, var(--color-accent) 10%, var(--color-bg-secondary))'
          : 'var(--color-bg-secondary)',
        border: `1px solid ${over ? 'var(--color-accent)' : isToday ? 'color-mix(in srgb, var(--color-accent) 55%, var(--color-border))' : 'var(--color-border)'}`,
        opacity: dimmed ? 0.55 : 1,
      }}
    >
      <header className="flex items-center gap-1">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] uppercase tracking-wide" style={{ color: isToday ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }}>
            {label}
          </p>
          <p className="text-xs font-medium truncate" style={{ color: 'var(--color-text)' }}>
            {date.slice(8)}/{date.slice(5, 7)}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onQuickAdd(date)}
          className="p-1 rounded-md cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          title="Ajouter une tâche"
          aria-label={`Ajouter une tâche le ${date}`}
        >
          <Plus size={14} />
        </button>
      </header>

      <div className="flex flex-col gap-2 flex-1 min-h-0 overflow-hidden">
        {visible.map((task) => (
          <BoardCard
            key={task.id}
            task={task}
            today={today}
            onToggle={onToggleTask}
            onOpenDay={() => onOpenDay(date)}
          />
        ))}
        {!tasks.length && (
          <p className="text-center text-xs py-4" style={{ color: 'var(--color-text-tertiary)' }}>—</p>
        )}
      </div>

      {tasks.length > 0 && (
        <button
          type="button"
          onClick={() => onOpenDay(date)}
          className="text-[11px] text-left cursor-pointer shrink-0"
          style={{ color: hidden > 0 ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }}
          title={`Voir les ${tasks.length} tâche${tasks.length > 1 ? 's' : ''} du jour`}
        >
          {hidden > 0 ? `+${hidden} autre${hidden > 1 ? 's' : ''} · ` : ''}
          {tasks.length} tâche{tasks.length > 1 ? 's' : ''}
        </button>
      )}
    </CadreVitre>
  );
}

/**
 * Le mois en étroit. Sous sm, la grille de DayColumn tombait à deux colonnes :
 * 28 à 42 cellules de 200 px, soit 3 000 à 4 200 px de défilement dans un
 * panneau de 620 px — inutilisable, et la source probable des retours
 * « n'importe où, en bas » (audit du mini-panneau, 16 sept. 2026). On rend
 * la forme du mini-calendrier du Planificateur : sept cases carrées par
 * rangée, une pastille de compte, et le tap ouvre le DayTasksModal existant —
 * le mois reste atteignable (§82), et une case reste une cible de dépôt.
 */
function MoisCompact({
  days,
  month,
  today,
  byDate,
  onOpenDay,
  onDropTask,
}: {
  days: string[];
  month: number;
  today: string;
  byDate: Map<string, SuccesTask[]>;
  onOpenDay: (date: string) => void;
  onDropTask: (taskId: string, date: string) => void;
}) {
  const [cible, setCible] = useState<string | null>(null);

  return (
    <div className="sm:hidden">
      <div className="grid grid-cols-7 gap-1 mb-1">
        {DAY_LABELS.map((label) => (
          <div key={label} className="text-center text-[10px] py-1" style={{ color: 'var(--color-text-tertiary)' }}>
            {label}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {days.map((date) => {
          const dansLeMois = parseIso(date).getMonth() === month;
          const isToday = date === today;
          const tasks = byDate.get(date) ?? [];
          const ouvertes = tasks.filter((task) => !task.done).length;
          const enRetard = ouvertes > 0 && date < today;
          return (
            <button
              key={date}
              type="button"
              onClick={() => onOpenDay(date)}
              onDragOver={(event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = 'move';
                setCible(date);
              }}
              onDragLeave={() => setCible((current) => (current === date ? null : current))}
              onDrop={(event) => {
                event.preventDefault();
                setCible(null);
                const id = event.dataTransfer.getData(MIME) || event.dataTransfer.getData('text/plain');
                if (id) onDropTask(id, date);
              }}
              className="relative aspect-square min-w-0 rounded-lg text-xs font-medium cursor-pointer flex flex-col items-center justify-center gap-0.5"
              style={{
                color: !dansLeMois ? 'var(--color-text-tertiary)' : isToday ? 'var(--color-text)' : 'var(--color-text-secondary)',
                background: cible === date
                  ? 'color-mix(in srgb, var(--color-accent) 18%, transparent)'
                  : 'var(--color-bg-secondary)',
                boxShadow: isToday ? 'inset 0 0 0 1px var(--color-accent)' : undefined,
                opacity: dansLeMois ? 1 : 0.45,
              }}
              aria-label={`${formatDayTitle(date)} — ${tasks.length} tâche${tasks.length > 1 ? 's' : ''}`}
              aria-current={isToday ? 'date' : undefined}
              title={`Voir les tâches du ${date}`}
            >
              <span className="leading-none">{date.slice(8)}</span>
              {tasks.length > 0 && (
                <span
                  className="min-w-4 px-1 rounded-full text-[9px] leading-4 font-semibold"
                  // Jamais de blanc en dur : sur l'accent cyan du thème sombre
                  // il faisait 1,8:1, et sur le gris d'un jour soldé 2,6:1
                  // (revue du 16 sept. 2026). L'encre « sur accent » de chaque
                  // palette, et un jour soldé en surface tertiaire + encre
                  // secondaire.
                  style={
                    enRetard
                      ? { color: 'var(--color-on-accent)', background: 'var(--color-error)' }
                      : ouvertes > 0
                        ? { color: 'var(--color-on-accent)', background: 'var(--color-accent)' }
                        : { color: 'var(--color-text-secondary)', background: 'var(--color-bg-tertiary)' }
                  }
                >
                  {ouvertes > 0 ? ouvertes : tasks.length}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function DropChoiceDialog({
  task,
  date,
  onOccurrence,
  onSeries,
  onCancel,
}: {
  task: SuccesTask;
  date: string;
  onOccurrence: () => void;
  onSeries: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onCancel]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Déplacer la tâche récurrente"
      onClick={onCancel}
      className="voile-modal z-50 flex items-center justify-center p-5 backdrop-blur-md"
      style={{ background: 'color-mix(in srgb, #000 55%, transparent)' }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-sm rounded-2xl p-5"
        style={{
          background: 'color-mix(in srgb, var(--color-surface) 92%, transparent)',
          border: '1px solid var(--color-border)',
          boxShadow: '0 24px 60px rgba(0,0,0,0.45)',
        }}
      >
        <h2 className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>
          Tâche récurrente
        </h2>
        <p className="text-sm mt-1 leading-6" style={{ color: 'var(--color-text-secondary)' }}>
          « {task.emoji ? `${task.emoji} ` : ''}{task.title} » fait partie d'une récurrence.
          Déplacer vers le {formatDayTitle(date).toLowerCase()} :
        </p>
        <div className="grid gap-2 mt-4">
          <button
            type="button"
            onClick={onOccurrence}
            className="w-full px-4 py-2.5 rounded-xl text-sm font-medium cursor-pointer text-left"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            Cette occurrence seulement
          </button>
          <button
            type="button"
            onClick={onSeries}
            className="w-full px-4 py-2.5 rounded-xl text-sm font-medium cursor-pointer text-left"
            style={{
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
          >
            Toute la série (même décalage)
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="w-full px-4 py-2 rounded-xl text-sm cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            Annuler
          </button>
        </div>
      </div>
    </div>
  );
}

interface Props {
  mode: BoardMode;
  anchor: string;
  tasks: SuccesTask[];
  onAnchorChange: (iso: string) => void;
  onReschedule: (taskId: string, date: string) => Promise<void>;
  onRescheduleSeries: (taskId: string, date: string) => Promise<void>;
  onClearDate: (taskId: string) => Promise<void>;
  onToggleTask: (task: SuccesTask) => Promise<void>;
  onToggleSubtask: (task: SuccesTask, subtask: SuccesSubtask) => Promise<void>;
  onQuickAdd: (date: string) => void;
}

export function TasksBoard({
  mode,
  anchor,
  tasks,
  onAnchorChange,
  onReschedule,
  onRescheduleSeries,
  onClearDate,
  onToggleTask,
  onToggleSubtask,
  onQuickAdd,
}: Props) {
  const today = localIsoDate();
  // null = closed, '' = the undated bucket, otherwise the ISO day.
  const [modalDate, setModalDate] = useState<string | null>(null);
  // Recurring occurrence dropped on a day → ask occurrence vs whole series.
  const [pendingDrop, setPendingDrop] = useState<{ task: SuccesTask; date: string } | null>(null);
  const [undatedOver, setUndatedOver] = useState(false);

  const weekStart = startOfWeekMonday(anchor);
  const weekDays = useMemo(
    () => Array.from({ length: 7 }, (_, index) => addDays(weekStart, index)),
    [weekStart],
  );
  const month = useMemo(() => monthMatrix(anchor), [anchor]);

  const byDate = useMemo(() => {
    const map = new Map<string, SuccesTask[]>();
    for (const task of tasks) {
      if (!task.date) continue;
      const bucket = map.get(task.date) ?? [];
      bucket.push(task);
      map.set(task.date, bucket);
    }
    for (const [key, value] of map) map.set(key, sortColumn(value));
    return map;
  }, [tasks]);

  // La réserve est repliée par défaut (24 août 2026) : le calendrier est ce
  // qu'on vient voir, la réserve est ce qu'on vient chercher. Elle reste une
  // cible de dépôt même repliée — glisser dessus déplie et retire la date.
  const [reserveOuverte, setReserveOuverte] = useState(false);
  const unscheduled = useMemo(
    () => sortColumn(tasks.filter((task) => !task.date)),
    [tasks],
  );

  // « Semaine du 2026-09-14 – 2026-09-20 » : 33 caractères serrés entre deux
  // chevrons à 340 px. La date humaine tient partout ; le préfixe revient
  // avec la largeur (16 sept. 2026).
  const heading =
    mode === 'week'
      ? (
        <>
          <span className="hidden sm:inline">Semaine du </span>
          {libelleIntervalle(weekDays[0], weekDays[6])}
        </>
      )
      : new Intl.DateTimeFormat('fr-CA', { month: 'long', year: 'numeric' }).format(parseIso(anchor));

  const shift = (direction: -1 | 1) => {
    if (mode === 'week') onAnchorChange(addDays(weekStart, direction * 7));
    else {
      const date = parseIso(anchor);
      date.setMonth(date.getMonth() + direction);
      onAnchorChange(localIsoDate(date));
    }
  };

  const drop = async (taskId: string, date: string) => {
    const task = tasks.find((item) => item.id === taskId);
    if (!task || task.date === date) return;
    // Recurring occurrence: let the user pick occurrence vs whole series.
    if (task.templateId && task.date) {
      setPendingDrop({ task, date });
      return;
    }
    await onReschedule(taskId, date);
  };

  const dropToUndated = async (taskId: string) => {
    const task = tasks.find((item) => item.id === taskId);
    if (!task || !task.date) return;
    await onClearDate(taskId);
  };

  const days = mode === 'week' ? weekDays : month.days;

  const modalTasks = modalDate === null
    ? []
    : modalDate === ''
      ? unscheduled
      : byDate.get(modalDate) ?? [];

  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => shift(-1)}
          className="p-2 rounded-xl cursor-pointer"
          style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
          aria-label="Période précédente"
        >
          <ChevronLeft size={16} />
        </button>
        <h2 className="text-sm font-medium capitalize text-center min-w-0 truncate" style={{ color: 'var(--color-text)' }}>
          {heading}
        </h2>
        <button
          type="button"
          onClick={() => shift(1)}
          className="p-2 rounded-xl cursor-pointer"
          style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
          aria-label="Période suivante"
        >
          <ChevronRight size={16} />
        </button>
      </div>

      {mode === 'month' && (
        <MoisCompact
          days={month.days}
          month={month.month}
          today={today}
          byDate={byDate}
          onOpenDay={setModalDate}
          onDropTask={(taskId, nextDate) => void drop(taskId, nextDate)}
        />
      )}

      {/* Sous sm, le mois vit dans MoisCompact : ses 200 px par cellule n'ont
          pas leur place ici. La semaine, elle, reste en une colonne souple. */}
      <div
        className={`gap-2 ${mode === 'week' ? 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-7' : 'hidden sm:grid sm:grid-cols-4 lg:grid-cols-7'}`}
      >
        {days.map((date) => (
          <DayColumn
            key={date}
            date={date}
            today={today}
            tasks={byDate.get(date) ?? []}
            dimmed={mode === 'month' && parseIso(date).getMonth() !== month.month}
            hauteur={mode === 'week' ? 'souple' : 'fixe'}
            onDropTask={(taskId, nextDate) => void drop(taskId, nextDate)}
            onToggleTask={(task) => void onToggleTask(task)}
            onQuickAdd={onQuickAdd}
            onOpenDay={setModalDate}
          />
        ))}
      </div>

      <CadreVitre as="section"
        className="rounded-2xl p-3 transition-colors"
        style={{
          background: undatedOver
            ? 'color-mix(in srgb, var(--color-accent) 10%, var(--color-bg-secondary))'
            : 'var(--color-bg-secondary)',
          border: `1px solid ${undatedOver ? 'var(--color-accent)' : 'var(--color-border)'}`,
        }}
        onDragOver={(event) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = 'move';
          setUndatedOver(true);
          if (!reserveOuverte) setReserveOuverte(true);
        }}
        onDragLeave={() => setUndatedOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setUndatedOver(false);
          const id = event.dataTransfer.getData(MIME) || event.dataTransfer.getData('text/plain');
          if (id) void dropToUndated(id);
        }}
      >
        <button
          type="button"
          onClick={() => setReserveOuverte((v) => !v)}
          className="w-full flex items-center gap-2 text-xs font-medium mb-2 cursor-pointer text-left"
          style={{ color: 'var(--color-text-tertiary)' }}
          aria-expanded={reserveOuverte}
        >
          <ChevronRight
            size={13}
            style={{
              transform: reserveOuverte ? 'rotate(90deg)' : 'none',
              transition: 'transform 160ms ease',
            }}
          />
          Sans date ({unscheduled.length})
          <span className="font-normal">{reserveOuverte ? '· replier' : '· déplier'}</span>
        </button>
        {reserveOuverte && unscheduled.length > 0 ? (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {unscheduled.map((task) => (
              <BoardCard
                key={task.id}
                task={task}
                today={today}
                onToggle={(item) => void onToggleTask(item)}
                onOpenDay={() => setModalDate('')}
              />
            ))}
          </div>
        ) : reserveOuverte ? (
          <p className="text-[11px] py-2 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
            Déposez une tâche ici pour retirer sa date.
          </p>
        ) : null}
        {reserveOuverte && (
          <p className="text-[11px] mt-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Glissez une tâche sur un jour pour la planifier, ou ici pour la remettre sans date.
          </p>
        )}
      </CadreVitre>

      {pendingDrop && (
        <DropChoiceDialog
          task={pendingDrop.task}
          date={pendingDrop.date}
          onOccurrence={() => {
            const { task, date } = pendingDrop;
            setPendingDrop(null);
            void onReschedule(task.id, date);
          }}
          onSeries={() => {
            const { task, date } = pendingDrop;
            setPendingDrop(null);
            void onRescheduleSeries(task.id, date);
          }}
          onCancel={() => setPendingDrop(null)}
        />
      )}

      {modalDate !== null && (
        <DayTasksModal
          date={modalDate}
          tasks={modalTasks}
          onClose={() => setModalDate(null)}
          onToggleTask={(task) => void onToggleTask(task)}
          onToggleSubtask={(task, subtask) => void onToggleSubtask(task, subtask)}
          onQuickAdd={onQuickAdd}
        />
      )}
    </div>
  );
}
