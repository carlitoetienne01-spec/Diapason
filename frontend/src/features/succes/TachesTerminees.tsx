import { useEffect, useMemo, useState } from 'react';
import { BriefcaseBusiness, CalendarDays, CheckCheck, Clock3, RotateCcw, Trash2 } from 'lucide-react';

import { CadreVitre } from '../../components/Glass/CadreVitre';
import { Pageur } from './Pageur';
import { MonogrammeProjet, styleLiseret } from './TaskCard';
import { libelleEcheance } from './echeances';
import { paginer, type TaillePage } from './pagination';
import { compterParJour, etendreSelection, grouperParJourDeCompletion, trierTerminees } from './terminees';
import type { SuccesProject, SuccesTask } from './types';

/**
 * L'onglet Terminées (demande de Carlito, 17 sept. 2026) : les tâches
 * faites, groupées par jour de complétion, les plus récentes d'abord,
 * paginées par tâches ; chaque ligne se rouvre d'un clic, se supprime, se
 * sélectionne — Maj+clic étend — et l'en-tête offre « Tout sélectionner »
 * (§82 : la plage au clavier a son bouton) et « Vider les terminées ».
 *
 * Les décisions (ordre, groupes, libellés, plage, bilan) vivent dans
 * `terminees.ts` ; la suppression en masse et son bilan serveur (§100)
 * vivent chez l'appelant, qui tient `load()` et les toasts.
 */
export interface TachesTermineesProps {
  /** Les terminées de l'onglet, filtre projet compris, dans n'importe quel ordre. */
  taches: SuccesTask[];
  projects: SuccesProject[];
  aujourdHui: string;
  page: number;
  parPage: TaillePage;
  onPage: (page: number) => void;
  onParPage: (taille: TaillePage) => void;
  onRouvrir: (task: SuccesTask) => Promise<unknown>;
  onSupprimer: (task: SuccesTask) => Promise<unknown>;
  /** Supprime plusieurs tâches — confirmation, requêtes une à une et bilan chez l'appelant. */
  onSupprimerPlusieurs: (taches: SuccesTask[]) => Promise<unknown>;
  saving: boolean;
  /** Ce qu'on dit quand il n'y a rien : la recherche ou le filtre l'expliquent peut-être. */
  filtreActif: boolean;
}

