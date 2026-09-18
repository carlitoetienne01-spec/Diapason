import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  Bell,
  ChevronLeft,
  ChevronRight,
  CirclePlus,
  Flame,
  Loader2,
  Pencil,
  Repeat2,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  createSuccesHabit,
  deleteSuccesHabit,
  fetchSuccesHabitLogs,
  listSuccesHabits,
  setSuccesHabitDone,
  updateSuccesHabit,
} from '../features/succes/api';
import { EmojiPicker } from '../features/succes/EmojiPicker';
import { RecurrencesPanel } from '../features/succes/RecurrencesPanel';
import {
  annualLevel,
  buildYearWeeks,
  cellIsToggleable,
  daysInMonth,
  habitDayCellState,
  habitLogKey,
  isHabitDueOnDate,
  localIsoDate,
  type HabitDayCellState,
} from '../features/succes/habitCalendar';
import {
  ensureHabitReminderPermission,
  resyncHabitReminders,
} from '../features/succes/habitReminders';
import type { SuccesHabit, SuccesHabitFrequency } from '../features/succes/types';
import { useConfirm } from '../components/ConfirmDialog';
import { CarteVitree } from '../components/Glass/CarteVitree';
import { isTauri } from '../lib/api';
import { useAppStore } from '../lib/store';
import { useRefreshOnFocus } from '../features/succes/useRefreshOnFocus';
import { appliquerAuCache, clesSucces, ecrireCache, lireCache } from '../features/succes/cacheSucces';
import './SuccesHabitsGlass.css';

const weekdays = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];
const monthLabels = [
  'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
  'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre',
];

const emptyHabit = () => ({
  name: '',
  icon: '✨',
  color: '#6366f1',
  frequency: 'daily' as SuccesHabitFrequency,
  startDate: localIsoDate(),
  endDate: '',
  weeklyDays: [] as number[],
  monthWeekSlots: [1] as Array<number | 'last'>,
  monthWeekDay: 1,
  reminderTime: '',
});

/** WebKit throws on <input type="time"> when value is not HH:mm / empty. */
function safeTimeInputValue(raw: string | null | undefined): string {
  const value = (raw ?? '').trim();
  return /^\d{2}:\d{2}(:\d{2})?$/.test(value) ? value.slice(0, 5) : '';
}

/** Year heatmap cell. Derived from the text color so empty days stay readable
 * on both themes — in dark mode the surface and secondary background match. */
function annualCellStyle(level: number): CSSProperties {
  return {
    background:
      level === 0
        ? 'color-mix(in srgb, var(--color-text) 10%, transparent)'
        : `color-mix(in srgb, var(--color-accent) ${28 + level * 18}%, transparent)`,
    boxShadow: 'inset 0 0 0 1px color-mix(in srgb, var(--color-text) 7%, transparent)',
  };
}

