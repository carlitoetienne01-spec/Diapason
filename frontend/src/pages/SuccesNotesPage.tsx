import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  Bookmark,
  Copy,
  FilePlus2,
  Loader2,
  NotebookPen,
  Pencil,
  Save,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  createSuccesNote,
  listNoteCategories,
  listSuccesProjects,
  orderNoteCategories,
  renameNoteCategory,
  deleteSuccesNote,
  listSuccesNotes,
  updateSuccesNote,
} from '../features/succes/api';
import { NOTE_DOC_LANGS, miseEnPageDeLaNote } from '../features/succes/noteFormats';
import {
  bornerZoom,
  ZOOM_MAX,
  ZOOM_MIN,
  ZOOM_PAS,
} from '../features/succes/noteZoom';
import { NoteFolderVisual } from '../features/succes/NoteFolderVisual';
import { countNotePages } from '../features/succes/notePages';
import { countNoteWords, sanitizeNoteHtml } from '../features/succes/noteSanitize';
import { RichNoteEditor } from '../features/succes/RichNoteEditor';
import { deplacerCategorie, grouperEnSections } from '../features/succes/notesSections';
import type {
  SuccesProject,
  SuccesNote,
  SuccesNoteDocLang,
  SuccesNotePageBackground,
  SuccesNotePageFormat,
  SuccesNotePageMargins,
  SuccesNotePageOrientation,
  SuccesNotePageSize,
} from '../features/succes/types';
import { useConfirm } from '../components/ConfirmDialog';
import { useAppStore } from '../lib/store';
import { useRefreshOnFocus } from '../features/succes/useRefreshOnFocus';
import { useContexteVue } from '../features/mesh/useContexteVue';

type SortMode = 'recent' | 'oldest' | 'name-asc' | 'name-desc';

const FOLDER_COLORS = [
  '#6366f1',
  '#0ea5e9',
  '#10b981',
  '#f59e0b',
  '#ef4444',
  '#ec4899',
  '#8b5cf6',
  '#64748b',
];

/** Les trois axes d'une note, hérités décomposés si elle ne les porte pas. */
function axesDeLaNote(note: {
  pageFormat?: SuccesNotePageFormat;
  pageSize?: SuccesNotePageSize;
  pageOrientation?: SuccesNotePageOrientation;
  pageMargins?: SuccesNotePageMargins;
}) {
  const mise = miseEnPageDeLaNote(note);
  return {
    pageSize: mise.size,
    pageOrientation: mise.orientation,
    pageMargins: mise.margins,
  };
}

const emptyMeta = () => ({
  // `pageFormat` reste écrit pour qu'une note neuve reste lisible par une
  // version antérieure de l'app ; les trois axes sont la vérité.
  pageFormat: 'a4' as SuccesNotePageFormat,
  pageSize: 'a4' as SuccesNotePageSize,
  pageOrientation: 'portrait' as SuccesNotePageOrientation,
  pageMargins: 'normales' as SuccesNotePageMargins,
  pageBackground: 'default' as SuccesNotePageBackground,
  fontFamily: 'Special Elite',
  docLang: 'fr' as SuccesNoteDocLang,
  color: FOLDER_COLORS[0],
  readingMark: 0,
});

