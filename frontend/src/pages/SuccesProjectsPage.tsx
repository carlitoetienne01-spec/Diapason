import { useCallback, useEffect, useState, type PointerEvent } from 'react';
import { BriefcaseBusiness, CirclePlus, Loader2, Pencil, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import projectFolder3d from '../assets/succes-project-folder-3d.png';
import {
  createSuccesProject,
  deleteSuccesProject,
  listSuccesProjects,
  updateSuccesProject,
} from '../features/succes/api';
import type { SuccesProject } from '../features/succes/types';
import { useAppStore } from '../lib/store';

const emptyDraft = {
  name: '', description: '', icon: '', color: '#6366f1', startDate: '', endDate: '',
};

function ProjectFolderVisual({ project }: { project: SuccesProject }) {
  const [tilt, setTilt] = useState({ x: 0, y: 0, glareX: 50, glareY: 50 });
  const [active, setActive] = useState(false);

  const followPointer = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const glareX = ((event.clientX - bounds.left) / bounds.width) * 100;
    const glareY = ((event.clientY - bounds.top) / bounds.height) * 100;
    setTilt({
      x: (glareX / 100 - 0.5) * 9,
      y: -(glareY / 100 - 0.5) * 7,
      glareX,
      glareY,
    });
  };

  const reset = () => {
    setActive(false);
    setTilt({ x: 0, y: 0, glareX: 50, glareY: 50 });
  };

  return (
    <div
      aria-hidden="true"
      className="relative h-64 overflow-hidden"
      onPointerEnter={() => setActive(true)}
      onPointerMove={followPointer}
      onPointerLeave={reset}
      style={{
        perspective: '950px',
        background: '#020c15',
        borderBottom: `1px solid ${project.color}30`,
      }}
    >
      <div
        className="absolute inset-3 overflow-hidden rounded-2xl"
        style={{
          transform: `rotateX(${tilt.y}deg) rotateY(${tilt.x}deg) scale(${active ? 1.025 : 1})`,
          transformStyle: 'preserve-3d',
          transition: active ? 'transform 80ms linear' : 'transform 420ms cubic-bezier(.2,.8,.2,1)',
          boxShadow: active
            ? `0 24px 54px ${project.color}20, 0 8px 24px rgba(0,0,0,.48)`
            : '0 14px 34px rgba(0,0,0,.38)',
          willChange: 'transform',
        }}
      >
        <img
          src={projectFolder3d}
          alt=""
          draggable={false}
          className="absolute inset-0 h-full w-full select-none object-cover"
          style={{ transform: 'translateZ(26px) scale(1.055)' }}
        />
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background: `radial-gradient(circle at ${tilt.glareX}% ${tilt.glareY}%, rgba(144,238,255,${active ? 0.2 : 0.06}) 0%, transparent 36%)`,
            mixBlendMode: 'screen',
            transform: 'translateZ(42px)',
            transition: active ? 'none' : 'background 300ms ease',
          }}
        />
      </div>
    </div>
  );
}

