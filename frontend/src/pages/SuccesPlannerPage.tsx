import { CadreVitre } from '../components/Glass/CadreVitre';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarCheck2,
  ChevronLeft,
  ChevronRight,
  CirclePlus,
  Loader2,
  Plus,
  Quote,
  X,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  DateAmbigueError,
  DateInconnueError,
  addSuccesSubtask,
  createSuccesQuote,
  createSuccesTask,
  fetchPlannerPastilles,
  fetchSuccesPlanner,
  listSuccesQuotes,
  listSuccesTasks,
  rescheduleSuccesTask,
  setSuccesSubtaskDone,
  setSuccesTaskDone,
} from '../features/succes/api';
import {
  analyserIso,
  dateIsoLocale,
  filtrer,
  grilleDuMois,
  libelleDuJour,
  pastillesLocales,
  resumeDuJour,
  type FiltrePlanner,
  type Pastille,
} from '../features/succes/planificateur';
import { phraseReportee } from '../features/succes/report';
import { TaskCard } from '../features/succes/TaskCard';
import type { SuccesQuote, SuccesSubtask, SuccesTask } from '../features/succes/types';
import { useConfirm } from '../components/ConfirmDialog';
import { useAppStore } from '../lib/store';
import { useRefreshOnFocus } from '../features/succes/useRefreshOnFocus';
import { clesSucces, ecrireCache, lireCache } from '../features/succes/cacheSucces';

const DAY_LABELS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
const MIME = 'application/x-diapason-task';
/** How long a random word-of-the-day stays on the card before another is drawn. */
const QUOTE_ROTATE_MS = 7 * 60 * 1000;

function pickRandomQuote(quotes: SuccesQuote[], avoidId?: string): SuccesQuote | null {
  if (!quotes.length) return null;
  if (quotes.length === 1) return quotes[0];
  const pool = avoidId ? quotes.filter((q) => q.id !== avoidId) : quotes;
  const source = pool.length ? pool : quotes;
  return source[Math.floor(Math.random() * source.length)] ?? null;
}

function AnalogClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const hours = now.getHours() % 12;
  const minutes = now.getMinutes();
  const seconds = now.getSeconds();
  const hourAngle = hours * 30 + minutes * 0.5;
  const minuteAngle = minutes * 6 + seconds * 0.1;
  const secondAngle = seconds * 6;

  // Sous sm, le cadran (176 px) est caché : l'heure vit déjà dans la barre
  // système du Mac, et il coûtait un tiers d'un panneau de 620 px. Reste
  // une ligne — l'heure et la date côte à côte (16 sept. 2026, audit du
  // mini-panneau).
  return (
    <div className="flex flex-col items-center gap-3">
      <svg viewBox="0 0 200 200" className="hidden sm:block w-44 h-44" aria-hidden="true">
        <defs>
          <linearGradient id="clockFace" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(255,255,255,0.14)" />
            <stop offset="100%" stopColor="rgba(255,255,255,0.04)" />
          </linearGradient>
        </defs>
        <rect x="18" y="18" width="164" height="164" rx="38" fill="url(#clockFace)" stroke="var(--color-border)" strokeWidth="1.5" />
        {Array.from({ length: 12 }, (_, index) => {
          const angle = (index * 30 * Math.PI) / 180;
          const x1 = 100 + Math.sin(angle) * 62;
          const y1 = 100 - Math.cos(angle) * 62;
          const x2 = 100 + Math.sin(angle) * 72;
          const y2 = 100 - Math.cos(angle) * 72;
          return <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--color-text-tertiary)" strokeWidth="2" strokeLinecap="round" />;
        })}
        <line x1="100" y1="100" x2="100" y2="58" stroke="var(--color-text)" strokeWidth="3.5" strokeLinecap="round" transform={`rotate(${hourAngle} 100 100)`} />
        <line x1="100" y1="100" x2="100" y2="42" stroke="var(--color-text)" strokeWidth="2" strokeLinecap="round" transform={`rotate(${minuteAngle} 100 100)`} />
        <line x1="100" y1="118" x2="100" y2="36" stroke="var(--color-accent)" strokeWidth="1.2" strokeLinecap="round" opacity="0.9" transform={`rotate(${secondAngle} 100 100)`} />
        <circle cx="100" cy="100" r="5" fill="var(--color-text)" />
        <circle cx="100" cy="100" r="2.4" fill="var(--color-accent)" />
      </svg>
      <div className="flex items-baseline gap-3 min-w-0 max-w-full sm:block sm:text-center">
        <p className="text-lg sm:text-2xl font-semibold tabular-nums shrink-0" style={{ color: 'var(--color-text)' }}>
          {now.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })}
        </p>
        <p className="text-xs sm:mt-1 capitalize truncate" style={{ color: 'var(--color-text-tertiary)' }}>
          {now.toLocaleDateString('fr-CA', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
        </p>
      </div>
    </div>
  );
}

