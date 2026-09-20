import { useDerniereLecture } from '../features/succes/useDerniereLecture';
import { CadreVitre } from '../components/Glass/CadreVitre';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, CirclePlus, HardDrive, Loader2, Repeat, Search, SlidersHorizontal } from 'lucide-react';
import { Link } from 'react-router';
import { toast } from 'sonner';

import {
  DateAmbigueError,
  DateInconnueError,
  addSuccesSubtask,
  createSuccesTask,
  deleteSuccesSubtask,
  deleteSuccesTask,
  fetchSuccesSyncStatus,
  listSuccesProjects,
  listSuccesTasks,
  listSuccesTemplates,
  rescheduleSuccesSeries,
  rescheduleSuccesTask,
  setSuccesSubtaskDone,
  setSuccesTaskDone,
  updateSuccesTask,
} from '../features/succes/api';
import { appliquerAuCache, clesSucces, ecrireCache, lireCache } from '../features/succes/cacheSucces';
import { EmojiPicker } from '../features/succes/EmojiPicker';
import { Pageur } from '../features/succes/Pageur';
import { TachesTerminees } from '../features/succes/TachesTerminees';
import { TaskCard, type SuccesTaskPatch } from '../features/succes/TaskCard';
import { TasksBoard } from '../features/succes/TasksBoard';
import { jalonSuivant, jalonsEnAttente, tachesDuJour } from '../features/succes/jalons';
import { nombreDePages, pageApresRetaille, pageDe, paginer, type TaillePage } from '../features/succes/pagination';
import { bilanSuppression, type EchecDeSuppression } from '../features/succes/terminees';
import {
  RecurrencesPanel,
  champsNonReprisParAmorce,
  type AmorceRecurrence,
  type RecurrencesPanelHandle,
} from '../features/succes/RecurrencesPanel';
import { phraseReportee } from '../features/succes/report';
import {
  GLISSEMENT_MS,
  SuiviDesRequetes,
  basculerSousTache,
  estDateIso,
  remplacerLigne,
  retirerSousTache,
  sansTerminees,
} from '../features/succes/reconciliation';
import type {
  SuccesPriority,
  SuccesProject,
  SuccesSubtask,
  SuccesSyncStatus,
  SuccesTask,
  SuccesTemplate,
} from '../features/succes/types';
import {
  loadTasksFilters,
  loadTasksPage,
  loadTasksPageSize,
  loadTasksViewMode,
  saveTasksFilters,
  saveTasksPage,
  saveTasksPageSize,
  saveTasksViewMode,
  type SuccesTasksOngletPagine,
  type SuccesTasksViewMode,
} from '../features/succes/uiPrefs';
import { useConfirm } from '../components/ConfirmDialog';
import { useAppStore } from '../lib/store';
import { useRefreshOnFocus } from '../features/succes/useRefreshOnFocus';
import { useChargementTemporise } from '../features/succes/useChargementTemporise';

type ViewMode = SuccesTasksViewMode;

function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/** Le filtre projet : « Sans projet » (`__none__`), un projet, ou tout. */
function duProjet(task: SuccesTask, projectFilter: string): boolean {
  if (projectFilter === '__none__') return !task.projectId;
  if (projectFilter) return task.projectId === projectFilter;
  return true;
}

function logSucces(level: 'info' | 'error', message: string) {
  useAppStore.getState().addLogEntry({
    timestamp: Date.now(),
    level,
    category: 'succes',
    message,
  });
}