export function TachesTerminees({
  taches, projects, aujourdHui, page, parPage, onPage, onParPage,
  onRouvrir, onSupprimer, onSupprimerPlusieurs, saving, filtreActif,
}: TachesTermineesProps) {
  const triees = useMemo(() => trierTerminees(taches), [taches]);
  const comptes = useMemo(() => compterParJour(triees), [triees]);
  const pagination = paginer(triees, page, parPage);
  const groupes = useMemo(
    () => grouperParJourDeCompletion(pagination.tranche, aujourdHui),
    [pagination.tranche, aujourdHui],
  );
  const ordre = useMemo(() => triees.map((task) => task.id), [triees]);
  // L'ordre d'une plage Maj+clic est celui de la PAGE affichée : calculé sur
  // toutes les terminées, une plage tirée depuis une ancre d'une autre page
  // emportait des lignes jamais vues dans « Supprimer » (revue du 17 sept.
  // 2026). L'ancre s'oublie donc aussi quand on change de page.
  const ordreDeLaPage = useMemo(() => pagination.tranche.map((task) => task.id), [pagination.tranche]);

  const [selection, setSelection] = useState<ReadonlySet<string>>(() => new Set());
  const [ancre, setAncre] = useState<string | null>(null);
  useEffect(() => {
    setAncre(null);
  }, [page]);

  // Une ligne rouverte ou supprimée quitte l'onglet : elle quitte aussi la
  // sélection, sinon « 3 sélectionnées » comptait des lignes invisibles et
  // « Supprimer » aurait visé une tâche revenue en Liste.
  useEffect(() => {
    setSelection((courante) => {
      const presentes = new Set(ordre);
      let changee = false;
      const suivante = new Set<string>();
      for (const id of courante) {
        if (presentes.has(id)) suivante.add(id);
        else changee = true;
      }
      return changee ? suivante : courante;
    });
  }, [ordre]);

  const selectionner = (task: SuccesTask, plage: boolean) => {
    setSelection((courante) => etendreSelection(ordreDeLaPage, courante, task.id, ancre, plage));
    if (!plage) setAncre(task.id);
  };

  const toutSelectionne = ordre.length > 0 && ordre.every((id) => selection.has(id));
  const basculerTout = () => {
    setSelection(toutSelectionne ? new Set() : new Set(ordre));
    setAncre(null);
  };

  const selectionnees = triees.filter((task) => selection.has(task.id));
  const projetDe = (task: SuccesTask) => projects.find((project) => project.id === task.projectId);

  if (triees.length === 0) {
    return (
      <CadreVitre className="rounded-2xl py-16 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
        <CheckCheck size={28} className="mx-auto mb-3" style={{ color: 'var(--color-success)' }} />
        <p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucune tâche terminée</p>
        <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
          {filtreActif ? 'Rien ne correspond à la recherche ou au filtre.' : 'Ce que vous cochez en Liste arrivera ici.'}
        </p>
      </CadreVitre>
    );
  }

  return (
    <section aria-label="Tâches terminées">
      {/* L'en-tête : la sélection à gauche, l'action de masse à droite. Sous
          340 px les deux se replient l'un sous l'autre ; les boutons gardent
          32 px de haut (mini-panneau). */}
      <CadreVitre compact
        className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-2xl px-3 py-2 mb-3"
        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      >
        <label className="flex items-center gap-2 text-xs cursor-pointer select-none h-8" style={{ color: 'var(--color-text-secondary)' }}>
          <input type="checkbox" checked={toutSelectionne} onChange={basculerTout} aria-label="Tout sélectionner" />
          {selection.size > 0 ? (
            <span className="tabular-nums" style={{ color: 'var(--color-text)' }}>
              {selection.size} sélectionnée{selection.size > 1 ? 's' : ''}
            </span>
          ) : (
            <span>Tout sélectionner</span>
          )}
        </label>
        {selection.size > 0 ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => { setSelection(new Set()); setAncre(null); }}
              className="h-8 px-2 rounded-lg text-xs cursor-pointer"
              style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            >
              Désélectionner
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => void onSupprimerPlusieurs(selectionnees)}
              className="h-8 px-3 rounded-lg text-xs font-medium cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
              style={{ background: 'var(--color-error)', color: '#fff' }}
            >
              <Trash2 size={13} aria-hidden />
              Supprimer
            </button>
          </div>
        ) : (
          <button
            type="button"
            disabled={saving}
            onClick={() => void onSupprimerPlusieurs(triees)}
            className="h-8 px-3 rounded-lg text-xs cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
            style={{ color: 'var(--color-error)', border: '1px solid color-mix(in srgb, var(--color-error) 45%, var(--color-border))' }}
            title={filtreActif ? 'Supprime les terminées affichées — filtre compris' : 'Supprime toutes les tâches terminées'}
          >
            <Trash2 size={13} aria-hidden />
            Vider les terminées
            <span className="tabular-nums">({triees.length})</span>
          </button>
        )}
      </CadreVitre>

      {groupes.map((groupe) => (
        <div key={groupe.jour || 'sans-date'} className="mb-4">
          <h2
            className="flex items-baseline gap-2 text-[11px] uppercase tracking-[0.14em] mb-2 px-1"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            <span>{groupe.libelle}</span>
            <span className="tabular-nums teinte-terminees" style={{ color: 'var(--color-success)' }}>
              · {comptes.get(groupe.jour) ?? groupe.taches.length}
            </span>
          </h2>
          <div className="grid gap-2">
            {groupe.taches.map((task) => (
              <LigneTerminee
                key={task.id}
                task={task}
                project={projetDe(task)}
                aujourdHui={aujourdHui}
                selectionnee={selection.has(task.id)}
                saving={saving}
                onSelectionner={(plage) => selectionner(task, plage)}
                onRouvrir={() => void onRouvrir(task)}
                onSupprimer={() => void onSupprimer(task)}
              />
            ))}
          </div>
        </div>
      ))}

      <Pageur
        page={pagination.page}
        nbPages={pagination.nbPages}
        total={pagination.total}
        debut={pagination.debut}
        fin={pagination.fin}
        parPage={parPage}
        onPage={onPage}
        onParPage={onParPage}
        unite="tâches terminées"
        teinte="succes"
      />
    </section>
  );
}

