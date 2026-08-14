import { useState } from 'react';
import { CalendarDays, Check, ChevronDown, ChevronRight, Clock3, Plus, Trash2 } from 'lucide-react';
import type { SuccesSubtask, SuccesTask } from './types';

const PRIORITY: Record<SuccesTask['priority'], { label: string; color: string }> = {
  urgent: { label: 'Urgente', color: 'var(--color-error)' },
  high: { label: 'Haute', color: 'var(--color-warning)' },
  medium: { label: 'Normale', color: 'var(--color-accent)' },
  low: { label: 'Basse', color: 'var(--color-text-tertiary)' },
};

interface Props {
  task: SuccesTask;
  onToggleTask: (task: SuccesTask) => Promise<void>;
  onToggleSubtask: (task: SuccesTask, subtask: SuccesSubtask) => Promise<void>;
  onAddSubtask: (task: SuccesTask, title: string, parentId?: string) => Promise<void>;
  onDelete?: (task: SuccesTask) => Promise<void>;
  compact?: boolean;
}

function SubtaskRow({
  task,
  subtask,
  depth,
  onToggle,
  onAdd,
}: {
  task: SuccesTask;
  subtask: SuccesSubtask;
  depth: number;
  onToggle: Props['onToggleSubtask'];
  onAdd: Props['onAddSubtask'];
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');
  const [expanded, setExpanded] = useState(true);

  const submit = async () => {
    const clean = title.trim();
    if (!clean) return;
    await onAdd(task, clean, subtask.id);
    setTitle('');
    setAdding(false);
    setExpanded(true);
  };

  return (
    <div style={{ marginLeft: depth ? 18 : 0 }}>
      <div className="group flex items-center gap-2 min-h-8 py-1">
        {subtask.children.length > 0 ? (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="p-0.5 rounded cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)' }}
            aria-label={expanded ? 'Réduire' : 'Développer'}
          >
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        ) : <span className="w-4" />}
        <button
          type="button"
          onClick={() => void onToggle(task, subtask)}
          className="size-5 rounded-md flex items-center justify-center cursor-pointer transition-colors"
          style={{
            border: `1px solid ${subtask.done ? 'var(--color-accent)' : 'var(--color-border)'}`,
            background: subtask.done ? 'var(--color-accent)' : 'transparent',
            color: '#fff',
          }}
          aria-label={subtask.done ? 'Rouvrir la sous-tâche' : 'Terminer la sous-tâche'}
        >
          {subtask.done && <Check size={12} />}
        </button>
        <span
          className="flex-1 text-sm"
          style={{
            color: subtask.done ? 'var(--color-text-tertiary)' : 'var(--color-text-secondary)',
            textDecoration: subtask.done ? 'line-through' : 'none',
          }}
        >
          {subtask.title || 'Sous-tâche sans titre'}
        </span>
        <button
          type="button"
          onClick={() => setAdding((value) => !value)}
          className="opacity-0 group-hover:opacity-100 p-1 rounded cursor-pointer transition-opacity"
          style={{ color: 'var(--color-text-tertiary)' }}
          title="Ajouter une étape à l'intérieur"
        >
          <Plus size={13} />
        </button>
      </div>
      {adding && (
        <div className="flex gap-2 ml-9 mb-2">
          <input
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void submit();
              if (event.key === 'Escape') setAdding(false);
            }}
            placeholder="Nouvelle étape…"
            className="flex-1 min-w-0 bg-transparent text-sm outline-none px-2 py-1 rounded-md"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
          />
        </div>
      )}
      {expanded && subtask.children.map((child) => (
        <SubtaskRow
          key={child.id}
          task={task}
          subtask={child}
          depth={depth + 1}
          onToggle={onToggle}
          onAdd={onAdd}
        />
      ))}
    </div>
  );
}

export function TaskCard({ task, onToggleTask, onToggleSubtask, onAddSubtask, onDelete, compact }: Props) {
  const [adding, setAdding] = useState(false);
  const [subtaskTitle, setSubtaskTitle] = useState('');
  const priority = PRIORITY[task.priority];

  const submitSubtask = async () => {
    const title = subtaskTitle.trim();
    if (!title) return;
    await onAddSubtask(task, title);
    setSubtaskTitle('');
    setAdding(false);
  };

  return (
    <article
      className={`rounded-2xl ${compact ? 'p-3' : 'p-4'} transition-colors`}
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={() => void onToggleTask(task)}
          className="mt-0.5 size-6 rounded-lg flex items-center justify-center shrink-0 cursor-pointer"
          style={{
            border: `1px solid ${task.done ? 'var(--color-accent)' : 'var(--color-border)'}`,
            background: task.done ? 'var(--color-accent)' : 'var(--color-bg-secondary)',
            color: '#fff',
          }}
          aria-label={task.done ? 'Rouvrir la tâche' : 'Terminer la tâche'}
        >
          {task.done && <Check size={14} />}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-3">
            <h3
              className="flex-1 font-medium leading-6 break-words"
              style={{
                color: task.done ? 'var(--color-text-tertiary)' : 'var(--color-text)',
                textDecoration: task.done ? 'line-through' : 'none',
              }}
            >
              {task.title}
            </h3>
            <span
              className="text-[11px] px-2 py-0.5 rounded-full shrink-0"
              style={{ color: priority.color, background: `color-mix(in srgb, ${priority.color} 12%, transparent)` }}
            >
              {priority.label}
            </span>
          </div>
          {(task.date || task.time || task.notes) && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {task.date && <span className="flex items-center gap-1"><CalendarDays size={12} />{task.date}</span>}
              {task.time && <span className="flex items-center gap-1"><Clock3 size={12} />{task.time}</span>}
              {task.notes && <span className="truncate max-w-[420px]">{task.notes}</span>}
            </div>
          )}
        </div>
        {onDelete && (
          <button
            type="button"
            onClick={() => void onDelete(task)}
            className="p-1.5 rounded-lg cursor-pointer opacity-60 hover:opacity-100"
            style={{ color: 'var(--color-error)' }}
            title="Supprimer"
          >
            <Trash2 size={15} />
          </button>
        )}
      </div>

      {(task.subtasks.length > 0 || adding) && (
        <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--color-border)' }}>
          {task.subtasks.map((subtask) => (
            <SubtaskRow
              key={subtask.id}
              task={task}
              subtask={subtask}
              depth={0}
              onToggle={onToggleSubtask}
              onAdd={onAddSubtask}
            />
          ))}
          {adding && (
            <div className="flex gap-2 mt-2 ml-9">
              <input
                autoFocus
                value={subtaskTitle}
                onChange={(event) => setSubtaskTitle(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void submitSubtask();
                  if (event.key === 'Escape') setAdding(false);
                }}
                placeholder="Nouvelle sous-tâche…"
                className="flex-1 min-w-0 bg-transparent text-sm outline-none px-2 py-1.5 rounded-lg"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
              <button
                type="button"
                onClick={() => void submitSubtask()}
                className="px-3 rounded-lg text-xs cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                Ajouter
              </button>
            </div>
          )}
        </div>
      )}
      {!task.done && !adding && (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="mt-3 flex items-center gap-1.5 text-xs cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          <Plus size={13} /> Ajouter une sous-tâche
        </button>
      )}
    </article>
  );
}