export function SuccesProjectsPage() {
  const [projects, setProjects] = useState<SuccesProject[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState(emptyDraft);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setProjects(await listSuccesProjects(search));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({ timestamp: Date.now(), level: 'error', category: 'succes', message: `Projets : ${message}` });
      toast.error('Les projets ne peuvent pas être chargés.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load]);

  const closeForm = () => {
    setShowForm(false);
    setEditingId(null);
    setDraft(emptyDraft);
  };

  const edit = (project: SuccesProject) => {
    setDraft({
      name: project.name,
      description: project.description,
      icon: project.icon,
      color: project.color,
      startDate: project.startDate,
      endDate: project.endDate,
    });
    setEditingId(project.id);
    setShowForm(true);
  };

  const save = async () => {
    if (!draft.name.trim()) return;
    setSaving(true);
    try {
      if (editingId) await updateSuccesProject(editingId, draft);
      else await createSuccesProject(draft);
      toast.success(editingId ? 'Projet mis à jour' : 'Projet créé', { description: 'Enregistré localement sur ce Mac.' });
      closeForm();
      await load();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error("Le projet n'a pas été enregistré.", { description: message });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (project: SuccesProject) => {
    if (!window.confirm(`Supprimer le projet « ${project.name} » ?\n\nSes tâches ne seront pas supprimées.`)) return;
    setSaving(true);
    try {
      await deleteSuccesProject(project.id);
      toast.success('Projet supprimé');
      await load();
    } catch (error) {
      toast.error('La suppression a échoué.', { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
      <main className="max-w-5xl mx-auto w-full">
        <header className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between mb-7">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>Succès</span>
              {saving && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}
            </div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>Projets</h1>
            <p className="text-sm mt-2 max-w-xl" style={{ color: 'var(--color-text-secondary)' }}>Transformez vos objectifs en ensembles d’actions clairs, suivis localement.</p>
          </div>
          <button type="button" onClick={() => { if (showForm) closeForm(); else setShowForm(true); }} className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>
            <CirclePlus size={16} /> Nouveau projet
          </button>
        </header>

        <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 mb-5" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <Search size={15} style={{ color: 'var(--color-text-tertiary)' }} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher un projet…" className="w-full bg-transparent outline-none text-sm" style={{ color: 'var(--color-text)' }} />
        </div>

        {showForm && (
          <section className="grid gap-3 rounded-2xl p-4 mb-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}>
            <div className="grid grid-cols-[1fr_54px] gap-3">
              <input autoFocus value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} maxLength={200} placeholder="Nom du projet" className="rounded-xl px-3 py-2.5 bg-transparent outline-none" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
              <input type="color" value={draft.color} onChange={(event) => setDraft({ ...draft, color: event.target.value })} aria-label="Couleur" className="size-[46px] rounded-xl bg-transparent cursor-pointer" />
            </div>
            <textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={3} maxLength={4000} placeholder="Description et résultat attendu…" className="rounded-xl px-3 py-2 bg-transparent outline-none resize-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
            <div className="grid sm:grid-cols-2 gap-3">
              <label className="grid gap-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Début<input type="date" value={draft.startDate} onChange={(event) => setDraft({ ...draft, startDate: event.target.value })} className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} /></label>
              <label className="grid gap-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Fin<input type="date" value={draft.endDate} onChange={(event) => setDraft({ ...draft, endDate: event.target.value })} className="rounded-xl px-3 py-2 bg-transparent outline-none text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }} /></label>
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={closeForm} className="px-3 py-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>Annuler</button>
              <button type="button" disabled={!draft.name.trim() || saving} onClick={() => void save()} className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>{editingId ? 'Mettre à jour' : 'Créer le projet'}</button>
            </div>
          </section>
        )}

        {loading ? (
          <div className="flex justify-center gap-2 py-20 text-sm" style={{ color: 'var(--color-text-tertiary)' }}><Loader2 size={17} className="animate-spin" /> Chargement des projets…</div>
        ) : projects.length === 0 ? (
          <div className="rounded-2xl py-16 text-center" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}><BriefcaseBusiness size={28} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} /><p className="font-medium" style={{ color: 'var(--color-text)' }}>Aucun projet</p><p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Créez votre premier projet ou demandez-le à DIA.</p></div>
        ) : (
          <div className="grid md:grid-cols-2 gap-3">
            {projects.map((project) => {
              const progress = project.taskTotal ? Math.round((project.taskCompleted / project.taskTotal) * 100) : 0;
              return (
                <article key={project.id} className="rounded-2xl overflow-hidden" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: '0 18px 45px rgba(0,0,0,.16)' }}>
                  <ProjectFolderVisual project={project} />
                  <div className="p-4">
                    <div className="flex items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="size-2 rounded-full shrink-0" style={{ background: project.color, boxShadow: `0 0 10px ${project.color}` }} />
                          <h2 className="font-medium truncate" style={{ color: 'var(--color-text)' }}>{project.name}</h2>
                        </div>
                        <p className="text-xs mt-2 line-clamp-2 min-h-8" style={{ color: 'var(--color-text-secondary)' }}>{project.description || 'Aucune description'}</p>
                      </div>
                      <button type="button" onClick={() => edit(project)} aria-label="Modifier" className="p-1.5 cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}><Pencil size={14} /></button>
                      <button type="button" onClick={() => void remove(project)} aria-label="Supprimer" className="p-1.5 cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}><Trash2 size={14} /></button>
                    </div>
                    <div className="mt-4 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-secondary)' }}><div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${progress}%`, background: project.color, boxShadow: `0 0 8px ${project.color}88` }} /></div>
                    <div className="flex justify-between mt-2 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}><span>{project.taskCompleted}/{project.taskTotal} tâche(s)</span><span>{progress}%</span></div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