/**
 * Une ligne de terminée — dédiée, pas la TaskCard : ici pas de carnet, pas
 * d'édition, pas de sous-tâches ; une case de sélection, le titre barré en
 * casse normale, le projet (liseré, ou monogramme en Ardéchine), l'échéance
 * qu'elle avait, et deux boutons : « Rouvrir », la corbeille.
 */
function LigneTerminee({
  task, project, aujourdHui, selectionnee, saving, onSelectionner, onRouvrir, onSupprimer,
}: {
  task: SuccesTask;
  project: SuccesProject | undefined;
  aujourdHui: string;
  selectionnee: boolean;
  saving: boolean;
  onSelectionner: (plage: boolean) => void;
  onRouvrir: () => void;
  onSupprimer: () => void;
}) {
  return (
    <CadreVitre as="article"
      className="group rounded-2xl p-3 transition-colors"
      style={{
        background: selectionnee ? 'color-mix(in srgb, var(--color-success) 8%, var(--color-surface))' : 'var(--color-surface)',
        border: `1px solid ${selectionnee ? 'color-mix(in srgb, var(--color-success) 45%, var(--color-border))' : 'var(--color-border)'}`,
      }}
    >
      <div
        className={`flex items-start gap-3 ${project ? 'liseret-projet' : ''}`}
        style={styleLiseret(project, '-8px')}
      >
        {/* Maj+clic étend depuis la dernière ligne cliquée ; l'événement
            natif d'un `change` de case est le clic, il porte `shiftKey`.
            `select-none` : Maj+clic sélectionnait aussi le texte entre les
            deux lignes. */}
        <input
          type="checkbox"
          checked={selectionnee}
          onChange={(event) => onSelectionner(Boolean((event.nativeEvent as MouseEvent).shiftKey))}
          className="mt-1.5 size-4 shrink-0 cursor-pointer select-none"
          aria-label={`Sélectionner « ${task.title} »`}
        />
        <div className="flex-1 min-w-0">
          <p
            className="titre-tache min-w-0 leading-6 break-words line-through"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <MonogrammeProjet project={project} />
            {task.emoji ? `${task.emoji} ` : ''}{task.title}
          </p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {task.date && (
              <span className="flex items-center gap-1" title={`Prévue le ${task.date}`}>
                <CalendarDays size={12} />
                {libelleEcheance(task.date, aujourdHui, { terminee: true })}
              </span>
            )}
            {task.time && <span className="flex items-center gap-1"><Clock3 size={12} />{task.time}</span>}
            {project && (
              <span className="flex items-center gap-1 min-w-0">
                <BriefcaseBusiness size={12} className="shrink-0" />
                <span className="truncate max-w-[9rem] sm:max-w-none">{project.name}</span>
              </span>
            )}
          </div>
        </div>
        {/* Révélés au survol, toujours visibles sous sm, au tactile et dans
            le mini-panneau (un NSPanel non activant ne livre pas le survol). */}
        <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100 max-sm:opacity-100 compact:opacity-100 transition-opacity">
          <button
            type="button"
            disabled={saving}
            onClick={onRouvrir}
            className="h-8 px-2 rounded-lg text-xs flex items-center gap-1 cursor-pointer disabled:opacity-50"
            style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            aria-label={`Rouvrir « ${task.title} »`}
            // Une étape de projet sans date ne revient pas en Liste : elle
            // retourne sur sa carte. L'info-bulle mentait pour 26 des 36
            // terminées réelles (revue du 17 sept. 2026).
            title={
              !task.date && project && (project.structure || 'flat') !== 'flat'
                ? `Rouvrir : l'étape retourne sur sa carte dans Projets (${project.name})`
                : 'Rouvrir : la tâche revient en Liste'
            }
          >
            <RotateCcw size={13} aria-hidden />
            <span className="hidden sm:inline">Rouvrir</span>
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={onSupprimer}
            className="size-8 rounded-lg flex items-center justify-center cursor-pointer disabled:opacity-50"
            style={{ color: 'var(--color-error)' }}
            aria-label={`Supprimer « ${task.title} »`}
            title="Supprimer"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
    </CadreVitre>
  );
}
