import { CadreVitre } from '../../components/Glass/CadreVitre';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  BriefcaseBusiness,
  CalendarClock,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Minus,
  MoreHorizontal,
  NotebookPen,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react';
import { useConfirm } from '../../components/ConfirmDialog';
import { CarnetDeTache, carnetRempli } from './CarnetDeTache';
import { SIGNES_PRIORITE, monogrammeProjet } from './carteTache';
import { EmojiPicker } from './EmojiPicker';
import { joursDeRetard, libelleEcheance } from './echeances';
import {
  EXEMPLES_EXPRESSION,
  EXPRESSION_MAX,
  chipsAmbiguite,
  expressionDeReport,
  lireRefusDeReport,
  proposeDecoupage,
  type RefusDeReport,
} from './report';
import type { SuccesPriority, SuccesProject, SuccesSubtask, SuccesTask } from './types';
import {
  loadSubtaskExpanded,
  loadTaskSubtasksOpen,
  saveSubtaskExpanded,
  saveTaskSubtasksOpen,
} from './uiPrefs';

/**
 * Le signe de priorité devant le titre : `!!!` urgent, `!!` haute, rien pour
 * la priorité par défaut. La pastille-mot « Normale » (~60 px) et le point
 * coloré sous sm signalaient 90 % des cartes, donc aucune (expertise de la
 * page Tâches, 17 sept. 2026). `reserve` garde la largeur du signe même
 * absent, pour que les titres d'une liste s'alignent ; la Semaine, à 180 px
 * la colonne, ne peut pas se l'offrir.
 *
 * `terminee` éteint la teinte : une tâche faite gardait son « !!! » rouge
 * vif devant un titre gris barré, alors que sa date, elle, cessait d'être
 * en retard — le signal le plus fort de la page sur ce qui est fini (revue
 * du 17 sept. 2026, défaut 19). `signe-priorite` sort le span de l'inversion
 * de bloc Ardéchine (voir index.css) ; `mr-1` dans les deux cas — la réserve
 * seule laissait le signe coller au titre (défaut 17).
 */
export function SignePriorite({
  priority,
  reserve = true,
  terminee = false,
}: { priority: SuccesPriority; reserve?: boolean; terminee?: boolean }) {
  const signe = SIGNES_PRIORITE[priority];
  if (!signe.signe) {
    return reserve ? <span aria-hidden className="inline-block min-w-[1.4em] mr-1" /> : null;
  }
  return (
    <span
      role="img"
      aria-label={signe.libelle}
      title={signe.libelle}
      className={`signe-priorite inline-block font-semibold mr-1 ${reserve ? 'min-w-[1.4em]' : ''}`}
      style={{ color: terminee ? 'var(--color-text-tertiary)' : signe.couleur }}
    >
      {signe.signe}
    </span>
  );
}

/**
 * Le projet, sans mot : le liseré gauche (`.liseret-projet` sur le conteneur
 * de contenu, jamais sur la carte vitrée) prend sa couleur, et en Ardéchine,
 * où toute teinte se replie sur l'encre, ce monogramme dans une boîte bordée
 * le remplace — `display: none` partout ailleurs (17 sept. 2026).
 */
export function MonogrammeProjet({ project }: { project: SuccesProject | undefined }) {
  if (!project) return null;
  return (
    <span aria-hidden className="monogramme-projet mr-1.5 align-middle" title={project.name}>
      {monogrammeProjet(project.name)}
    </span>
  );
}

/** Les variables CSS du liseré — `gauche` est la marge de la carte, en négatif. */
export function styleLiseret(project: SuccesProject | undefined, gauche: string): React.CSSProperties | undefined {
  if (!project) return undefined;
  return {
    '--liseret-couleur': project.color || 'var(--color-border)',
    '--liseret-gauche': gauche,
  } as React.CSSProperties;
}

// `journal` : le carnet, distinct de `notes` — ce qu'on écrit PENDANT la
// tâche, depuis la carte où on la fait (17 sept. 2026).
export type SuccesTaskPatch = Partial<
  Pick<SuccesTask, 'title' | 'date' | 'time' | 'priority' | 'notes' | 'journal' | 'projectId' | 'category' | 'emoji'>
>;

function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function shiftIsoDate(iso: string | undefined, days: number) {
  const base = iso ? new Date(`${iso}T12:00:00`) : new Date();
  if (Number.isNaN(base.getTime())) {
    const fallback = new Date();
    fallback.setDate(fallback.getDate() + days);
    return localIsoDate(fallback);
  }
  base.setDate(base.getDate() + days);
  return localIsoDate(base);
}