export function SuccesHabitsPage() {
  const confirm = useConfirm();
  const today = localIsoDate();
  const now = new Date();
  // L'état initial vient du cache — la dernière réponse du serveur pour
  // aujourd'hui et l'année en cours. Chaque montage repartait de
  // « Chargement des habitudes… » (Carlito, 18 sept. 2026).
  const [habits, setHabits] = useState<SuccesHabit[]>(
    () => lireCache<SuccesHabit[]>(clesSucces.habitudes(today)) ?? [],
  );
  const [logs, setLogs] = useState<Record<string, boolean>>(
    () =>
      lireCache<Record<string, boolean>>(clesSucces.journalHabitudes(`${now.getFullYear()}-01-01`, `${now.getFullYear()}-12-31`)) ??
      {},
  );
  // Le spinner n'existe qu'au premier chargement sans cache ; `rafraichit`
  // tient le voyant discret de l'en-tête pendant les relectures.
  const [loading, setLoading] = useState(() => lireCache(clesSucces.habitudes(today)) === null);
  const [rafraichit, setRafraichit] = useState(false);
  /** Les clés sous lesquelles `habits` et `logs` ont été chargés — celles du miroir, plus bas. */
  const clesChargees = useRef<{ habitudes: string; journal: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState(emptyHabit());
  const [viewYear, setViewYear] = useState(now.getFullYear());
  const [viewMonth, setViewMonth] = useState(now.getMonth());
  const formRef = useRef<HTMLDivElement>(null);

  // Le formulaire naît sous les cartes résumé, en haut de page ; « Modifier »
  // se clique sur une carte souvent bien plus bas. Dans le mini-panneau
  // (620 px de haut), le formulaire s'ouvrait hors champ et le clic semblait
  // mort (16 sept. 2026). On l'amène en vue à chaque ouverture ou changement
  // de cible.
  useEffect(() => {
    if (showForm) formRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }, [showForm, editingId]);

  const spanFrom = `${viewYear}-01-01`;
  const spanTo = `${viewYear}-12-31`;

  const load = useCallback(async () => {
    setRafraichit(true);
    try {
      const [nextHabits, nextLogs] = await Promise.all([
        listSuccesHabits(today),
        fetchSuccesHabitLogs(spanFrom, spanTo),
      ]);
      // Une seule entrée persistée par ressource : une par jour (habitudes)
      // et une par année feuilletée (journal) s'accumulaient sans que rien
      // ne les relise ni ne les retire (revue du cache, 18 sept. 2026).
      ecrireCache(clesSucces.habitudes(today), nextHabits, { uniqueParRessource: true });
      ecrireCache(clesSucces.journalHabitudes(spanFrom, spanTo), nextLogs, { uniqueParRessource: true });
      clesChargees.current = {
        habitudes: clesSucces.habitudes(today),
        journal: clesSucces.journalHabitudes(spanFrom, spanTo),
      };
      setHabits(nextHabits);
      setLogs(nextLogs);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'error',
        category: 'succes',
        message: `Habitudes : ${message}`,
      });
      toast.error('Les habitudes ne peuvent pas être chargées.', { description: message });
    } finally {
      setLoading(false);
      setRafraichit(false);
    }
  }, [spanFrom, spanTo, today]);

  useEffect(() => {
    void load();
  }, [load]);

  // Le miroir : une case cochée (réconciliée avec la réponse du serveur, ou
  // rétablie en échec) se reflète dans le cache, pour qu'un retour sur la
  // page la montre sans attendre la relecture. Après un chargement réussi
  // seulement, et sous la clé de CE chargement : entre le changement
  // d'année et la réponse, `logs` porte encore l'année d'avant.
  useEffect(() => {
    if (clesChargees.current) ecrireCache(clesChargees.current.habitudes, habits, { uniqueParRessource: true });
  }, [habits]);
  useEffect(() => {
    if (clesChargees.current) ecrireCache(clesChargees.current.journal, logs, { uniqueParRessource: true });
  }, [logs]);

  // Une page ouverte gardait son état indéfiniment : ce qui change
  // ailleurs — téléphone, autre fenêtre, assistant — n'apparaissait
  // jamais. On relit au retour du focus.
  useRefreshOnFocus(() => void load());

  const closeFormNow = () => {
    setShowForm(false);
    setEditingId(null);
    setDraft(emptyHabit());
  };

  const closeForm = async () => {
    const blank = emptyHabit();
    const dirty = editingId
      ? true // editing always asks — safer than reconstructing the original snapshot
      : Boolean(
          draft.name.trim() ||
            draft.icon !== blank.icon ||
            draft.color !== blank.color ||
            draft.frequency !== blank.frequency ||
            draft.startDate ||
            draft.endDate ||
            draft.weeklyDays.length ||
            draft.reminderTime,
        );
    if (dirty) {
      const confirmed = await confirm({
        title: editingId ? 'Annuler les modifications ?' : 'Annuler la création ?',
        description: 'Les changements non enregistrés seront perdus.',
        confirmLabel: 'Annuler',
        keepLabel: 'Garder',
        tone: 'warning',
      });
      if (!confirmed) return;
    }
    closeFormNow();
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
      reminderTime: safeTimeInputValue(habit.reminderTime),
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
      toast.success(editingId ? 'Habitude mise à jour' : 'Habitude créée', {
        description: 'Enregistrée localement sur ce Mac.',
      });
      closeFormNow();
      await load();
      void resyncHabitReminders();
    } catch (error) {
      toast.error("L'habitude n'a pas été enregistrée.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const enableReminders = async () => {
    const granted = await ensureHabitReminderPermission();
    if (granted) {
      toast.success('Notifications autorisées', {
        description: 'Les rappels sonnent tant que Diapason est ouvert.',
      });
      void resyncHabitReminders();
    } else {
      toast.error('Notifications refusées', {
        description: 'Autorisez Diapason dans Réglages système → Notifications.',
      });
    }
  };

  /**
   * Ce que le serveur a rendu (la coche acceptée, l'habitude mise à jour) —
   * ou le rétablissement en échec — va aussi DROIT dans le cache, sous les
   * clés de ce chargement, comme `refleterLigne` dans Tâches : le miroir
   * (les effets sur `logs` et `habits`) ne bat que page montée. Reproduit
   * le 18 sept. 2026 (revue du cache) : POST en 2,5 s puis 503, clic sur un
   * autre module avant la réponse → le `setLogs` du catch était un no-op
   * React, et la case refusée par le serveur restait « terminée » dans le
   * cache, persistée, rejouée au relancement tant qu'aucune relecture ne
   * réussissait — un faux SUCCESS (§100).
   */
  const refleterCoche = (key: string, done: boolean) => {
    const cles = clesChargees.current;
    if (!cles) return;
    appliquerAuCache<Record<string, boolean>>(cles.journal, (journal) => {
      const copie = { ...journal };
      if (done) copie[key] = true;
      else delete copie[key];
      return copie;
    });
  };
  const refleterHabitude = (updated: SuccesHabit) => {
    const cles = clesChargees.current;
    if (!cles) return;
    appliquerAuCache<SuccesHabit[]>(cles.habitudes, (liste) =>
      liste.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)),
    );
  };

  const toggleDay = async (habit: SuccesHabit, iso: string) => {
    if (iso > today) {
      toast.info('Jour futur — non modifiable');
      return;
    }
    const key = habitLogKey(habit.id, iso);
    const nextDone = !logs[key];
    setSaving(true);
    setLogs((prev) => {
      const copy = { ...prev };
      if (nextDone) copy[key] = true;
      else delete copy[key];
      return copy;
    });
    try {
      const updated = await setSuccesHabitDone(habit.id, iso, nextDone);
      refleterCoche(key, nextDone);
      refleterHabitude(updated);
      setHabits((prev) => prev.map((item) => (item.id === habit.id ? { ...item, ...updated } : item)));
      if (iso === today) void resyncHabitReminders();
    } catch (error) {
      refleterCoche(key, !nextDone);
      setLogs((prev) => {
        const copy = { ...prev };
        if (nextDone) delete copy[key];
        else copy[key] = true;
        return copy;
      });
      toast.error("Le suivi n'a pas été enregistré.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (habit: SuccesHabit) => {
    const confirmed = await confirm({
      title: `Supprimer l’habitude « ${habit.name} » ?`,
      description: 'Son historique de suivi sera également retiré.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    setSaving(true);
    try {
      await deleteSuccesHabit(habit.id);
      toast.success('Habitude supprimée');
      await load();
      void resyncHabitReminders();
    } catch (error) {
      toast.error('La suppression a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const shiftMonth = (delta: number) => {
    const cursor = new Date(viewYear, viewMonth + delta, 1);
    setViewYear(cursor.getFullYear());
    setViewMonth(cursor.getMonth());
  };

  const dueToday = habits.filter((habit) => isHabitDueOnDate(habit, today));
  const doneToday = dueToday.filter((habit) => logs[habitLogKey(habit.id, today)]).length;
  const maxStreak = Math.max(0, ...habits.map((habit) => habit.streak));
  const totalCompletions = Object.keys(logs).filter((key) =>
    habits.some((habit) => key.startsWith(`${habit.id}_`)),
  ).length;

  const yearWeeks = useMemo(() => buildYearWeeks(viewYear), [viewYear]);
  const dayCount = daysInMonth(viewYear, viewMonth);

  return (
    <div className="habitudes-verre flex-1 overflow-y-auto px-3 py-4 sm:px-5 sm:py-8 md:px-8 md:py-10" data-verre-defilement>
      <main className="max-w-6xl mx-auto w-full">
        {/* En miniature (sous sm), l'en-tête tient sur UNE rangée : la
            description se tait et les deux boutons deviennent des icônes —
            empilés sous le titre, ils coûtaient ~170 px du panneau avant le
            premier chiffre (16 sept. 2026, audit du mini-panneau). */}
        <header className="flex flex-row items-end justify-between gap-3 mb-4 sm:mb-7">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1 sm:mb-2">
              <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>
                Succès
              </span>
              {(loading || rafraichit || saving) && (
                <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
              )}
            </div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
              Habitudes
            </h1>
            <p className="hidden sm:block text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
              Grilles mensuelle et annuelle — cochez un jour pour valider, directement sur ce Mac.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {isTauri() && (
              <button
                type="button"
                onClick={() => void enableReminders()}
                className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border)',
                }}
                aria-label="Rappels OS"
              >
                <Bell size={16} />
                <span className="hidden sm:inline">Rappels OS</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                if (showForm) void closeForm();
                else setShowForm(true);
              }}
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer"
              style={{ background: 'var(--color-accent)', color: '#fff' }}
              aria-label="Nouvelle habitude"
              aria-expanded={showForm}
            >
              <CirclePlus size={16} />
              <span className="hidden sm:inline">Nouvelle habitude</span>
            </button>
          </div>
        </header>

        {/* Trois colonnes dès la base : trois cartes empilées faisaient
            ~210 px pour trois chiffres (16 sept. 2026). */}
        <section className="grid gap-2 sm:gap-3 grid-cols-3 mb-4 sm:mb-5">
          <SummaryCard icon="🔥" value={`${maxStreak}`} label="Jours consécutifs" />
          <SummaryCard
            icon="✅"
            value={dueToday.length ? `${doneToday}/${dueToday.length}` : '—'}
            label="Aujourd’hui (prévu)"
          />
          <SummaryCard icon="📊" value={`${totalCompletions}`} label="Total complétions" />
        </section>

        {showForm && (
          <CarteVitree as="section" className="mb-5" contenuClassName="grid gap-3 p-4">
            <div ref={formRef} className="grid grid-cols-[56px_1fr_54px] gap-3 scroll-mt-6">
              <EmojiPicker
                value={draft.icon}
                onChange={(icon) => setDraft({ ...draft, icon })}
                aria-label="Icône de l’habitude"
              />
              <input
                autoFocus
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                maxLength={200}
                placeholder="Nom de l’habitude"
                className="rounded-xl px-3 py-2.5 bg-transparent outline-none"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
              <input
                type="color"
                value={draft.color}
                onChange={(event) => setDraft({ ...draft, color: event.target.value })}
                aria-label="Couleur"
                className="size-[46px] rounded-xl bg-transparent cursor-pointer"
              />
            </div>
            <div className="grid sm:grid-cols-3 gap-3">
              <select
                value={draft.frequency}
                onChange={(event) =>
                  setDraft({ ...draft, frequency: event.target.value as SuccesHabitFrequency })
                }
                className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
              >
                <option value="daily">Quotidienne</option>
                <option value="weekly">Hebdomadaire</option>
                <option value="monthly">Mensuelle</option>
              </select>
              <input
                type="date"
                value={draft.startDate}
                onChange={(event) => setDraft({ ...draft, startDate: event.target.value })}
                aria-label="Date de début"
                className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
              />
              <input
                type="time"
                value={safeTimeInputValue(draft.reminderTime)}
                onChange={(event) => setDraft({ ...draft, reminderTime: event.target.value })}
                aria-label="Heure de rappel"
                className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
              />
            </div>
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {draft.reminderTime
                ? 'Notification macOS à cette heure (tant que Diapason est ouvert).'
                : 'Sans heure : rappels horaires de 10 h à 23 h pour les jours dus non cochés.'}
            </p>
            {draft.frequency === 'weekly' && (
              <div className="flex flex-wrap gap-2">
                {weekdays.map((label, index) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() =>
                      setDraft({ ...draft, weeklyDays: toggleListValue(draft.weeklyDays, index) })
                    }
                    className="size-9 rounded-lg text-xs cursor-pointer"
                    style={{
                      background: draft.weeklyDays.includes(index)
                        ? 'var(--color-accent)'
                        : 'var(--color-bg-secondary)',
                      color: draft.weeklyDays.includes(index) ? '#fff' : 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
            {draft.frequency === 'monthly' && (
              <div className="grid gap-3">
                <div className="flex flex-wrap gap-2">
                  {([1, 2, 3, 4, 'last'] as Array<number | 'last'>).map((slot) => (
                    <button
                      key={slot}
                      type="button"
                      onClick={() =>
                        setDraft({
                          ...draft,
                          monthWeekSlots: toggleListValue(draft.monthWeekSlots, slot),
                        })
                      }
                      className="px-3 h-9 rounded-lg text-xs cursor-pointer"
                      style={{
                        background: draft.monthWeekSlots.includes(slot)
                          ? 'var(--color-accent)'
                          : 'var(--color-bg-secondary)',
                        color: draft.monthWeekSlots.includes(slot)
                          ? '#fff'
                          : 'var(--color-text-secondary)',
                        border: '1px solid var(--color-border)',
                      }}
                    >
                      {slot === 'last' ? 'Dernière' : `${slot}e`}
                    </button>
                  ))}
                </div>
                <select
                  value={draft.monthWeekDay}
                  onChange={(event) =>
                    setDraft({ ...draft, monthWeekDay: Number(event.target.value) })
                  }
                  className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                >
                  {weekdays.map((label, index) => (
                    <option key={label} value={index}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => void closeForm()}
                className="px-3 py-2 text-sm cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                Annuler
              </button>
              <button
                type="button"
                disabled={!draft.name.trim() || saving}
                onClick={() => void save()}
                className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                {editingId ? 'Mettre à jour' : 'Créer l’habitude'}
              </button>
            </div>
            <RecurrencesPanel kind="habit" embedded />
          </CarteVitree>
        )}

        {loading ? (
          <div className="flex justify-center gap-2 py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
            <Loader2 size={17} className="animate-spin" /> Chargement des habitudes…
          </div>
        ) : (
          <>
            {/* Sous sm, la vue annuelle se tait : 53 colonnes dans 340 px
                font des cases de ~6 px — elle ne faisait qu'exister, et
                repoussait la grille mensuelle (le cœur du module) sous le
                pli (16 sept. 2026). */}
            <CarteVitree as="section" className="hidden sm:block mb-5" contenuClassName="p-4">
              <div className="flex items-center justify-between gap-3 mb-4">
                <h2 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                  Vue annuelle
                </h2>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setViewYear((year) => year - 1)}
                    aria-label="Année précédente"
                    className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span className="text-sm tabular-nums min-w-[3.5rem] text-center" style={{ color: 'var(--color-text)' }}>
                    {viewYear}
                  </span>
                  <button
                    type="button"
                    onClick={() => setViewYear((year) => year + 1)}
                    aria-label="Année suivante"
                    className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
              <div className="flex gap-px w-full" style={{ minHeight: 96 }}>
                {yearWeeks.map((week, weekIndex) => (
                  <div key={weekIndex} className="flex flex-col flex-1 gap-px min-w-0">
                    {week.map((day) => {
                      const iso = localIsoDate(day);
                      const count = habits.filter((habit) => logs[habitLogKey(habit.id, iso)]).length;
                      const level = annualLevel(count, habits.length);
                      const future = iso > today;
                      return (
                        <div
                          key={iso}
                          title={`${iso} : ${count} habitude${count === 1 ? '' : 's'}`}
                          className="flex-1 min-h-[10px] rounded-[2px]"
                          style={{
                            ...annualCellStyle(level),
                            opacity: future ? 0.45 : 1,
                          }}
                        />
                      );
                    })}
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-end gap-1.5 mt-3 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                Moins
                {[0, 1, 2, 3, 4].map((level) => (
                  <span
                    key={level}
                    className="size-2.5 rounded-[2px]"
                    style={annualCellStyle(level)}
                  />
                ))}
                Plus
              </div>
            </CarteVitree>

            <section className="flex items-center justify-between gap-3 mb-4">
              <h2 className="text-sm font-medium capitalize min-w-0 truncate" style={{ color: 'var(--color-text)' }}>
                Grille de {monthLabels[viewMonth]} {viewYear}
              </h2>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => shiftMonth(-1)}
                  aria-label="Mois précédent"
                  className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                >
                  <ChevronLeft size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const current = new Date();
                    setViewYear(current.getFullYear());
                    setViewMonth(current.getMonth());
                  }}
                  className="px-3 h-8 rounded-lg text-xs cursor-pointer"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                >
                  Ce mois
                </button>
                <button
                  type="button"
                  onClick={() => shiftMonth(1)}
                  aria-label="Mois suivant"
                  className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </section>

            {!habits.length ? (
              <CarteVitree contenuClassName="py-16 text-center">
                <Repeat2 size={28} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} />
                <p className="font-medium" style={{ color: 'var(--color-text)' }}>
                  Aucune habitude
                </p>
                <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                  Commencez petit et laissez DIA vous accompagner.
                </p>
              </CarteVitree>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {habits.map((habit) => (
                  <HabitMonthCard
                    key={habit.id}
                    habit={habit}
                    year={viewYear}
                    month={viewMonth}
                    dayCount={dayCount}
                    logs={logs}
                    today={today}
                    onToggle={(iso) => void toggleDay(habit, iso)}
                    onEdit={() => edit(habit)}
                    onRemove={() => void remove(habit)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function SummaryCard({ icon, value, label }: { icon: string; value: string; label: string }) {
  return (
    <CarteVitree contenuClassName="px-3 py-2 sm:px-4 sm:py-3 flex items-center gap-3">
      {/* Sous sm, la colonne fait ~100 px : l'emoji (20 px + espace) prenait
          le tiers de la carte et poussait le libellé sur trois lignes
          (16 sept. 2026). Il revient dès sm. */}
      <span className="hidden sm:inline text-xl" aria-hidden>
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-base sm:text-lg font-semibold tabular-nums truncate" style={{ color: 'var(--color-text)' }}>
          {value}
        </p>
        <p className="text-[11px] sm:text-xs leading-tight" style={{ color: 'var(--color-text-tertiary)' }}>
          {label}
        </p>
      </div>
    </CarteVitree>
  );
}

function HabitMonthCard({
  habit,
  year,
  month,
  dayCount,
  logs,
  today,
  onToggle,
  onEdit,
  onRemove,
}: {
  habit: SuccesHabit;
  year: number;
  month: number;
  dayCount: number;
  logs: Record<string, boolean>;
  today: string;
  onToggle: (iso: string) => void;
  onEdit: () => void;
  onRemove: () => void;
}) {
  return (
    <CarteVitree as="article" contenuClassName="p-4">
      <div className="flex items-center gap-2 mb-3">
        <span
          className="size-9 rounded-xl flex items-center justify-center text-base shrink-0"
          style={{ background: `${habit.color}22`, border: `1px solid ${habit.color}55` }}
        >
          {habit.icon || '✨'}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
            {habit.name}
          </h3>
          <p className="text-[11px] flex items-center gap-1.5 mt-0.5 flex-wrap" style={{ color: 'var(--color-text-tertiary)' }}>
            <span className="inline-flex items-center gap-1">
              <Flame size={11} /> {habit.streak} jour{habit.streak === 1 ? '' : 's'}
            </span>
            <span aria-hidden>·</span>
            <span className="inline-flex items-center gap-1">
              <Bell size={11} />
              {(habit.reminderTime ?? '').trim()
                ? habit.reminderTime
                : '10–23 h'}
            </span>
          </p>
        </div>
        <button
          type="button"
          onClick={onEdit}
          aria-label="Modifier"
          className="p-1.5 cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          <Pencil size={14} />
        </button>
        <button
          type="button"
          onClick={onRemove}
          aria-label="Supprimer"
          className="p-1.5 cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          <Trash2 size={14} />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-1">
        {Array.from({ length: dayCount }, (_, index) => {
          const day = index + 1;
          const iso = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
          const state = habitDayCellState(habit, iso, logs, today);
          const toggleable = cellIsToggleable(state);
          return (
            <button
              key={iso}
              type="button"
              disabled={!toggleable}
              onClick={() => onToggle(iso)}
              title={cellTitle(state, iso)}
              className="h-6 rounded-md text-[9px] flex items-center justify-center disabled:cursor-default cursor-pointer"
              style={cellStyle(state, habit.color)}
            >
              {day}
            </button>
          );
        })}
      </div>
    </CarteVitree>
  );
}

function cellTitle(state: HabitDayCellState, iso: string) {
  switch (state) {
    case 'before-start':
      return 'Avant la période de suivi';
    case 'after-end':
      return 'Après la fin de la période de suivi';
    case 'future':
    case 'future-off':
      return 'Jour futur';
    case 'today-pending':
      return "Aujourd'hui — en attente";
    case 'today-done':
    case 'past-done':
      return `${iso} — terminé (cliquer pour décocher)`;
    case 'today-off':
      return "Aujourd'hui — hors planification (cliquer pour cocher)";
    case 'missed':
      return 'Jour manqué — cliquer pour cocher';
    case 'off-past':
      return 'Jour sans objectif — cliquer pour cocher';
    default:
      return iso;
  }
}

function cellStyle(state: HabitDayCellState, color: string): CSSProperties {
  switch (state) {
    case 'today-done':
    case 'past-done':
      return {
        background: color,
        border: `1px solid ${color}`,
        color: '#fff',
        boxShadow: state === 'today-done' ? `0 0 0 1px ${color}` : undefined,
      };
    case 'today-pending':
      return {
        background: 'color-mix(in srgb, #f59e0b 18%, transparent)',
        border: '1px solid color-mix(in srgb, #f59e0b 55%, transparent)',
        color: 'var(--color-text-secondary)',
      };
    case 'missed':
      return {
        background: 'color-mix(in srgb, #ef4444 14%, transparent)',
        border: '1px solid color-mix(in srgb, #ef4444 40%, transparent)',
        color: 'var(--color-text-secondary)',
      };
    case 'before-start':
    case 'after-end':
    case 'future':
    case 'future-off':
      return {
        background: 'transparent',
        border: '1px solid transparent',
        color: 'var(--color-text-tertiary)',
        opacity: 0.35,
      };
    case 'today-off':
    case 'off-past':
      return {
        background: 'var(--color-bg-secondary)',
        border: '1px dashed var(--color-border)',
        color: 'var(--color-text-tertiary)',
      };
    default:
      return {
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-text-tertiary)',
      };
  }
}
