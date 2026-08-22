import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, CirclePlus, HardDrive, Loader2, Search } from 'lucide-react';
import { toast } from 'sonner';

import {
  addSuccesSubtask,
  createSuccesTask,
  deleteSuccesSubtask,
  deleteSuccesTask,
  fetchSuccesSyncStatus,
  listSuccesProjects,
  listSuccesTasks,
  rescheduleSuccesSeries,
  rescheduleSuccesTask,
  setSuccesSubtaskDone,
  setSuccesTaskDone,
  updateSuccesTask,
} from '../features/succes/api';
import { TaskCard, type SuccesTaskPatch } from '../features/succes/TaskCard';
import { TasksBoard } from '../features/succes/TasksBoard';
import { RecurrencesPanel } from '../features/succes/RecurrencesPanel';
import type { SuccesPriority, SuccesProject, SuccesSubtask, SuccesSyncStatus, SuccesTask } from '../features/succes/types';
import { loadTasksViewMode, saveTasksViewMode, type SuccesTasksViewMode } from '../features/succes/uiPrefs';
import { useConfirm } from '../components/ConfirmDialog';
import { useAppStore } from '../lib/store';
import { useRefreshOnFocus } from '../features/succes/useRefreshOnFocus';

type ViewMode = SuccesTasksViewMode;

function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function logSucces(level: 'info' | 'error', message: string) {
  useAppStore.getState().addLogEntry({
    timestamp: Date.now(),
    level,
    category: 'succes',
    message,
  });
}

