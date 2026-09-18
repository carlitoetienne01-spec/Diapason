import { CadreVitre } from '../components/Glass/CadreVitre';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  CalendarDays,
  CheckCircle2,
  Flame,
  LayoutDashboard,
  Loader2,
  NotebookPen,
  Quote,
} from 'lucide-react';
import { toast } from 'sonner';

import { fetchSuccesDashboard, setSuccesHabitDone } from '../features/succes/api';
import { resyncHabitReminders } from '../features/succes/habitReminders';
import type { SuccesDashboard, SuccesHabit } from '../features/succes/types';
import { useAppStore } from '../lib/store';
import { useRefreshOnFocus } from '../features/succes/useRefreshOnFocus';
import { clesSucces, ecrireCache, lireCache } from '../features/succes/cacheSucces';

function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

const WEEK_LABELS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];

export function SuccesDashboardPage() {
  const navigate = useNavigate();
  const [date, setDate] = useState(localIsoDate);
  // L'état initial vient du cache — le tableau que le serveur a rendu pour
  // cette date à la dernière visite (46 ms côté serveur ; c'était l'écran
  // vide par montage qui coûtait, Carlito, 18 sept. 2026). Un changement de
  // date relit derrière le tableau affiché, avec le voyant de l'en-tête.
  const [data, setData] = useState<SuccesDashboard | null>(
    () => lireCache<SuccesDashboard>(clesSucces.tableauDeBord(localIsoDate())),
  );
  const [loading, setLoading] = useState(() => lireCache(clesSucces.tableauDeBord(localIsoDate())) === null);
  const [rafraichit, setRafraichit] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setRafraichit(true);
    try {
      const next = await fetchSuccesDashboard(date);
      ecrireCache(clesSucces.tableauDeBord(date), next);
      setData(next);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'error',
        category: 'succes',
        message: `Dashboard Succès : ${message}`,
      });
      toast.error('Le tableau de bord ne peut pas être chargé.', { description: message });
    } finally {
      setLoading(false);
      setRafraichit(false);
    }
  }, [date]);

  useEffect(() => {
    void load();
  }, [load]);

  // Une page ouverte gardait son état indéfiniment : ce qui change
  // ailleurs — téléphone, autre fenêtre, assistant — n'apparaissait
  // jamais. On relit au retour du focus.
  useRefreshOnFocus(() => void load());

  const toggleHabit = async (habit: SuccesHabit) => {
    setSaving(true);
    try {
      await setSuccesHabitDone(habit.id, date, !habit.done);
      await load();
      void resyncHabitReminders();
    } catch (error) {
      toast.error("L'habitude n'a pas été mise à jour.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const maxBar = Math.max(1, ...(data?.tasks.weeklyCounts ?? [0]));
  const activeProjects = (data?.projects ?? []).filter(
    (project) => project.taskTotal === 0 || project.taskCompleted < project.taskTotal,
  );

  return (
    <div data-verre-defilement className="flex-1 overflow-y-auto px-3 py-4 sm:px-5 sm:py-8 md:px-8 md:py-10">
      <main className="max-w-5xl mx-auto w-full">
        {/* En miniature (sous sm), l'en-tête tient sur UNE rangée : la
            description se tait et la date reste à droite du titre — empilés,
            ils coûtaient ~150 px du panneau avant le premier chiffre
            (16 sept. 2026, audit du mini-panneau). */}
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
              Tableau de bord
            </h1>
            <p className="hidden sm:block text-sm mt-2 max-w-xl" style={{ color: 'var(--color-text-secondary)' }}>
              Une vue d’ensemble de votre semaine : tâches, habitudes et projets, entièrement locale.
            </p>
          </div>
          <input
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
            className="h-9 rounded-xl px-3 text-sm bg-transparent outline-none shrink-0"
            style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            aria-label="Date du tableau de bord"
          />
        </header>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-24 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
            <Loader2 size={17} className="animate-spin" /> Chargement…
          </div>
        ) : data ? (
          <div className="grid gap-3 sm:gap-5">
            {/* La citation était le PREMIER bloc rendu : en miniature elle
                repoussait les KPI sous le pli pour du décoratif. Sous sm elle
                se tait (16 sept. 2026). */}
            {data.quote && (
              <CadreVitre as="section"
                className="rounded-2xl px-5 py-4 hidden sm:flex items-start gap-3"
                style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
              >
                <Quote size={18} className="mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
                <div>
                  <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text)' }}>
                    « {data.quote.text} »
                  </p>
                  {data.quote.author && (
                    <p className="text-xs mt-1.5" style={{ color: 'var(--color-text-tertiary)' }}>
                      — {data.quote.author}
                    </p>
                  )}
                </div>
              </CadreVitre>
            )}

            {/* Base à DEUX colonnes : en une seule, les quatre KPI faisaient
                ~550 px de cartes avant le premier graphique dans un panneau
                de 620 (16 sept. 2026). */}
            <section className="grid gap-2 sm:gap-3 grid-cols-2 lg:grid-cols-4">
              <KpiCard
                icon={<CheckCircle2 size={18} />}
                label="Tâches complétées"
                value={`${data.tasks.weekCompleted}`}
                hint={`/${data.tasks.weekTotal} cette semaine`}
                tint="var(--color-accent)"
                onClick={() => navigate('/succes/tasks')}
              />
              <KpiCard
                icon={<CalendarDays size={18} />}
                label="Tâches aujourd’hui"
                value={`${data.tasks.todayOpen}`}
                hint={`${data.tasks.todayTotal} planifiée(s)`}
                tint="var(--color-accent)"
                onClick={() => navigate('/succes/planner')}
              />
              <KpiCard
                icon={<Flame size={18} />}
                label="Habitudes / jour"
                value={data.habits.due ? `${data.habits.completed}/${data.habits.due}` : '—'}
                hint="prévues ce jour"
                tint="#f59e0b"
                onClick={() => navigate('/succes/habits')}
              />
              <KpiCard
                icon={<NotebookPen size={18} />}
                label="Notes"
                value={`${data.notes}`}
                hint="enregistrées"
                tint="var(--color-text-secondary)"
                onClick={() => navigate('/succes/notes')}
              />
            </section>

            <section className="grid gap-3 sm:gap-5 lg:grid-cols-[1.2fr_1fr]">
              <CadreVitre as="article"
                className="rounded-2xl p-4 sm:p-5"
                style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
              >
                <div className="flex items-center gap-2 mb-3 sm:mb-4">
                  <LayoutDashboard size={16} style={{ color: 'var(--color-accent)' }} />
                  <h2 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                    Tâches cette semaine
                  </h2>
                </div>
                <div className="flex items-end gap-2 h-28 sm:h-36">
                  {data.tasks.weeklyCounts.map((count, index) => (
                    <div key={WEEK_LABELS[index]} className="flex-1 flex flex-col items-center gap-2 h-full justify-end">
                      <span className="text-[11px] tabular-nums" style={{ color: 'var(--color-text-tertiary)' }}>
                        {count}
                      </span>
                      <div
                        className="w-full rounded-t-lg min-h-[4px] transition-all"
                        style={{
                          height: `${Math.max(4, (count / maxBar) * 100)}%`,
                          background: 'var(--color-accent)',
                          opacity: 0.35 + (count / maxBar) * 0.65,
                        }}
                      />
                      <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                        {WEEK_LABELS[index]}
                      </span>
                    </div>
                  ))}
                </div>
              </CadreVitre>

              <CadreVitre as="article"
                className="rounded-2xl p-4 sm:p-5"
                style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
              >
                <h2 className="text-sm font-medium mb-3 sm:mb-4" style={{ color: 'var(--color-text)' }}>
                  Habitudes du jour
                </h2>
                {!data.habits.items.length ? (
                  <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                    Aucune habitude prévue aujourd’hui.
                  </p>
                ) : (
                  <div className="grid gap-2">
                    {data.habits.items.map((habit) => (
                      <CadreVitre as="button" compact
                        key={habit.id}
                        type="button"
                        disabled={saving}
                        onClick={() => void toggleHabit(habit)}
                        className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-left cursor-pointer disabled:opacity-60"
                        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                      >
                        <span
                          className="size-8 rounded-full flex items-center justify-center text-sm shrink-0"
                          style={{
                            background: habit.done ? habit.color : `${habit.color}22`,
                            color: habit.done ? '#fff' : habit.color,
                            border: `1px solid ${habit.color}66`,
                          }}
                        >
                          {habit.done ? '✓' : habit.icon || '✨'}
                        </span>
                        <span
                          className="flex-1 text-sm truncate"
                          style={{
                            color: 'var(--color-text)',
                            textDecoration: habit.done ? 'line-through' : 'none',
                          }}
                        >
                          {habit.name}
                        </span>
                        {habit.streak > 0 && (
                          <span className="text-[11px] flex items-center gap-1" style={{ color: 'var(--color-text-tertiary)' }}>
                            <Flame size={11} /> {habit.streak}
                          </span>
                        )}
                      </CadreVitre>
                    ))}
                  </div>
                )}
              </CadreVitre>
            </section>

            <CadreVitre as="article"
              className="rounded-2xl p-4 sm:p-5"
              style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-center justify-between mb-3 sm:mb-4">
                <h2 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                  Projets actifs
                </h2>
                <button
                  type="button"
                  onClick={() => navigate('/succes/projects')}
                  className="text-xs cursor-pointer"
                  style={{ color: 'var(--color-accent)' }}
                >
                  Voir tout
                </button>
              </div>
              {!activeProjects.length ? (
                <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                  Aucun projet en cours.
                </p>
              ) : (
                <div className="grid gap-2 sm:gap-3 sm:grid-cols-2">
                  {activeProjects.slice(0, 6).map((project, index) => {
                    const percent = project.taskTotal
                      ? Math.round((project.taskCompleted / project.taskTotal) * 100)
                      : 0;
                    // Sous sm, seuls les trois premiers restent : six cartes
                    // empilées en colonne unique faisaient défiler le panneau
                    // pour un bloc que « Voir tout » sert déjà (16 sept. 2026).
                    // La largeur se lit en CSS, pas en JS — règle 2.
                    return (
                      <CadreVitre as="button" compact
                        key={project.id}
                        type="button"
                        onClick={() => navigate('/succes/projects')}
                        className={`rounded-xl p-3 text-left cursor-pointer${index >= 3 ? ' max-sm:hidden' : ''}`}
                        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                      >
                        <div className="flex items-center justify-between gap-2 mb-2">
                          <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
                            {project.icon ? `${project.icon} ` : ''}{project.name}
                          </p>
                          <span className="text-[11px] tabular-nums shrink-0" style={{ color: project.color || 'var(--color-accent)' }}>
                            {percent}%
                          </span>
                        </div>
                        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-tertiary, var(--color-border))' }}>
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${percent}%`,
                              background: project.color || 'var(--color-accent)',
                            }}
                          />
                        </div>
                        <p className="text-[11px] mt-1.5" style={{ color: 'var(--color-text-tertiary)' }}>
                          {project.taskCompleted}/{project.taskTotal} tâches
                        </p>
                      </CadreVitre>
                    );
                  })}
                </div>
              )}
            </CadreVitre>
          </div>
        ) : null}
      </main>
    </div>
  );
}

function KpiCard({
  icon,
  label,
  value,
  hint,
  tint,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint: string;
  tint: string;
  onClick: () => void;
}) {
  return (
    <CadreVitre as="button"
      type="button"
      onClick={onClick}
      className="rounded-2xl p-3 sm:p-4 text-left cursor-pointer transition-opacity hover:opacity-90 min-w-0"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      {/* Sous sm, l'icône se range sur la ligne du chiffre : empilés
          (icône 36 px + marge + valeur + libellé + complément), chaque carte
          dépassait 120 px de haut dans une colonne de 160 px de large
          (16 sept. 2026). */}
      <div className="flex items-center gap-2 sm:block">
        <div
          className="size-7 sm:size-9 rounded-lg sm:rounded-xl flex items-center justify-center shrink-0 sm:mb-3"
          style={{ background: `color-mix(in srgb, ${tint} 16%, transparent)`, color: tint }}
        >
          {icon}
        </div>
        <p className="text-xl sm:text-2xl font-semibold tabular-nums truncate" style={{ color: 'var(--color-text)' }}>
          {value}
        </p>
      </div>
      <p className="text-xs sm:text-sm mt-1 truncate" style={{ color: 'var(--color-text-secondary)' }}>
        {label}
      </p>
      {/* Le complément reste visible sous sm : pour « Tâches complétées » il
          porte le dénominateur (« /12 cette semaine ») — sans lui, « 3 » ne
          dit rien. Une ligne de 10 px, tronquée, pas cachée. */}
      <p className="text-[10px] sm:text-[11px] mt-0.5 truncate" style={{ color: 'var(--color-text-tertiary)' }}>
        {hint}
      </p>
    </CadreVitre>
  );
}
