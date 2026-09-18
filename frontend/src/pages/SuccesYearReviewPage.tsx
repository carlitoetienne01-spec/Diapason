import { CadreVitre } from '../components/Glass/CadreVitre';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Download, Loader2, Trophy } from 'lucide-react';
import { toast } from 'sonner';

import { downloadSuccesExport, fetchSuccesYearReview } from '../features/succes/api';
import type { SuccesYearReview } from '../features/succes/types';
import { useAppStore } from '../lib/store';
import { useRefreshOnFocus } from '../features/succes/useRefreshOnFocus';
import { clesSucces, ecrireCache, lireCache } from '../features/succes/cacheSucces';

const MONTHS = ['JAN', 'FÉV', 'MAR', 'AVR', 'MAI', 'JUN', 'JUL', 'AOÛ', 'SEP', 'OCT', 'NOV', 'DÉC'];
const MONTH_NAMES = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];

export function SuccesYearReviewPage() {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);
  const [month, setMonth] = useState<number | undefined>();
  // L'état initial vient du cache — le bilan que le serveur a rendu pour
  // cette année à la dernière visite (Carlito, 18 sept. 2026 : chaque
  // montage repartait d'une frise vide sous un spinner).
  const [review, setReview] = useState<SuccesYearReview | null>(
    () => lireCache<SuccesYearReview>(clesSucces.bilan(currentYear)),
  );
  const [loading, setLoading] = useState(() => lireCache(clesSucces.bilan(currentYear)) === null);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    // Une autre année ou un autre mois : ce que le cache en sait s'affiche
    // tout de suite ; sinon le spinner — les chiffres de 2025 ne tiendront
    // pas lieu de ceux de 2026, même cinquante millisecondes.
    const cle = clesSucces.bilan(year, month);
    const connu = lireCache<SuccesYearReview>(cle);
    if (connu) setReview(connu);
    else setLoading(true);
    try {
      const next = await fetchSuccesYearReview(year, month);
      // Une seule entrée persistée : une par année ou mois feuilleté
      // s'accumulait (revue du cache, 18 sept. 2026).
      ecrireCache(cle, next, {
        uniqueParRessource: true,
        // L'année courante est la clé que le montage relit : regarder un
        // mois ne doit pas l'évincer du disque (contre-revue, 18 sept. 2026).
        conserver: [clesSucces.bilan(currentYear)],
      });
      setReview(next);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `Bilan : ${message}` });
      toast.error('Le bilan ne peut pas être calculé.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [month, year]);

  useEffect(() => { void load(); }, [load]);

  // Une page ouverte gardait son état indéfiniment : ce qui change
  // ailleurs — téléphone, autre fenêtre, assistant — n'apparaissait
  // jamais. On relit au retour du focus.
  useRefreshOnFocus(() => void load());

  const maxActivity = Math.max(1, ...(review?.activityByMonth ?? []));
  const metrics = useMemo(() => {
    const summary = review?.summary;
    return [
      ['✅', 'Tâches créées', summary?.tasksCreated ?? 0],
      ['🎯', 'Tâches complétées', summary?.tasksCompleted ?? 0],
      ['🏃', 'Habitudes complétées', summary?.habitsCompleted ?? 0],
      ['📁', 'Projets créés', summary?.projectsCreated ?? 0],
      ['🏁', 'Projets terminés', summary?.projectsCompleted ?? 0],
    ] as const;
  }, [review]);

  const exportData = async () => {
    setExporting(true);
    try {
      await downloadSuccesExport();
      toast.success('Export JSON téléchargé');
    } catch (error) {
      toast.error("L'export n'a pas pu être créé.", { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setExporting(false);
    }
  };

  // 16 sept. 2026, audit du mini-panneau : px-5 py-8 mangeait 40 px de
  // large sur 340 et poussait la frise sous la ligne de flottaison à 380 px
  // de haut. La base est la miniature ; sm: rend les marges.
  return (
    <div data-verre-defilement className="flex-1 overflow-y-auto px-3 py-5 sm:px-5 sm:py-8 md:px-8 md:py-10">
      <main className="max-w-5xl mx-auto w-full">
        <header className="flex flex-col gap-3 sm:gap-5 md:flex-row md:items-end md:justify-between mb-5 sm:mb-7">
          <div>
            <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>Succès</span>
            <button type="button" onClick={() => setMonth(undefined)} className="block mt-2 text-left cursor-pointer" aria-label="Revenir au bilan annuel">
              <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>Bilan annuel</h1>
            </button>
            <p className="hidden sm:block text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
              Prenez du recul sur vos actions, habitudes et projets.
            </p>
          </div>
          {/* Empilé sous md, le bouton s'étirait sur toute la largeur du
              panneau (align-items: stretch) : une barre « Export JSON » de
              340 px sous le titre. self-start le rend à sa taille. */}
          <button type="button" disabled={exporting} onClick={() => void exportData()} aria-label="Export JSON" title="Export JSON" className="self-start md:self-auto flex items-center gap-2 px-3 sm:px-4 py-2 rounded-xl text-sm cursor-pointer disabled:opacity-50" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>
            {exporting ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} <span className="hidden sm:inline">Export JSON</span>
          </button>
        </header>

        <CadreVitre as="section" className="rounded-2xl p-4 mb-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <div className="flex items-center justify-center gap-4 mb-5">
            <button type="button" disabled={year <= 1970} onClick={() => { setYear((value) => value - 1); setMonth(undefined); }} className="size-9 rounded-lg flex items-center justify-center disabled:opacity-30 cursor-pointer" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }} aria-label="Année précédente"><ChevronLeft size={17} /></button>
            <p className="min-w-24 text-center text-xl font-semibold" style={{ color: 'var(--color-text)' }}>{year}</p>
            <button type="button" disabled={year >= currentYear + 15} onClick={() => { setYear((value) => value + 1); setMonth(undefined); }} className="size-9 rounded-lg flex items-center justify-center disabled:opacity-30 cursor-pointer" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }} aria-label="Année suivante"><ChevronRight size={17} /></button>
          </div>

          {loading ? <div className="h-40 flex items-center justify-center"><Loader2 className="animate-spin" style={{ color: 'var(--color-accent)' }} /></div> : (
            <div className="grid grid-cols-6 md:grid-cols-12 gap-1.5 sm:gap-2" aria-label="Activité par mois">
              {(review?.activityByMonth ?? Array(12).fill(0)).map((value, index) => {
                const selected = month === index + 1;
                const ratio = value / maxActivity;
                // Sous md la frise passe sur deux rangées de six ; avec une
                // jauge h-24 le bloc faisait ~270 px de haut dans un panneau
                // de 620, écrasant à 380 (16 sept. 2026). h-14 garde le ratio
                // lisible et ramène le bloc vers 180 px.
                return (
                  <CadreVitre as="button" compact key={MONTHS[index]} type="button" aria-pressed={selected} onClick={() => setMonth(selected ? undefined : index + 1)} className="rounded-xl px-1 py-1.5 sm:py-2 flex flex-col items-center gap-1.5 sm:gap-2 cursor-pointer" style={{ background: selected ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)', border: selected ? '1px solid var(--color-accent)' : '1px solid transparent' }}>
                    <span className="h-14 sm:h-24 w-3 rounded-full flex items-end overflow-hidden" style={{ background: 'var(--color-bg-tertiary)' }}><span className="block w-full rounded-full transition-all" style={{ height: `${Math.max(value ? 8 : 0, Math.round(ratio * 100))}%`, background: `hsl(${Math.round(index * 360 / 12)} 82% 48%)` }} /></span>
                    <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>{MONTHS[index]}</span>
                    <span className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>{value}</span>
                  </CadreVitre>
                );
              })}
            </div>
          )}
        </CadreVitre>

        <section className="grid md:grid-cols-[1.1fr_0.9fr] gap-4 sm:gap-5">
          <CadreVitre className="rounded-2xl p-4 sm:p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <h2 className="font-medium mb-4" style={{ color: 'var(--color-text)' }}>
              {month ? `Résumé mensuel — ${MONTH_NAMES[month - 1]} ${year}` : 'Résumé annuel'}
            </h2>
            <div className="grid gap-2">
              {metrics.map(([icon, label, value]) => <CadreVitre compact key={label} className="flex items-center gap-3 rounded-xl px-3 py-2.5" style={{ background: 'var(--color-bg-secondary)' }}><span>{icon}</span><span className="flex-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{label}</span><strong style={{ color: 'var(--color-text)' }}>{value}</strong></CadreVitre>)}
            </div>
          </CadreVitre>

          <CadreVitre className="rounded-2xl p-4 sm:p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <div className="flex items-center gap-2 mb-4"><Trophy size={18} style={{ color: 'var(--color-accent)' }} /><h2 className="font-medium" style={{ color: 'var(--color-text)' }}>Top accomplissements</h2></div>
            <p className="text-xs mb-4 capitalize" style={{ color: 'var(--color-text-tertiary)' }}>{month ? `${MONTH_NAMES[month - 1]} ${year}` : `Année ${year}`}</p>
            <div className="grid gap-3">
              <CadreVitre compact className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)' }}><p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>🎯 Tâches complétées</p><p className="text-2xl font-semibold mt-1" style={{ color: 'var(--color-text)' }}>{review?.summary.tasksCompleted ?? 0}</p></CadreVitre>
              <CadreVitre compact className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)' }}><p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>🏁 Projets terminés</p><p className="text-2xl font-semibold mt-1" style={{ color: 'var(--color-text)' }}>{review?.summary.projectsCompleted ?? 0}</p></CadreVitre>
              {!month && (review?.catalog.longestHabitStreak ?? 0) >= 1 && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>🔥 Plus long streak : {review?.catalog.longestHabitStreak} j.</p>}
            </div>
          </CadreVitre>
        </section>
      </main>
    </div>
  );
}