export function SuccesTasksPage() {
  const confirm = useConfirm();
  // L'état initial vient du cache : la dernière liste que le serveur a
  // rendue, en mémoire depuis la visite précédente ou relue du disque au
  // lancement. Sans lui, chaque retour sur la page — Tâches → Projets →
  // Tâches, chaque clic de module du mini-panneau — repartait d'un écran
  // vide avec « Chargement des tâches… » pendant que l'onglet disait déjà
  // « Terminées 37 » (capture de Carlito, 18 sept. 2026).
  const [tasks, setTasks] = useState<SuccesTask[]>(() => lireCache<SuccesTask[]>(clesSucces.taches()) ?? []);
  const [projects, setProjects] = useState<SuccesProject[]>(
    () => lireCache<SuccesProject[]>(clesSucces.projets()) ?? [],
  );
  // `loading` ne vaut que pour le PREMIER chargement SANS cache : ensuite
  // `load()` relit derrière la liste affichée. Le spinner remplaçait toute
  // la liste à chaque relecture — retour de focus, frappe dans la recherche,
  // filtre — et démontait les cartes avec leur carnet ouvert, leur
  // formulaire d'édition et les deux chips d'un 409 (revue du 17 sept.
  // 2026, défauts 5 et 14).
  const [loading, setLoading] = useState(() => lireCache(clesSucces.taches()) === null);
  const chargeReussi = useRef(false);
  /** La clé sous laquelle `tasks` a été chargée — celle du miroir, plus bas. */
  const cleChargee = useRef<string | null>(null);
  const [rafraichit, setRafraichit] = useState(false);
  // Un compteur, pas un booléen : deux écritures en vol (deux sous-tâches,
  // coche + carnet), et le `finally` de la première éteignait le voyant
  // pendant que la seconde attendait encore (revue du 17 sept. 2026, défaut 9).
  const [ecrituresEnVol, setEcrituresEnVol] = useState(0);
  const saving = ecrituresEnVol > 0;
  const commencerEcriture = () => { lecture.invalider(); setRafraichit(false); setEcrituresEnVol((n) => n + 1); };
  const finirEcriture = () => setEcrituresEnVol((n) => n - 1);
  const [search, setSearch] = useState('');
  const lecture = useDerniereLecture(search);
  // Retenus comme le mode d'affichage : ils repartaient à zéro à chaque
  // visite — les terminées revenaient, le projet s'oubliait (17 sept. 2026).
  // `includeDone` ne gouverne plus que la Semaine et le Mois : la Liste ne
  // montre que l'ouvert et les terminées ont leur onglet.
  const [filtres] = useState(() => loadTasksFilters({ includeDone: true, projectFilter: '' }));
  const [includeDone, setIncludeDone] = useState(filtres.includeDone);
  const [projectFilter, setProjectFilter] = useState(filtres.projectFilter);
  const [filtresOuverts, setFiltresOuverts] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>(() => loadTasksViewMode('week'));
  // Les pages (demande de Carlito, 17 sept. 2026) : cinq tâches par défaut,
  // taille et page retenues — par onglet, la Liste et les Terminées ne
  // comptent pas les mêmes lignes.
  const [parPage, setParPage] = useState<TaillePage>(loadTasksPageSize);
  const [pages, setPages] = useState<Record<SuccesTasksOngletPagine, number>>(() => ({
    list: loadTasksPage('list'),
    done: loadTasksPage('done'),
  }));
  const changerPage = useCallback((onglet: SuccesTasksOngletPagine, page: number) => {
    setPages((courantes) => (courantes[onglet] === page ? courantes : { ...courantes, [onglet]: page }));
    saveTasksPage(onglet, page);
  }, []);
  const changerParPage = (taille: TaillePage) => {
    // Le premier élément de la page courante reste sous les yeux.
    changerPage('list', pageApresRetaille(pages.list, parPage, taille));
    changerPage('done', pageApresRetaille(pages.done, parPage, taille));
    setParPage(taille);
    saveTasksPageSize(taille);
  };
  const changerPageListe = useCallback((page: number) => changerPage('list', page), [changerPage]);
  const changerPageTerminees = useCallback((page: number) => changerPage('done', page), [changerPage]);
  // La recherche ou le filtre projet change la liste de fond : la page 7
  // d'une liste de 690 ne veut rien dire dans une liste de 12. Pas au
  // montage — la page retenue est justement ce qu'on vient chercher ; on
  // compare aux valeurs précédentes plutôt que de compter les passages,
  // StrictMode joue l'effet deux fois au montage.
  const dernierFiltrage = useRef({ search, projectFilter });
  useEffect(() => {
    const precedent = dernierFiltrage.current;
    if (precedent.search === search && precedent.projectFilter === projectFilter) return;
    dernierFiltrage.current = { search, projectFilter };
    changerPage('list', 1);
    changerPage('done', 1);
  }, [search, projectFilter, changerPage]);
  const [boardAnchor, setBoardAnchor] = useState(localIsoDate);
  const [showCreate, setShowCreate] = useState(false);
  // Les récurrences vivent dans leur propre section, jamais en même temps
  // que le formulaire de création : un gestionnaire de 798 lignes incrusté
  // sous « Enregistrer » doublait la hauteur du formulaire (17 sept. 2026).
  const [recurrencesOuvertes, setRecurrencesOuvertes] = useState(false);
  const [amorceRecurrence, setAmorceRecurrence] = useState<AmorceRecurrence | null>(null);
  /** Pour fermer la section par la confirmation du panneau, jamais en la démontant sec (défaut 21). */
  const panneauRecurrences = useRef<RecurrencesPanelHandle>(null);
  const [nbRecurrences, setNbRecurrences] = useState<number | null>(
    () => lireCache<SuccesTemplate[]>(clesSucces.gabarits())?.filter((item) => item.templateKind === 'task').length ?? null,
  );
  const [title, setTitle] = useState('');
  const [date, setDate] = useState('');
  const [time, setTime] = useState('');
  const [priority, setPriority] = useState<SuccesPriority>('medium');
  const [notes, setNotes] = useState('');
  const [projectId, setProjectId] = useState('');
  const [category, setCategory] = useState('');
  const [emoji, setEmoji] = useState('');
  const [syncStatus, setSyncStatus] = useState<SuccesSyncStatus | null>(null);

  useEffect(() => {
    saveTasksFilters({ includeDone, projectFilter });
  }, [includeDone, projectFilter]);

  const load = useCallback(async () => {
    const actuelle = lecture.commencer();
    setRafraichit(true);
    // Le voyant de synchronisation se charge À CÔTÉ, jamais devant : jusqu'au
    // 18 sept. 2026 son `await` précédait `setLoading(false)`, et la liste
    // déjà reçue attendait derrière le spinner qu'un second aller-retour
    // réponde — d'où la capture « Chargement des tâches… » sous « Terminées
    // 37 ». Une sonde indisponible ne doit jamais cacher des tâches lues
    // avec succès dans SQLite.
    void fetchSuccesSyncStatus()
      .then((statut) => { if (actuelle()) setSyncStatus(statut); })
      .catch((statusError: unknown) => {
        if (!actuelle()) return;
        setSyncStatus(null);
        const statusMessage = statusError instanceof Error ? statusError.message : String(statusError);
        logSucces('error', `État de synchronisation indisponible : ${statusMessage}`);
      });
    try {
      // TOUJOURS avec les terminées : le compte de l'onglet Terminées et
      // l'onglet lui-même en ont besoin (17 sept. 2026). La Liste filtre
      // `!done` chez elle ; la Semaine et le Mois filtrent selon la case.
      // Les projets et récurrences enrichissent les cartes dès qu'ils sont
      // disponibles ; ni leur lenteur ni leur panne ne retiennent les tâches.
      void listSuccesProjects().then((nextProjects) => {
        if (!actuelle()) return;
        ecrireCache(clesSucces.projets(), nextProjects);
        setProjects(nextProjects);
        setProjectFilter((courant) => courant && courant !== '__none__'
          && !nextProjects.some((p) => p.id === courant) ? '' : courant);
      }).catch(() => {});
      void listSuccesTemplates().then((nextTemplates) => {
        if (!actuelle()) return;
        ecrireCache(clesSucces.gabarits(), nextTemplates);
        setNbRecurrences(nextTemplates.filter((item) => item.templateKind === 'task').length);
      }).catch(() => {});
      const nextTasks = await listSuccesTasks({ includeDone: true, search });
      if (!actuelle()) return;
      cleChargee.current = clesSucces.taches(search);
      ecrireCache(cleChargee.current, nextTasks, { memoireSeule: Boolean(search) });
      setTasks(nextTasks);
      suivi.current.rafraichir(nextTasks);
      chargeReussi.current = true;
    } catch (error) {
      if (!actuelle()) return;
      const message = error instanceof Error ? error.message : String(error);
      logSucces('error', `Chargement des tâches échoué : ${message}`);
      toast.error('Les tâches ne peuvent pas être chargées.', { description: message });
    } finally {
      if (actuelle()) { setLoading(false); setRafraichit(false); }
    }
  }, [search]);

  useChargementTemporise(load, search);

  // Le miroir : chaque ligne réconciliée (coche, report, sous-tâche) se
  // reflète dans le cache, pour qu'un retour sur la page montre l'état à
  // jour sans attendre la relecture. Après un chargement réussi seulement —
  // avant lui, `tasks` EST le cache, ou le vide.
  useEffect(() => {
    if (!cleChargee.current) return;
    ecrireCache(cleChargee.current, tasks, { memoireSeule: cleChargee.current !== clesSucces.taches() });
  }, [tasks]);

  // Une page ouverte gardait son état indéfiniment : ce qui change
  // ailleurs — téléphone, autre fenêtre, assistant — n'apparaissait
  // jamais. On relit au retour du focus.
  useRefreshOnFocus(() => void load());

  // Le GET complet ne reste que pour ce qui change la LISTE : création,
  // suppression, retour de focus. Une coche relançait `load()` sur les 702
  // tâches — case figée quelques centaines de ms, cinq rechargements pour
  // cinq sous-tâches (expertise du 17 sept. 2026, défaut 6).
  /** Rend vrai si l'action a abouti : un brouillon ne se vide que sur un vrai succès. */
  const refreshAfter = async (action: () => Promise<unknown>, success: string): Promise<boolean> => {
    commencerEcriture();
    try {
      await action();
      await load();
      logSucces('info', success);
      toast.success(success, { description: 'Enregistré localement sur ce Mac.' });
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logSucces('error', `${success} — échec : ${message}`);
      toast.error("L'action n'a pas été enregistrée.", { description: message });
      return false;
    } finally {
      finirEcriture();
    }
  };

  const glissements = useRef<number[]>([]);
  useEffect(() => () => {
    for (const timer of glissements.current) window.clearTimeout(timer);
    glissements.current = [];
  }, []);

  /**
   * Les tâches cochées il y a moins de GLISSEMENT_MS : encore barrées à leur
   * place dans une liste qui cache les terminées. Avant le 17 sept. 2026, le
   * glissement RETIRAIT la tâche de `tasks` — impossible depuis que l'onglet
   * Terminées et son compte lisent la même liste ; c'est le filtre qui
   * glisse (`sansTerminees`). Une ligne en sursis dans une vue qui montre
   * les terminées est simplement montrée : le sursis n'a plus rien à
   * relire au moment de tirer (l'ancien défaut 8 disparaît avec le retrait).
   */
  const [sursis, setSursis] = useState<ReadonlySet<string>>(() => new Set());

  /** Les requêtes en vol, tâche par tâche — voir `SuiviDesRequetes`. */
  const suivi = useRef(new SuiviDesRequetes());

  /**
   * Les entrées du cache qu'une mutation doit toucher : la clé chargée, et
   * TOUJOURS la clé principale (`taches('')`) — celle que Planificateur,
   * Projets et le prochain montage de Tâches lisent, et que le disque garde.
   * Sous une recherche active, le miroir n'écrit que la clé de recherche :
   * une tâche supprimée sous « rapport » restait dans la principale, peinte
   * par Planificateur et rejouée au relancement ; un PATCH refusé après la
   * bascule de clé y laissait la coche optimiste, persistée — un état que le
   * serveur avait REFUSÉ (revue du cache, 18 sept. 2026). Chaque clé reçoit
   * sa propre liste transformée : jamais une liste filtrée sous la
   * principale.
   */
  const appliquerAuxCaches = (transformer: (liste: SuccesTask[]) => SuccesTask[]) => {
    const principale = clesSucces.taches();
    const cle = cleChargee.current;
    if (cle && cle !== principale) appliquerAuCache<SuccesTask[]>(cle, transformer, { memoireSeule: true });
    appliquerAuCache<SuccesTask[]>(principale, transformer);
  };

  /**
   * La ligne SERVEUR va aussi droit dans le cache : le miroir (l'effet sur
   * `tasks`) ne bat que tant que la page est montée, et une réponse qui
   * arrive après qu'on a quitté la page laissait l'intérim optimiste dans le
   * cache jusqu'à la relecture suivante (§100, 18 sept. 2026).
   */
  const refleterLigne = (ligne: SuccesTask) => {
    appliquerAuxCaches((liste) => remplacerLigne(liste, ligne));
  };

  /** Une suppression que le serveur a confirmée : la tâche sort de chaque entrée. */
  const retirerDesCaches = (id: string) => {
    appliquerAuxCaches((liste) => (liste.some((task) => task.id === id) ? liste.filter((task) => task.id !== id) : liste));
  };

  /**
   * Peint `attendu` tout de suite, puis remplace la ligne par celle que le
   * serveur renvoie — elle seule reste (§100). En erreur, la dernière ligne
   * SERVEUR connue revient et un toast rouge le dit ; pas de toast de
   * succès : le résultat est déjà sous les yeux. Rend la ligne serveur, ou
   * `null` en échec. Deux requêtes en vol sur la même ligne : seule la plus
   * récente peint (revue du 17 sept. 2026, défaut 3).
   *
   * `relancer` : les refus que la CARTE sait répondre (« lundi prochain »
   * désigne deux jours — lesquels ? ; « je n'ai pas reconnu cette date »)
   * lui reviennent tels quels, sans toast : un toast rouge en faisait une
   * question sans bouton (§34, 17 sept. 2026).
   */
  const reconcilier = async (
    avant: SuccesTask,
    attendu: SuccesTask | null,
    action: () => Promise<SuccesTask>,
    journal: string,
    relancer: (error: unknown) => boolean = () => false,
  ): Promise<SuccesTask | null> => {
    const numero = suivi.current.partir(avant);
    if (attendu) setTasks((courantes) => remplacerLigne(courantes, attendu));
    commencerEcriture();
    try {
      const serveur = await action();
      const ligne = suivi.current.reussir(avant.id, numero, serveur);
      if (ligne) {
        setTasks((courantes) => remplacerLigne(courantes, ligne));
        refleterLigne(ligne);
      }
      logSucces('info', journal);
      return serveur;
    } catch (error) {
      const ligne = suivi.current.echouer(avant.id, numero);
      if (ligne) {
        setTasks((courantes) => remplacerLigne(courantes, ligne));
        refleterLigne(ligne);
      }
      const message = error instanceof Error ? error.message : String(error);
      logSucces('error', `${journal} — échec : ${message}`);
      if (relancer(error)) throw error;
      toast.error("L'action n'a pas été enregistrée.", { description: message });
      return null;
    } finally {
      finirEcriture();
    }
  };

  /**
   * Une tâche cochée reste barrée à sa place le temps de GLISSEMENT_MS avant
   * de quitter une liste qui cache les terminées — si elle l'est toujours :
   * rouverte entre-temps, elle est ouverte et reste, sursis ou non.
   */
  const programmerGlissement = (taskId: string) => {
    setSursis((courant) => new Set(courant).add(taskId));
    const timer = window.setTimeout(() => {
      glissements.current = glissements.current.filter((item) => item !== timer);
      setSursis((courant) => {
        if (!courant.has(taskId)) return courant;
        const suivant = new Set(courant);
        suivant.delete(taskId);
        return suivant;
      });
    }, GLISSEMENT_MS);
    glissements.current.push(timer);
  };

  /**
   * Après une action de sous-tâche, le serveur recalcule `done` sur la tâche
   * (`_recompute_task`) : cocher la dernière sous-tâche la termine, et la
   * carte restait indéfiniment dans une liste censée cacher les terminées —
   * la coche directe, elle, glissait après 1 s (revue du 17 sept. 2026,
   * défaut 4). Revenue rouverte, rien à glisser : le minuteur relit `done`.
   */
  const glisserSiTermineeParSousTache = (avant: SuccesTask, serveur: SuccesTask | null) => {
    if (serveur && serveur.done && !avant.done) programmerGlissement(serveur.id);
  };

  const handleCreate = async () => {
    const clean = title.trim();
    if (!clean) return;
    const ok = await refreshAfter(
      () => createSuccesTask({
        title: clean,
        date,
        time,
        priority,
        notes,
        projectId,
        category: category.trim(),
        emoji: emoji.trim(),
      }),
      `Tâche créée : ${clean}`,
    );
    // Sur un échec, le brouillon reste : le vider après un toast rouge
    // faisait retaper titre, notes et date (contre-revue du 17 sept. 2026).
    if (!ok) return;
    viderCreation();
  };

  const toggleTask = async (task: SuccesTask) => {
    // Le sursis se pose AVANT la réconciliation : l'état optimiste `done`
    // est peint tout de suite, et sans sursis la Liste retirait la carte
    // sous le doigt, la remontait barrée à la réponse du serveur, puis la
    // faisait repartir — deux sauts au lieu d'un glissement (revue du
    // 17 sept. 2026). Sur un échec, la ligne serveur revient `done: false`
    // et le sursis expire sans effet.
    if (!task.done) programmerGlissement(task.id);
    const serveur = await reconcilier(
      task,
      { ...task, done: !task.done },
      () => setSuccesTaskDone(task.id, !task.done),
      task.done ? 'Tâche rouverte' : 'Tâche terminée',
    );
    if (!serveur) return;
    // Rouverte depuis Terminées sans date, dans un projet à jalons : elle
    // ne revient pas en Liste mais sur sa carte — le dire, sinon la ligne
    // qui disparaît de l'onglet ressemble à une perte.
    if (task.done && !serveur.done && !serveur.date && serveur.projectId) {
      const projet = projects.find((p) => p.id === serveur.projectId);
      if (projet && (projet.structure || 'flat') !== 'flat') {
        toast(`Rouverte : ${serveur.title}`, {
          description: `Sans date, elle attend sur sa carte dans Projets (${projet.name}).`,
        });
      }
    }
    // Une étape de parcours cochée appelle la suivante (24 août 2026) :
    // « une étape datée à la fois ». On la propose pour aujourd'hui, sans
    // rien imposer — un clic la pose, l'ignorer la laisse sur sa carte.
    if (task.done || !task.projectId) return;
    const projet = projects.find((p) => p.id === task.projectId);
    if (!projet || (projet.structure || 'flat') === 'flat') return;
    const suivant = jalonSuivant(tasks, task.projectId, task);
    if (!suivant || suivant.date) return;
    toast(`Étape suivante : ${suivant.title}`, {
      description: `Prochaine sur ${projet.name}.`,
      action: {
        label: "Faire aujourd'hui",
        onClick: () => {
          const aujourdHui = localIsoDate();
          void reconcilier(
            suivant,
            { ...suivant, date: aujourdHui },
            () => updateSuccesTask(suivant.id, { date: aujourdHui }),
            'Étape programmée pour aujourd’hui',
          );
        },
      },
    });
  };

  const toggleSubtask = async (task: SuccesTask, subtask: SuccesSubtask) => {
    const serveur = await reconcilier(
      task,
      basculerSousTache(task, subtask.id, !subtask.done),
      () => setSuccesSubtaskDone(task.id, subtask.id, !subtask.done),
      'Sous-tâche mise à jour',
    );
    glisserSiTermineeParSousTache(task, serveur);
  };

  // Pas d'intérim : la sous-tâche n'a d'id qu'une fois créée. Rend la ligne
  // serveur (ou `null`) : la carte ne vide son champ que sur une ligne
  // (revue du 17 sept. 2026, défaut 11).
  const addSubtask = async (task: SuccesTask, subtaskTitle: string, parentId?: string) => {
    const serveur = await reconcilier(
      task,
      null,
      () => addSuccesSubtask(task.id, subtaskTitle, parentId),
      'Sous-tâche ajoutée',
    );
    glisserSiTermineeParSousTache(task, serveur);
    return serveur;
  };

  const removeSubtask = async (task: SuccesTask, subtask: SuccesSubtask) => {
    const serveur = await reconcilier(
      task,
      retirerSousTache(task, subtask.id),
      () => deleteSuccesSubtask(task.id, subtask.id),
      'Sous-tâche supprimée',
    );
    glisserSiTermineeParSousTache(task, serveur);
  };

  // Rend la ligne serveur (ou `null`) : la carte ne ferme son formulaire
  // que sur une ligne (défaut 11).
  const updateTask = (task: SuccesTask, patch: SuccesTaskPatch) =>
    reconcilier(task, { ...task, ...patch }, () => updateSuccesTask(task.id, patch), 'Tâche mise à jour');

  // Le carnet de la carte, sur sa prop dédiée : réconciliation silencieuse
  // (pas de toast de succès — une bulle par pause de 700 ms), et la ligne
  // serveur ou `null` — le carnet ne dit « Enregistré » que sur une ligne
  // (§100, revue du 17 sept. 2026, défaut 1).
  const journalTask = (task: SuccesTask, journal: string) =>
    reconcilier(task, { ...task, journal }, () => updateSuccesTask(task.id, { journal }), 'Carnet enregistré');

  /**
   * Le jeton « Découper » ciblé sur une carte : `{ taskId, n }`, où `n`
   * change à chaque demande pour que la carte rouvre son champ « Nouvelle
   * sous-tâche » même deux fois de suite. Un état, jamais une requête DOM.
   * CONSOMMÉ dès que la carte a ouvert son champ (`acquitterDecoupage`) :
   * laissé posé, chaque remontage de la liste — une lettre dans Rechercher,
   * la case « Terminées », un retour de focus — rouvrait le champ et lui
   * volait le focus (revue du 17 sept. 2026, défaut 2).
   */
  const [decoupage, setDecoupage] = useState<{ taskId: string; n: number } | null>(null);
  const compteurDecoupage = useRef(0);
  /** Les ouvertes de la Liste au dernier rendu : le toast « Découper » vit plus longtemps qu'un rendu. */
  const ouvertesRef = useRef<SuccesTask[]>([]);
  const demanderDecoupage = (taskId: string) => {
    // La Semaine et le Mois n'ont pas de champ de sous-tâche : la réponse
    // vit sur la carte de la Liste, on y va (sans retenir ce saut comme
    // préférence — c'est le toast qui l'a demandé, pas l'onglet). Et sur
    // SA page : depuis que la Liste est paginée, ouvrir le champ d'une
    // carte qui n'est pas affichée n'ouvrait rien (17 sept. 2026).
    if (viewMode !== 'list') setViewMode('list');
    const page = pageDe(ouvertesRef.current, (task) => task.id === taskId, parPage);
    if (page !== null) changerPage('list', page);
    compteurDecoupage.current += 1;
    setDecoupage({ taskId, n: compteurDecoupage.current });
  };
  const acquitterDecoupage = () => setDecoupage(null);

  const rescheduleTask = async (task: SuccesTask, date: string): Promise<SuccesTask | null> => {
    // La route résout aussi « lundi » ou « dans 3 jours » : on ne peint
    // d'avance qu'une date ISO, le reste attend la réponse.
    const attendu = estDateIso(date) ? { ...task, date } : null;
    const reponse: { warning: string | null } = { warning: null };
    const serveur = await reconcilier(
      task,
      attendu,
      async () => {
        const result = await rescheduleSuccesTask(task.id, date);
        reponse.warning = result.warning;
        return result.task;
      },
      `Tâche reportée (${date})`,
      (error) => error instanceof DateAmbigueError || error instanceof DateInconnueError,
    );
    // La nouvelle date est sur la carte ; seul l'avertissement mérite un
    // toast — il n'est visible nulle part ailleurs. Il pose une question
    // (« voulez-vous la découper ? ») : « Découper » y répond en ouvrant
    // le champ « Nouvelle sous-tâche » de la carte (§34, 17 sept. 2026).
    // La date du SERVEUR, dans la langue de la carte : le toast disait
    // « Reportée au 2026-09-21 » sous une carte qui dit « lun. 21 sept. »
    // (défaut 12).
    if (serveur && reponse.warning) {
      toast.warning(phraseReportee(serveur.date, localIsoDate()), {
        description: reponse.warning,
        action: { label: 'Découper', onClick: () => demanderDecoupage(serveur.id) },
      });
    }
    return serveur;
  };

  const rescheduleById = async (taskId: string, date: string) => {
    const task = tasks.find((item) => item.id === taskId);
    if (!task) return;
    await rescheduleTask(task, date);
  };

  const rescheduleSeriesById = async (taskId: string, date: string) => {
    commencerEcriture();
    try {
      const result = await rescheduleSuccesSeries(taskId, date);
      await load();
      logSucces('info', `Série décalée de ${result.deltaDays} j (${result.updated} occurrence(s))`);
      toast.success('Série décalée', {
        description: `${result.updated} occurrence(s) déplacée(s) du même écart.`,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logSucces('error', `Décalage de série échoué : ${message}`);
      toast.error("Le décalage de la série a échoué.", { description: message });
    } finally {
      finirEcriture();
    }
  };

  const clearTaskDate = async (taskId: string) => {
    const task = tasks.find((item) => item.id === taskId);
    if (!task) return;
    const serveur = await reconcilier(
      task,
      { ...task, date: '' },
      () => updateSuccesTask(taskId, { date: '' }),
      `Tâche remise sans date : ${task.title}`,
    );
    // La carte quitte la grille : sans un mot, cela ressemble à une perte.
    if (serveur) toast.success(`Remise sans date : ${serveur.title}`);
  };

  /**
   * Ferme la section des récurrences par le chemin d'annulation du panneau :
   * un brouillon de règle non vide (titre hérité de l'amorce compris)
   * demande « Garder ? » avant d'être perdu. Rend `false` si on le garde.
   * L'exclusion Récurrences/formulaire est SYMÉTRIQUE : dans un sens comme
   * dans l'autre, ouvrir l'un ferme l'autre par son annulation confirmée —
   * « Nouvelle tâche » et le clic sur un jour de la Semaine démontaient la
   * section d'un `setRecurrencesOuvertes(false)` sec (revue du 17 sept.
   * 2026, défaut 21).
   */
  const fermerRecurrences = async (): Promise<boolean> => {
    if (!recurrencesOuvertes) return true;
    const fermee = (await panneauRecurrences.current?.fermerEditeur()) ?? true;
    if (!fermee) return false;
    setRecurrencesOuvertes(false);
    setAmorceRecurrence(null);
    return true;
  };

  const ouvrirCreation = async (nextDate?: string) => {
    const fermee = await fermerRecurrences();
    if (!fermee) return;
    if (nextDate !== undefined) setDate(nextDate);
    setShowCreate(true);
  };

  const openCreateForDate = (nextDate: string) => void ouvrirCreation(nextDate);

  /**
   * Ouvre la section des récurrences — à la place du formulaire de création,
   * jamais à côté. Avec une `amorce`, la règle neuve hérite du brouillon de
   * tâche : « Créer une récurrence à partir de ce brouillon » ne fait pas
   * retaper le titre. Une règle n'a ni heure, ni notes, ni catégorie : ces
   * champs, s'ils sont remplis, partiraient en silence — on le dit et on
   * demande avant de vider (défaut 21).
   */
  const ouvrirRecurrences = async (amorce: AmorceRecurrence | null = null) => {
    if (showCreate && !amorce) {
      const fermee = await cancelCreate();
      if (!fermee) return;
    }
    if (amorce) {
      const perdus = champsNonReprisParAmorce({ time, notes, category });
      if (perdus.length > 0) {
        const confirmed = await confirm({
          title: 'Créer la récurrence sans tout reprendre ?',
          description: `Une récurrence ne porte pas ${perdus.join(', ')} : ce que vous avez saisi là ne sera pas repris. Le titre, l’emoji, la priorité, le projet et la date le seront.`,
          confirmLabel: 'Créer la récurrence',
          keepLabel: 'Garder le brouillon',
          tone: 'warning',
        });
        if (!confirmed) return;
      }
      viderCreation();
    }
    setAmorceRecurrence(amorce);
    setRecurrencesOuvertes(true);
  };

  const basculerRecurrences = () => {
    if (recurrencesOuvertes) {
      void fermerRecurrences();
      return;
    }
    void ouvrirRecurrences();
  };

  const removeTask = async (task: SuccesTask) => {
    const confirmed = await confirm({
      title: `Supprimer « ${task.title} » ?`,
      description: 'Cette action est sensible et sera enregistrée comme suppression synchronisable.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    await refreshAfter(async () => {
      await deleteSuccesTask(task.id);
      retirerDesCaches(task.id);
    }, `Tâche supprimée : ${task.title}`);
  };

  /**
   * Supprime plusieurs terminées — la sélection, ou tout l'onglet (« Vider
   * les terminées », filtre compris). Une requête par tâche, en séquence ;
   * puis `load()` ; puis un toast qui rend le BILAN des réponses : « 4
   * supprimées », ou « 3 sur 4 supprimées » avec ce qui a échoué et
   * pourquoi. Jamais un succès global déduit du nombre demandé (§100) : ce
   * qui a échoué reste dans l'onglet, sélectionné, et le toast le nomme.
   */
  const supprimerTerminees = async (cibles: SuccesTask[]) => {
    if (cibles.length === 0) return;
    const confirmed = await confirm({
      title: cibles.length === 1
        ? `Supprimer « ${cibles[0].title} » ?`
        : `Supprimer ${cibles.length} tâches terminées ?`,
      description: 'Chaque suppression est enregistrée comme suppression synchronisable. Rien ne se rouvre après.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    const echecs: EchecDeSuppression[] = [];
    commencerEcriture();
    try {
      for (const cible of cibles) {
        try {
          await deleteSuccesTask(cible.id);
          retirerDesCaches(cible.id);
        } catch (error) {
          echecs.push({ titre: cible.title, message: error instanceof Error ? error.message : String(error) });
        }
      }
      await load();
    } finally {
      finirEcriture();
    }
    const bilan = bilanSuppression(cibles.length, echecs);
    logSucces(bilan.ok ? 'info' : 'error', `Terminées : ${bilan.titre}${bilan.description ? ` — ${bilan.description}` : ''}`);
    if (bilan.ok) toast.success(bilan.titre, { description: 'Enregistré localement sur ce Mac.' });
    else toast.error(bilan.titre, { description: bilan.description });
  };

  /** Ferme le formulaire, brouillon compris, sans demander : pour la remise du brouillon aux récurrences. */
  const viderCreation = () => {
    setTitle('');
    setNotes('');
    setDate('');
    setTime('');
    setPriority('medium');
    setProjectId('');
    setCategory('');
    setEmoji('');
    setShowCreate(false);
  };

  /** Rend `false` si Carlito a choisi de garder son brouillon. */
  const cancelCreate = async (): Promise<boolean> => {
    const dirty = Boolean(
      title.trim() || notes.trim() || date || time || projectId || category.trim() || emoji.trim() || priority !== 'medium',
    );
    if (dirty) {
      const confirmed = await confirm({
        title: 'Annuler la création ?',
        description: 'Les informations saisies ne seront pas enregistrées.',
        confirmLabel: 'Annuler',
        keepLabel: 'Garder',
        tone: 'warning',
      });
      if (!confirmed) return false;
    }
    setShowCreate(false);
    return true;
  };

  // Les jalons des projets structurés (parcours, anglais) ne remplissent
  // plus cette page : ils vivent sur leur carte, dans Projets, et n'entrent
  // ici que lorsqu'on leur donne une date (24 août 2026). Choisir un projet
  // dans le filtre les fait réapparaître : demander à voir un projet, c'est
  // vouloir tout son contenu.
  const jalonsQuiAttendent = useMemo(
    () => (projectFilter ? [] : jalonsEnAttente(tasks, projects)),
    [tasks, projects, projectFilter],
  );
  const tachesDuQuotidien = useMemo(
    () => (projectFilter ? tasks : tachesDuJour(tasks, projects)),
    [tasks, projects, projectFilter],
  );
  const visibleTasks = useMemo(
    () => tachesDuQuotidien.filter((task) => duProjet(task, projectFilter)),
    [tachesDuQuotidien, projectFilter],
  );
  // La Liste : l'ouvert seulement, plus ce qui glisse encore ; la Semaine et
  // le Mois : selon la case « Afficher les tâches terminées ».
  const ouvertes = useMemo(() => sansTerminees(visibleTasks, sursis), [visibleTasks, sursis]);
  useEffect(() => {
    ouvertesRef.current = ouvertes;
  }, [ouvertes]);
  const tachesDuTableau = includeDone ? visibleTasks : ouvertes;
  // Les Terminées : TOUTES les faites, étapes de projet comprises — une
  // étape faite n'attend plus sur sa carte —, sous le même filtre projet.
  const terminees = useMemo(
    () => tasks.filter((task) => task.done && duProjet(task, projectFilter)),
    [tasks, projectFilter],
  );
  const paginationListe = paginer(ouvertes, pages.list, parPage);
  const nbPagesTerminees = nombreDePages(terminees.length, parPage);

  // Une page retenue qui n'existe plus (moins de tâches qu'à la dernière
  // visite, taille de page plus grande) revient sur la dernière — après un
  // chargement RÉUSSI seulement : avant lui la liste est vide et TOUTE page
  // retenue serait « hors bornes » ; un premier chargement en échec (serveur
  // injoignable) écrasait la page de la veille par 1 dans les préférences
  // (revue du 17 sept. 2026).
  useEffect(() => {
    if (loading || !chargeReussi.current) return;
    if (pages.list > paginationListe.nbPages) changerPage('list', paginationListe.nbPages);
    if (pages.done > nbPagesTerminees) changerPage('done', nbPagesTerminees);
  }, [loading, pages.list, pages.done, paginationListe.nbPages, nbPagesTerminees, changerPage]);

  const surTableau = viewMode === 'week' || viewMode === 'month';
  const filtreActif = Boolean(search.trim() || projectFilter || (surTableau && !includeDone));
  const libelleRecurrences = nbRecurrences === null ? 'Récurrences' : `Récurrences (${nbRecurrences})`;

  // Le sélecteur de mode vit sur la rangée du titre dès sm, sur la sienne
  // en dessous : rendu deux fois, une seule copie est affichée à la fois.
  // Quatre onglets à 340 px : `px-2` sous sm — avec `px-3`, « Terminées 36 »
  // poussait le bouton des filtres à la ligne (17 sept. 2026).
  const selecteurMode = (
    <CadreVitre compact
      className="flex rounded-xl p-1"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      role="tablist"
      aria-label="Mode d’affichage"
    >
      {([
        { id: 'list' as const, label: 'Liste' },
        { id: 'week' as const, label: 'Semaine' },
        { id: 'month' as const, label: 'Mois' },
        { id: 'done' as const, label: 'Terminées' },
      ]).map((option) => (
        <button
          key={option.id}
          type="button"
          role="tab"
          aria-selected={viewMode === option.id}
          aria-label={option.id === 'done' ? `Terminées (${terminees.length})` : undefined}
          onClick={() => {
            setViewMode(option.id);
            saveTasksViewMode(option.id);
          }}
          className="px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg text-xs font-medium cursor-pointer flex items-center gap-1"
          style={{
            background: viewMode === option.id ? 'var(--color-surface)' : 'transparent',
            color: viewMode === option.id ? 'var(--color-text)' : 'var(--color-text-secondary)',
          }}
        >
          {option.label}
          {/* Le compte des terminées, dans leur couleur — la même que les
              numéros de leur pageur (Carlito, 17 sept. 2026). */}
          {option.id === 'done' && (
            <span className="tabular-nums teinte-terminees" style={{ color: 'var(--color-success)' }} aria-hidden>
              {terminees.length}
            </span>
          )}
        </button>
      ))}
    </CadreVitre>
  );

  // La ligne « Ce Mac est prêt à appairer… Journal local : 4387 opérations »
  // doublonnait la page Synchronisation et prenait une rangée au-dessus des
  // tâches (17 sept. 2026). Une icône suffit : le message dans `title`, le
  // lien vers la vraie page, et la couleur d'erreur seulement quand il y a
  // une erreur — un voyant qui ne dit rien n'a pas à se faire voir.
  const iconeSynchro = syncStatus && (
    <Link
      to="/succes/sync"
      className="inline-flex items-center shrink-0 rounded"
      style={{ color: syncStatus.lastSyncError ? 'var(--color-error)' : 'var(--color-text-tertiary)' }}
      title={`${syncStatus.message} Journal local : ${syncStatus.localCursor} opération(s).${
        syncStatus.lastSyncError ? ` Dernière erreur : ${syncStatus.lastSyncError}` : ''
      }`}
      aria-label={syncStatus.lastSyncError ? 'Synchronisation en erreur — ouvrir' : 'Synchronisation — ouvrir'}
    >
      <HardDrive size={14} />
    </Link>
  );

  // Le même voyant discret pour une écriture en vol et pour la relecture
  // derrière une liste déjà affichée ; le grand spinner ne revient jamais
  // sur une liste peuplée (revue du 17 sept. 2026, défaut 5).
  const voyantActivite = (saving || (rafraichit && !loading)) && (
    <Loader2
      size={13}
      className="animate-spin"
      style={{ color: 'var(--color-accent)' }}
      aria-label={saving ? 'Enregistrement en cours' : 'Relecture des tâches'}
      role="status"
    />
  );

  return (
    // Budget de chrome au-dessus de la première tâche (expertise du 17 sept.
    // 2026) : ≤ 96 px à 340 px, ≤ 150 px à 1384 × 868. Compté par la
    // structure, bordures de verre (1 px) comprises — base : 12 (padding)
    // + 32 (titre et boutons) + 8 + 34 (modes : 4 + 24 + 4 + 2) + 8 = 94 ;
    // sm+ : 24 + 52 (surtitre 20 + titre 32) + 12 + 46 (filtres : 8 + 28 +
    // 8 + 2) + 12 = 146. Le sous-titre et la ligne de synchro — ~300 px de
    // chrome en tout — sont partis.
    <div data-verre-defilement className="flex-1 overflow-y-auto px-4 py-3 sm:px-5 sm:py-6 md:px-8">
      <main className={`mx-auto w-full ${surTableau ? 'max-w-7xl' : 'max-w-5xl'}`}>
        <header className="mb-2 sm:mb-3">
          {/* Le titre ne se casse jamais et c'est la rangée de droite qui
              revient à la ligne : avec le quatrième onglet, « TÂCHES » en
              pixel passait sur deux lignes et montait sur l'eyebrow
              (17 sept. 2026, 1280 px). */}
          <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-2">
            <div className="shrink-0">
              <div className="hidden sm:flex items-center gap-2 mb-1 h-4">
                <span className="text-xs font-medium tracking-[0.16em] uppercase leading-4" style={{ color: 'var(--color-accent)' }}>Succès</span>
                {iconeSynchro}
                {voyantActivite}
              </div>
              <div className="flex items-center gap-2 h-8">
                <h1 className="text-xl sm:text-2xl font-semibold leading-8 whitespace-nowrap" style={{ color: 'var(--color-text)' }}>Tâches</h1>
                <span className="flex sm:hidden items-center gap-2">
                  {iconeSynchro}
                  {voyantActivite}
                </span>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2 ml-auto">
              <span className="hidden sm:block">{selecteurMode}</span>
              {/* Les récurrences en section à part, ouverte par ce bouton et
                  fermée par lui ; N dit qu'il y a quelque chose derrière. */}
              <button
                type="button"
                onClick={basculerRecurrences}
                className="flex items-center gap-1.5 h-8 sm:h-9 px-2 sm:px-3 rounded-xl text-sm cursor-pointer"
                style={{
                  color: recurrencesOuvertes ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  border: `1px solid ${recurrencesOuvertes ? 'var(--color-accent)' : 'var(--color-border)'}`,
                }}
                aria-label={libelleRecurrences}
                aria-expanded={recurrencesOuvertes}
                title={libelleRecurrences}
              >
                <Repeat size={15} />
                <span className="hidden sm:inline">{libelleRecurrences}</span>
                {nbRecurrences !== null && nbRecurrences > 0 && (
                  <span className="sm:hidden text-xs tabular-nums">{nbRecurrences}</span>
                )}
              </button>
              {/* À 340 px, « Nouvelle tâche » (~150 px) faisait passer la rangée
                  sur deux lignes ; l'icône seule suffit (16 sept. 2026). */}
              <button
                type="button"
                onClick={() => void (showCreate ? cancelCreate() : ouvrirCreation())}
                className="flex items-center gap-2 h-8 sm:h-9 px-2 sm:px-3 rounded-xl text-sm font-medium cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
                aria-label="Nouvelle tâche"
                aria-expanded={showCreate}
              >
                <CirclePlus size={16} /> <span className="hidden sm:inline">Nouvelle tâche</span>
              </button>
            </div>
          </div>
          {/* Sous sm : les modes sur leur rangée, et un bouton pour dérouler
              recherche et filtres — trois rangées ne tenaient pas dans 96 px.
              Le bouton se teinte quand un filtre agit sur la liste, pour ne
              pas cacher ce qui la réduit (§5). */}
          <div className="mt-2 flex items-center justify-between gap-2 sm:hidden">
            {selecteurMode}
            <button
              type="button"
              onClick={() => setFiltresOuverts((value) => !value)}
              className="flex items-center justify-center size-8 rounded-xl cursor-pointer"
              style={{
                color: filtreActif || filtresOuverts ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                border: `1px solid ${filtresOuverts ? 'var(--color-accent)' : 'var(--color-border)'}`,
              }}
              aria-label={filtreActif ? 'Recherche et filtres (actifs)' : 'Recherche et filtres'}
              aria-expanded={filtresOuverts}
              title={filtreActif ? 'Un filtre réduit la liste' : 'Recherche et filtres'}
            >
              <SlidersHorizontal size={15} />
            </button>
          </div>
        </header>

        {/* Une seule rangée : recherche, terminées, projet. Sous sm elle
            n'apparaît qu'à la demande (bouton ci-dessus) et s'empile. */}
        <CadreVitre as="section"
          className={`${filtresOuverts ? 'flex' : 'hidden'} sm:flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 rounded-2xl p-2 mb-3`}
          style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex-1 min-w-0 flex items-center gap-2 px-2 h-7">
            <Search size={15} className="shrink-0" style={{ color: 'var(--color-text-tertiary)' }} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Rechercher une tâche…"
              className="w-full min-w-0 bg-transparent outline-none text-sm"
              style={{ color: 'var(--color-text)' }}
            />
          </div>
          {/* `ml-auto` sur le sélecteur : quand la case « Terminées » est
              absente (Liste, onglet Terminées), `justify-between` n'a plus
              qu'un enfant et le collait à gauche — le même contrôle changeait
              de côté selon l'onglet (revue du 17 sept. 2026). */}
          <div className="flex items-center justify-between gap-2 min-w-0 sm:contents">
            {/* La case ne vaut que pour la Semaine et le Mois : la Liste ne
                montre que l'ouvert et les terminées ont leur onglet (17 sept.
                2026). En Liste et en Terminées, elle est cachée — une case
                sans effet est une promesse (§5). */}
            {surTableau && (
              <label className="flex items-center gap-2 text-xs cursor-pointer px-2 shrink-0" style={{ color: 'var(--color-text-secondary)' }}>
                <input type="checkbox" checked={includeDone} onChange={(event) => setIncludeDone(event.target.checked)} />
                <span className="sm:hidden">Terminées</span>
                <span className="hidden sm:inline">Afficher les tâches terminées</span>
              </label>
            )}
            <select
              value={projectFilter}
              onChange={(event) => setProjectFilter(event.target.value)}
              className="min-w-0 max-w-[60%] sm:max-w-none ml-auto sm:ml-0 rounded-xl px-3 h-7 text-xs bg-transparent outline-none cursor-pointer"
              style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
              aria-label="Filtrer par projet"
            >
              <option value="">Tous les projets</option>
              <option value="__none__">Sans projet</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>{project.name}</option>
              ))}
            </select>
          </div>
        </CadreVitre>

        {recurrencesOuvertes && (
          <CadreVitre as="section"
            className="rounded-2xl px-4 pt-4 mb-5"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
            aria-label="Récurrences de tâches"
          >
            <RecurrencesPanel
              key={amorceRecurrence ? `amorce:${amorceRecurrence.title}` : 'libre'}
              ref={panneauRecurrences}
              kind="task"
              amorce={amorceRecurrence}
              onCompte={setNbRecurrences}
            />
          </CadreVitre>
        )}

        {showCreate && (
          <CadreVitre as="section"
            className="grid gap-3 rounded-2xl p-4 mb-5"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}
          >
            {/* Le même sélecteur qu'Habitudes et Finances : un champ texte de
                8 caractères obligeait à trouver l'emoji ailleurs et à le
                coller (expertise du 17 sept. 2026, cohérence entre pages). */}
            <div className="flex items-stretch gap-2">
              <div className="w-14 shrink-0">
                <EmojiPicker value={emoji} onChange={setEmoji} aria-label="Emoji de la tâche" optionnel />
              </div>
              <input
                autoFocus
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) void handleCreate(); }}
                placeholder="Qu'est-ce qui doit être fait ?"
                maxLength={200}
                className="flex-1 bg-transparent outline-none text-base font-medium px-2 py-1"
                style={{ color: 'var(--color-text)' }}
              />
            </div>
            {/* Quatre champs empilés sous sm faisaient un formulaire de ~250 px
                dans un panneau de 620 ; par paires (date+heure, priorité+projet)
                chaque champ garde ~130 px à 340 px — assez (16 sept. 2026).
                `min-w-0` : un <input type=date> WebKit a une largeur
                intrinsèque qui, sinon, déborde la colonne. */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <input
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
                className="min-w-0 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
                style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                aria-label="Date"
              />
              <input
                type="time"
                value={time}
                onChange={(event) => setTime(event.target.value)}
                className="min-w-0 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
                style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                aria-label="Heure"
              />
              <select
                value={priority}
                onChange={(event) => setPriority(event.target.value as SuccesPriority)}
                className="min-w-0 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
                style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                aria-label="Priorité"
              >
                <option value="low">Priorité basse</option>
                <option value="medium">Priorité normale</option>
                <option value="high">Priorité haute</option>
                <option value="urgent">Priorité urgente</option>
              </select>
              <select
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                className="min-w-0 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
                style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                aria-label="Projet"
              >
                <option value="">Sans projet</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            </div>
            <input
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              placeholder="Catégorie (facultatif)"
              maxLength={100}
              className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
              style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            />
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Notes facultatives…"
              maxLength={2000}
              rows={2}
              className="resize-none rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
              style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              {/* Le gestionnaire de récurrences (798 lignes) était incrusté
                  ici, sous « Enregistrer », pour la création d'UNE tâche
                  (17 sept. 2026). Il ne reste qu'un bouton : il remet ce
                  brouillon à la section Récurrences, qui s'ouvre sur une
                  règle neuve pré-remplie — titre, emoji, priorité, projet,
                  date de départ. Un BOUTON, pas une case « Répéter… » à
                  `checked={false}` : une case qui ne se coche jamais et qui
                  vide le formulaire est un bouton déguisé (revue du 17 sept.
                  2026, défaut 21). */}
              <button
                type="button"
                onClick={() => {
                  void ouvrirRecurrences({
                    title: title.trim(),
                    emoji: emoji.trim(),
                    priority,
                    projectId,
                    startDate: date,
                  });
                }}
                className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs cursor-pointer"
                style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                title="Ouvre les récurrences sur une règle neuve reprenant le titre, l’emoji, la priorité, le projet et la date"
              >
                <Repeat size={13} aria-hidden />
                Créer une récurrence à partir de ce brouillon
              </button>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => void cancelCreate()} className="px-3 py-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>Annuler</button>
                <button type="button" disabled={!title.trim() || saving} onClick={() => void handleCreate()} className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>Enregistrer localement</button>
              </div>
            </div>
          </CadreVitre>
        )}

        {!loading && viewMode !== 'done' && jalonsQuiAttendent.length > 0 && (
          <CadreVitre as="section"
            className="mb-5 rounded-2xl px-4 py-3 flex flex-wrap items-center gap-x-3 gap-y-2"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            <span className="text-[11px] uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>
              Sur leurs cartes
            </span>
            {jalonsQuiAttendent.map(({ projet, total }) => (
              <button
                key={projet.id}
                type="button"
                onClick={() => setProjectFilter(projet.id)}
                className="text-xs px-2.5 py-1 rounded-full cursor-pointer transition-colors"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                title={`Voir les ${total} étapes de ${projet.name} ici`}
              >
                {projet.name} · {total}
              </button>
            ))}
            {/* `min-w-[12rem]` forçait un retour à la ligne entier en étroit ;
                l'information reste dans le `title` des chips (16 sept. 2026). */}
            <span className="hidden sm:inline text-[11px] flex-1 min-w-[12rem]" style={{ color: 'var(--color-text-tertiary)' }}>
              Ces étapes attendent dans Projets. Donnez-en une à une date pour la voir ici.
            </span>
          </CadreVitre>
        )}
        {/* Le premier chargement seulement : ensuite la liste reste montée
            pendant les relectures (carnet, édition, chips d'un 409 vivent
            dans les cartes). */}
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
            <Loader2 size={17} className="animate-spin" /> Chargement des tâches…
          </div>
        ) : viewMode === 'done' ? (
          <TachesTerminees
            taches={terminees}
            projects={projects}
            aujourdHui={localIsoDate()}
            page={pages.done}
            parPage={parPage}
            onPage={changerPageTerminees}
            onParPage={changerParPage}
            onRouvrir={toggleTask}
            onSupprimer={removeTask}
            onSupprimerPlusieurs={supprimerTerminees}
            saving={saving}
            filtreActif={filtreActif}
          />
        ) : surTableau ? (
          <TasksBoard
            mode={viewMode}
            anchor={boardAnchor}
            tasks={tachesDuTableau}
            projects={projects}
            onAnchorChange={setBoardAnchor}
            onReschedule={rescheduleById}
            onRescheduleSeries={rescheduleSeriesById}
            onClearDate={clearTaskDate}
            onToggleTask={toggleTask}
            onToggleSubtask={toggleSubtask}
            onQuickAdd={openCreateForDate}
          />
        ) : paginationListe.total === 0 ? (
          <CadreVitre className="rounded-2xl py-16 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <CheckCircle2 size={28} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} />
            <p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucune tâche ici</p>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
              {terminees.length > 0 && !filtreActif
                ? 'Tout est fait — les terminées vous attendent dans leur onglet.'
                : 'Créez-en une, ou demandez simplement à DIA.'}
            </p>
          </CadreVitre>
        ) : (
          <>
            {/* Une page à la fois (Carlito, 17 sept. 2026) : 473 cartes
                vitrées montées d'un coup pour un filtre projet, c'était la
                molette pour retrouver la seule qu'on voulait. */}
            <div className="grid gap-3">
              {paginationListe.tranche.map((task) => (
                <TaskCard
                  key={task.id}
                  vitre
                  task={task}
                  projects={projects}
                  onToggleTask={toggleTask}
                  onToggleSubtask={toggleSubtask}
                  onAddSubtask={addSubtask}
                  onDeleteSubtask={removeSubtask}
                  onUpdate={updateTask}
                  onJournal={journalTask}
                  onReschedule={rescheduleTask}
                  onDelete={removeTask}
                  decoupage={decoupage?.taskId === task.id ? decoupage.n : undefined}
                  onDecoupageOuvert={acquitterDecoupage}
                />
              ))}
            </div>
            <Pageur
              page={paginationListe.page}
              nbPages={paginationListe.nbPages}
              total={paginationListe.total}
              debut={paginationListe.debut}
              fin={paginationListe.fin}
              parPage={parPage}
              onPage={changerPageListe}
              onParPage={changerParPage}
              unite="tâches"
            />
          </>
        )}
      </main>
    </div>
  );
}
