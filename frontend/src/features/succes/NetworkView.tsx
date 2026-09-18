import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { Check, CirclePlus, Link2, Loader2 } from 'lucide-react';

import { CadreVitre } from '../../components/Glass/CadreVitre';
import {
  chaineComplete,
  colonnesInitiales,
  construireReseau,
  faisables,
  positionner,
  statuts,
  type StatutTache,
} from './reseau';
import type { SuccesTask, SuccesTaskEdge } from './types';

type Props = {
  tasks: SuccesTask[];
  edges: SuccesTaskEdge[];
  saving?: boolean;
  onToggle: (task: SuccesTask) => Promise<void>;
  onLink: (fromTaskId: string, toTaskId: string) => Promise<void>;
  onUnlink: (fromTaskId: string, toTaskId: string) => Promise<void>;
  onCreate: (input: { title: string }) => Promise<void>;
  onSelect?: (task: SuccesTask) => void;
  /**
   * La tâche mise en avant (ouverte dans la fiche « Branches ») : sa chaîne
   * amont + aval reste nette, le reste du graphe passe à 0.3. La
   * proposition 4 y ajoutera le survol et le focus clavier.
   */
  miseEnAvantId?: string | null;
  /**
   * « Relier depuis ici » de la fiche : entrer en mode liaison avec cette
   * source. Le jeton change à chaque demande, pour qu'une seconde demande
   * sur la même tâche soit encore entendue.
   */
  liaisonDemandee?: { sourceId: string; jeton: number } | null;
};

// Des cartes HTML vitrées (chantier réseau, 18 sept. 2026). Jusque-là la
// carte était un <rect> SVG : `truncate(title, 20)` donnait « Avoir les bons
// agri… » sur 6 des 7 titres d'AgriCulture, et le <svg width="100%">
// mettait le graphe À L'ÉCHELLE — 3 colonnes = 762 px de viewBox rendus dans
// les 340 px du mini-panneau, texte de 13 px affiché à ~6 px.
// 210 × 76 : deux lignes de 13 px (interligne 1,3 → 34 px), une ligne d'état
// de 11 px, 10 px de marge en haut et en bas ; il reste 6 px pour la bordure
// de 2 px du focus et l'arrondi.
const CARD_W = 210;
const CARD_H = 76;
const GAP_X = 72;
const GAP_Y = 26;
const PAD = 24;
const DANGER = 'var(--color-error, var(--color-text-secondary))';

// Le raisonnement (niveaux, statuts, faisables, colonnes) vit dans
// `reseau.ts`, testé sur AgriCulture (chantier réseau, 18 sept. 2026) :
// ici on ne fait que dessiner.

