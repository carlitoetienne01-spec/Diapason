import { useCallback, useEffect, useRef, useState } from 'react';
import { ArchiveRestore, CheckCircle2, CirclePlus, HardDrive, Loader2, Search } from 'lucide-react';
import { toast } from 'sonner';

import {
  addSuccesSubtask,
  createSuccesTask,
  deleteSuccesTask,
  fetchSuccesSyncStatus,
  importLegacySuccesSnapshot,
  listSuccesTasks,
  setSuccesSubtaskDone,
  setSuccesTaskDone,
} from '../features/succes/api';
import { TaskCard } from '../features/succes/TaskCard';
import type { SuccesPriority, SuccesSubtask, SuccesSyncStatus, SuccesTask } from '../features/succes/types';
import { useAppStore } from '../lib/store';

function logSucces(level: 'info' | 'error', message: string) {
  useAppStore.getState().addLogEntry({
    timestamp: Date.now(),
    level,
    category: 'succes',
    message,
  });
}

export function SuccesTasksPage() {
  const [tasks, setTasks] = useState<SuccesTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState('');
  const [includeDone, setIncludeDone] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [date, setDate] = useState('');
  const [priority, setPriority] = useState<SuccesPriority>('medium');
  const [notes, setNotes] = useState('');
  const [syncStatus, setSyncStatus] = useState<SuccesSyncStatus | null>(null);
  const importRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await listSuccesTasks({ includeDone, search });
      setTasks(next);
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
      () => createSuccesTask({ title: clean, date, priority, notes }),
      `Tâche créée : ${clean}`,
    );
    setTitle('');
    setNotes('');
    setDate('');
    setPriority('medium');
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

  const removeTask = async (task: SuccesTask) => {
    const confirmed = window.confirm(
      `Supprimer « ${task.title} » ?\n\nCette action est sensible et sera enregistrée comme suppression synchronisable.`,
    );
    if (!confirmed) return;
    await refreshAfter(() => deleteSuccesTask(task.id), `Tâche supprimée : ${task.title}`);
  };

  const importLegacy = async (file: File) => {
    setSaving(true);
    try {
      const raw = await file.text();
      const snapshot = JSON.parse(raw) as unknown;
      const result = await importLegacySuccesSnapshot(snapshot);
      await load();
      const summary = result.summary;
      const message = summary.alreadyImported
        ? 'Cette sauvegarde avait déjà été importée.'
        : `${summary.tasksImported} tâche(s) et ${summary.projectsImported} projet(s) importés.`;
      logSucces('info', `Import Life OS : ${message}`);
      toast.success('Import terminé', { description: message });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logSucces('error', `Import Life OS échoué : ${message}`);
      toast.error("La sauvegarde n'a pas pu être importée.", { description: message });
    } finally {
      setSaving(false);
      if (importRef.current) importRef.current.value = '';
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
      <main className="max-w-5xl mx-auto w-full">
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
            <input
              ref={importRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void importLegacy(file);
              }}
            />
            <button
              type="button"
              onClick={() => importRef.current?.click()}
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm cursor-pointer"
              style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            >
              <ArchiveRestore size={15} /> Importer Life OS
            </button>
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
            <input
              autoFocus
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) void handleCreate(); }}
              placeholder="Qu'est-ce qui doit être fait ?"
              maxLength={200}
              className="bg-transparent outline-none text-base font-medium px-2 py-1"
              style={{ color: 'var(--color-text)' }}
            />
            <div className="grid sm:grid-cols-[1fr_170px] gap-3">
              <input
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
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
            </div>
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
              <button type="button" onClick={() => setShowCreate(false)} className="px-3 py-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>Annuler</button>
              <button type="button" disabled={!title.trim() || saving} onClick={() => void handleCreate()} className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>Enregistrer localement</button>
            </div>
          </section>
        )}

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
            <Loader2 size={17} className="animate-spin" /> Chargement des tâches…
          </div>
        ) : tasks.length === 0 ? (
          <div className="rounded-2xl py-16 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <CheckCircle2 size={28} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} />
            <p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucune tâche ici</p>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Créez-en une, ou demandez simplement à DIA.</p>
          </div>
        ) : (
          <div className="grid gap-3">
            {tasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onToggleTask={toggleTask}
                onToggleSubtask={toggleSubtask}
                onAddSubtask={addSubtask}
                onDelete={removeTask}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