export function SuccesTasksPage() {
  const confirm = useConfirm();
  const [tasks, setTasks] = useState<SuccesTask[]>([]);
  const [projects, setProjects] = useState<SuccesProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState('');
  const [includeDone, setIncludeDone] = useState(true);
  const [projectFilter, setProjectFilter] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>(() => loadTasksViewMode('week'));
  const [boardAnchor, setBoardAnchor] = useState(localIsoDate);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [date, setDate] = useState('');
  const [time, setTime] = useState('');
  const [priority, setPriority] = useState<SuccesPriority>('medium');
  const [notes, setNotes] = useState('');
  const [projectId, setProjectId] = useState('');
  const [category, setCategory] = useState('');
  const [emoji, setEmoji] = useState('');
  const [syncStatus, setSyncStatus] = useState<SuccesSyncStatus | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextTasks, nextProjects] = await Promise.all([
        listSuccesTasks({ includeDone, search }),
        listSuccesProjects(),
      ]);
      setTasks(nextTasks);
      setProjects(nextProjects);
      // This diagnostic is secondary: a temporarily unavailable status poll
      // must never hide task data that was loaded successfully from SQLite.
      try {
        setSyncStatus(await fetchSuccesSyncStatus());
      } catch (statusError) {
        setSyncStatus(null);
        const statusMessage = statusError instanceof Error ? statusError.message : String(statusError);
        logSucces('error', `État de synchronisation indisponible : ${statusMessage}`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logSucces('error', `Chargement des tâches échoué : ${message}`);
      toast.error('Les tâches ne peuvent pas être chargées.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [includeDone, search]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load]);

  // Une page ouverte gardait son état indéfiniment : ce qui change
  // ailleurs — téléphone, autre fenêtre, assistant — n'apparaissait
  // jamais. On relit au retour du focus.
  useRefreshOnFocus(() => void load());

  const refreshAfter = async (action: () => Promise<unknown>, success: string) => {
    setSaving(true);
    try {
      await action();
      await load();
      logSucces('info', success);
      toast.success(success, { description: 'Enregistré localement sur ce Mac.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logSucces('error', `${success} — échec : ${message}`);
      toast.error("L'action n'a pas été enregistrée.", { description: message });
    } finally {
      setSaving(false);
    }
  };

  const handleCreate = async () => {
    const clean = title.trim();
    if (!clean) return;
    await refreshAfter(
      () => createSuccesTask({
        title: clean,
        date,
        time,
        priority,
        notes,
        projectId,
        category: category.trim(),
        emoji: emoji.trim(),
      }),
      `Tâche créée : ${clean}`,
    );
    setTitle('');
    setNotes('');
    setDate('');
    setTime('');
    setPriority('medium');
    setProjectId('');
    setCategory('');
    setEmoji('');
    setShowCreate(false);
  };

  const toggleTask = (task: SuccesTask) =>
    refreshAfter(() => setSuccesTaskDone(task.id, !task.done), task.done ? 'Tâche rouverte' : 'Tâche terminée');

  const toggleSubtask = (task: SuccesTask, subtask: SuccesSubtask) =>
    refreshAfter(
      () => setSuccesSubtaskDone(task.id, subtask.id, !subtask.done),
      'Sous-tâche mise à jour',
    );

  const addSubtask = (task: SuccesTask, subtaskTitle: string, parentId?: string) =>
    refreshAfter(
      () => addSuccesSubtask(task.id, subtaskTitle, parentId),
      'Sous-tâche ajoutée',
    );

  const removeSubtask = (task: SuccesTask, subtask: SuccesSubtask) =>
    refreshAfter(
      () => deleteSuccesSubtask(task.id, subtask.id),
      'Sous-tâche supprimée',
    );

  const updateTask = (task: SuccesTask, patch: SuccesTaskPatch) =>
    refreshAfter(() => updateSuccesTask(task.id, patch), 'Tâche mise à jour');

  const rescheduleTask = async (task: SuccesTask, date: string) => {
    setSaving(true);
    try {
      const result = await rescheduleSuccesTask(task.id, date);
      await load();
      logSucces('info', `Tâche reportée au ${date}`);
      toast.success(`Reportée au ${date}`, {
        description: result.warning || 'Enregistré localement sur ce Mac.',
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logSucces('error', `Report échoué : ${message}`);
      toast.error('Le report a échoué.', { description: message });
    } finally {
      setSaving(false);
    }
  };

  const rescheduleById = async (taskId: string, date: string) => {
    const task = tasks.find((item) => item.id === taskId);
    if (!task) return;
    await rescheduleTask(task, date);
  };

  const rescheduleSeriesById = async (taskId: string, date: string) => {
    setSaving(true);
    try {
      const result = await rescheduleSuccesSeries(taskId, date);
      await load();
      logSucces('info', `Série décalée de ${result.deltaDays} j (${result.updated} occurrence(s))`);
      toast.success('Série décalée', {
        description: `${result.updated} occurrence(s) déplacée(s) du même écart.`,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logSucces('error', `Décalage de série échoué : ${message}`);
      toast.error("Le décalage de la série a échoué.", { description: message });
    } finally {
      setSaving(false);
    }
  };

  const clearTaskDate = async (taskId: string) => {
    const task = tasks.find((item) => item.id === taskId);
    if (!task) return;
    await refreshAfter(() => updateSuccesTask(taskId, { date: '' }), `Tâche remise sans date : ${task.title}`);
  };

  const openCreateForDate = (nextDate: string) => {
    setDate(nextDate);
    setShowCreate(true);
  };

  const removeTask = async (task: SuccesTask) => {
    const confirmed = await confirm({
      title: `Supprimer « ${task.title} » ?`,
      description: 'Cette action est sensible et sera enregistrée comme suppression synchronisable.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    await refreshAfter(() => deleteSuccesTask(task.id), `Tâche supprimée : ${task.title}`);
  };

  const cancelCreate = async () => {
    const dirty = Boolean(
      title.trim() || notes.trim() || date || time || projectId || category.trim() || emoji.trim() || priority !== 'medium',
    );
    if (dirty) {
      const confirmed = await confirm({
        title: 'Annuler la création ?',
        description: 'Les informations saisies ne seront pas enregistrées.',
        confirmLabel: 'Annuler',
        keepLabel: 'Garder',
        tone: 'warning',
      });
      if (!confirmed) return;
    }
    setShowCreate(false);
  };

  const visibleTasks = tasks.filter((task) => {
    if (projectFilter === '__none__') return !task.projectId;
    if (projectFilter) return task.projectId === projectFilter;
    return true;
  });

  return (
    <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
      <main className={`mx-auto w-full ${viewMode === 'list' ? 'max-w-5xl' : 'max-w-7xl'}`}>
        <header className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between mb-7">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>Succès</span>
              {saving && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}
            </div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>Tâches</h1>
            <p className="text-sm mt-2 max-w-xl" style={{ color: 'var(--color-text-secondary)' }}>
              Organisez vos actions et leurs étapes. DIA peut les gérer avec vous, sans envoyer vos données hors du Mac.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <div
              className="flex rounded-xl p-1"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              role="tablist"
              aria-label="Mode d’affichage"
            >
              {([
                { id: 'list' as const, label: 'Liste' },
                { id: 'week' as const, label: 'Semaine' },
                { id: 'month' as const, label: 'Mois' },
              ]).map((option) => (
                <button
                  key={option.id}
                  type="button"
                  role="tab"
                  aria-selected={viewMode === option.id}
                  onClick={() => {
                    setViewMode(option.id);
                    saveTasksViewMode(option.id);
                  }}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer"
                  style={{
                    background: viewMode === option.id ? 'var(--color-surface)' : 'transparent',
                    color: viewMode === option.id ? 'var(--color-text)' : 'var(--color-text-secondary)',
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setShowCreate((value) => !value)}
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer"
              style={{ background: 'var(--color-accent)', color: '#fff' }}
            >
              <CirclePlus size={16} /> Nouvelle tâche
            </button>
          </div>
        </header>

        <section
          className="flex flex-col md:flex-row md:items-center gap-3 rounded-2xl p-3 mb-4"
          style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex-1 flex items-center gap-2 px-2">
            <Search size={15} style={{ color: 'var(--color-text-tertiary)' }} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Rechercher une tâche…"
              className="w-full bg-transparent outline-none text-sm"
              style={{ color: 'var(--color-text)' }}
            />
          </div>
          <label className="flex items-center gap-2 text-xs cursor-pointer px-2" style={{ color: 'var(--color-text-secondary)' }}>
            <input type="checkbox" checked={includeDone} onChange={(event) => setIncludeDone(event.target.checked)} />
            Afficher les tâches terminées
          </label>
          <select
            value={projectFilter}
            onChange={(event) => setProjectFilter(event.target.value)}
            className="rounded-xl px-3 py-2 text-xs bg-transparent outline-none cursor-pointer"
            style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            aria-label="Filtrer par projet"
          >
            <option value="">Tous les projets</option>
            <option value="__none__">Sans projet</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>{project.name}</option>
            ))}
          </select>
        </section>

        {syncStatus && (
          <div className="flex items-start gap-2 mb-5 px-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            <HardDrive size={14} className="mt-0.5 shrink-0" />
            <span>{syncStatus.message} Journal local : {syncStatus.localCursor} opération(s).</span>
          </div>
        )}

        {showCreate && (
          <section
            className="grid gap-3 rounded-2xl p-4 mb-5"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}
          >
            <div className="flex items-center gap-2">
              <input
                value={emoji}
                onChange={(event) => setEmoji(event.target.value.slice(0, 8))}
                placeholder="✨"
                maxLength={8}
                className="w-14 rounded-xl px-2 py-2 text-center text-lg bg-transparent outline-none"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                aria-label="Emoji"
              />
              <input
                autoFocus
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) void handleCreate(); }}
                placeholder="Qu'est-ce qui doit être fait ?"
                maxLength={200}
                className="flex-1 bg-transparent outline-none text-base font-medium px-2 py-1"
                style={{ color: 'var(--color-text)' }}
              />
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
              <input
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
                className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
                style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
              />
              <input
                type="time"
                value={time}
                onChange={(event) => setTime(event.target.value)}
                className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
                style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
              />
              <select
                value={priority}
                onChange={(event) => setPriority(event.target.value as SuccesPriority)}
                className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
                style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
              >
                <option value="low">Priorité basse</option>
                <option value="medium">Priorité normale</option>
                <option value="high">Priorité haute</option>
                <option value="urgent">Priorité urgente</option>
              </select>
              <select
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
                style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
              >
                <option value="">Sans projet</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            </div>
            <input
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              placeholder="Catégorie (facultatif)"
              maxLength={100}
              className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
              style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            />
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Notes facultatives…"
              maxLength={2000}
              rows={2}
              className="resize-none rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
              style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            />
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => void cancelCreate()} className="px-3 py-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>Annuler</button>
              <button type="button" disabled={!title.trim() || saving} onClick={() => void handleCreate()} className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>Enregistrer localement</button>
            </div>
            <RecurrencesPanel kind="task" embedded />
          </section>
        )}

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
            <Loader2 size={17} className="animate-spin" /> Chargement des tâches…
          </div>
        ) : viewMode !== 'list' ? (
          <TasksBoard
            mode={viewMode}
            anchor={boardAnchor}
            tasks={visibleTasks}
            onAnchorChange={setBoardAnchor}
            onReschedule={rescheduleById}
            onRescheduleSeries={rescheduleSeriesById}
            onClearDate={clearTaskDate}
            onToggleTask={toggleTask}
            onToggleSubtask={toggleSubtask}
            onQuickAdd={openCreateForDate}
          />
        ) : visibleTasks.length === 0 ? (
          <div className="rounded-2xl py-16 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <CheckCircle2 size={28} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} />
            <p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucune tâche ici</p>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Créez-en une, ou demandez simplement à DIA.</p>
          </div>
        ) : (
          <div className="grid gap-3">
            {visibleTasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                projects={projects}
                onToggleTask={toggleTask}
                onToggleSubtask={toggleSubtask}
                onAddSubtask={addSubtask}
                onDeleteSubtask={removeSubtask}
                onUpdate={updateTask}
                onReschedule={rescheduleTask}
                onDelete={removeTask}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
