import { useCallback, useEffect, useState } from 'react';
import { CalendarCheck2, ChevronLeft, ChevronRight, CirclePlus, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import {
  addSuccesSubtask,
  createSuccesTask,
  fetchSuccesPlanner,
  setSuccesSubtaskDone,
  setSuccesTaskDone,
} from '../features/succes/api';
import { TaskCard } from '../features/succes/TaskCard';
import type { PlannerResponse, SuccesSubtask, SuccesTask } from '../features/succes/types';
import { useAppStore } from '../lib/store';

function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function moveDate(iso: string, days: number) {
  const [year, month, day] = iso.split('-').map(Number);
  const next = new Date(year, month - 1, day);
  next.setDate(next.getDate() + days);
  return localIsoDate(next);
}

export function SuccesPlannerPage() {
  const [selectedDate, setSelectedDate] = useState(localIsoDate());
  const [planner, setPlanner] = useState<PlannerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [quickTitle, setQuickTitle] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPlanner(await fetchSuccesPlanner(selectedDate));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `Planificateur : ${message}` });
      toast.error('Le plan du jour ne peut pas être chargé.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [selectedDate]);

  useEffect(() => { void load(); }, [load]);

  const change = async (action: () => Promise<unknown>, success: string) => {
    setSaving(true);
    try {
      await action();
      await load();
      toast.success(success, { description: 'Enregistré localement sur ce Mac.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `${success} — échec : ${message}` });
      toast.error("L'action n'a pas été enregistrée.", { description: message });
    } finally {
      setSaving(false);
    }
  };

  const createQuickTask = async () => {
    const title = quickTitle.trim();
    if (!title) return;
    await change(() => createSuccesTask({ title, date: selectedDate }), `Tâche ajoutée au ${selectedDate}`);
    setQuickTitle('');
  };

  const toggleTask = (task: SuccesTask) =>
    change(() => setSuccesTaskDone(task.id, !task.done), task.done ? 'Tâche rouverte' : 'Tâche terminée');
  const toggleSubtask = (task: SuccesTask, subtask: SuccesSubtask) =>
    change(() => setSuccesSubtaskDone(task.id, subtask.id, !subtask.done), 'Sous-tâche mise à jour');
  const addSubtask = (task: SuccesTask, title: string, parentId?: string) =>
    change(() => addSuccesSubtask(task.id, title, parentId), 'Sous-tâche ajoutée');

  const displayDate = new Intl.DateTimeFormat('fr-CA', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
  }).format(new Date(`${selectedDate}T12:00:00Z`));

  return (
    <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
      <main className="max-w-5xl mx-auto w-full">
        <header className="mb-7">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>Succès</span>
            {saving && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}
          </div>
          <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>Planificateur</h1>
          <p className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>Une vue calme de votre journée, privée et disponible hors ligne.</p>
        </header>

        <section
          className="rounded-2xl p-4 mb-5"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-3">
              <CalendarCheck2 size={22} style={{ color: 'var(--color-accent)' }} />
              <div>
                <p className="font-medium capitalize" style={{ color: 'var(--color-text)' }}>{displayDate}</p>
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{selectedDate}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => setSelectedDate(moveDate(selectedDate, -1))} className="size-8 rounded-lg flex items-center justify-center cursor-pointer" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }} aria-label="Jour précédent"><ChevronLeft size={16} /></button>
              <button type="button" onClick={() => setSelectedDate(localIsoDate())} className="px-3 h-8 rounded-lg text-xs cursor-pointer" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>Aujourd'hui</button>
              <input type="date" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} className="h-8 rounded-lg px-2 bg-transparent text-xs outline-none" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }} />
              <button type="button" onClick={() => setSelectedDate(moveDate(selectedDate, 1))} className="size-8 rounded-lg flex items-center justify-center cursor-pointer" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }} aria-label="Jour suivant"><ChevronRight size={16} /></button>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 mt-5">
            {[
              ['Total', planner?.summary.total ?? 0],
              ['À faire', planner?.summary.open ?? 0],
              ['Terminées', planner?.summary.completed ?? 0],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded-xl px-3 py-3" style={{ background: 'var(--color-bg-secondary)' }}>
                <p className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>{value}</p>
                <p className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{label}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="flex gap-2 mb-5">
          <input
            value={quickTitle}
            onChange={(event) => setQuickTitle(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') void createQuickTask(); }}
            placeholder={`Ajouter une tâche au ${selectedDate}…`}
            maxLength={200}
            className="flex-1 min-w-0 rounded-xl px-4 py-2.5 text-sm bg-transparent outline-none"
            style={{ color: 'var(--color-text)', background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          />
          <button type="button" disabled={!quickTitle.trim() || saving} onClick={() => void createQuickTask()} className="px-4 rounded-xl text-sm font-medium flex items-center gap-2 disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}><CirclePlus size={16} /> Ajouter</button>
        </section>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}><Loader2 size={17} className="animate-spin" /> Chargement du plan…</div>
        ) : !planner?.tasks.length ? (
          <div className="rounded-2xl py-16 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <p className="font-medium" style={{ color: 'var(--color-text)' }}>Cette journée est libre</p>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Ajoutez une tâche ici ou demandez à DIA de la planifier.</p>
          </div>
        ) : (
          <div className="grid gap-3">
            {planner.tasks.map((task) => (
              <TaskCard key={task.id} task={task} compact onToggleTask={toggleTask} onToggleSubtask={toggleSubtask} onAddSubtask={addSubtask} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
