import { useEffect, useState } from 'react';
import {
  BriefcaseBusiness,
  CalendarClock,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Minus,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react';
import { useConfirm } from '../../components/ConfirmDialog';
import type { SuccesPriority, SuccesProject, SuccesSubtask, SuccesTask } from './types';
import {
  loadSubtaskExpanded,
  loadTaskSubtasksOpen,
  saveSubtaskExpanded,
  saveTaskSubtasksOpen,
} from './uiPrefs';

const PRIORITY: Record<SuccesTask['priority'], { label: string; color: string }> = {
  urgent: { label: 'Urgente', color: 'var(--color-error)' },
  high: { label: 'Haute', color: 'var(--color-warning)' },
  medium: { label: 'Normale', color: 'var(--color-accent)' },
  low: { label: 'Basse', color: 'var(--color-text-tertiary)' },
};

export type SuccesTaskPatch = Partial<
  Pick<SuccesTask, 'title' | 'date' | 'time' | 'priority' | 'notes' | 'projectId' | 'category' | 'emoji'>
>;

function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function shiftIsoDate(iso: string | undefined, days: number) {
  const base = iso ? new Date(`${iso}T12:00:00`) : new Date();
  if (Number.isNaN(base.getTime())) {
    const fallback = new Date();
    fallback.setDate(fallback.getDate() + days);
    return localIsoDate(fallback);
  }
  base.setDate(base.getDate() + days);
  return localIsoDate(base);
}

interface Props {
  task: SuccesTask;
  projects?: SuccesProject[];
  onToggleTask: (task: SuccesTask) => Promise<void>;
  onToggleSubtask: (task: SuccesTask, subtask: SuccesSubtask) => Promise<void>;
  onAddSubtask: (task: SuccesTask, title: string, parentId?: string) => Promise<void>;
  onDeleteSubtask?: (task: SuccesTask, subtask: SuccesSubtask) => Promise<void>;
  onUpdate?: (task: SuccesTask, patch: SuccesTaskPatch) => Promise<void>;
  onReschedule?: (task: SuccesTask, date: string) => Promise<void>;
  onAssignProject?: (task: SuccesTask, projectId: string) => Promise<void>;
  onDelete?: (task: SuccesTask) => Promise<void>;
  compact?: boolean;
}

function SubtaskRow({
  task,
  subtask,
  depth,
  onToggle,
  onAdd,
  onDelete,
}: {
  task: SuccesTask;
  subtask: SuccesSubtask;
  depth: number;
  onToggle: Props['onToggleSubtask'];
  onAdd: Props['onAddSubtask'];
  onDelete?: Props['onDeleteSubtask'];
}) {
  const confirm = useConfirm();
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');
  const [expanded, setExpanded] = useState(() => loadSubtaskExpanded(subtask.id, true));

  const submit = async () => {
    const clean = title.trim();
    if (!clean) return;
    await onAdd(task, clean, subtask.id);
    setTitle('');
    setAdding(false);
    setExpanded(true);
    saveSubtaskExpanded(subtask.id, true);
  };

  const remove = async () => {
    if (!onDelete) return;
    const hasChildren = subtask.children.length > 0;
    const confirmed = await confirm({
      title: 'Supprimer cette sous-tâche ?',
      description: hasChildren
        ? `« ${subtask.title || 'Sous-tâche'} » et ses étapes internes seront supprimées.`
        : `« ${subtask.title || 'Sous-tâche'} » sera supprimée définitivement.`,
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    await onDelete(task, subtask);
  };

  const toggleExpanded = () => {
    setExpanded((value) => {
      const next = !value;
      saveSubtaskExpanded(subtask.id, next);
      return next;
    });
  };

  return (
    <div style={{ marginLeft: depth ? 18 : 0 }}>
      <div className="group flex items-center gap-2 min-h-8 py-1">
        {subtask.children.length > 0 ? (
          <button
            type="button"
            onClick={toggleExpanded}
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
        <div className="flex items-center gap-0.5">
          {onDelete ? (
            <button
              type="button"
              onClick={() => void remove()}
              className="p-1 rounded cursor-pointer opacity-55 hover:opacity-100 transition-opacity"
              style={{ color: 'var(--color-error)' }}
              aria-label="Supprimer la sous-tâche"
              title="Supprimer"
            >
              <Minus size={13} strokeWidth={2.25} />
            </button>
          ) : null}
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
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}

function draftFromTask(task: SuccesTask) {
  return {
    title: task.title,
    date: task.date || '',
    time: task.time || '',
    priority: task.priority,
    notes: task.notes || '',
    projectId: task.projectId || '',
    category: task.category || '',
    emoji: task.emoji || '',
  };
}

export function TaskCard({
  task,
  projects = [],
  onToggleTask,
  onToggleSubtask,
  onAddSubtask,
  onDeleteSubtask,
  onUpdate,
  onReschedule,
  onAssignProject,
  onDelete,
  compact,
}: Props) {
  const confirm = useConfirm();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(false);
  const [rescheduling, setRescheduling] = useState(false);
  const [saving, setSaving] = useState(false);
  const [customDate, setCustomDate] = useState(task.date || localIsoDate());
  const [subtaskTitle, setSubtaskTitle] = useState('');
  const [draft, setDraft] = useState(() => draftFromTask(task));
  const [subtasksOpen, setSubtasksOpen] = useState(() => loadTaskSubtasksOpen(task.id, true));
  const priority = PRIORITY[task.priority];
  const project = projects.find((item) => item.id === task.projectId);
  const hasSubtasks = task.subtasks.length > 0;

  useEffect(() => {
    if (!editing) setDraft(draftFromTask(task));
    if (!rescheduling) setCustomDate(task.date || localIsoDate());
  }, [task, editing, rescheduling]);

  useEffect(() => {
    setSubtasksOpen(loadTaskSubtasksOpen(task.id, true));
  }, [task.id]);

  const submitSubtask = async () => {
    const title = subtaskTitle.trim();
    if (!title) return;
    await onAddSubtask(task, title);
    setSubtaskTitle('');
    setAdding(false);
    setSubtasksOpen(true);
    saveTaskSubtasksOpen(task.id, true);
  };

  const toggleSubtasksOpen = () => {
    setSubtasksOpen((value) => {
      const next = !value;
      saveTaskSubtasksOpen(task.id, next);
      return next;
    });
  };

  const moveTo = async (date: string) => {
    if (!onReschedule) return;
    setSaving(true);
    try {
      await onReschedule(task, date);
      setRescheduling(false);
    } finally {
      setSaving(false);
    }
  };

  const saveEdit = async () => {
    if (!onUpdate) return;
    const cleanTitle = draft.title.trim();
    if (!cleanTitle) return;
    setSaving(true);
    try {
      const patch: SuccesTaskPatch = {};
      if (cleanTitle !== task.title) patch.title = cleanTitle;
      if (draft.date !== (task.date || '')) patch.date = draft.date;
      if (draft.time !== (task.time || '')) patch.time = draft.time;
      if (draft.priority !== task.priority) patch.priority = draft.priority;
      if (draft.notes !== (task.notes || '')) patch.notes = draft.notes;
      if (draft.projectId !== (task.projectId || '')) patch.projectId = draft.projectId;
      if (draft.category !== (task.category || '')) patch.category = draft.category;
      if (draft.emoji !== (task.emoji || '')) patch.emoji = draft.emoji;
      if (Object.keys(patch).length) await onUpdate(task, patch);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const cancelEdit = async () => {
    const baseline = draftFromTask(task);
    const dirty =
      draft.title !== baseline.title ||
      draft.date !== baseline.date ||
      draft.time !== baseline.time ||
      draft.priority !== baseline.priority ||
      draft.notes !== baseline.notes ||
      draft.projectId !== baseline.projectId ||
      draft.category !== baseline.category ||
      draft.emoji !== baseline.emoji;
    if (dirty) {
      const confirmed = await confirm({
        title: 'Annuler les modifications ?',
        description: 'Les changements non enregistrés seront perdus.',
        confirmLabel: 'Annuler',
        keepLabel: 'Garder',
        tone: 'warning',
      });
      if (!confirmed) return;
    }
    setEditing(false);
  };

  const cancelReschedule = async () => {
    if (customDate !== (task.date || localIsoDate())) {
      const confirmed = await confirm({
        title: 'Annuler le report ?',
        description: 'La nouvelle date saisie ne sera pas appliquée.',
        confirmLabel: 'Annuler',
        keepLabel: 'Garder',
        tone: 'warning',
      });
      if (!confirmed) return;
    }
    setRescheduling(false);
  };

  if (editing && onUpdate) {
    return (
      <article
        className="rounded-2xl p-4 grid gap-3"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}
      >
        <div className="flex items-center gap-2">
          <input
            value={draft.emoji}
            onChange={(event) => setDraft({ ...draft, emoji: event.target.value.slice(0, 8) })}
            placeholder="✨"
            maxLength={8}
            className="w-14 rounded-xl px-2 py-2 text-center text-lg bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            aria-label="Emoji"
          />
          <input
            autoFocus
            value={draft.title}
            onChange={(event) => setDraft({ ...draft, title: event.target.value })}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) void saveEdit();
              if (event.key === 'Escape') setEditing(false);
            }}
            maxLength={200}
            className="flex-1 rounded-xl px-3 py-2 font-medium bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            aria-label="Titre"
          />
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
          <input
            type="date"
            value={draft.date}
            onChange={(event) => setDraft({ ...draft, date: event.target.value })}
            className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            aria-label="Date"
          />
          <input
            type="time"
            value={draft.time}
            onChange={(event) => setDraft({ ...draft, time: event.target.value })}
            className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            aria-label="Heure"
          />
          <select
            value={draft.priority}
            onChange={(event) => setDraft({ ...draft, priority: event.target.value as SuccesPriority })}
            className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            aria-label="Priorité"
          >
            <option value="low">Priorité basse</option>
            <option value="medium">Priorité normale</option>
            <option value="high">Priorité haute</option>
            <option value="urgent">Priorité urgente</option>
          </select>
          <select
            value={draft.projectId}
            onChange={(event) => setDraft({ ...draft, projectId: event.target.value })}
            className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            aria-label="Projet"
          >
            <option value="">Sans projet</option>
            {projects.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        </div>
        <input
          value={draft.category}
          onChange={(event) => setDraft({ ...draft, category: event.target.value })}
          placeholder="Catégorie (facultatif)"
          maxLength={100}
          className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        />
        <textarea
          value={draft.notes}
          onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
          placeholder="Notes…"
          maxLength={2000}
          rows={3}
          className="resize-none rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => void cancelEdit()}
            className="flex items-center gap-1.5 px-3 py-2 text-sm cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <X size={14} /> Annuler
          </button>
          <button
            type="button"
            disabled={!draft.title.trim() || saving}
            onClick={() => void saveEdit()}
            className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            Enregistrer
          </button>
        </div>
      </article>
    );
  }

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
              {task.emoji ? `${task.emoji} ` : ''}{task.title}
            </h3>
            <span
              className="succes-priority text-[11px] px-2 py-0.5 rounded-full shrink-0"
              data-priority={task.priority}
              style={{ color: priority.color, background: `color-mix(in srgb, ${priority.color} 12%, transparent)` }}
            >
              {priority.label}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {task.date && <span className="flex items-center gap-1"><CalendarDays size={12} />{task.date}</span>}
            {task.time && <span className="flex items-center gap-1"><Clock3 size={12} />{task.time}</span>}
            {project && (
              <span className="flex items-center gap-1" style={{ color: project.color || 'var(--color-text-tertiary)' }}>
                <BriefcaseBusiness size={12} />
                {project.name}
              </span>
            )}
            {task.category && <span>{task.category}</span>}
            {task.postponedCount > 0 && (
              <span className="flex items-center gap-1" style={{ color: task.postponedCount >= 4 ? 'var(--color-warning)' : undefined }}>
                <CalendarClock size={12} />
                Reportée {task.postponedCount}×
              </span>
            )}
            {task.notes && <span className="truncate max-w-[420px]">{task.notes}</span>}
          </div>
          {rescheduling && onReschedule && (
            <div
              className="mt-3 grid gap-2 rounded-xl p-3"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <p className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>Reporter au…</p>
              <div className="flex flex-wrap gap-1.5">
                {[
                  { label: 'Aujourd’hui', date: localIsoDate() },
                  { label: 'Demain', date: shiftIsoDate(undefined, 1) },
                  { label: '+3 jours', date: shiftIsoDate(task.date || undefined, 3) },
                  { label: '+1 semaine', date: shiftIsoDate(task.date || undefined, 7) },
                ].map((option) => (
                  <button
                    key={option.label}
                    type="button"
                    disabled={saving || option.date === task.date}
                    onClick={() => void moveTo(option.date)}
                    className="px-2.5 py-1.5 rounded-lg text-xs cursor-pointer disabled:opacity-40"
                    style={{
                      background: 'var(--color-surface)',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="date"
                  value={customDate}
                  onChange={(event) => setCustomDate(event.target.value)}
                  className="rounded-lg px-2 py-1.5 text-xs bg-transparent outline-none"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                />
                <button
                  type="button"
                  disabled={!customDate || saving || customDate === task.date}
                  onClick={() => void moveTo(customDate)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40 cursor-pointer"
                  style={{ background: 'var(--color-accent)', color: '#fff' }}
                >
                  Reporter
                </button>
                <button
                  type="button"
                  onClick={() => void cancelReschedule()}
                  className="px-2 py-1.5 text-xs cursor-pointer"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  Annuler
                </button>
              </div>
            </div>
          )}
          {!onUpdate && onAssignProject && projects.length > 0 && (
            <select
              value={task.projectId || ''}
              onChange={(event) => void onAssignProject(task, event.target.value)}
              className="mt-2 rounded-lg px-2 py-1 text-xs bg-transparent outline-none cursor-pointer"
              style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
              aria-label="Assigner à un projet"
            >
              <option value="">Sans projet</option>
              {projects.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          )}
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          {onReschedule && !task.done && (
            <button
              type="button"
              onClick={() => { setRescheduling((value) => !value); setEditing(false); }}
              className="p-1.5 rounded-lg cursor-pointer opacity-60 hover:opacity-100"
              style={{ color: rescheduling ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }}
              title="Reporter"
              aria-label="Reporter la tâche"
              aria-expanded={rescheduling}
            >
              <CalendarClock size={15} />
            </button>
          )}
          {onUpdate && (
            <button
              type="button"
              onClick={() => { setEditing(true); setRescheduling(false); }}
              className="p-1.5 rounded-lg cursor-pointer opacity-60 hover:opacity-100"
              style={{ color: 'var(--color-text-tertiary)' }}
              title="Modifier"
              aria-label="Modifier la tâche"
            >
              <Pencil size={15} />
            </button>
          )}
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
          {hasSubtasks && (
            <button
              type="button"
              onClick={toggleSubtasksOpen}
              className="p-1.5 rounded-lg cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
              aria-label={subtasksOpen ? 'Masquer les sous-tâches' : 'Afficher les sous-tâches'}
              aria-expanded={subtasksOpen}
            >
              {subtasksOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </button>
          )}
        </div>
      </div>

      {((hasSubtasks && subtasksOpen) || adding) && (
        <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--color-border)' }}>
          {subtasksOpen &&
            task.subtasks.map((subtask) => (
            <SubtaskRow
              key={subtask.id}
              task={task}
              subtask={subtask}
              depth={0}
              onToggle={onToggleSubtask}
              onAdd={onAddSubtask}
              onDelete={onDeleteSubtask}
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
          onClick={() => {
            setAdding(true);
            setSubtasksOpen(true);
            saveTaskSubtasksOpen(task.id, true);
          }}
          className="mt-3 flex items-center gap-1.5 text-xs cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          <Plus size={13} /> Ajouter une sous-tâche
        </button>
      )}
    </article>
  );
}
