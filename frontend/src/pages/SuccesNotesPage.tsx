import { useCallback, useEffect, useMemo, useState } from 'react';
import { FilePlus2, Loader2, NotebookPen, Save, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import {
  createSuccesNote,
  deleteSuccesNote,
  listSuccesNotes,
  updateSuccesNote,
} from '../features/succes/api';
import type { SuccesNote } from '../features/succes/types';
import { useAppStore } from '../lib/store';

export function SuccesNotesPage() {
  const [notes, setNotes] = useState<SuccesNote[]>([]);
  const [search, setSearch] = useState('');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftContent, setDraftContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await listSuccesNotes(search);
      setNotes(next);
      if (activeId && !next.some((note) => note.id === activeId)) setActiveId(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `Notes : ${message}` });
      toast.error('Les notes ne peuvent pas être chargées.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [activeId, search]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load]);

  const active = useMemo(() => notes.find((note) => note.id === activeId) ?? null, [activeId, notes]);

  const select = (note: SuccesNote) => {
    setActiveId(note.id);
    setDraftTitle(note.title);
    setDraftContent(note.content);
  };

  const startNew = () => {
    setActiveId(null);
    setDraftTitle('');
    setDraftContent('');
  };

  const save = async () => {
    const title = draftTitle.trim();
    if (!title) return;
    setSaving(true);
    try {
      const saved = activeId
        ? await updateSuccesNote(activeId, { title, content: draftContent })
        : await createSuccesNote({ title, content: draftContent });
      setActiveId(saved.id);
      setDraftTitle(saved.title);
      setDraftContent(saved.content);
      await load();
      toast.success(activeId ? 'Note mise à jour' : 'Note créée', { description: 'Enregistrée localement sur ce Mac.' });
    } catch (error) {
      toast.error("La note n'a pas été enregistrée.", { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!active || !window.confirm(`Supprimer la note « ${active.title} » ?`)) return;
    setSaving(true);
    try {
      await deleteSuccesNote(active.id);
      startNew();
      await load();
      toast.success('Note supprimée');
    } catch (error) {
      toast.error('La suppression a échoué.', { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setSaving(false);
    }
  };

  const hasDraft = activeId !== null || draftTitle.length > 0 || draftContent.length > 0;

  return (
    <div className="flex-1 overflow-hidden px-5 py-8 md:px-8 md:py-10">
      <main className="max-w-6xl mx-auto w-full h-full flex flex-col">
        <header className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between mb-6 shrink-0">
          <div>
            <div className="flex items-center gap-2 mb-2"><span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>Succès</span>{saving && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}</div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>Notes</h1>
            <p className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>Vos idées restent privées, recherchables et disponibles hors ligne.</p>
          </div>
          <button type="button" onClick={startNew} className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}><FilePlus2 size={16} /> Nouvelle note</button>
        </header>

        <section className="grid md:grid-cols-[300px_1fr] min-h-0 flex-1 rounded-2xl overflow-hidden" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <aside className="min-h-0 flex flex-col" style={{ borderRight: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}>
            <div className="flex items-center gap-2 p-3" style={{ borderBottom: '1px solid var(--color-border)' }}><Search size={14} style={{ color: 'var(--color-text-tertiary)' }} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher…" className="w-full bg-transparent outline-none text-sm" style={{ color: 'var(--color-text)' }} /></div>
            <div className="overflow-y-auto p-2 grid gap-1">
              {loading ? <div className="flex items-center justify-center gap-2 py-10 text-xs" style={{ color: 'var(--color-text-tertiary)' }}><Loader2 size={14} className="animate-spin" /> Chargement…</div> : notes.length === 0 ? <div className="text-center py-10 px-4"><NotebookPen size={23} className="mx-auto mb-2" style={{ color: 'var(--color-accent)' }} /><p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Aucune note trouvée</p></div> : notes.map((note) => <button key={note.id} type="button" onClick={() => select(note)} className="text-left rounded-xl p-3 cursor-pointer" style={{ background: note.id === activeId ? 'var(--color-surface)' : 'transparent', border: note.id === activeId ? '1px solid var(--color-border)' : '1px solid transparent' }}><p className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>{note.title}</p><p className="text-xs mt-1 line-clamp-2" style={{ color: 'var(--color-text-tertiary)' }}>{note.content || 'Note vide'}</p></button>)}
            </div>
          </aside>

          <div className="min-h-0 flex flex-col p-4 md:p-6">
            {hasDraft ? <>
              <div className="flex items-center gap-2 mb-4">
                <input autoFocus value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} maxLength={200} placeholder="Titre de la note" className="flex-1 min-w-0 bg-transparent outline-none text-xl font-semibold" style={{ color: 'var(--color-text)' }} />
                {active && <button type="button" onClick={() => void remove()} aria-label="Supprimer" className="p-2 cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}><Trash2 size={16} /></button>}
                <button type="button" disabled={!draftTitle.trim() || saving} onClick={() => void save()} className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}><Save size={15} /> Enregistrer</button>
              </div>
              <textarea value={draftContent} onChange={(event) => setDraftContent(event.target.value)} maxLength={100000} placeholder="Écrivez librement…" className="flex-1 min-h-[300px] resize-none bg-transparent outline-none text-sm leading-7" style={{ color: 'var(--color-text-secondary)' }} />
              <div className="flex justify-between pt-3 text-[11px]" style={{ color: 'var(--color-text-tertiary)', borderTop: '1px solid var(--color-border)' }}><span>{draftContent.length.toLocaleString('fr-CA')} caractère(s)</span><span>{active ? `Modifiée ${active.updatedAt || ''}` : 'Nouvelle note locale'}</span></div>
            </> : <div className="flex-1 flex flex-col items-center justify-center text-center"><NotebookPen size={34} className="mb-3" style={{ color: 'var(--color-accent)' }} /><p className="font-medium" style={{ color: 'var(--color-text)' }}>Sélectionnez ou créez une note</p><p className="text-sm mt-1 max-w-sm" style={{ color: 'var(--color-text-tertiary)' }}>DIA pourra ensuite retrouver et organiser ces informations avec vous.</p></div>}
          </div>
        </section>
      </main>
    </div>
  );
}