export function SuccesNotesPage() {
  const confirm = useConfirm();
  const [notes, setNotes] = useState<SuccesNote[]>([]);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortMode>('recent');
  const [view, setView] = useState<'list' | 'editor'>('list');
  const [activeId, setActiveId] = useState<string | null>(null);


  // Le référent de « cette note » (handoff, 25/08/2026).
  const noteOuverte = notes.find((note) => note.id === activeId) ?? null;
  useContexteVue(
    noteOuverte
      ? { type: 'note', id: noteOuverte.id, title: noteOuverte.title }
      : null,
  );
  const [draftTitle, setDraftTitle] = useState('Sans titre');
  const [draftContent, setDraftContent] = useState('');
  const [meta, setMeta] = useState(emptyMeta());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [formNoteId, setFormNoteId] = useState<string | null>(null);
  const [formDraft, setFormDraft] = useState({
    title: '',
    color: FOLDER_COLORS[0],
    category: '',
    projectId: '',
  });
  /** L'ordre des sections, celui du serveur — le glisser de l'utilisateur. */
  const [categories, setCategories] = useState<string[]>([]);
  const [projects, setProjects] = useState<SuccesProject[]>([]);
  /** La catégorie en cours de renommage dans son en-tête, et son brouillon. */
  const [renommage, setRenommage] = useState<{ nom: string; brouillon: string } | null>(null);
  const [cibleSection, setCibleSection] = useState<string | null>(null);
  const autoSaveRef = useRef<number | null>(null);
  const draftRef = useRef({ title: 'Sans titre', content: '', meta: emptyMeta(), activeId: null as string | null });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await listSuccesNotes(search);
      setNotes(next);
      // L'ordre des sections et les projets (pour la pastille et le menu).
      // Non bloquants : la liste des notes vaut mieux seule que pas du tout.
      void listNoteCategories().then(setCategories).catch(() => {});
      void listSuccesProjects().then(setProjects).catch(() => {});
      if (activeId && !next.some((note) => note.id === activeId)) {
        setActiveId(null);
        setView('list');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'error',
        category: 'succes',
        message: `Notes : ${message}`,
      });
      toast.error('Les notes ne peuvent pas être chargées.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [activeId, search]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load]);

  // Une page ouverte gardait son état indéfiniment : ce qui change
  // ailleurs — téléphone, autre fenêtre, assistant — n'apparaissait
  // jamais. On relit au retour du focus.
  useRefreshOnFocus(() => void load());

  useEffect(() => {
    draftRef.current = { title: draftTitle, content: draftContent, meta, activeId };
  }, [draftTitle, draftContent, meta, activeId]);

  const sortedNotes = useMemo(() => {
    const copy = [...notes];
    copy.sort((a, b) => {
      if (sort === 'recent') return b.updatedAtMs - a.updatedAtMs;
      if (sort === 'oldest') return a.updatedAtMs - b.updatedAtMs;
      if (sort === 'name-asc') return a.title.localeCompare(b.title, 'fr');
      return b.title.localeCompare(a.title, 'fr');
    });
    return copy;
  }, [notes, sort]);

  const openNote = (note: SuccesNote) => {
    setActiveId(note.id);
    setDraftTitle(note.title);
    setDraftContent(note.content);
    setMeta({
      pageFormat: note.pageFormat || 'a4',
      ...axesDeLaNote(note),
      pageBackground: note.pageBackground || 'default',
      fontFamily: note.fontFamily || 'Special Elite',
      docLang: note.docLang || 'fr',
      color: note.color || FOLDER_COLORS[0],
      readingMark: note.readingMark || 0,
    });
    setDirty(false);
    setView('editor');
  };

  // Un autre appareil peut demander « montre-moi cette note ». On passe par
  // openNote plutôt que par setActiveId : c'est lui qui charge le contenu et
  // bascule en mode éditeur, et court-circuiter cela ouvrirait une note vide.
  const pendingMeshSelection = useAppStore((s) => s.pendingMeshSelection);
  const setPendingMeshSelection = useAppStore((s) => s.setPendingMeshSelection);
  useEffect(() => {
    if (pendingMeshSelection?.kind !== 'note' || loading) return;
    const wanted = notes.find((note) => note.id === pendingMeshSelection.id);
    // Absente en local : l'appareil émetteur est peut-être en avance sur la
    // synchronisation. On abandonne sans bruit plutôt que d'ouvrir autre chose.
    if (wanted) openNote(wanted);
    setPendingMeshSelection(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingMeshSelection, notes, loading, setPendingMeshSelection]);

  const openCreateForm = () => {
    setFormNoteId(null);
    setFormDraft({ title: '', color: FOLDER_COLORS[0], category: '', projectId: '' });
    setFormOpen(true);
  };

  const openEditForm = (note: SuccesNote) => {
    setFormNoteId(note.id);
    setFormDraft({
      title: note.title,
      color: note.color || FOLDER_COLORS[0],
      category: note.category || '',
      projectId: note.projectId || '',
    });
    setFormOpen(true);
  };

  const closeFormNow = () => {
    setFormOpen(false);
    setFormNoteId(null);
    setFormDraft({ title: '', color: FOLDER_COLORS[0], category: '', projectId: '' });
  };

  const closeForm = async () => {
    const source = formNoteId ? notes.find((note) => note.id === formNoteId) : null;
    const dirtyForm = formNoteId
      ? formDraft.title !== (source?.title ?? '') ||
        formDraft.color !== (source?.color ?? FOLDER_COLORS[0]) ||
        formDraft.category !== (source?.category ?? '') ||
        formDraft.projectId !== (source?.projectId ?? '')
      : Boolean(formDraft.title.trim()) ||
        formDraft.color !== FOLDER_COLORS[0] ||
        Boolean(formDraft.category) ||
        Boolean(formDraft.projectId);
    if (dirtyForm) {
      const confirmed = await confirm({
        title: formNoteId ? 'Annuler les modifications ?' : 'Annuler la création ?',
        description: 'Les changements non enregistrés seront perdus.',
        confirmLabel: 'Annuler',
        keepLabel: 'Continuer',
        tone: 'danger',
      });
      if (!confirmed) return;
    }
    closeFormNow();
  };

  const submitForm = async () => {
    const title = formDraft.title.trim() || 'Sans titre';
    setSaving(true);
    try {
      if (formNoteId) {
        const saved = await updateSuccesNote(formNoteId, {
          title,
          color: formDraft.color,
          category: formDraft.category.trim(),
          projectId: formDraft.projectId,
        });
        setNotes((prev) => prev.map((note) => (note.id === saved.id ? saved : note)));
        toast.success('Note mise à jour');
        closeFormNow();
      } else {
        const saved = await createSuccesNote({
          title,
          content: '',
          ...emptyMeta(),
          color: formDraft.color,
          category: formDraft.category.trim(),
          projectId: formDraft.projectId,
        });
        setNotes((prev) => [saved, ...prev]);
        toast.success('Note créée', { description: 'Enregistrée localement sur ce Mac.' });
        closeFormNow();
        openNote(saved);
      }
    } catch (error) {
      toast.error("La note n'a pas été enregistrée.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const removeNote = async (note: SuccesNote) => {
    const confirmed = await confirm({
      title: `Supprimer la note « ${note.title || 'Sans titre'} » ?`,
      description: 'Cette note sera définitivement retirée de ce Mac.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    setSaving(true);
    try {
      await deleteSuccesNote(note.id);
      toast.success('Note supprimée');
      if (formNoteId === note.id) closeFormNow();
      await load();
    } catch (error) {
      toast.error('La suppression a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  /** Glisser un cartable sur une section : la note change de catégorie. */
  const deposerNoteSurSection = async (noteId: string, nomSection: string) => {
    const note = notes.find((n) => n.id === noteId);
    if (!note || (note.category || '') === nomSection) return;
    setSaving(true);
    try {
      const saved = await updateSuccesNote(noteId, { category: nomSection });
      setNotes((prev) => prev.map((n) => (n.id === saved.id ? saved : n)));
      void listNoteCategories().then(setCategories).catch(() => {});
      toast.success(nomSection ? `Classée dans « ${nomSection} »` : 'Sortie de sa catégorie');
    } catch (error) {
      toast.error('Le classement a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  /** Glisser un en-tête de section avant un autre : l'ordre est mémorisé. */
  const deposerCategorieAvant = async (nom: string, avant: string) => {
    const suivant = deplacerCategorie(categories, nom, avant);
    if (suivant.join('\u0000') === categories.join('\u0000')) return;
    setCategories(suivant);
    try {
      setCategories(await orderNoteCategories(suivant));
    } catch (error) {
      toast.error("L'ordre n'a pas été enregistré.", {
        description: error instanceof Error ? error.message : String(error),
      });
      void listNoteCategories().then(setCategories).catch(() => {});
    }
  };

  const validerRenommage = async () => {
    if (!renommage) return;
    const nouveau = renommage.brouillon.trim();
    const ancien = renommage.nom;
    setRenommage(null);
    if (!nouveau || nouveau === ancien) return;
    setSaving(true);
    try {
      setCategories(await renameNoteCategory(ancien, nouveau));
      await load();
      toast.success(`« ${ancien} » devient « ${nouveau} »`);
    } catch (error) {
      toast.error('Le renommage a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const dissoudreCategorie = async (nom: string) => {
    const confirmed = await confirm({
      title: `Dissoudre « ${nom} » ?`,
      description: 'Ses notes redeviennent « sans catégorie ». Aucune note n’est supprimée.',
      confirmLabel: 'Dissoudre',
      keepLabel: 'Garder',
      tone: 'warning',
    });
    if (!confirmed) return;
    setSaving(true);
    try {
      setCategories(await renameNoteCategory(nom, ''));
      await load();
      toast.success(`Catégorie « ${nom} » dissoute`);
    } catch (error) {
      toast.error('La dissolution a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const backToList = async () => {
    if (dirty) await persist(true);
    setView('list');
    setDirty(false);
    await load();
  };

  const persist = async (silent = false) => {
    const snapshot = draftRef.current;
    const title = snapshot.title.trim() || 'Sans titre';
    setSaving(true);
    try {
      const payload = {
        title,
        content: sanitizeNoteHtml(snapshot.content),
        ...snapshot.meta,
      };
      const saved = snapshot.activeId
        ? await updateSuccesNote(snapshot.activeId, payload)
        : await createSuccesNote(payload);
      setActiveId(saved.id);
      setDraftTitle(saved.title);
      setDraftContent(saved.content);
      setMeta({
        pageFormat: saved.pageFormat || 'a4',
        ...axesDeLaNote(saved),
        pageBackground: saved.pageBackground || 'default',
        fontFamily: saved.fontFamily || 'Special Elite',
        docLang: saved.docLang || 'fr',
        color: saved.color || FOLDER_COLORS[0],
        readingMark: saved.readingMark || 0,
      });
      setDirty(false);
      setNotes((prev) => {
        const without = prev.filter((note) => note.id !== saved.id);
        return [saved, ...without];
      });
      if (!silent) {
        toast.success(snapshot.activeId ? 'Note mise à jour' : 'Note créée', {
          description: 'Enregistrée localement sur ce Mac.',
        });
      }
      return saved;
    } catch (error) {
      toast.error("La note n'a pas été enregistrée.", {
        description: error instanceof Error ? error.message : String(error),
      });
      return null;
    } finally {
      setSaving(false);
    }
  };

  const scheduleAutoSave = () => {
    setDirty(true);
    if (autoSaveRef.current) window.clearTimeout(autoSaveRef.current);
    autoSaveRef.current = window.setTimeout(() => {
      void persist(true);
    }, 1500);
  };

  useEffect(() => {
    return () => {
      if (autoSaveRef.current) window.clearTimeout(autoSaveRef.current);
    };
  }, []);

  const remove = async () => {
    if (!activeId) return;
    const title = draftTitle.trim() || 'Sans titre';
    const confirmed = await confirm({
      title: `Supprimer la note « ${title} » ?`,
      description: 'Cette note sera définitivement retirée de ce Mac.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    setSaving(true);
    try {
      await deleteSuccesNote(activeId);
      toast.success('Note supprimée');
      setView('list');
      setActiveId(null);
      setDirty(false);
      await load();
    } catch (error) {
      toast.error('La suppression a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const duplicate = async () => {
    const source = notes.find((note) => note.id === activeId);
    if (!source && !draftTitle.trim()) return;
    setSaving(true);
    try {
      if (dirty) await persist(true);
      const saved = await createSuccesNote({
        title: `${(source?.title || draftTitle).trim() || 'Sans titre'} (copie)`,
        content: source?.content ?? draftContent,
        pageFormat: source?.pageFormat ?? meta.pageFormat,
        pageSize: source?.pageSize ?? meta.pageSize,
        pageOrientation: source?.pageOrientation ?? meta.pageOrientation,
        pageMargins: source?.pageMargins ?? meta.pageMargins,
        pageBackground: source?.pageBackground ?? meta.pageBackground,
        fontFamily: source?.fontFamily ?? meta.fontFamily,
        docLang: source?.docLang ?? meta.docLang,
        color: source?.color ?? meta.color,
      });
      toast.success('Note dupliquée');
      openNote(saved);
      await load();
    } catch (error) {
      toast.error('La duplication a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const wordCount = countNoteWords(draftContent);
  // Le compte que l'ÉDITEUR remonte après avoir posé ses cales. `null` tant
  // qu'il n'a pas encore mesuré — au premier rendu, et pour une note vide.
  // `countNotePages` ne sert alors que de valeur d'attente : il compte des
  // caractères, et affichait « 20 pages » sous un éditeur qui en dessinait 43.
  const [feuillesMesurees, setFeuillesMesurees] = useState<number | null>(null);
  // `null` = « Largeur de page ». La réglette écrit ici, l'éditeur renvoie le
  // zoom réellement appliqué pour que le pour cent affiché ne mente pas.
  const [zoomVoulu, setZoomVoulu] = useState<number | null>(null);
  const [zoomEffectif, setZoomEffectif] = useState(1);
  const [pageCourante, setPageCourante] = useState(1);
  const [navigationOuverte, setNavigationOuverte] = useState(false);
  // Le jeton change à chaque demande de saut, y compris vers la même page :
  // sans lui, cliquer deux fois sur « Reprendre p. 12 » ne ferait rien la
  // seconde fois, la valeur n'ayant pas changé.
  const [saut, setSaut] = useState<{ page: number; jeton: number } | null>(null);
  const jetonDeSaut = useRef(0);

  /**
   * Poser, atteindre ou retirer le signet de lecture.
   *
   * Enregistré TOUT DE SUITE, sans attendre la sauvegarde différée : on pose
   * un signet précisément quand on s'apprête à fermer, et un signet perdu à la
   * fermeture ne sert à rien.
   */
  const poserLeSignet = async (page: number) => {
    setMeta((m) => ({ ...m, readingMark: page }));
    if (!activeId) return;
    try {
      const saved = await updateSuccesNote(activeId, { readingMark: page });
      setNotes((liste) =>
        liste.map((n) => (n.id === saved.id ? { ...n, readingMark: saved.readingMark } : n)),
      );
    } catch {
      // Le serveur n'a pas pris : on ne ment pas sur l'état enregistré.
      setMeta((m) => ({ ...m, readingMark: noteOuverte?.readingMark || 0 }));
    }
  };
  // PAS de remise à zéro par `useEffect` sur `activeId` : `useLayoutEffect`
  // — donc la pagination de l'éditeur, donc `onPageCount` — s'exécute AVANT
  // les `useEffect`. Une remise à zéro écrite là efface le compte à l'instant
  // même où il arrive, et le pied de page reste éternellement sur
  // l'estimation. Constaté ici : 20 pages affichées pour 43 feuilles, malgré
  // un câblage par ailleurs correct.
  //
  // L'éditeur remonte son compte à chaque pagination, montage compris : la
  // valeur se corrige d'elle-même dans la même passe de rendu.
  const draftPages = feuillesMesurees ?? countNotePages(draftContent, meta.pageFormat);

  if (view === 'editor') {
    return (
      <div className="flex-1 overflow-hidden px-5 py-6 md:px-8 md:py-8">
        <main className="max-w-6xl mx-auto w-full h-full flex flex-col min-h-0">
          <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4 shrink-0">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <button
                type="button"
                onClick={() => void backToList()}
                className="size-9 rounded-xl flex items-center justify-center cursor-pointer shrink-0"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                aria-label="Retour à la liste"
              >
                <ArrowLeft size={16} />
              </button>
              <input
                value={draftTitle}
                onChange={(event) => {
                  setDraftTitle(event.target.value);
                  scheduleAutoSave();
                }}
                maxLength={200}
                placeholder="Titre de la note"
                className="flex-1 min-w-0 bg-transparent outline-none text-xl font-semibold"
                style={{ color: 'var(--color-text)', fontFamily: 'inherit' }}
              />
              {saving && <Loader2 size={14} className="animate-spin shrink-0" style={{ color: 'var(--color-accent)' }} />}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {activeId && (
                <>
                  <button
                    type="button"
                    onClick={() => void duplicate()}
                    className="size-9 rounded-xl flex items-center justify-center cursor-pointer"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                    aria-label="Dupliquer"
                  >
                    <Copy size={15} />
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove()}
                    className="size-9 rounded-xl flex items-center justify-center cursor-pointer"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}
                    aria-label="Supprimer"
                  >
                    <Trash2 size={15} />
                  </button>
                </>
              )}
              <button
                type="button"
                disabled={saving}
                onClick={() => void persist(false)}
                className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                <Save size={15} /> {dirty ? 'Enregistrer' : 'Enregistré'}
              </button>
            </div>
          </header>

          <RichNoteEditor
            editorKey={activeId ?? 'new'}
            content={draftContent}
            pageFormat={meta.pageFormat}
            pageSize={meta.pageSize}
            pageOrientation={meta.pageOrientation}
            pageMargins={meta.pageMargins}
            pageBackground={meta.pageBackground}
            fontFamily={meta.fontFamily}
            docLang={meta.docLang}
            color={meta.color}
            onPageCount={setFeuillesMesurees}
            zoom={zoomVoulu}
            onZoomEffectif={setZoomEffectif}
            onPageCourante={setPageCourante}
            navigation={navigationOuverte}
            onFermerNavigation={() => setNavigationOuverte(false)}
            marqueur={meta.readingMark}
            saut={saut}
            onContentChange={(html) => {
              setDraftContent(html);
              scheduleAutoSave();
            }}
            onMetaChange={(patch) => {
              setMeta((prev) => ({ ...prev, ...patch }));
              scheduleAutoSave();
            }}
          />

          {/* La barre d'état, disposée comme celle de Word : le décompte et
              la langue à GAUCHE, la réglette de zoom à DROITE. Les trois
              contrôles vivaient dans la barre d'outils du haut, où l'on ne
              les cherche pas. */}
          {/* Le pied s'adapte à SA largeur (container queries), pas à celle
              de la fenêtre : en fenêtre réduite, ses deux groupes se
              chevauchaient sur deux rangées (13 septembre 2026). Les mots
              cèdent avant les commandes — l'état, puis l'étiquette du signet,
              puis les tirets — et le curseur de zoom raccourcit. */}
          <div
            className="@container flex flex-nowrap items-center justify-between gap-x-3 pt-3 text-[11px] shrink-0 min-w-0"
            style={{ color: 'var(--color-text-tertiary)', borderTop: '1px solid var(--color-border)' }}
          >
            <span className="flex items-center gap-2 min-w-0 shrink">
              {/* « Page 3 sur 47 », comme Word : le total seul ne dit pas où
                  l'on se trouve. Et comme dans Word, cliquer dessus ouvre le
                  volet de navigation — miniatures des pages et plan des
                  titres. */}
              <button
                type="button"
                onClick={() => setNavigationOuverte((v) => !v)}
                aria-pressed={navigationOuverte}
                title="Numéro de la page actuelle. Cliquez pour ouvrir le volet de navigation."
                className="tabular-nums px-1.5 rounded cursor-pointer"
                style={{
                  border: '1px solid var(--color-border)',
                  color: navigationOuverte ? 'var(--color-accent)' : 'inherit',
                }}
              >
                Page {Math.min(pageCourante, draftPages)} sur {draftPages}
              </button>
              {/* LE SIGNET DE LECTURE.
                  Un document de soixante et une pages se lit en plusieurs
                  fois. Rien ne retenait l'endroit : rouvrir ramenait en haut,
                  et retrouver sa place se faisait à la molette et de mémoire. */}
              {meta.readingMark > 0 ? (
                <span
                  className="inline-flex items-center rounded overflow-hidden"
                  style={{ border: '1px solid var(--color-accent)' }}
                >
                  <button
                    type="button"
                    onClick={() => {
                      jetonDeSaut.current += 1;
                      setSaut({ page: meta.readingMark, jeton: jetonDeSaut.current });
                    }}
                    title={`Reprendre la lecture page ${meta.readingMark}`}
                    className="tabular-nums px-1.5 flex items-center gap-1 cursor-pointer"
                    style={{ color: 'var(--color-accent)' }}
                  >
                    <Bookmark size={11} fill="currentColor" />
                    Reprendre p. {meta.readingMark}
                  </button>
                  <button
                    type="button"
                    onClick={() => void poserLeSignet(0)}
                    aria-label="Retirer le signet"
                    title="Retirer le signet"
                    className="px-1 cursor-pointer"
                    style={{
                      color: 'var(--color-text-tertiary)',
                      borderLeft: '1px solid var(--color-border)',
                    }}
                  >
                    <X size={11} />
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => void poserLeSignet(Math.min(pageCourante, draftPages))}
                  title="Marquer cette page pour reprendre la lecture plus tard"
                  className="px-1.5 rounded flex items-center gap-1 cursor-pointer"
                  style={{ border: '1px solid var(--color-border)' }}
                >
                  <Bookmark size={11} />
                  <span className="hidden @2xl:inline">Marquer ma page</span>
                </button>
              )}
              <span aria-hidden="true" className="hidden @2xl:inline">—</span>
              <span className="tabular-nums whitespace-nowrap">
                {wordCount.toLocaleString('fr-CA')} mot{wordCount === 1 ? '' : 's'}
              </span>
              <span aria-hidden="true" className="hidden @2xl:inline">—</span>
              <select
                aria-label="Langue du document"
                title="Langue du document"
                value={meta.docLang}
                onChange={(event) => {
                  setMeta((m) => ({
                    ...m,
                    docLang: event.target.value as SuccesNoteDocLang,
                  }));
                  setDirty(true);
                  scheduleAutoSave();
                }}
                className="bg-transparent outline-none cursor-pointer text-[11px]"
                style={{ color: 'inherit', border: 'none' }}
              >
                {NOTE_DOC_LANGS.map((lang) => (
                  <option key={lang.id} value={lang.id}>
                    {lang.label}
                  </option>
                ))}
              </select>
            </span>
            <span className="flex items-center gap-2 shrink-0 ml-auto">
              <span className="hidden @3xl:inline whitespace-nowrap">
                {dirty
                  ? 'Modifications non enregistrées…'
                  : activeId
                    ? 'Synchronisé localement'
                    : 'Nouvelle note locale'}
              </span>
              <button
                type="button"
                title="Largeur de page"
                onClick={() => setZoomVoulu(null)}
                className="px-1.5 rounded cursor-pointer"
                style={{ border: '1px solid var(--color-border)', color: 'inherit' }}
              >
                Ajuster
              </button>
              <button
                type="button"
                aria-label="Réduire le zoom"
                onClick={() => setZoomVoulu(bornerZoom(zoomEffectif - ZOOM_PAS))}
                className="px-1.5 cursor-pointer"
                style={{ color: 'inherit' }}
              >
                −
              </button>
              <input
                type="range"
                aria-label="Zoom"
                min={ZOOM_MIN * 100}
                max={ZOOM_MAX * 100}
                step={ZOOM_PAS * 100}
                value={Math.round(zoomEffectif * 100)}
                onChange={(event) => setZoomVoulu(bornerZoom(Number(event.target.value) / 100))}
                className="w-14 @2xl:w-24 @4xl:w-32 cursor-pointer"
              />
              <button
                type="button"
                aria-label="Augmenter le zoom"
                onClick={() => setZoomVoulu(bornerZoom(zoomEffectif + ZOOM_PAS))}
                className="px-1.5 cursor-pointer"
                style={{ color: 'inherit' }}
              >
                +
              </button>
              <span className="tabular-nums w-11 text-right">
                {Math.round(zoomEffectif * 100)} %
              </span>
            </span>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
      <main className="max-w-6xl mx-auto w-full">
        <header className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between mb-6">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>
                Succès
              </span>
              {loading && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}
            </div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
              Notes
            </h1>
            <p className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
              Traitement de texte riche, formats de page et enregistrement local.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              if (formOpen) void closeForm();
              else openCreateForm();
            }}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            <FilePlus2 size={16} /> Nouvelle note
          </button>
        </header>

        {formOpen && (
          <section
            className="grid gap-3 rounded-2xl p-4 mb-5"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}
          >
            <input
              autoFocus
              value={formDraft.title}
              onChange={(event) => setFormDraft({ ...formDraft, title: event.target.value })}
              maxLength={200}
              placeholder="Titre de la note"
              className="rounded-xl px-3 py-2.5 bg-transparent outline-none"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                Couleur du cartable
              </span>
              {FOLDER_COLORS.map((swatch) => (
                <button
                  key={swatch}
                  type="button"
                  aria-label={`Couleur ${swatch}`}
                  onClick={() => setFormDraft({ ...formDraft, color: swatch })}
                  className="size-6 rounded-full cursor-pointer"
                  style={{
                    background: swatch,
                    boxShadow:
                      formDraft.color === swatch
                        ? '0 0 0 2px var(--color-surface), 0 0 0 4px var(--color-accent)'
                        : 'inset 0 0 0 1px rgba(0,0,0,0.25)',
                  }}
                />
              ))}
              <input
                type="color"
                value={formDraft.color}
                onChange={(event) => setFormDraft({ ...formDraft, color: event.target.value })}
                aria-label="Couleur personnalisée"
                title="Ouvrir la palette complète"
                className="size-8 rounded-lg bg-transparent cursor-pointer"
                style={{ border: '1px solid var(--color-border)' }}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-1.5 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                Catégorie
                <input
                  value={formDraft.category}
                  onChange={(event) => setFormDraft({ ...formDraft, category: event.target.value })}
                  maxLength={60}
                  list="notes-categories"
                  placeholder="Aucune — tapez pour en créer une"
                  className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
                <datalist id="notes-categories">
                  {categories.map((nom) => (
                    <option key={nom} value={nom} />
                  ))}
                </datalist>
              </label>
              <label className="grid gap-1.5 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                Projet
                <select
                  value={formDraft.projectId}
                  onChange={(event) => setFormDraft({ ...formDraft, projectId: event.target.value })}
                  className="rounded-xl px-3 py-2 outline-none text-sm h-[38px]"
                  style={{
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                    background: 'var(--color-surface)',
                  }}
                >
                  <option value="">Aucun</option>
                  {projects.map((projet) => (
                    <option key={projet.id} value={projet.id}>
                      {projet.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              Format de page, fond, police et langue se règlent ensuite dans l’éditeur.
            </p>
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
                disabled={saving}
                onClick={() => void submitForm()}
                className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                {formNoteId ? 'Mettre à jour' : 'Créer la note'}
              </button>
            </div>
          </section>
        )}

        <div className="flex flex-col sm:flex-row gap-3 mb-5">
          <div
            className="flex items-center gap-2 flex-1 rounded-xl px-3 h-10"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          >
            <Search size={14} style={{ color: 'var(--color-text-tertiary)' }} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Rechercher…"
              className="w-full bg-transparent outline-none text-sm"
              style={{ color: 'var(--color-text)' }}
            />
          </div>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as SortMode)}
            className="h-10 rounded-xl px-3 text-sm bg-transparent outline-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)', background: 'var(--color-surface)' }}
            aria-label="Trier les notes"
          >
            <option value="recent">Modification (récent)</option>
            <option value="oldest">Modification (ancien)</option>
            <option value="name-asc">Nom (A→Z)</option>
            <option value="name-desc">Nom (Z→A)</option>
          </select>
        </div>

        {loading && !notes.length ? (
          <div className="flex justify-center gap-2 py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
            <Loader2 size={17} className="animate-spin" /> Chargement…
          </div>
        ) : sortedNotes.length === 0 ? (
          <div
            className="rounded-2xl py-16 text-center"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          >
            <NotebookPen size={28} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} />
            <p className="font-medium" style={{ color: 'var(--color-text)' }}>
              Aucune note
            </p>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
              Cliquez sur Nouvelle note pour commencer.
            </p>
          </div>
        ) : (
          <div className="grid gap-1">
            {grouperEnSections(sortedNotes, categories).map((section) => (
              <section
                key={section.nom || '\u2205'}
                onDragOver={(event) => {
                  if (!event.dataTransfer.types.includes('application/x-diapason-note')) return;
                  event.preventDefault();
                  setCibleSection(section.nom);
                }}
                onDragLeave={() =>
                  setCibleSection((c) => (c === section.nom ? null : c))
                }
                onDrop={(event) => {
                  const id = event.dataTransfer.getData('application/x-diapason-note');
                  setCibleSection(null);
                  if (!id) return;
                  event.preventDefault();
                  void deposerNoteSurSection(id, section.nom);
                }}
                className="rounded-2xl px-2 pb-1 transition-colors"
                style={{
                  background:
                    cibleSection === section.nom
                      ? 'color-mix(in srgb, var(--color-accent) 8%, transparent)'
                      : 'transparent',
                }}
                aria-label={section.nom || 'Sans catégorie'}
              >
                {(section.nom !== '' || categories.length > 0) && (
                  <div
                    className="group/section flex items-center gap-3 pt-4 pb-3"
                    draggable={section.nom !== ''}
                    onDragStart={(event) => {
                      if (!section.nom) return;
                      event.dataTransfer.setData('application/x-diapason-categorie', section.nom);
                      event.dataTransfer.effectAllowed = 'move';
                    }}
                    onDragOver={(event) => {
                      if (!event.dataTransfer.types.includes('application/x-diapason-categorie'))
                        return;
                      event.preventDefault();
                      event.stopPropagation();
                    }}
                    onDrop={(event) => {
                      const nom = event.dataTransfer.getData('application/x-diapason-categorie');
                      if (!nom) return;
                      event.preventDefault();
                      event.stopPropagation();
                      void deposerCategorieAvant(nom, section.nom);
                    }}
                    style={{ cursor: section.nom ? 'grab' : undefined, WebkitUserDrag: section.nom ? 'element' : undefined } as React.CSSProperties}
                  >
                    {renommage && renommage.nom === section.nom ? (
                      <input
                        autoFocus
                        value={renommage.brouillon}
                        maxLength={60}
                        onChange={(event) =>
                          setRenommage({ nom: section.nom, brouillon: event.target.value })
                        }
                        onBlur={() => void validerRenommage()}
                        onKeyDown={(event) => {
                          event.stopPropagation();
                          if (event.key === 'Enter') void validerRenommage();
                          if (event.key === 'Escape') setRenommage(null);
                        }}
                        className="text-xs font-semibold tracking-[0.14em] uppercase bg-transparent outline-none rounded px-1"
                        style={{ color: 'var(--color-text)', border: '1px solid var(--color-accent)' }}
                        aria-label="Renommer la catégorie"
                      />
                    ) : (
                      <h2
                        className="text-xs font-semibold tracking-[0.14em] uppercase shrink-0"
                        style={{ color: section.nom ? 'var(--color-text-secondary)' : 'var(--color-text-tertiary)' }}
                      >
                        {section.nom || 'Sans catégorie'}
                      </h2>
                    )}
                    <span className="text-[11px] tabular-nums shrink-0" style={{ color: 'var(--color-text-tertiary)' }}>
                      {section.notes.length}
                    </span>
                    {/* Le trait horizontal demandé : il part du nom et sépare la section. */}
                    <span aria-hidden="true" className="flex-1 h-px" style={{ background: 'var(--color-border)' }} />
                    {section.nom && (
                      <span className="flex gap-0.5 opacity-0 transition-opacity group-hover/section:opacity-100 focus-within:opacity-100">
                        <button
                          type="button"
                          onClick={() => setRenommage({ nom: section.nom, brouillon: section.nom })}
                          className="rounded-md p-1 cursor-pointer"
                          style={{ color: 'var(--color-text-tertiary)' }}
                          title="Renommer la catégorie"
                          aria-label={`Renommer ${section.nom}`}
                        >
                          <Pencil size={12} />
                        </button>
                        <button
                          type="button"
                          onClick={() => void dissoudreCategorie(section.nom)}
                          className="rounded-md p-1 cursor-pointer"
                          style={{ color: 'var(--color-text-tertiary)' }}
                          title="Dissoudre la catégorie (les notes restent)"
                          aria-label={`Dissoudre ${section.nom}`}
                        >
                          <X size={12} />
                        </button>
                      </span>
                    )}
                  </div>
                )}
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-4 gap-y-2">
            {section.notes.map((note) => {
              const pages = countNotePages(note.content, note.pageFormat);
              return (
                <article
                  key={note.id}
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.setData('application/x-diapason-note', note.id);
                    event.dataTransfer.effectAllowed = 'move';
                  }}
                  className="group relative flex flex-col items-center"
                  style={{ WebkitUserDrag: 'element' } as React.CSSProperties}
                >
                  <button
                    type="button"
                    onClick={() => openNote(note)}
                    className="w-full cursor-pointer bg-transparent border-0 p-0 text-inherit"
                    aria-label={`Ouvrir ${note.title}`}
                  >
                    <NoteFolderVisual
                      color={note.color || FOLDER_COLORS[0]}
                      sheets={Math.min(3, pages)}
                    />
                    <h2
                      className="max-w-full truncate text-sm font-medium text-center px-2 pb-1"
                      title={note.title}
                      style={{ color: 'var(--color-text)' }}
                    >
                      {note.title}
                    </h2>
                    <p className="text-[11px] pb-4 flex items-center justify-center gap-1.5" style={{ color: 'var(--color-text-tertiary)' }}>
                      {(() => {
                        const projet = note.projectId
                          ? projects.find((item) => item.id === note.projectId)
                          : null;
                        return projet ? (
                          <span
                            className="inline-flex items-center gap-1 max-w-[9rem] truncate"
                            title={`Rattachée au projet ${projet.name}`}
                          >
                            <span
                              aria-hidden="true"
                              className="size-1.5 rounded-full shrink-0"
                              style={{ background: projet.color || 'var(--color-accent)' }}
                            />
                            {projet.name}
                            <span aria-hidden="true">·</span>
                          </span>
                        ) : null;
                      })()}
                      {note.updatedAt
                        ? new Date(`${note.updatedAt}T12:00:00`).toLocaleDateString('fr-CA', {
                            day: 'numeric',
                            month: 'short',
                            year: 'numeric',
                          })
                        : ''}
                      {` · ${pages} page${pages === 1 ? '' : 's'}`}
                    </p>
                  </button>

                  <div className="absolute right-1 top-1 flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        openEditForm(note);
                      }}
                      aria-label={`Modifier ${note.title}`}
                      className="rounded-lg p-1.5 cursor-pointer"
                      style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-surface)' }}
                    >
                      <Pencil size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        void removeNote(note);
                      }}
                      aria-label={`Supprimer ${note.title}`}
                      className="rounded-lg p-1.5 cursor-pointer"
                      style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-surface)' }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </article>
              );
            })}
                </div>
              </section>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
