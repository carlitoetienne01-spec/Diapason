import { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, CirclePlus, Flame, Loader2, Pencil, Repeat2, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import {
  createSuccesHabit,
  deleteSuccesHabit,
  listSuccesHabits,
  setSuccesHabitDone,
  updateSuccesHabit,
} from '../features/succes/api';
import type { SuccesHabit, SuccesHabitFrequency } from '../features/succes/types';
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

const weekdays = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];
const emptyHabit = () => ({
  name: '', icon: '✨', color: '#6366f1', frequency: 'daily' as SuccesHabitFrequency,
  startDate: localIsoDate(), endDate: '', weeklyDays: [] as number[],
  monthWeekSlots: [1] as Array<number | 'last'>, monthWeekDay: 1, reminderTime: '',
});

export function SuccesHabitsPage() {
  const [selectedDate, setSelectedDate] = useState(localIsoDate());
  const [habits, setHabits] = useState<SuccesHabit[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState(emptyHabit());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setHabits(await listSuccesHabits(selectedDate));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `Habitudes : ${message}` });
      toast.error('Les habitudes ne peuvent pas être chargées.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [selectedDate]);

  useEffect(() => { void load(); }, [load]);

  const closeForm = () => {
    setShowForm(false);
    setEditingId(null);
    setDraft(emptyHabit());
  };

  const edit = (habit: SuccesHabit) => {
    setDraft({
      name: habit.name,
      icon: habit.icon || '✨',
      color: habit.color,
      frequency: habit.frequency,
      startDate: habit.startDate,
      endDate: habit.endDate,
      weeklyDays: habit.weeklyDays,
      monthWeekSlots: habit.monthWeekSlots.length ? habit.monthWeekSlots : [1],
      monthWeekDay: habit.monthWeekDay,
      reminderTime: habit.reminderTime,
    });
    setEditingId(habit.id);
    setShowForm(true);
  };

  const toggleListValue = <T,>(values: T[], value: T) =>
    values.includes(value) ? values.filter((item) => item !== value) : [...values, value];

  const save = async () => {
    if (!draft.name.trim()) return;
    if (draft.frequency === 'weekly' && !draft.weeklyDays.length) {
      toast.warning('Choisissez au moins un jour de la semaine.');
      return;
    }
    if (draft.frequency === 'monthly' && !draft.monthWeekSlots.length) {
      toast.warning('Choisissez au moins une occurrence mensuelle.');
      return;
    }
    setSaving(true);
    try {
      if (editingId) await updateSuccesHabit(editingId, draft);
      else await createSuccesHabit(draft);
      toast.success(editingId ? 'Habitude mise à jour' : 'Habitude créée', { description: 'Enregistrée localement sur ce Mac.' });
      closeForm();
      await load();
    } catch (error) {
      toast.error("L'habitude n'a pas été enregistrée.", { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (habit: SuccesHabit) => {
    setSaving(true);
    try {
      await setSuccesHabitDone(habit.id, selectedDate, !habit.done);
      await load();
    } catch (error) {
      toast.error("Le suivi n'a pas été enregistré.", { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (habit: SuccesHabit) => {
    if (!window.confirm(`Supprimer l’habitude « ${habit.name} » et son historique de suivi ?`)) return;
    setSaving(true);
    try {
      await deleteSuccesHabit(habit.id);
      toast.success('Habitude supprimée');
      await load();
    } catch (error) {
      toast.error('La suppression a échoué.', { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setSaving(false);
    }
  };

  const displayDate = new Intl.DateTimeFormat('fr-CA', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
  }).format(new Date(`${selectedDate}T12:00:00Z`));
  const due = habits.filter((habit) => habit.due);
  const completed = due.filter((habit) => habit.done).length;

  return (
    <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
      <main className="max-w-5xl mx-auto w-full">
        <header className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between mb-7">
          <div>
            <div className="flex items-center gap-2 mb-2"><span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>Succès</span>{saving && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}</div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>Habitudes</h1>
            <p className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>Des gestes réguliers, suivis sans quitter ce Mac.</p>
          </div>
          <button type="button" onClick={() => { if (showForm) closeForm(); else setShowForm(true); }} className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}><CirclePlus size={16} /> Nouvelle habitude</button>
        </header>

        <section className="rounded-2xl p-4 mb-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
            <div><p className="font-medium capitalize" style={{ color: 'var(--color-text)' }}>{displayDate}</p><p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>{completed}/{due.length} prévue(s) terminée(s)</p></div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => setSelectedDate(moveDate(selectedDate, -1))} aria-label="Jour précédent" className="size-8 rounded-lg flex items-center justify-center cursor-pointer" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}><ChevronLeft size={16} /></button>
              <button type="button" onClick={() => setSelectedDate(localIsoDate())} className="px-3 h-8 rounded-lg text-xs cursor-pointer" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>Aujourd'hui</button>
              <input type="date" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} className="h-8 rounded-lg px-2 bg-transparent text-xs outline-none" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} />
              <button type="button" onClick={() => setSelectedDate(moveDate(selectedDate, 1))} aria-label="Jour suivant" className="size-8 rounded-lg flex items-center justify-center cursor-pointer" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}><ChevronRight size={16} /></button>
            </div>
          </div>
          <div className="h-1.5 rounded-full overflow-hidden mt-4" style={{ background: 'var(--color-bg-secondary)' }}><div className="h-full rounded-full" style={{ width: `${due.length ? (completed / due.length) * 100 : 0}%`, background: 'var(--color-accent)' }} /></div>
        </section>

        {showForm && (
          <section className="grid gap-3 rounded-2xl p-4 mb-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}>
            <div className="grid grid-cols-[56px_1fr_54px] gap-3">
              <input value={draft.icon} onChange={(event) => setDraft({ ...draft, icon: event.target.value })} maxLength={16} aria-label="Icône" className="rounded-xl px-3 text-center bg-transparent outline-none" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
              <input autoFocus value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} maxLength={200} placeholder="Nom de l’habitude" className="rounded-xl px-3 py-2.5 bg-transparent outline-none" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
              <input type="color" value={draft.color} onChange={(event) => setDraft({ ...draft, color: event.target.value })} aria-label="Couleur" className="size-[46px] rounded-xl bg-transparent cursor-pointer" />
            </div>
            <div className="grid sm:grid-cols-3 gap-3">
              <select value={draft.frequency} onChange={(event) => setDraft({ ...draft, frequency: event.target.value as SuccesHabitFrequency })} className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}><option value="daily">Quotidienne</option><option value="weekly">Hebdomadaire</option><option value="monthly">Mensuelle</option></select>
              <input type="date" value={draft.startDate} onChange={(event) => setDraft({ ...draft, startDate: event.target.value })} aria-label="Date de début" className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} />
              <input type="time" value={draft.reminderTime} onChange={(event) => setDraft({ ...draft, reminderTime: event.target.value })} aria-label="Heure de rappel" className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} />
            </div>
            {draft.frequency === 'weekly' && <div className="flex flex-wrap gap-2">{weekdays.map((label, index) => <button key={label} type="button" onClick={() => setDraft({ ...draft, weeklyDays: toggleListValue(draft.weeklyDays, index) })} className="size-9 rounded-lg text-xs cursor-pointer" style={{ background: draft.weeklyDays.includes(index) ? 'var(--color-accent)' : 'var(--color-bg-secondary)', color: draft.weeklyDays.includes(index) ? '#fff' : 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>{label}</button>)}</div>}
            {draft.frequency === 'monthly' && <div className="grid gap-3"><div className="flex flex-wrap gap-2">{([1, 2, 3, 4, 'last'] as Array<number | 'last'>).map((slot) => <button key={slot} type="button" onClick={() => setDraft({ ...draft, monthWeekSlots: toggleListValue(draft.monthWeekSlots, slot) })} className="px-3 h-9 rounded-lg text-xs cursor-pointer" style={{ background: draft.monthWeekSlots.includes(slot) ? 'var(--color-accent)' : 'var(--color-bg-secondary)', color: draft.monthWeekSlots.includes(slot) ? '#fff' : 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>{slot === 'last' ? 'Dernière' : `${slot}e`}</button>)}</div><select value={draft.monthWeekDay} onChange={(event) => setDraft({ ...draft, monthWeekDay: Number(event.target.value) })} className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>{weekdays.map((label, index) => <option key={label} value={index}>{label}</option>)}</select></div>}
            <div className="flex justify-end gap-2"><button type="button" onClick={closeForm} className="px-3 py-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>Annuler</button><button type="button" disabled={!draft.name.trim() || saving} onClick={() => void save()} className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>{editingId ? 'Mettre à jour' : 'Créer l’habitude'}</button></div>
          </section>
        )}

        {loading ? <div className="flex justify-center gap-2 py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}><Loader2 size={17} className="animate-spin" /> Chargement des habitudes…</div> : habits.length === 0 ? <div className="rounded-2xl py-16 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}><Repeat2 size={28} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} /><p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucune habitude</p><p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Commencez petit et laissez DIA vous accompagner.</p></div> : (
          <div className="grid gap-3">{habits.map((habit) => <article key={habit.id} className="flex items-center gap-3 rounded-2xl p-4" style={{ background: 'var(--color-surface)', border: `1px solid ${habit.done ? `${habit.color}77` : 'var(--color-border)'}`, opacity: habit.due ? 1 : 0.58 }}><button type="button" disabled={!habit.due} onClick={() => void toggle(habit)} aria-label={habit.done ? 'Marquer à faire' : 'Marquer terminée'} className="size-11 rounded-xl text-xl flex items-center justify-center disabled:cursor-not-allowed cursor-pointer" style={{ background: habit.done ? habit.color : `${habit.color}22`, border: `1px solid ${habit.color}66` }}>{habit.done ? '✓' : habit.icon || '✨'}</button><div className="min-w-0 flex-1"><h2 className="font-medium truncate" style={{ color: 'var(--color-text)', textDecoration: habit.done ? 'line-through' : 'none' }}>{habit.name}</h2><div className="flex flex-wrap gap-3 mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}><span>{habit.frequency === 'daily' ? 'Chaque jour' : habit.frequency === 'weekly' ? 'Chaque semaine' : 'Chaque mois'}</span>{habit.reminderTime && <span>{habit.reminderTime}</span>}<span className="flex items-center gap-1"><Flame size={12} /> {habit.streak} série</span>{!habit.due && <span>Non prévue ce jour</span>}</div></div><button type="button" onClick={() => edit(habit)} aria-label="Modifier" className="p-2 cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}><Pencil size={14} /></button><button type="button" onClick={() => void remove(habit)} aria-label="Supprimer" className="p-2 cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}><Trash2 size={14} /></button></article>)}</div>
        )}
      </main>
    </div>
  );
}