export function SuccesPlannerPage() {
  const confirm = useConfirm();
  const today = dateIsoLocale();
  const [selectedDate, setSelectedDate] = useState(today);
  const [calendarMonth, setCalendarMonth] = useState(today);
  const [filter, setFilter] = useState<FiltrePlanner>('day');
  // L'état initial vient du cache — la même liste que Tâches et Projets
  // (`/v1/succes/tasks?include_done=true`), rendue par le serveur à la
  // dernière visite de l'une des trois. Chaque montage repartait d'un écran
  // vide et de « Chargement du plan… » (Carlito, 18 sept. 2026).
  const [tasks, setTasks] = useState<SuccesTask[]>(() => lireCache<SuccesTask[]>(clesSucces.taches()) ?? []);
  /** Les points du calendrier, servis par le serveur ; null tant qu'ils n'ont pas répondu. */
  const [pastilles, setPastilles] = useState<Record<string, Pastille> | null>(null);
  const [loading, setLoading] = useState(() => lireCache(clesSucces.taches()) === null);
  const [saving, setSaving] = useState(false);
  const [quickTitle, setQuickTitle] = useState('');
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [quoteModalOpen, setQuoteModalOpen] = useState(false);
  const [quoteDraft, setQuoteDraft] = useState({ text: '', author: '' });
  const [quotes, setQuotes] = useState<SuccesQuote[]>(() => lireCache<SuccesQuote[]>(clesSucces.citations()) ?? []);
  const [displayQuote, setDisplayQuote] = useState<SuccesQuote | null>(() =>
    quotes.length ? pickRandomQuote(quotes) : null,
  );

  const loadQuotes = useCallback(async () => {
    try {
      const next = await listSuccesQuotes();
      ecrireCache(clesSucces.citations(), next);
      setQuotes(next);
      setDisplayQuote((current) => {
        if (!next.length) return null;
        if (current && next.some((q) => q.id === current.id)) return current;
        return pickRandomQuote(next);
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error('Les mots du jour ne peuvent pas être chargés.', { description: message });
    }
  }, []);

  // `loading` n'est vrai qu'au PREMIER chargement sans cache : ensuite la
  // liste reste montée pendant qu'on relit. Démonter les cartes à chaque
  // load() — retour de focus, coche d'une autre tâche — emportait la boîte
  // Reporter et ses deux dates proposées (contre-revue du 17 sept. 2026, §34).
  const load = useCallback(async () => {
    try {
      // D'ABORD le planificateur, ENSUITE la liste : le premier matérialise
      // les récurrences du jour ; chargés en parallèle, la liste pouvait
      // arriver avant elles et contredire les points du calendrier.
      await fetchSuccesPlanner(selectedDate).catch(() => null);
      const nextTasks = await listSuccesTasks({ includeDone: true });
      ecrireCache(clesSucces.taches(), nextTasks);
      setTasks(nextTasks);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'error',
        category: 'succes',
        message: `Planificateur : ${message}`,
      });
      toast.error('Le planificateur ne peut pas être chargé.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [selectedDate]);

  useEffect(() => {
    void load();
  }, [load]);

  // Une page ouverte gardait son état indéfiniment : ce qui change
  // ailleurs — téléphone, autre fenêtre, assistant — n'apparaissait
  // jamais. On relit au retour du focus.
  useRefreshOnFocus(() => void load());

  useEffect(() => {
    void loadQuotes();
  }, [loadQuotes]);

  // Fresh random draw every seven minutes while the planner is open.
  useEffect(() => {
    if (quotes.length < 2) return;
    const timer = window.setInterval(() => {
      setDisplayQuote((current) => pickRandomQuote(quotes, current?.id));
    }, QUOTE_ROTATE_MS);
    return () => window.clearInterval(timer);
  }, [quotes]);

  useEffect(() => {
    if (!quoteModalOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      // Consommé : le mini-panneau ne se ferme qu'au second Échap (contrat du 17 sept. 2026, lib.rs lit `defaultPrevented`).
      event.preventDefault();
      void closeQuoteModal();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [quoteModalOpen, quoteDraft.text, quoteDraft.author]);

  const closeQuoteModalNow = () => {
    setQuoteModalOpen(false);
    setQuoteDraft({ text: '', author: '' });
  };

  const closeQuoteModal = async () => {
    if (quoteDraft.text.trim() || quoteDraft.author.trim()) {
      const confirmed = await confirm({
        title: 'Fermer sans enregistrer ?',
        description: "Ce que vous avez écrit ne sera pas enregistré.",
        confirmLabel: 'Fermer',
        keepLabel: 'Garder',
        tone: 'warning',
      });
      if (!confirmed) return;
    }
    closeQuoteModalNow();
  };

  const submitQuote = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = quoteDraft.text.trim();
    if (!text) return;
    setSaving(true);
    try {
      const created = await createSuccesQuote({ text, author: quoteDraft.author.trim() });
      setQuoteDraft({ text: '', author: '' });
      await loadQuotes();
      setDisplayQuote(created);
      toast.success('Mot du jour ajouté.');
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error("Ce mot du jour n'a pas pu être ajouté.", { description: message });
    } finally {
      setSaving(false);
    }
  };

  const change = async (action: () => Promise<unknown>, success: string) => {
    setSaving(true);
    try {
      await action();
      await load();
      toast.success(success, { description: 'Enregistré localement sur ce Mac.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'error',
        category: 'succes',
        message: `${success} — échec : ${message}`,
      });
      toast.error("L'action n'a pas été enregistrée.", { description: message });
    } finally {
      setSaving(false);
    }
  };

  const createQuickTask = async () => {
    const title = quickTitle.trim();
    if (!title) return;
    const date = filter === 'day' ? selectedDate : today;
    await change(() => createSuccesTask({ title, date }), `Tâche ajoutée au ${date}`);
    setQuickTitle('');
  };

  const toggleTask = (task: SuccesTask) =>
    change(() => setSuccesTaskDone(task.id, !task.done), task.done ? 'Tâche rouverte' : 'Tâche terminée');
  const toggleSubtask = (task: SuccesTask, subtask: SuccesSubtask) =>
    change(() => setSuccesSubtaskDone(task.id, subtask.id, !subtask.done), 'Sous-tâche mise à jour');
  const addSubtask = (task: SuccesTask, title: string, parentId?: string) =>
    change(() => addSuccesSubtask(task.id, title, parentId), 'Sous-tâche ajoutée');

  /**
   * `date` : une ISO (glisser-déposer, chips) ou l'expression tapée dans le
   * champ libre de la carte (« lundi prochain »), que le serveur résout.
   * Ses deux refus — deux jours possibles, date non reconnue — sont
   * RELANCÉS : c'est la carte qui y répond (chips datées, message sous le
   * champ). Attrapés ici, ils fermaient la boîte comme après un succès et
   * la question du 409 restait sans bouton (§34, revue du 17 sept. 2026,
   * défauts 6 et 16). Le toast dit la date que le SERVEUR a rendue : il
   * répétait l'expression envoyée — « Reportée au dans 3 jours » (§100).
   */
  const rescheduleTask = async (task: SuccesTask, date: string) => {
    setSaving(true);
    try {
      const result = await rescheduleSuccesTask(task.id, date);
      await load();
      toast.success(phraseReportee(result.task.date, today), {
        description: result.warning || 'Enregistré localement sur ce Mac.',
      });
    } catch (error) {
      if (error instanceof DateAmbigueError || error instanceof DateInconnueError) throw error;
      toast.error('Le report a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const dropOnDay = async (taskId: string, date: string) => {
    const task = tasks.find((item) => item.id === taskId);
    if (!task || task.date === date) return;
    await rescheduleTask(task, date);
    setSelectedDate(date);
  };

  const month = useMemo(() => grilleDuMois(calendarMonth), [calendarMonth]);

  // Les points viennent du serveur : lui seul connaît les récurrences pas
  // encore matérialisées. En attendant sa réponse (ou s'il échoue), le
  // calcul local — mêmes règles, sans projection — évite un calendrier nu.
  useEffect(() => {
    let visible = true;
    const debut = month.days[0];
    const fin = month.days[month.days.length - 1];
    fetchPlannerPastilles(debut, fin)
      .then((reponse) => {
        if (visible) setPastilles(reponse.days);
      })
      .catch(() => {
        if (visible) setPastilles(null);
      });
    return () => {
      visible = false;
    };
  }, [month, tasks]);
  const points = pastilles ?? pastillesLocales(tasks);

  const visibleTasks = useMemo(
    () => filtrer(tasks, filter, selectedDate, today),
    [tasks, filter, selectedDate, today],
  );
  const resume = useMemo(() => resumeDuJour(tasks, selectedDate), [tasks, selectedDate]);
  const retardCount = useMemo(
    () => filtrer(tasks, 'late', selectedDate, today).length,
    [tasks, selectedDate, today],
  );

  /**
   * Cliquer un jour montre CE jour. L'ancien geste basculait sur
   * « Terminées de la semaine » : le point promettait des tâches, la liste
   * montrait autre chose — « je clique et je ne vois pas les tâches »
   * (13 septembre 2026).
   */
  const selectDay = (date: string) => {
    setSelectedDate(date);
    setFilter('day');
    setCalendarMonth(date);
  };

  const emptyCopy =
    filter === 'done'
      ? 'Aucune tâche terminée cette semaine'
      : filter === 'week'
        ? 'Rien de planifié cette semaine'
        : filter === 'high'
          ? 'Aucune priorité haute en cours'
          : filter === 'late'
            ? 'Rien en retard'
            : 'Cette journée est libre';

  return (
    <div data-verre-defilement className="flex-1 overflow-y-auto px-4 py-4 sm:px-5 sm:py-8 md:px-8 md:py-10">
      <main className="max-w-6xl mx-auto w-full">
        <header className="mb-4 sm:mb-7">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>
              Succès
            </span>
            {saving && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}
          </div>
          <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
            Planificateur
          </h1>
          <p className="hidden sm:block text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
            Une vue calme de votre journée, privée et disponible hors ligne.
          </p>
        </header>

        <div className="grid gap-4 lg:gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
          {/* Left column: clock + quote + calendar.
              Sous lg (donc toujours dans le mini-panneau), cette colonne
              passait AVANT les tâches : ~700 px de décor — horloge, citation,
              calendrier — dans un panneau de 620 px, et la première tâche du
              jour hors champ. Les tâches d'abord, le décor ensuite
              (16 sept. 2026, audit du mini-panneau). */}
          <aside className="order-2 lg:order-none grid gap-4 content-start">
            <CadreVitre as="section"
              className="rounded-2xl p-3 sm:p-5"
              style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
            >
              <AnalogClock />
            </CadreVitre>

            {/* Rendered even with nothing saved yet: hiding the card would hide
                the only way to open the quote library. Sous sm, la citation
                tient sur une ligne tronquée et l'auteur disparaît — la carte
                reste, le texte entier se lit dans la bibliothèque (16 sept.
                2026, audit du mini-panneau). */}
            <CadreVitre as="section"
              className="group rounded-2xl px-4 py-3 sm:py-4"
              style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
              aria-label="Les mots du jour"
            >
              <div className="flex items-start gap-3">
                <Quote size={16} className="mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
                <div className="min-w-0 flex-1">
                  {displayQuote ? (
                    <>
                      <p className="text-sm leading-relaxed max-sm:truncate" style={{ color: 'var(--color-text)' }} title={displayQuote.text}>
                        « {displayQuote.text} »
                      </p>
                      {displayQuote.author && (
                        <p className="hidden sm:block text-xs mt-1.5" style={{ color: 'var(--color-text-tertiary)' }}>
                          — {displayQuote.author}
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="text-sm truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                      Aucun mot du jour pour l’instant.
                    </p>
                  )}
                </div>
                {/* Le « + » n'apparaissait qu'au survol : dans le NSPanel non
                    activant, le survol n'arrive pas — le bouton restait à 30 %
                    pour toujours, seul accès à la bibliothèque (§82). */}
                <button
                  type="button"
                  onClick={() => setQuoteModalOpen(true)}
                  className="shrink-0 size-6 rounded-lg flex items-center justify-center cursor-pointer transition-opacity max-sm:opacity-100 compact:opacity-100 opacity-30 group-hover:opacity-100 focus-visible:opacity-100"
                  style={{ color: 'var(--color-text-tertiary)' }}
                  title="Mots du jour"
                  aria-label="Ouvrir les mots du jour"
                >
                  <Plus size={14} />
                </button>
              </div>
            </CadreVitre>

            {quoteModalOpen && (
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="quote-modal-title"
                onClick={() => void closeQuoteModal()}
                className="voile-modal z-[100] flex items-center justify-center p-5 backdrop-blur-md"
                style={{ background: 'color-mix(in srgb, #000 55%, transparent)' }}
              >
                <div
                  onClick={(event) => event.stopPropagation()}
                  className="w-full max-w-md rounded-2xl p-5 max-h-[min(80vh,560px)] flex flex-col"
                  style={{
                    background: 'color-mix(in srgb, var(--color-surface) 94%, transparent)',
                    border: '1px solid var(--color-border)',
                    boxShadow: '0 24px 60px rgba(0,0,0,0.45)',
                  }}
                >
                  <div className="flex items-center justify-between gap-3 mb-4">
                    <h2
                      id="quote-modal-title"
                      className="text-base font-semibold"
                      style={{ color: 'var(--color-text)' }}
                    >
                      Mots du jour
                    </h2>
                    <button
                      type="button"
                      onClick={() => void closeQuoteModal()}
                      className="p-1.5 rounded-lg cursor-pointer"
                      style={{ color: 'var(--color-text-tertiary)' }}
                      aria-label="Fermer"
                    >
                      <X size={16} />
                    </button>
                  </div>

                  <div className="flex-1 overflow-y-auto min-h-0 grid gap-2 mb-4">
                    {!quotes.length ? (
                      <p className="text-sm py-6 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
                        Aucune citation pour l’instant. Ajoutez-en une ci-dessous.
                      </p>
                    ) : (
                      quotes.map((item) => (
                        <div
                          key={item.id}
                          className="rounded-xl px-3 py-2.5"
                          style={{
                            background: 'var(--color-bg-secondary)',
                            border:
                              displayQuote?.id === item.id
                                ? '1px solid var(--color-accent)'
                                : '1px solid transparent',
                          }}
                        >
                          <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text)' }}>
                            « {item.text} »
                          </p>
                          {item.author && (
                            <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                              — {item.author}
                            </p>
                          )}
                        </div>
                      ))
                    )}
                  </div>

                  <form onSubmit={submitQuote} className="grid gap-2 shrink-0 pt-3" style={{ borderTop: '1px solid var(--color-border-subtle)' }}>
                    <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                      Ajouter une citation
                    </p>
                    <textarea
                      autoFocus
                      rows={2}
                      value={quoteDraft.text}
                      onChange={(e) => setQuoteDraft((d) => ({ ...d, text: e.target.value }))}
                      placeholder="La citation"
                      className="w-full text-sm px-2.5 py-2 rounded-lg outline-none resize-none"
                      style={{
                        background: 'var(--color-input-bg)',
                        color: 'var(--color-text)',
                        border: '1px solid var(--color-input-border)',
                      }}
                    />
                    <input
                      value={quoteDraft.author}
                      onChange={(e) => setQuoteDraft((d) => ({ ...d, author: e.target.value }))}
                      placeholder="L’auteur (facultatif)"
                      className="w-full text-sm px-2.5 py-1.5 rounded-lg outline-none"
                      style={{
                        background: 'var(--color-input-bg)',
                        color: 'var(--color-text)',
                        border: '1px solid var(--color-input-border)',
                      }}
                    />
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => void closeQuoteModal()}
                        className="text-xs px-2.5 py-1.5 rounded-lg cursor-pointer"
                        style={{ color: 'var(--color-text-tertiary)' }}
                      >
                        Fermer
                      </button>
                      <button
                        type="submit"
                        disabled={!quoteDraft.text.trim() || saving}
                        className="text-xs px-3 py-1.5 rounded-lg cursor-pointer disabled:opacity-40 disabled:cursor-default"
                        style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent, #fff)' }}
                      >
                        Ajouter
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            )}

            <CadreVitre as="section"
              className="rounded-2xl p-4"
              style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-center justify-between mb-3">
                <button
                  type="button"
                  onClick={() => {
                    const date = analyserIso(calendarMonth);
                    date.setMonth(date.getMonth() - 1);
                    setCalendarMonth(dateIsoLocale(date));
                  }}
                  className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
                  aria-label="Mois précédent"
                >
                  <ChevronLeft size={16} />
                </button>
                <p className="text-sm font-medium capitalize" style={{ color: 'var(--color-text)' }}>
                  {month.label}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    const date = analyserIso(calendarMonth);
                    date.setMonth(date.getMonth() + 1);
                    setCalendarMonth(dateIsoLocale(date));
                  }}
                  className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
                  aria-label="Mois suivant"
                >
                  <ChevronRight size={16} />
                </button>
              </div>

              <div className="grid grid-cols-7 gap-1 mb-1">
                {DAY_LABELS.map((label) => (
                  <div key={label} className="text-center text-[10px] py-1" style={{ color: 'var(--color-text-tertiary)' }}>
                    {label}
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-7 gap-1">
                {month.days.map((date) => {
                  const inMonth = analyserIso(date).getMonth() === month.month;
                  const isToday = date === today;
                  const isSelected = date === selectedDate;
                  const pastille = points[date];
                  const hasOpen = (pastille?.open ?? 0) > 0;
                  const hasDone = (pastille?.done ?? 0) > 0;
                  return (
                    <button
                      key={date}
                      type="button"
                      onClick={() => selectDay(date)}
                      onDragOver={(event) => {
                        event.preventDefault();
                        setDropTarget(date);
                      }}
                      onDragLeave={() => setDropTarget((current) => (current === date ? null : current))}
                      onDrop={(event) => {
                        event.preventDefault();
                        setDropTarget(null);
                        const id = event.dataTransfer.getData(MIME) || event.dataTransfer.getData('text/plain');
                        if (id) void dropOnDay(id, date);
                      }}
                      className="relative aspect-square rounded-lg text-xs font-medium cursor-pointer"
                      style={{
                        color: !inMonth
                          ? 'var(--color-text-tertiary)'
                          : isSelected || isToday
                            ? 'var(--color-text)'
                            : 'var(--color-text-secondary)',
                        background: dropTarget === date
                          ? 'color-mix(in srgb, var(--color-accent) 18%, transparent)'
                          : isSelected
                            ? 'color-mix(in srgb, var(--color-accent) 22%, transparent)'
                            : isToday
                              ? 'var(--color-bg-secondary)'
                              : 'transparent',
                        boxShadow: isSelected ? 'inset 0 0 0 1px var(--color-accent)' : undefined,
                        opacity: inMonth ? 1 : 0.45,
                      }}
                      aria-label={date}
                      aria-current={isToday ? 'date' : undefined}
                    >
                      {date.slice(8)}
                      {(hasOpen || hasDone) && (
                        <span
                          className="absolute bottom-1 left-1/2 -translate-x-1/2 size-1 rounded-full"
                          style={{
                            background: hasOpen ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
                          }}
                        />
                      )}
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedDate(today);
                  setCalendarMonth(today);
                  setFilter('day');
                }}
                className="mt-3 w-full h-8 rounded-lg text-xs cursor-pointer"
                style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
              >
                Aujourd’hui
              </button>
            </CadreVitre>
          </aside>

          {/* Right column: filters + tasks — first under lg, see the aside. */}
          <section className="order-1 lg:order-none min-w-0 grid gap-4 content-start">
            <CadreVitre
              className="rounded-2xl p-4"
              style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-center gap-3 mb-4">
                <CalendarCheck2 size={20} className="shrink-0" style={{ color: 'var(--color-accent)' }} />
                <div className="min-w-0 flex-1">
                  <p className="font-medium capitalize truncate" style={{ color: 'var(--color-text)' }}>
                    {new Intl.DateTimeFormat('fr-CA', {
                      weekday: 'long',
                      day: 'numeric',
                      month: 'long',
                      year: 'numeric',
                    }).format(analyserIso(selectedDate))}
                  </p>
                  <p className="hidden sm:block text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                    {selectedDate}
                  </p>
                </div>
                {/* Sous lg, le mini-calendrier — seul moyen de changer de jour —
                    passe APRÈS les tâches (les tâches d'abord) : un jour chargé
                    le renvoyait à quinze cartes de défilement. Les chevrons
                    rendent le jour d'avant et d'après à portée de pouce
                    (revue du 16 sept. 2026). */}
                <div className="flex items-center gap-1 shrink-0 lg:hidden">
                  <button
                    type="button"
                    onClick={() => {
                      const date = analyserIso(selectedDate);
                      date.setDate(date.getDate() - 1);
                      selectDay(dateIsoLocale(date));
                    }}
                    className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
                    aria-label="Jour précédent"
                    title="Jour précédent"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const date = analyserIso(selectedDate);
                      date.setDate(date.getDate() + 1);
                      selectDay(dateIsoLocale(date));
                    }}
                    className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
                    aria-label="Jour suivant"
                    title="Jour suivant"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5 mb-4" role="tablist" aria-label="Filtres">
                {(
                  [
                    { id: 'day' as const, label: libelleDuJour(selectedDate, today) },
                    { id: 'week' as const, label: 'Cette semaine' },
                    { id: 'done' as const, label: 'Terminées' },
                    { id: 'high' as const, label: 'Priorité haute' },
                    // L'onglet n'existe que s'il y a du retard : zéro retard,
                    // zéro reproche.
                    ...(retardCount > 0 ? [{ id: 'late' as const, label: `En retard (${retardCount})` }] : []),
                  ]
                ).map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    role="tab"
                    aria-selected={filter === option.id}
                    onClick={() => setFilter(option.id)}
                    className="px-3 py-1.5 rounded-full text-xs font-medium cursor-pointer"
                    style={{
                      background: filter === option.id ? 'var(--color-accent)' : 'var(--color-bg-secondary)',
                      color: filter === option.id ? '#fff' : 'var(--color-text-secondary)',
                      border: filter === option.id ? 'none' : '1px solid var(--color-border)',
                    }}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              <div className="grid grid-cols-3 gap-2">
                {[
                  ['Total jour', resume.total],
                  ['À faire', resume.open],
                  ['Terminées', resume.done],
                ].map(([label, value]) => (
                  <CadreVitre compact key={String(label)} className="rounded-xl px-3 py-3" style={{ background: 'var(--color-bg-secondary)' }}>
                    <p className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>{value}</p>
                    <p className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{label}</p>
                  </CadreVitre>
                ))}
              </div>
            </CadreVitre>

            <div className="flex gap-2">
              <input
                value={quickTitle}
                onChange={(event) => setQuickTitle(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void createQuickTask();
                }}
                placeholder={`Ajouter une tâche…`}
                maxLength={200}
                className="flex-1 min-w-0 rounded-xl px-4 py-2.5 text-sm bg-transparent outline-none"
                style={{
                  color: 'var(--color-text)',
                  background: 'var(--color-bg-secondary)',
                  border: '1px solid var(--color-border)',
                }}
              />
              <button
                type="button"
                disabled={!quickTitle.trim() || saving}
                onClick={() => void createQuickTask()}
                className="px-3 sm:px-4 rounded-xl text-sm font-medium flex items-center gap-2 disabled:opacity-50 cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
                aria-label="Ajouter la tâche"
                title="Ajouter la tâche"
              >
                <CirclePlus size={16} /> <span className="hidden sm:inline">Ajouter</span>
              </button>
            </div>

            {loading ? (
              <div className="flex items-center justify-center gap-2 py-10 sm:py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                <Loader2 size={17} className="animate-spin" /> Chargement du plan…
              </div>
            ) : !visibleTasks.length ? (
              <CadreVitre
                className="rounded-2xl px-4 py-8 sm:py-16 text-center"
                style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
              >
                <p className="font-medium" style={{ color: 'var(--color-text)' }}>{emptyCopy}</p>
                <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                  Ajoutez une tâche ici ou demandez à DIA de la planifier.
                </p>
              </CadreVitre>
            ) : (
              <div className="grid gap-3">
                {visibleTasks.map((task) => (
                  <div
                    key={task.id}
                    draggable
                    onDragStart={(event) => {
                      event.dataTransfer.setData(MIME, task.id);
                      event.dataTransfer.setData('text/plain', task.id);
                      event.dataTransfer.effectAllowed = 'move';
                    }}
                  >
                    <TaskCard
                      task={task}
                      vitre
                      compact
                      onToggleTask={toggleTask}
                      onToggleSubtask={toggleSubtask}
                      onAddSubtask={addSubtask}
                      onReschedule={rescheduleTask}
                    />
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
