import { useCallback, useEffect, useState } from 'react';
import { CalendarClock, CirclePlus, Loader2, Pause, Play, Quote, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import {
  createSuccesQuote,
  createSuccesTemplate,
  deleteSuccesQuote,
  deleteSuccesTemplate,
  listSuccesQuotes,
  listSuccesTemplates,
  updateSuccesTemplate,
} from '../features/succes/api';
import type {
  SuccesPriority,
  SuccesQuote,
  SuccesTemplate,
  SuccesTemplateFrequency,
  SuccesTemplateKind,
} from '../features/succes/types';
import { useAppStore } from '../lib/store';

const DAYS = ['D', 'L', 'M', 'M', 'J', 'V', 'S'];
const TODAY = new Date().toISOString().slice(0, 10);

function addMonths(iso: string, count: number) {
  const value = new Date(`${iso}T12:00:00`);
  value.setMonth(value.getMonth() + count);
  return value.toISOString().slice(0, 10);
}

export function SuccesTemplatesPage() {
  const [templates, setTemplates] = useState<SuccesTemplate[]>([]);
  const [quotes, setQuotes] = useState<SuccesQuote[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [emoji, setEmoji] = useState('');
  const [frequency, setFrequency] = useState<SuccesTemplateFrequency>('weekly');
  const [kind, setKind] = useState<SuccesTemplateKind>('task');
  const [priority, setPriority] = useState<SuccesPriority>('medium');
  const [weeklyDays, setWeeklyDays] = useState<number[]>([1]);
  const [monthSlots, setMonthSlots] = useState<Array<number | 'last'>>([1]);
  const [monthDow, setMonthDow] = useState(1);
  const [startDate, setStartDate] = useState(TODAY);
  const [endDate, setEndDate] = useState(addMonths(TODAY, 3));
  const [quoteText, setQuoteText] = useState('');
  const [quoteAuthor, setQuoteAuthor] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextTemplates, nextQuotes] = await Promise.all([
        listSuccesTemplates(),
        listSuccesQuotes(),
      ]);
      setTemplates(nextTemplates);
      setQuotes(nextQuotes);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `Récurrences : ${message}` });
      toast.error('Les récurrences ne peuvent pas être chargées.', { description: message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const run = async (action: () => Promise<unknown>, success: string) => {
    setSaving(true);
    try {
      await action();
      await load();
      toast.success(success, { description: 'Enregistré localement sur ce Mac.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `${success} — ${message}` });
      toast.error("L'action n'a pas été enregistrée.", { description: message });
    } finally {
      setSaving(false);
    }
  };

  const createTemplate = async () => {
    if (!title.trim()) return;
    await run(
      () => createSuccesTemplate({
        title: title.trim(), emoji, frequency, templateKind: kind, priority,
        weeklyDays: frequency === 'weekly' ? weeklyDays : [],
        monthWeekSlots: frequency === 'monthly' ? monthSlots : [],
        monthWeekDow: monthDow, startDate, endDate,
      }),
      `Récurrence créée : ${title.trim()}`,
    );
    setTitle('');
    setEmoji('');
    setShowCreate(false);
  };

  const removeTemplate = async (item: SuccesTemplate) => {
    if (!window.confirm(`Supprimer « ${item.title} » et toutes ses occurrences générées ?`)) return;
    setSaving(true);
    try {
      const removed = await deleteSuccesTemplate(item.id);
      await load();
      toast.success(`Récurrence supprimée (${removed} occurrence(s))`, {
        description: 'La suppression est enregistrée localement et synchronisable.',
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `Suppression de récurrence — ${message}` });
      toast.error("La récurrence n'a pas été supprimée.", { description: message });
    } finally {
      setSaving(false);
    }
  };

  const addQuote = async () => {
    if (!quoteText.trim()) return;
    await run(
      () => createSuccesQuote({ text: quoteText.trim(), author: quoteAuthor.trim(), category: 'motivation' }),
      'Citation ajoutée aux mots du jour',
    );
    setQuoteText('');
    setQuoteAuthor('');
  };

  const removeQuote = async (item: SuccesQuote) => {
    if (!window.confirm(`Supprimer la citation « ${item.text} » ?`)) return;
    await run(() => deleteSuccesQuote(item.id), 'Citation supprimée');
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
      <main className="max-w-5xl mx-auto w-full">
        <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between mb-7">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>Succès</span>
              {saving && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}
            </div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>Récurrences</h1>
            <p className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
              Créez une règle une fois. Succès génère ensuite les tâches ou habitudes sans doublon.
            </p>
          </div>
          <button type="button" onClick={() => setShowCreate((value) => !value)} className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>
            <CirclePlus size={16} /> Nouvelle récurrence
          </button>
        </header>

        {showCreate && (
          <section className="rounded-2xl p-4 mb-5 grid gap-4" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}>
            <div className="grid grid-cols-[70px_1fr] gap-3">
              <input value={emoji} onChange={(event) => setEmoji(event.target.value.slice(0, 4))} placeholder="✨" className="rounded-xl px-3 py-2 bg-transparent text-center outline-none" style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
              <input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Titre de la récurrence" maxLength={200} className="rounded-xl px-3 py-2 bg-transparent outline-none" style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
            </div>
            <div className="grid sm:grid-cols-3 gap-3">
              <select value={kind} onChange={(event) => setKind(event.target.value as SuccesTemplateKind)} className="rounded-xl px-3 py-2 bg-transparent" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}><option value="task">Tâche</option><option value="habit">Habitude</option></select>
              <select value={frequency} onChange={(event) => setFrequency(event.target.value as SuccesTemplateFrequency)} className="rounded-xl px-3 py-2 bg-transparent" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}><option value="daily">Tous les jours</option><option value="weekly">Chaque semaine</option><option value="monthly">Chaque mois</option></select>
              <select value={priority} onChange={(event) => setPriority(event.target.value as SuccesPriority)} className="rounded-xl px-3 py-2 bg-transparent" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}><option value="low">Basse</option><option value="medium">Moyenne</option><option value="high">Haute</option><option value="urgent">Urgente</option></select>
            </div>
            {frequency === 'weekly' && (
              <div className="flex gap-2" aria-label="Jours de la semaine">
                {DAYS.map((label, day) => <button key={`${label}-${day}`} type="button" aria-pressed={weeklyDays.includes(day)} onClick={() => setWeeklyDays((current) => current.includes(day) ? current.filter((item) => item !== day) : [...current, day].sort())} className="size-9 rounded-full text-xs cursor-pointer" style={{ color: weeklyDays.includes(day) ? '#fff' : 'var(--color-text-secondary)', background: weeklyDays.includes(day) ? 'var(--color-accent)' : 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>{label}</button>)}
              </div>
            )}
            {frequency === 'monthly' && (
              <div className="flex flex-wrap items-center gap-2">
                {[1, 2, 3, 4, 'last' as const].map((slot) => <button key={String(slot)} type="button" aria-pressed={monthSlots.includes(slot)} onClick={() => setMonthSlots((current) => current.includes(slot) ? current.filter((item) => item !== slot) : [...current, slot])} className="px-3 h-9 rounded-xl text-xs cursor-pointer" style={{ color: monthSlots.includes(slot) ? '#fff' : 'var(--color-text-secondary)', background: monthSlots.includes(slot) ? 'var(--color-accent)' : 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>{slot === 'last' ? 'Dernier' : `${slot}e`}</button>)}
                <select value={monthDow} onChange={(event) => setMonthDow(Number(event.target.value))} className="h-9 rounded-xl px-3 bg-transparent text-xs" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>{DAYS.map((label, day) => <option key={day} value={day}>{label}</option>)}</select>
              </div>
            )}
            <div className="grid sm:grid-cols-2 gap-3">
              <label className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Début<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} className="mt-1 w-full rounded-xl px-3 py-2 bg-transparent" style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }} /></label>
              <label className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Fin<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} className="mt-1 w-full rounded-xl px-3 py-2 bg-transparent" style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }} /></label>
            </div>
            <div className="flex justify-end gap-2"><button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2 rounded-xl text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>Annuler</button><button type="button" disabled={!title.trim() || !startDate || !endDate || saving} onClick={() => void createTemplate()} className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-40 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>Créer</button></div>
          </section>
        )}

        {loading ? <div className="py-16 flex justify-center"><Loader2 className="animate-spin" style={{ color: 'var(--color-accent)' }} /></div> : (
          <section className="grid gap-3 mb-8">
            {!templates.length && <div className="rounded-2xl py-14 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}><CalendarClock className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} /><p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucune récurrence</p><p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Créez votre première règle ou demandez-la à DIA.</p></div>}
            {templates.map((item) => (
              <article key={item.id} className="rounded-2xl p-4 flex items-center gap-4" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', opacity: item.active ? 1 : 0.62 }}>
                <div className="size-11 rounded-xl flex items-center justify-center text-xl" style={{ background: 'var(--color-bg-secondary)' }}>{item.emoji || (item.templateKind === 'habit' ? '🏃' : '✓')}</div>
                <div className="flex-1 min-w-0"><p className="font-medium truncate" style={{ color: 'var(--color-text)' }}>{item.title}</p><p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>{item.templateKind === 'habit' ? 'Habitude' : 'Tâche'} · {item.frequency} · {item.startDate} → {item.endDate}</p></div>
                <button type="button" onClick={() => void run(() => updateSuccesTemplate(item.id, { active: !item.active }), item.active ? 'Récurrence mise en pause' : 'Récurrence activée')} aria-label={item.active ? 'Mettre en pause' : 'Activer'} className="size-9 rounded-lg flex items-center justify-center cursor-pointer" style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-secondary)' }}>{item.active ? <Pause size={15} /> : <Play size={15} />}</button>
                <button type="button" onClick={() => void removeTemplate(item)} aria-label="Supprimer la récurrence" className="size-9 rounded-lg flex items-center justify-center cursor-pointer" style={{ color: 'var(--color-danger, #ef4444)', background: 'var(--color-bg-secondary)' }}><Trash2 size={15} /></button>
              </article>
            ))}
          </section>
        )}

        <section className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <div className="flex items-center gap-2 mb-1"><Quote size={17} style={{ color: 'var(--color-accent)' }} /><h2 className="font-medium" style={{ color: 'var(--color-text)' }}>Mots du jour</h2></div>
          <p className="text-xs mb-4" style={{ color: 'var(--color-text-tertiary)' }}>Une citation différente apparaît dans le planificateur selon la date.</p>
          <div className="grid sm:grid-cols-[1fr_190px_auto] gap-2 mb-4"><input value={quoteText} onChange={(event) => setQuoteText(event.target.value)} placeholder="Votre citation…" className="rounded-xl px-3 py-2 bg-transparent text-sm outline-none" style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }} /><input value={quoteAuthor} onChange={(event) => setQuoteAuthor(event.target.value)} placeholder="Auteur" className="rounded-xl px-3 py-2 bg-transparent text-sm outline-none" style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }} /><button type="button" disabled={!quoteText.trim() || saving} onClick={() => void addQuote()} className="px-4 py-2 rounded-xl text-sm disabled:opacity-40 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>Ajouter</button></div>
          <div className="grid gap-2">{quotes.map((item) => <div key={item.id} className="flex items-start gap-3 rounded-xl px-3 py-2" style={{ background: 'var(--color-bg-secondary)' }}><p className="flex-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>« {item.text} » {item.author && <span style={{ color: 'var(--color-text-tertiary)' }}>— {item.author}</span>}</p><button type="button" aria-label="Supprimer la citation" onClick={() => void removeQuote(item)} className="cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}><Trash2 size={14} /></button></div>)}</div>
        </section>
      </main>
    </div>
  );
}