interface Props {
  task: SuccesTask;
  projects?: SuccesProject[];
  onToggleTask: (task: SuccesTask) => Promise<void>;
  onToggleSubtask: (task: SuccesTask, subtask: SuccesSubtask) => Promise<void>;
  /**
   * Même contrat que `onUpdate` : `null` dit « rien n'a été enregistré », et
   * la carte garde alors le titre tapé et son champ ouvert. Elle les vidait
   * après tout `await`, réussi ou non — le brouillon partait avec l'échec,
   * seul le toast le disait (revue du 17 sept. 2026, défaut 11).
   */
  onAddSubtask: (task: SuccesTask, title: string, parentId?: string) => Promise<SuccesTask | null | void>;
  onDeleteSubtask?: (task: SuccesTask, subtask: SuccesSubtask) => Promise<void>;
  /**
   * Rend la ligne que le serveur a renvoyée, ou `null` si rien n'a été
   * enregistré — la carte garde alors son brouillon ouvert. Un `void` vaut
   * « la page a rechargé depuis le serveur » pour le formulaire d'édition,
   * qui a son toast ; le carnet, lui, ne s'en contente pas : voir `onJournal`.
   */
  onUpdate?: (task: SuccesTask, patch: SuccesTaskPatch) => Promise<SuccesTask | null | void>;
  /**
   * Le carnet, sur une prop DÉDIÉE : la ligne serveur, ou `null`. Le bouton
   * Carnet n'existe que si la page la fournit. Il s'ouvrait dès `onUpdate`,
   * donc aussi dans Projets, dont le `refreshAfter` avale l'erreur et rend
   * `undefined` : le carnet y disait « Enregistré » sur un PATCH refusé, et
   * chaque pause de 700 ms y déclenchait un toast et un rechargement complet
   * (revue du 17 sept. 2026, défauts 1 et 15). Rien d'autre qu'une ligne
   * n'est un succès (§100) — `undefined` non plus.
   */
  onJournal?: (task: SuccesTask, journal: string) => Promise<SuccesTask | null>;
  /**
   * `date` est une ISO ou une expression (« lundi », « dans 3 jours ») que
   * le serveur résout. Doit RELANCER `DateAmbigueError` et `DateInconnueError`
   * : la carte y répond (chips datées, message sous le champ).
   */
  onReschedule?: (task: SuccesTask, date: string) => Promise<SuccesTask | null | void>;
  onAssignProject?: (task: SuccesTask, projectId: string) => Promise<void>;
  onDelete?: (task: SuccesTask) => Promise<void>;
  /**
   * Un jeton qui change à chaque « Découper » venu de la page (le toast du
   * warning « reportée 4× ») : la carte ouvre son champ « Nouvelle
   * sous-tâche », puis le signale par `onDecoupageOuvert`, et la page remet
   * le jeton à `null`. Il restait posé pour toute la vie de la page, et la
   * liste entière se remonte à chaque `load()` (recherche, filtre, retour de
   * focus) : la carte neuve voyait un jeton « nouveau », rouvrait le champ
   * et lui volait le focus — les lettres tapées dans Rechercher tombaient
   * dans « Nouvelle sous-tâche » (revue du 17 sept. 2026, défaut 2).
   */
  decoupage?: number;
  onDecoupageOuvert?: () => void;
  compact?: boolean;
  vitre?: boolean;
}