export function NetworkView({
  tasks,
  edges,
  saving = false,
  onToggle,
  onLink,
  onUnlink,
  onCreate,
  onSelect,
  miseEnAvantId = null,
  liaisonDemandee = null,
}: Props) {
  const [linkMode, setLinkMode] = useState(false);
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<{ from: string; to: string } | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [error, setError] = useState<string | null>(null);

  const reseau = useMemo(() => construireReseau(tasks, edges), [tasks, edges]);
  const byId = reseau.parId;
  const visibleEdges = reseau.aretes;
  const statusById = useMemo(() => statuts(reseau), [reseau]);
  const feasible = useMemo(() => faisables(reseau), [reseau]);

  const chaineNette = useMemo(
    () => (miseEnAvantId && byId.has(miseEnAvantId) ? chaineComplete(reseau, miseEnAvantId) : null),
    [reseau, byId, miseEnAvantId],
  );
  const estompe = (...ids: string[]) =>
    chaineNette !== null && !ids.every((id) => chaineNette.has(id));

  useEffect(() => {
    if (!liaisonDemandee || !byId.has(liaisonDemandee.sourceId)) return;
    setError(null);
    setSelectedEdge(null);
    setLinkMode(true);
    setLinkFrom(liaisonDemandee.sourceId);
  }, [liaisonDemandee]); // eslint-disable-line react-hooks/exhaustive-deps -- une demande, une fois

  const layout = useMemo(
    () =>
      positionner(colonnesInitiales(reseau), {
        largeurCarte: CARD_W,
        hauteurCarte: CARD_H,
        ecartX: GAP_X,
        ecartY: GAP_Y,
        marge: PAD,
      }),
    [reseau],
  );

  /** La courbe d'une arête, du bord droit de la source au bord gauche de la cible. */
  const cheminArete = (edge: SuccesTaskEdge): string | null => {
    const from = layout.pos.get(edge.fromTaskId);
    const to = layout.pos.get(edge.toTaskId);
    if (!from || !to) return null;
    const x1 = from.x + CARD_W;
    const y1 = from.y + CARD_H / 2;
    const x2 = to.x - 2;
    const y2 = to.y + CARD_H / 2;
    const dx = Math.max(28, Math.abs(x2 - x1) / 2);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  };

  // À l'ouverture, la première colonne faisable est visible : le graphe
  // défile désormais au lieu de rétrécir, et un projet dont les racines sont
  // faites aurait montré deux colonnes de cartes barrées à 340 px.
  const defilement = useRef<HTMLDivElement>(null);
  const dejaCadre = useRef(false);
  useLayoutEffect(() => {
    if (dejaCadre.current || tasks.length === 0) return;
    dejaCadre.current = true;
    const conteneur = defilement.current;
    if (!conteneur) return;
    let xMin = Number.POSITIVE_INFINITY;
    for (const task of feasible) {
      const p = layout.pos.get(task.id);
      if (p) xMin = Math.min(xMin, p.x);
    }
    if (Number.isFinite(xMin)) conteneur.scrollLeft = Math.max(0, xMin - PAD);
  }, [tasks.length, feasible, layout]);

  useEffect(() => {
    if (!linkMode && !selectedEdge) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        // Consommé : le mini-panneau ne se ferme qu'au second Échap (contrat du 17 sept. 2026, lib.rs lit `defaultPrevented`).
        event.preventDefault();
        setLinkMode(false);
        setLinkFrom(null);
        setSelectedEdge(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [linkMode, selectedEdge]);

  const run = async (action: () => Promise<void>) => {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const keyActivate = (action: () => void) => (event: ReactKeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      event.stopPropagation();
      action();
    }
  };

  const activateCard = (task: SuccesTask) => {
    setSelectedEdge(null);
    if (linkMode) {
      if (!linkFrom) {
        setLinkFrom(task.id);
        return;
      }
      if (linkFrom === task.id) {
        setLinkFrom(null);
        return;
      }
      const from = linkFrom;
      setLinkMode(false);
      setLinkFrom(null);
      void run(() => onLink(from, task.id));
      return;
    }
    onSelect?.(task);
  };

  const toggleTask = (task: SuccesTask) => {
    if (saving) return;
    void run(() => onToggle(task));
  };

  const unlinkSelected = () => {
    if (!selectedEdge || saving) return;
    const { from, to } = selectedEdge;
    void run(async () => {
      await onUnlink(from, to);
      setSelectedEdge(null);
    });
  };

  const addTask = () => {
    const title = newTitle.trim();
    if (!title || saving) return;
    void run(async () => {
      await onCreate({ title });
      setNewTitle('');
    });
  };

  const statusLabel = (status: StatutTache) =>
    status === 'faite' ? 'Faite' : status === 'faisable' ? 'Faisable maintenant' : 'Bloquée';

  const statusColor = (status: StatutTache) =>
    status === 'faite'
      ? 'var(--color-text-secondary)'
      : status === 'faisable'
        ? 'var(--color-accent)'
        : 'var(--color-text-tertiary)';

  return (
    <div className="grid gap-4">
      <section
        className="grid gap-2 rounded-2xl p-4"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          Faisable maintenant : <span style={{ color: 'var(--color-accent)' }}>{feasible.length}</span>
        </p>
        {feasible.length === 0 ? (
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Aucune tâche débloquée pour l’instant.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {feasible.map((task) => (
              <button
                key={task.id}
                type="button"
                onClick={() => onSelect?.(task)}
                className="px-2.5 py-1 rounded-full text-xs cursor-pointer"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <span style={{ color: 'var(--color-accent)' }}>→ </span>
                {task.title}
              </button>
            ))}
          </div>
        )}
      </section>

      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          disabled={saving || tasks.length < 2}
          onClick={() => {
            setError(null);
            setSelectedEdge(null);
            setLinkFrom(null);
            setLinkMode((value) => !value);
          }}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer disabled:opacity-50"
          style={
            linkMode
              ? { background: 'var(--color-accent)', color: 'var(--color-on-accent)' }
              : { border: '1px solid var(--color-border)', color: 'var(--color-text)' }
          }
        >
          {saving ? <Loader2 size={15} className="animate-spin" /> : <Link2 size={15} />}
          {linkMode ? 'Annuler la liaison' : 'Relier'}
        </button>
        {linkMode && (
          <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {linkFrom
              ? 'Cliquez la tâche à débloquer (cible). Échap pour annuler.'
              : 'Cliquez la tâche source. Échap pour annuler.'}
          </span>
        )}
      </div>

      {error && (
        <p className="text-xs" role="alert" style={{ color: DANGER }}>
          {error}
        </p>
      )}

      {tasks.length === 0 ? (
        <div
          className="rounded-2xl py-12 text-center"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <p className="font-medium" style={{ color: 'var(--color-text)' }}>
            Aucune tâche dans le réseau
          </p>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
            Ajoutez une première tâche ci-dessous, puis reliez-les avec « Relier ».
          </p>
        </div>
      ) : (
        <div
          ref={defilement}
          className="rounded-2xl p-2 overflow-x-auto"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          {/* Le canevas prend sa largeur RÉELLE en pixels : à 340 px il défile,
              il ne rétrécit plus. Les cartes sont posées en absolu aux
              positions de `positionner`, à taille fixe (`overflow-hidden`,
              titre replié sur deux lignes) : la géométrie des arêtes est donc
              celle du layout, sans mesure du DOM — une carte ne peut pas
              grandir sans que la disposition le sache. */}
          <div
            role="group"
            aria-label="Réseau des tâches reliées par « débloque »"
            className="relative isolate"
            style={{ width: layout.largeur, height: layout.hauteur }}
            onClick={() => setSelectedEdge(null)}
          >
            <svg
              className="absolute inset-0 -z-10 pointer-events-none"
              width={layout.largeur}
              height={layout.hauteur}
              viewBox={`0 0 ${layout.largeur} ${layout.hauteur}`}
              aria-hidden="true"
            >
              <defs>
                <marker
                  id="nv-arrow-border"
                  viewBox="0 0 8 8"
                  refX="7"
                  refY="4"
                  markerWidth="8"
                  markerHeight="8"
                  orient="auto-start-reverse"
                >
                  <path d="M0,0 L8,4 L0,8 Z" fill="var(--color-border)" />
                </marker>
                <marker
                  id="nv-arrow-accent"
                  viewBox="0 0 8 8"
                  refX="7"
                  refY="4"
                  markerWidth="8"
                  markerHeight="8"
                  orient="auto-start-reverse"
                >
                  <path d="M0,0 L8,4 L0,8 Z" fill="var(--color-accent)" />
                </marker>
              </defs>
              {visibleEdges.map((edge) => {
                const d = cheminArete(edge);
                const fromTask = byId.get(edge.fromTaskId);
                if (!d || !fromTask) return null;
                const waiting = !fromTask.done;
                const isSelected =
                  selectedEdge?.from === edge.fromTaskId && selectedEdge?.to === edge.toTaskId;
                return (
                  <path
                    key={`${edge.fromTaskId}->${edge.toTaskId}`}
                    className="reseau-estompable"
                    d={d}
                    fill="none"
                    stroke={waiting ? 'var(--color-accent)' : 'var(--color-border)'}
                    strokeWidth={isSelected ? 2.5 : 1.5}
                    markerEnd={`url(#${waiting ? 'nv-arrow-accent' : 'nv-arrow-border'})`}
                    style={{ opacity: estompe(edge.fromTaskId, edge.toTaskId) ? 0.3 : 1 }}
                  />
                );
              })}
            </svg>

            {tasks.map((task) => {
              const p = layout.pos.get(task.id);
              if (!p) return null;
              const status = statusById.get(task.id) ?? 'faisable';
              const isLinkSource = linkFrom === task.id;
              const isFocused = focusedId === task.id;
              const highlighted = isLinkSource || isFocused;
              return (
                <CadreVitre
                  compact
                  key={task.id}
                  className="reseau-carte reseau-estompable rounded-xl p-2.5 flex items-start gap-2 overflow-hidden"
                  data-statut={status}
                  // `position` en inline : `.composer-glass { position: relative }`
                  // (ComposerGlass.css, hors couche) l'emporte sur l'utilitaire
                  // `absolute` de Tailwind (couche utilities) — les cartes
                  // s'empilaient en flux, décalées de leur `left/top`.
                  style={{
                    position: 'absolute',
                    left: p.x,
                    top: p.y,
                    width: CARD_W,
                    height: CARD_H,
                    background: 'var(--color-surface)',
                    border: `1px solid ${
                      highlighted || status === 'faisable' ? 'var(--color-accent)' : 'var(--color-border)'
                    }`,
                    borderWidth: highlighted ? 2 : undefined,
                    borderStyle: isLinkSource ? 'dashed' : undefined,
                    opacity: estompe(task.id) ? 0.3 : task.done ? 0.72 : 1,
                  }}
                >
                  <button
                    type="button"
                    disabled={saving}
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleTask(task);
                    }}
                    aria-label={task.done ? `Rouvrir « ${task.title} »` : `Terminer « ${task.title} »`}
                    className="mt-0.5 size-5 rounded-full flex items-center justify-center cursor-pointer shrink-0 disabled:opacity-50"
                    // Le glyphe d'état par la forme, et la coche : plein = faite,
                    // cerclé = faisable, pointillé = bloquée.
                    style={{
                      border: `1.5px ${status === 'bloquee' ? 'dashed' : 'solid'} ${
                        task.done || status === 'faisable' ? 'var(--color-accent)' : 'var(--color-border)'
                      }`,
                      background: task.done ? 'var(--color-accent)' : 'transparent',
                      color: 'var(--color-on-accent)',
                    }}
                  >
                    {task.done && <Check size={12} />}
                  </button>
                  <button
                    type="button"
                    onClick={() => activateCard(task)}
                    onFocus={() => setFocusedId(task.id)}
                    onBlur={() => setFocusedId(null)}
                    aria-label={`${task.title} — ${statusLabel(status)}${
                      linkMode ? (linkFrom ? '. Choisir comme cible' : '. Choisir comme source') : ''
                    }`}
                    title={task.title}
                    className="flex-1 min-w-0 text-left cursor-pointer grid gap-0.5 outline-none"
                  >
                    <span
                      className="text-[13px] font-semibold leading-[1.3] line-clamp-2 break-words"
                      style={{
                        color: 'var(--color-text)',
                        textDecoration: task.done ? 'line-through' : undefined,
                      }}
                    >
                      {task.title}
                    </span>
                    <span className="text-[11px] leading-none truncate" style={{ color: statusColor(status) }}>
                      {statusLabel(status)}
                    </span>
                  </button>
                </CadreVitre>
              );
            })}

            {/* Au-dessus des cartes, les arêtes cliquables : un trait invisible de
                14 px qui n'attrape que sa propre épaisseur, et le « × » de
                suppression quand une arête est choisie. */}
            <svg
              className="absolute inset-0 pointer-events-none"
              width={layout.largeur}
              height={layout.hauteur}
              viewBox={`0 0 ${layout.largeur} ${layout.hauteur}`}
            >
              {visibleEdges.map((edge) => {
                const d = cheminArete(edge);
                const fromTask = byId.get(edge.fromTaskId);
                const toTask = byId.get(edge.toTaskId);
                if (!d || !fromTask || !toTask) return null;
                return (
                  <path
                    key={`${edge.fromTaskId}->${edge.toTaskId}`}
                    d={d}
                    fill="none"
                    stroke="transparent"
                    strokeWidth={14}
                    role="button"
                    tabIndex={0}
                    aria-label={`Lien : « ${fromTask.title} » débloque « ${toTask.title} ». Sélectionner pour supprimer.`}
                    style={{ cursor: 'pointer', outline: 'none', pointerEvents: 'stroke' }}
                    onClick={(event: ReactMouseEvent<SVGPathElement>) => {
                      event.stopPropagation();
                      setSelectedEdge({ from: edge.fromTaskId, to: edge.toTaskId });
                    }}
                    onKeyDown={keyActivate(() =>
                      setSelectedEdge({ from: edge.fromTaskId, to: edge.toTaskId }),
                    )}
                  />
                );
              })}

              {selectedEdge &&
                (() => {
                  const from = layout.pos.get(selectedEdge.from);
                  const to = layout.pos.get(selectedEdge.to);
                  if (!from || !to) return null;
                  const mx = (from.x + CARD_W + to.x - 2) / 2;
                  const my = (from.y + CARD_H / 2 + to.y + CARD_H / 2) / 2;
                  return (
                    <g
                      transform={`translate(${mx} ${my})`}
                      role="button"
                      tabIndex={0}
                      aria-label="Supprimer ce lien"
                      style={{ cursor: 'pointer', outline: 'none', pointerEvents: 'all' }}
                      onClick={(event: ReactMouseEvent<SVGGElement>) => {
                        event.stopPropagation();
                        unlinkSelected();
                      }}
                      onKeyDown={keyActivate(unlinkSelected)}
                    >
                      <circle r={11} fill="var(--color-surface)" stroke={DANGER} strokeWidth={1.5} />
                      <text
                        textAnchor="middle"
                        dominantBaseline="central"
                        fontSize={14}
                        fontWeight={600}
                        fill={DANGER}
                      >
                        ×
                      </text>
                    </g>
                  );
                })()}
            </svg>
          </div>
        </div>
      )}

      <section
        className="flex gap-2 rounded-2xl p-3"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <input
          value={newTitle}
          onChange={(event) => setNewTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') addTask();
          }}
          placeholder="+ Tâche : titre…"
          maxLength={200}
          aria-label="Titre de la nouvelle tâche"
          className="flex-1 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
        />
        <button
          type="button"
          disabled={!newTitle.trim() || saving}
          onClick={addTask}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
          style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
        >
          {saving ? <Loader2 size={15} className="animate-spin" /> : <CirclePlus size={15} />}
          Ajouter
        </button>
      </section>
    </div>
  );
}