function SubtaskRow({
  task,
  subtask,
  depth,
  onToggle,
  onAdd,
  onDelete,
}: {
  task: SuccesTask;
  subtask: SuccesSubtask;
  depth: number;
  onToggle: Props['onToggleSubtask'];
  onAdd: Props['onAddSubtask'];
  onDelete?: Props['onDeleteSubtask'];
}) {
  const confirm = useConfirm();
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');
  const [expanded, setExpanded] = useState(() => loadSubtaskExpanded(subtask.id, true));

  const submit = async () => {
    const clean = title.trim();
    if (!clean) return;
    const ligne = await onAdd(task, clean, subtask.id);
    // `null` : rien d'enregistré, le titre reste dans son champ (défaut 11).
    if (ligne === null) return;
    setTitle('');
    setAdding(false);
    setExpanded(true);
    saveSubtaskExpanded(subtask.id, true);
  };

  const remove = async () => {
    if (!onDelete) return;
    const hasChildren = subtask.children.length > 0;
    const confirmed = await confirm({
      title: 'Supprimer cette sous-tâche ?',
      description: hasChildren
        ? `« ${subtask.title || 'Sous-tâche'} » et ses étapes internes seront supprimées.`
        : `« ${subtask.title || 'Sous-tâche'} » sera supprimée définitivement.`,
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    await onDelete(task, subtask);
  };

  const toggleExpanded = () => {
    setExpanded((value) => {
      const next = !value;
      saveSubtaskExpanded(subtask.id, next);
      return next;
    });
  };

  return (
    <div style={{ marginLeft: depth ? 18 : 0 }}>
      <div className="group flex items-center gap-2 min-h-8 py-1">
        {subtask.children.length > 0 ? (
          <button
            type="button"
            onClick={toggleExpanded}
            className="p-0.5 rounded cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)' }}
            aria-label={expanded ? 'Réduire' : 'Développer'}
          >
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        ) : <span className="w-4" />}
        <button
          type="button"
          onClick={() => void onToggle(task, subtask)}
          className="size-5 rounded-md flex items-center justify-center cursor-pointer transition-colors"
          style={{
            border: `1px solid ${subtask.done ? 'var(--color-accent)' : 'var(--color-border)'}`,
            background: subtask.done ? 'var(--color-accent)' : 'transparent',
            color: '#fff',
          }}
          aria-label={subtask.done ? 'Rouvrir la sous-tâche' : 'Terminer la sous-tâche'}
        >
          {subtask.done && <Check size={12} />}
        </button>
        <span
          className="flex-1 min-w-0 text-sm break-words"
          style={{
            color: subtask.done ? 'var(--color-text-tertiary)' : 'var(--color-text-secondary)',
            textDecoration: subtask.done ? 'line-through' : 'none',
          }}
        >
          {subtask.title || 'Sous-tâche sans titre'}
        </span>
        {/* Le mini-panneau est un NSPanel non activant : le survol n'y
            arrive plus dès qu'une autre app passe devant. Un « + » à
            `opacity-0` y était invisible et introuvable, le « − » restait
            fantôme (audit du 16 sept. 2026). Le défaut est un MODE, pas une
            largeur — le préréglage L du panneau fait exactement 640 px, où
            `max-sm:` s'éteint — d'où `compact:opacity-100` (et `max-sm:`
            pour le tactile et les fenêtres étroites) : §82, rien ne devient
            inatteignable. */}
        <div className="flex items-center gap-0.5 shrink-0">
          {onDelete ? (
            <button
              type="button"
              onClick={() => void remove()}
              className="p-1 rounded cursor-pointer opacity-55 hover:opacity-100 max-sm:opacity-100 compact:opacity-100 transition-opacity"
              style={{ color: 'var(--color-error)' }}
              aria-label="Supprimer la sous-tâche"
              title="Supprimer"
            >
              <Minus size={13} strokeWidth={2.25} />
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setAdding((value) => !value)}
            className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 max-sm:opacity-100 compact:opacity-100 p-1 rounded cursor-pointer transition-opacity"
            style={{ color: 'var(--color-text-tertiary)' }}
            title="Ajouter une étape à l'intérieur"
            aria-label="Ajouter une étape à l'intérieur"
          >
            <Plus size={13} />
          </button>
        </div>
      </div>
      {adding && (
        <div className="flex gap-2 ml-9 mb-2">
          <input
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void submit();
              if (event.key === 'Escape') setAdding(false);
            }}
            placeholder="Nouvelle étape…"
            className="flex-1 min-w-0 bg-transparent text-sm outline-none px-2 py-1 rounded-md"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
          />
        </div>
      )}
      {expanded && subtask.children.map((child) => (
        <SubtaskRow
          key={child.id}
          task={task}
          subtask={child}
          depth={depth + 1}
          onToggle={onToggle}
          onAdd={onAdd}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}

/** Hauteur d'une entrée du menu « ⋯ » (py-2 + une ligne de 20 px) et ce que
    prennent le cadre, le `py-1` et la marge de 4 px — pour décider du
    retournement. La constante de 130 px était calée sur trois entrées ;
    le Carnet en fait une quatrième (17 sept. 2026). */
const MENU_ACTIONS_ENTREE = 36;
const MENU_ACTIONS_CADRE = 22;

/**
 * Les actions secondaires de la carte, regroupées sous « ⋯ » en étroit.
 *
 * À 420 px, quatre boutons toujours visibles (~110 px, `shrink-0`) ne
 * laissaient que ~180 px au titre (audit du mini-panneau, 16 sept. 2026).
 *
 * Le menu est un PORTAIL `fixed` sur body, jamais un `absolute` dans la
 * carte : une carte vitrée (`backdrop-filter`) est un contexte d'empilement,
 * et un menu `z-50` posé dedans était peint SOUS la carte suivante — le
 * verre à 97 % de transparence le laissait voir, mais le clic sur
 * « Supprimer » atteignait l'autre carte (revue du 16 sept. 2026, reproduit
 * avec les trois feuilles CSS du dépôt). Modèle ChipMenu : position calculée
 * depuis le rectangle du bouton, retourné vers le haut quand la place
 * manque, borné aux bords, refermé au `resize` et au défilement — le panneau
 * se redimensionne en continu, une ancre mesurée devient fausse.
 */
function MenuActions({
  entrees,
}: {
  entrees: { id: string; label: string; icon: React.ReactNode; color?: string; onSelect: () => void }[];
}) {
  const [ancre, setAncre] = useState<DOMRect | null>(null);
  const boutonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const ouvert = ancre !== null;

  useEffect(() => {
    if (!ouvert) return;
    const onPointer = (event: MouseEvent) => {
      const cible = event.target as Node;
      // Le bouton n'est pas « dehors » : fermer ici ferait la course avec
      // son propre onClick, qui rouvrirait un menu déjà fermé.
      if (boutonRef.current?.contains(cible)) return;
      if (!menuRef.current?.contains(cible)) setAncre(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAncre(null);
    };
    const fermer = () => setAncre(null);
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', fermer);
    // Capture : le défilement se produit dans le conteneur de la page, pas
    // sur window ; un menu `fixed` resterait planté pendant que sa carte
    // s'en va.
    document.addEventListener('scroll', fermer, true);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', fermer);
      document.removeEventListener('scroll', fermer, true);
    };
  }, [ouvert]);

  const basculer = () => {
    if (ancre) {
      setAncre(null);
      return;
    }
    const rect = boutonRef.current?.getBoundingClientRect();
    if (rect) setAncre(rect);
  };

  let menu: React.ReactNode = null;
  if (ancre) {
    const largeur = Math.min(176, Math.max(0, window.innerWidth - 16));
    const left = Math.min(Math.max(8, ancre.right - largeur), window.innerWidth - largeur - 8);
    const hauteur = entrees.length * MENU_ACTIONS_ENTREE + MENU_ACTIONS_CADRE;
    const versLeHaut = ancre.bottom + hauteur > window.innerHeight && ancre.top > hauteur;
    const position = versLeHaut
      ? { bottom: window.innerHeight - ancre.top + 4 }
      : { top: ancre.bottom + 4 };
    menu = createPortal(
      <div
        ref={menuRef}
        role="menu"
        className="fixed z-50 max-h-[min(40vh,240px)] overflow-y-auto rounded-xl py-1 shadow-lg"
        style={{
          ...position,
          left,
          width: largeur,
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
        }}
      >
        {entrees.map((entree) => (
          <button
            key={entree.id}
            type="button"
            role="menuitem"
            onClick={() => {
              setAncre(null);
              entree.onSelect();
            }}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left cursor-pointer"
            style={{ color: entree.color ?? 'var(--color-text)' }}
          >
            {entree.icon}
            {entree.label}
          </button>
        ))}
      </div>,
      document.body,
    );
  }

  return (
    // `compact:block` : dans le mini-panneau, le « ⋯ » vit à toute largeur
    // (et les actions inline s'y cachent) — un panneau étiré à 640 px n'a
    // pas plus de place pour cinq icônes que pour quatre (17 sept. 2026).
    <div className="sm:hidden compact:block">
      <button
        ref={boutonRef}
        type="button"
        onClick={basculer}
        className="p-1.5 rounded-lg cursor-pointer"
        style={{ color: ouvert ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }}
        aria-label="Autres actions"
        aria-haspopup="menu"
        aria-expanded={ouvert}
      >
        <MoreHorizontal size={16} />
      </button>
      {menu}
    </div>
  );
}

function draftFromTask(task: SuccesTask) {
  return {
    title: task.title,
    date: task.date || '',
    time: task.time || '',
    priority: task.priority,
    notes: task.notes || '',
    projectId: task.projectId || '',
    category: task.category || '',
    emoji: task.emoji || '',
  };
}

export function TaskCard({
  task,
  projects = [],
  onToggleTask,
  onToggleSubtask,
  onAddSubtask,
  onDeleteSubtask,
  onUpdate,
  onJournal,
  onReschedule,
  onAssignProject,
  onDelete,
  decoupage,
  onDecoupageOuvert,
  compact,
  vitre = false,
}: Props) {
  const confirm = useConfirm();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(false);
  const [rescheduling, setRescheduling] = useState(false);
  const [saving, setSaving] = useState(false);
  const [customDate, setCustomDate] = useState(task.date || localIsoDate());
  // L'expression en langage naturel de la boîte Reporter, et ce que le
  // serveur lui a répondu : deux jours à choisir, ou « pas reconnu ».
  const [expression, setExpression] = useState('');
  const [refus, setRefus] = useState<RefusDeReport | null>(null);
  const [carnetOuvert, setCarnetOuvert] = useState(false);
  const [subtaskTitle, setSubtaskTitle] = useState('');
  const [draft, setDraft] = useState(() => draftFromTask(task));
  const [subtasksOpen, setSubtasksOpen] = useState(() => loadTaskSubtasksOpen(task.id, true));
  const project = projects.find((item) => item.id === task.projectId);
  const hasSubtasks = task.subtasks.length > 0;
  // Une tâche terminée n'est jamais en retard : sa date passée redevient
  // une date (expertise de la page Tâches, 17 sept. 2026).
  const aujourdHui = localIsoDate();
  const enRetard = !task.done && joursDeRetard(task.date, aujourdHui) > 0;

  useEffect(() => {
    if (!editing) setDraft(draftFromTask(task));
    if (!rescheduling) {
      setCustomDate(task.date || localIsoDate());
      setExpression('');
      setRefus(null);
    }
  }, [task, editing, rescheduling]);

  useEffect(() => {
    setSubtasksOpen(loadTaskSubtasksOpen(task.id, true));
  }, [task.id]);

  /** Ouvre le champ « Nouvelle sous-tâche » : la réponse à « Reportée 4×, la découper ? ». */
  const ouvrirDecoupage = () => {
    setRescheduling(false);
    setEditing(false);
    setAdding(true);
    setSubtasksOpen(true);
    saveTaskSubtasksOpen(task.id, true);
  };

  // Le jeton `decoupage` vient du toast de la page : chaque valeur nouvelle
  // ouvre le champ, y compris au montage — depuis la Semaine, la page bascule
  // en Liste et la carte naît avec le jeton déjà posé. Puis il est CONSOMMÉ
  // (`onDecoupageOuvert` → la page le remet à null) : plus de ref d'instance
  // qui « voyait » le jeton pour la première fois à chaque remontage de la
  // liste (défaut 2). Par un ref pour le rappel, pour ne pas relancer l'effet
  // quand la page en redonne une fermeture neuve à chaque rendu.
  const acquitterDecoupage = useRef(onDecoupageOuvert);
  acquitterDecoupage.current = onDecoupageOuvert;
  useEffect(() => {
    if (decoupage === undefined) return;
    ouvrirDecoupage();
    acquitterDecoupage.current?.();
  }, [decoupage]); // eslint-disable-line react-hooks/exhaustive-deps -- `ouvrirDecoupage` ne lit que task.id

  const submitSubtask = async () => {
    const title = subtaskTitle.trim();
    if (!title) return;
    const ligne = await onAddSubtask(task, title);
    // `null` : rien d'enregistré, le titre reste dans son champ (défaut 11).
    if (ligne === null) return;
    setSubtaskTitle('');
    setAdding(false);
    setSubtasksOpen(true);
    saveTaskSubtasksOpen(task.id, true);
  };

  const toggleSubtasksOpen = () => {
    setSubtasksOpen((value) => {
      const next = !value;
      saveTaskSubtasksOpen(task.id, next);
      return next;
    });
  };

  /**
   * `date` : une ISO (chips, calendrier) ou l'expression tapée telle quelle
   * — le serveur la résout. Ses deux refus reviennent ici et restent dans
   * la boîte, qui ne se ferme pas : deux chips datées pour « lundi
   * prochain », un mot sous le champ pour ce qu'il n'a pas reconnu. Tout
   * autre échec a déjà son toast, posé par la page.
   */
  const moveTo = async (date: string) => {
    if (!onReschedule) return;
    setSaving(true);
    setRefus(null);
    try {
      // `null` = la page a essayé et le serveur a refusé (elle l'a dit en
      // toast) : la boîte reste ouverte avec la date choisie — se fermer
      // comme un succès la perdait (contre-revue du 17 sept. 2026).
      // `void` = la page a rechargé (Planificateur, Projets) : succès.
      const ligne = await onReschedule(task, date);
      if (ligne !== null) setRescheduling(false);
    } catch (error) {
      const lu = lireRefusDeReport(error);
      if (!lu) return;
      setRefus(lu);
    } finally {
      setSaving(false);
    }
  };

  const envoyerExpression = () => {
    const propre = expressionDeReport(expression);
    if (!propre) return;
    void moveTo(propre);
  };

  const saveEdit = async () => {
    if (!onUpdate) return;
    const cleanTitle = draft.title.trim();
    if (!cleanTitle) return;
    setSaving(true);
    try {
      const patch: SuccesTaskPatch = {};
      if (cleanTitle !== task.title) patch.title = cleanTitle;
      if (draft.date !== (task.date || '')) patch.date = draft.date;
      if (draft.time !== (task.time || '')) patch.time = draft.time;
      if (draft.priority !== task.priority) patch.priority = draft.priority;
      if (draft.notes !== (task.notes || '')) patch.notes = draft.notes;
      if (draft.projectId !== (task.projectId || '')) patch.projectId = draft.projectId;
      if (draft.category !== (task.category || '')) patch.category = draft.category;
      if (draft.emoji !== (task.emoji || '')) patch.emoji = draft.emoji;
      if (Object.keys(patch).length) {
        const ligne = await onUpdate(task, patch);
        // `null` : rien d'enregistré. Fermer remettait le brouillon sur la
        // ligne revenue à l'ancien état — titre, notes, date : perdus, seul
        // le toast le disait (revue du 17 sept. 2026, défaut 11).
        if (ligne === null) return;
      }
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const cancelEdit = async () => {
    const baseline = draftFromTask(task);
    const dirty =
      draft.title !== baseline.title ||
      draft.date !== baseline.date ||
      draft.time !== baseline.time ||
      draft.priority !== baseline.priority ||
      draft.notes !== baseline.notes ||
      draft.projectId !== baseline.projectId ||
      draft.category !== baseline.category ||
      draft.emoji !== baseline.emoji;
    if (dirty) {
      const confirmed = await confirm({
        title: 'Annuler les modifications ?',
        description: 'Les changements non enregistrés seront perdus.',
        confirmLabel: 'Annuler',
        keepLabel: 'Garder',
        tone: 'warning',
      });
      if (!confirmed) return;
    }
    setEditing(false);
  };

  const cancelReschedule = async () => {
    if (customDate !== (task.date || localIsoDate()) || expression.trim()) {
      const confirmed = await confirm({
        title: 'Annuler le report ?',
        description: 'La nouvelle date saisie ne sera pas appliquée.',
        confirmLabel: 'Annuler',
        keepLabel: 'Garder',
        tone: 'warning',
      });
      if (!confirmed) return;
    }
    setRescheduling(false);
  };

  if (editing && onUpdate) {
    return (
      <CadreVitre as="article" actif={vitre}
        className="rounded-2xl p-4 grid gap-3"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}
      >
        {/* Le même sélecteur qu'Habitudes et Finances : un champ texte de
            8 caractères obligeait à trouver l'emoji ailleurs et à le coller
            (expertise du 17 sept. 2026, cohérence entre les pages). */}
        <div className="flex items-stretch gap-2">
          <div className="w-14 shrink-0">
            <EmojiPicker
              value={draft.emoji}
              onChange={(emoji) => setDraft({ ...draft, emoji })}
              aria-label="Emoji de la tâche"
              optionnel
            />
          </div>
          <input
            autoFocus
            value={draft.title}
            onChange={(event) => setDraft({ ...draft, title: event.target.value })}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) void saveEdit();
              if (event.key === 'Escape') setEditing(false);
            }}
            maxLength={200}
            className="flex-1 rounded-xl px-3 py-2 font-medium bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            aria-label="Titre"
          />
        </div>
        {/* Même plan que le formulaire de création : par paires dès 340 px,
            `min-w-0` contre la largeur intrinsèque des <input type=date>
            WebKit (16 sept. 2026). */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          <input
            type="date"
            value={draft.date}
            onChange={(event) => setDraft({ ...draft, date: event.target.value })}
            className="min-w-0 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            aria-label="Date"
          />
          <input
            type="time"
            value={draft.time}
            onChange={(event) => setDraft({ ...draft, time: event.target.value })}
            className="min-w-0 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            aria-label="Heure"
          />
          <select
            value={draft.priority}
            onChange={(event) => setDraft({ ...draft, priority: event.target.value as SuccesPriority })}
            className="min-w-0 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            aria-label="Priorité"
          >
            <option value="low">Priorité basse</option>
            <option value="medium">Priorité normale</option>
            <option value="high">Priorité haute</option>
            <option value="urgent">Priorité urgente</option>
          </select>
          <select
            value={draft.projectId}
            onChange={(event) => setDraft({ ...draft, projectId: event.target.value })}
            className="min-w-0 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            aria-label="Projet"
          >
            <option value="">Sans projet</option>
            {projects.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        </div>
        <input
          value={draft.category}
          onChange={(event) => setDraft({ ...draft, category: event.target.value })}
          placeholder="Catégorie (facultatif)"
          maxLength={100}
          className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        />
        <textarea
          value={draft.notes}
          onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
          placeholder="Notes…"
          maxLength={2000}
          rows={3}
          className="resize-none rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => void cancelEdit()}
            className="flex items-center gap-1.5 px-3 py-2 text-sm cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <X size={14} /> Annuler
          </button>
          <button
            type="button"
            disabled={!draft.title.trim() || saving}
            onClick={() => void saveEdit()}
            className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            Enregistrer
          </button>
        </div>
      </CadreVitre>
    );
  }

  const journalEcrit = carnetRempli(task.journal);
  const libelleCarnet = journalEcrit
    ? 'Carnet — des notes vous attendent'
    : 'Carnet — prendre des notes sur cette tâche';

  // Les mêmes actions que les boutons inline, servies par « ⋯ » sous sm et
  // en mode compact.
  const actionsMenu = [
    ...(onReschedule && !task.done
      ? [{
        id: 'reporter',
        label: 'Reporter',
        icon: <CalendarClock size={15} />,
        onSelect: () => { setRescheduling((value) => !value); setEditing(false); },
      }]
      : []),
    ...(onUpdate
      ? [{
        id: 'modifier',
        label: 'Modifier',
        icon: <Pencil size={15} />,
        onSelect: () => { setEditing(true); setRescheduling(false); },
      }]
      : []),
    ...(onJournal
      ? [{
        id: 'carnet',
        label: journalEcrit ? 'Carnet (écrit)' : 'Carnet',
        icon: <NotebookPen size={15} />,
        color: journalEcrit ? 'var(--color-accent)' : undefined,
        onSelect: () => setCarnetOuvert(true),
      }]
      : []),
    ...(onDelete
      ? [{
        id: 'supprimer',
        label: 'Supprimer',
        icon: <Trash2 size={15} />,
        color: 'var(--color-error)',
        onSelect: () => void onDelete(task),
      }]
      : []),
  ];

  return (
    <CadreVitre as="article" actif={vitre}
      className={`rounded-2xl ${compact ? 'p-3' : 'p-4'} transition-colors`}
      style={{
        background: 'var(--color-surface)',
        // La même bordure que BoardCard donne au retard : la Liste ne le
        // disait nulle part (17 sept. 2026). `styleCadreVitre` ne retire que
        // la bordure neutre, celle-ci survit au verre.
        border: `1px solid ${enRetard ? 'color-mix(in srgb, var(--color-error) 45%, var(--color-border))' : 'var(--color-border)'}`,
      }}
    >
      <div
        className={`flex items-start gap-3 ${project ? 'liseret-projet' : ''}`}
        style={styleLiseret(project, compact ? '-8px' : '-10px')}
      >
        <button
          type="button"
          onClick={() => void onToggleTask(task)}
          className="mt-0.5 size-6 rounded-lg flex items-center justify-center shrink-0 cursor-pointer"
          style={{
            border: `1px solid ${task.done ? 'var(--color-accent)' : 'var(--color-border)'}`,
            background: task.done ? 'var(--color-accent)' : 'var(--color-bg-secondary)',
            color: '#fff',
          }}
          aria-label={task.done ? 'Rouvrir la tâche' : 'Terminer la tâche'}
        >
          {task.done && <Check size={14} />}
        </button>
        <div className="flex-1 min-w-0">
          {/* `titre-tache` sort le titre de la règle `.terminal h3` (Press
              Start en capitales, 2-3 lignes par titre) ; la priorité est un
              signe devant lui et la basse s'efface en encre secondaire — la
              pastille-mot et le point sous sm sont partis (17 sept. 2026). */}
          <h3
            className="titre-tache min-w-0 font-medium leading-6 break-words"
            style={{
              color: task.done
                ? 'var(--color-text-tertiary)'
                : task.priority === 'low'
                  ? 'var(--color-text-secondary)'
                  : 'var(--color-text)',
              textDecoration: task.done ? 'line-through' : 'none',
            }}
          >
            <MonogrammeProjet project={project} />
            <SignePriorite priority={task.priority} terminee={task.done} />
            {task.emoji ? `${task.emoji} ` : ''}{task.title}
          </h3>
          {/* Sous sm : date, heure, projet et le compteur de reports restent ;
              catégorie et notes (`max-w-[420px]`, plus large que le panneau)
              reviennent avec la largeur — elles restent en édition.
              L'échéance vient en premier, relative (« Demain », « sam. 19
              sept. ») ou en retard, en rouge et en gras ; l'ISO reste dans
              `title`. En Ardéchine, le mot « retard » et l'inversion de bloc
              portent le signal, jamais la couleur seule (17 sept. 2026). */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {task.date && (
              <span
                className={`flex items-center gap-1 ${enRetard ? 'font-medium' : ''}`}
                style={enRetard ? { color: 'var(--color-error)' } : undefined}
                title={task.date}
              >
                <CalendarDays size={12} />
                {libelleEcheance(task.date, aujourdHui, { terminee: task.done })}
              </span>
            )}
            {task.time && <span className="flex items-center gap-1"><Clock3 size={12} />{task.time}</span>}
            {project && (
              <span className="flex items-center gap-1 min-w-0">
                <BriefcaseBusiness size={12} className="shrink-0" />
                <span className="truncate max-w-[9rem] sm:max-w-none">{project.name}</span>
              </span>
            )}
            {task.category && <span className="hidden sm:inline">{task.category}</span>}
            {/* À partir du quatrième report, la mention devient un bouton vers
                « Nouvelle sous-tâche » : le warning du serveur posait une
                question — « voulez-vous la découper ? » — sans rien pour y
                répondre (§34, 17 sept. 2026). Le soulignement porte le
                signal là où la teinte se replie sur l'encre (Ardéchine). */}
            {task.postponedCount > 0 && (
              proposeDecoupage(task.postponedCount) && !task.done ? (
                <button
                  type="button"
                  onClick={ouvrirDecoupage}
                  className="flex items-center gap-1 underline underline-offset-2 decoration-dotted cursor-pointer"
                  style={{ color: 'var(--color-warning)' }}
                  title="Reportée souvent — la découper en sous-tâches ?"
                  aria-label={`Reportée ${task.postponedCount} fois — découper en sous-tâches`}
                >
                  <CalendarClock size={12} />
                  Reportée {task.postponedCount}× · découper ?
                </button>
              ) : (
                <span className="flex items-center gap-1">
                  <CalendarClock size={12} />
                  Reportée {task.postponedCount}×
                </span>
              )
            )}
            {task.notes && <span className="hidden sm:inline truncate max-w-[420px]">{task.notes}</span>}
          </div>
          {rescheduling && onReschedule && (
            <CadreVitre compact actif={vitre}
              className="mt-3 grid gap-2 rounded-xl p-3"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <p className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>Reporter au…</p>
              {/* Les quatre chips, puis un champ libre : le résolveur du
                  serveur (« lundi », « dans 3 jours », « 21/09/2026 ») n'était
                  atteint que par la voix ; au clic il fallait le calendrier
                  (17 sept. 2026). Entrée envoie l'expression telle quelle ;
                  `min-w-[9rem]` la fait passer à la ligne sous 340 px plutôt
                  que d'écraser les chips. Les exemples du placeholder sont
                  ceux que `dates.py` comprend : « 21 sept » y figurait et
                  rendait 422 à coup sûr (défaut 7). */}
              <div className="flex flex-wrap items-center gap-1.5">
                {[
                  { label: 'Aujourd’hui', date: localIsoDate() },
                  { label: 'Demain', date: shiftIsoDate(undefined, 1) },
                  { label: '+3 jours', date: shiftIsoDate(task.date || undefined, 3) },
                  { label: '+1 semaine', date: shiftIsoDate(task.date || undefined, 7) },
                ].map((option) => (
                  <button
                    key={option.label}
                    type="button"
                    disabled={saving || option.date === task.date}
                    onClick={() => void moveTo(option.date)}
                    className="px-2.5 py-1.5 rounded-lg text-xs cursor-pointer disabled:opacity-40"
                    style={{
                      background: 'var(--color-surface)',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    {option.label}
                  </button>
                ))}
                <input
                  value={expression}
                  onChange={(event) => {
                    setExpression(event.target.value);
                    if (refus) setRefus(null);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      envoyerExpression();
                    }
                    if (event.key === 'Escape') {
                      // Échap efface d'abord ce qui est tapé ; vide, il ferme
                      // la boîte — sans passer par le dialogue « Annuler le
                      // report ? » : monté PENDANT la propagation de ce même
                      // keydown, il s'ouvrait et se refermait sur la même
                      // touche, laissant la boîte et emportant le focus
                      // (contre-revue du 17 sept. 2026).
                      event.preventDefault();
                      event.stopPropagation();
                      if (expression.trim() || refus) {
                        setExpression('');
                        setRefus(null);
                      } else {
                        setRescheduling(false);
                      }
                    }
                  }}
                  disabled={saving}
                  maxLength={EXPRESSION_MAX}
                  size={12}
                  placeholder={EXEMPLES_EXPRESSION}
                  className="flex-1 min-w-0 basis-[9rem] rounded-lg px-2.5 py-1.5 text-xs bg-transparent outline-none disabled:opacity-40"
                  style={{
                    border: `1px solid ${refus?.type === 'inconnue' ? 'var(--color-error)' : 'var(--color-border)'}`,
                    color: 'var(--color-text)',
                  }}
                  aria-label="Reporter à une date en toutes lettres — Entrée pour envoyer"
                  aria-invalid={refus?.type === 'inconnue' || undefined}
                  aria-describedby={refus ? `refus-report-${task.id}` : undefined}
                />
              </div>
              {/* La réponse du serveur, dans la boîte et pas en toast : deux
                  jours à choisir (409 ambiguous_date, ses `options`), ou le
                  mot qu'il n'a pas reconnu (422). */}
              {refus && (
                <div id={`refus-report-${task.id}`} role="status" className="grid gap-1.5 text-xs">
                  <p style={{ color: refus.type === 'inconnue' ? 'var(--color-error)' : 'var(--color-text-secondary)' }}>
                    {refus.type === 'inconnue' ? "Je n'ai pas reconnu cette date." : refus.message}
                  </p>
                  {refus.type === 'ambigue' && (
                    <div className="flex flex-wrap gap-1.5">
                      {chipsAmbiguite(refus.options, aujourdHui).map((chip) => (
                        <button
                          key={chip.date}
                          type="button"
                          disabled={saving}
                          onClick={() => void moveTo(chip.date)}
                          className="px-2.5 py-1.5 rounded-lg text-xs font-medium cursor-pointer disabled:opacity-40"
                          style={{
                            background: 'var(--color-surface)',
                            color: 'var(--color-accent)',
                            border: '1px solid var(--color-accent)',
                          }}
                          title={chip.date}
                        >
                          {chip.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="date"
                  value={customDate}
                  onChange={(event) => setCustomDate(event.target.value)}
                  className="rounded-lg px-2 py-1.5 text-xs bg-transparent outline-none"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                />
                <button
                  type="button"
                  disabled={!customDate || saving || customDate === task.date}
                  onClick={() => void moveTo(customDate)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40 cursor-pointer"
                  style={{ background: 'var(--color-accent)', color: '#fff' }}
                >
                  Reporter
                </button>
                <button
                  type="button"
                  onClick={() => void cancelReschedule()}
                  className="px-2 py-1.5 text-xs cursor-pointer"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  Annuler
                </button>
              </div>
            </CadreVitre>
          )}
          {!onUpdate && onAssignProject && projects.length > 0 && (
            <select
              value={task.projectId || ''}
              onChange={(event) => void onAssignProject(task, event.target.value)}
              className="mt-2 rounded-lg px-2 py-1 text-xs bg-transparent outline-none cursor-pointer"
              style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
              aria-label="Assigner à un projet"
            >
              <option value="">Sans projet</option>
              {projects.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          )}
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          {/* Sous sm ET en mode compact, les actions vivent dans MenuActions ;
              ici elles n'apparaissent qu'avec la largeur, hors panneau. Le
              survol n'arrive pas au NSPanel non activant dès qu'une autre
              app est devant (16 sept. 2026) ; avec le Carnet, cinq icônes
              toujours pleines à 640 px reprenaient au titre ce que le « ⋯ »
              lui avait rendu — d'où `compact:hidden` (17 sept. 2026). */}
          {onReschedule && !task.done && (
            <button
              type="button"
              onClick={() => { setRescheduling((value) => !value); setEditing(false); }}
              className="hidden sm:block compact:hidden p-1.5 rounded-lg cursor-pointer opacity-60 hover:opacity-100"
              style={{ color: rescheduling ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }}
              title="Reporter"
              aria-label="Reporter la tâche"
              aria-expanded={rescheduling}
            >
              <CalendarClock size={15} />
            </button>
          )}
          {onUpdate && (
            <button
              type="button"
              onClick={() => { setEditing(true); setRescheduling(false); }}
              className="hidden sm:block compact:hidden p-1.5 rounded-lg cursor-pointer opacity-60 hover:opacity-100"
              style={{ color: 'var(--color-text-tertiary)' }}
              title="Modifier"
              aria-label="Modifier la tâche"
            >
              <Pencil size={15} />
            </button>
          )}
          {/* Le carnet, depuis la carte où l'on FAIT la tâche : une étape
              datée apparaissait ici et l'on ne pouvait pas y noter où l'on
              bloque — il fallait la retrouver dans Projets (17 sept. 2026).
              Même repère que LigneEtape : accent quand il y a quelque chose
              dedans, et le point plein le dit aussi là où la teinte se
              replie sur l'encre. Seulement avec `onJournal` : Projets a déjà
              son carnet dans LigneEtape et ne le fournit pas (défaut 15). */}
          {onJournal && (
            <button
              type="button"
              onClick={() => setCarnetOuvert(true)}
              className={`hidden sm:block compact:hidden relative p-1.5 rounded-lg cursor-pointer hover:opacity-100 ${journalEcrit ? '' : 'opacity-60'}`}
              style={{ color: journalEcrit ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }}
              title={libelleCarnet}
              aria-label={journalEcrit ? `Carnet de « ${task.title} » — écrit` : `Carnet de « ${task.title} » — vide`}
              aria-haspopup="dialog"
            >
              <NotebookPen size={15} />
              {journalEcrit && (
                <span
                  aria-hidden
                  className="absolute top-1 right-1 size-1.5 rounded-full"
                  style={{ background: 'currentColor' }}
                />
              )}
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              onClick={() => void onDelete(task)}
              className="hidden sm:block compact:hidden p-1.5 rounded-lg cursor-pointer opacity-60 hover:opacity-100"
              style={{ color: 'var(--color-error)' }}
              title="Supprimer"
              aria-label="Supprimer la tâche"
            >
              <Trash2 size={15} />
            </button>
          )}
          {actionsMenu.length > 0 && <MenuActions entrees={actionsMenu} />}
          {hasSubtasks && (
            <button
              type="button"
              onClick={toggleSubtasksOpen}
              className="p-1.5 rounded-lg cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
              aria-label={subtasksOpen ? 'Masquer les sous-tâches' : 'Afficher les sous-tâches'}
              aria-expanded={subtasksOpen}
            >
              {subtasksOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </button>
          )}
        </div>
      </div>

      {((hasSubtasks && subtasksOpen) || adding) && (
        <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--color-border)' }}>
          {subtasksOpen &&
            task.subtasks.map((subtask) => (
            <SubtaskRow
              key={subtask.id}
              task={task}
              subtask={subtask}
              depth={0}
              onToggle={onToggleSubtask}
              onAdd={onAddSubtask}
              onDelete={onDeleteSubtask}
            />
          ))}
          {adding && (
            <div className="flex gap-2 mt-2 ml-9">
              <input
                autoFocus
                value={subtaskTitle}
                onChange={(event) => setSubtaskTitle(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void submitSubtask();
                  if (event.key === 'Escape') setAdding(false);
                }}
                placeholder="Nouvelle sous-tâche…"
                className="flex-1 min-w-0 bg-transparent text-sm outline-none px-2 py-1.5 rounded-lg"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
              <button
                type="button"
                onClick={() => void submitSubtask()}
                className="px-3 rounded-lg text-xs cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                Ajouter
              </button>
            </div>
          )}
        </div>
      )}
      {!task.done && !adding && (
        <button
          type="button"
          onClick={() => {
            setAdding(true);
            setSubtasksOpen(true);
            saveTaskSubtasksOpen(task.id, true);
          }}
          className="mt-3 flex items-center gap-1.5 text-xs cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          <Plus size={13} /> Ajouter une sous-tâche
        </button>
      )}
      {/* Monté seulement ouvert (un texte en mémoire par carnet regardé, pas
          par carte). CarnetDeTache est déjà un portail `fixed` sur body — la
          carte vitrée (`backdrop-filter`) est un contexte d'empilement où un
          `z-50` local passerait sous la carte suivante, modèle MenuActions.
          Il écrit tout seul, sans toast : `onJournal` de la page réconcilie
          en silence et rend la ligne serveur ; tout le reste — `null`, et
          aussi `undefined` — est un échec que le carnet dit, au lieu
          d'« Enregistré » (§100, défaut 1). */}
      {carnetOuvert && onJournal && (
        <CarnetDeTache
          tache={task}
          onFermer={() => setCarnetOuvert(false)}
          onEnregistrer={async (journal) => {
            const ligne = await onJournal(task, journal);
            if (!ligne) throw new Error("Le carnet n'a pas été enregistré.");
          }}
        />
      )}
    </CadreVitre>
  );
}
