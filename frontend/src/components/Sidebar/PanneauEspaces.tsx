import { useCallback, useEffect, useState } from 'react';
import { ChevronRight, FileText, Folder, FolderOpen, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router';
import { listVieNoteResumes, listVieProjects } from '../../features/vie/api';
import { clesVie, ecrireCache, lireCache } from '../../features/vie/cacheVie';
import type { VieNoteResume, VieProject } from '../../features/vie/types';
import { useAppStore } from '../../lib/store';
import { correspondALaRecherche } from './navigation';

/** §5 : les dossiers du prototype deviennent des projets réels, jamais des exemples. */
export function PanneauEspaces({ mode, recherche }: { mode: 'projets' | 'notes'; recherche: string }) {
  const navigate = useNavigate();
  const [projets, setProjets] = useState<VieProject[]>(() => lireCache(clesVie.projets()) ?? []);
  const [notes, setNotes] = useState<VieNoteResume[]>(() => lireCache(clesVie.resumesNotes()) ?? []);
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState(false);
  const [revision, setRevision] = useState(0);
  const [selection, setSelection] = useState<string | null>(null);
  const rafraichir = useCallback(() => setRevision((r) => r + 1), []);

  useEffect(() => {
    let present = true;
    setChargement(true);
    setErreur(false);
    const lecture = mode === 'projets' ? listVieProjects() : listVieNoteResumes();
    void lecture.then((donnees) => {
      if (!present) return;
      if (mode === 'projets') {
        setProjets(donnees as VieProject[]);
        ecrireCache(clesVie.projets(), donnees);
      } else {
        setNotes(donnees as VieNoteResume[]);
        ecrireCache(clesVie.resumesNotes(), donnees);
      }
    }).catch(() => { if (present) setErreur(true); })
      .finally(() => { if (present) setChargement(false); });
    return () => { present = false; };
  }, [mode, revision]);

  useEffect(() => {
    window.addEventListener('focus', rafraichir);
    return () => window.removeEventListener('focus', rafraichir);
  }, [rafraichir]);

  const ouvrir = (kind: 'project' | 'note', id: string) => {
    setSelection(id);
    useAppStore.getState().setPendingMeshSelection({ kind, id });
    navigate(kind === 'project' ? '/vie/projects' : '/vie/notes');
  };
  const visibles = projets.filter((p) => correspondALaRecherche(p.name, recherche));
  const notesVisibles = notes.filter((n) => correspondALaRecherche(`${n.title} ${n.category ?? ''}`, recherche));
  const categories = [...new Set(notesVisibles.map((n) => n.category || 'Sans catégorie'))];
  const vide = mode === 'projets' ? !visibles.length : !notesVisibles.length;

  return <div className="navigation-espaces" aria-busy={chargement}>
    <div className="navigation-section-entete">
      <span>{mode === 'projets' ? 'Mes projets' : 'Mes notes'}</span>
      <button className="navigation-icone" aria-label="Actualiser la liste" title="Actualiser la liste" onClick={rafraichir} disabled={chargement}><RefreshCw size={14} /></button>
    </div>
    {erreur && <p className="navigation-message" role="status">La liste ne peut pas être actualisée.</p>}
    {vide && <p className="navigation-message">{chargement ? 'Chargement…' : recherche ? 'Aucun résultat.' : mode === 'projets' ? 'Aucun projet pour le moment.' : 'Aucune note pour le moment.'}</p>}
    {mode === 'projets' ? visibles.map((p) => <button key={p.id} className="navigation-ligne" onClick={() => ouvrir('project', p.id)} aria-current={selection === p.id ? 'page' : undefined} title={p.name}>
      <Folder size={17} /><span>{p.name}</span>
    </button>) : categories.map((categorie) => <details key={categorie} className="navigation-dossier" open={recherche ? true : undefined}>
      <summary><ChevronRight size={14} className="navigation-chevron" /><FolderOpen size={17} /><span>{categorie}</span></summary>
      <div className="navigation-enfants">{notesVisibles.filter((n) => (n.category || 'Sans catégorie') === categorie).map((n) => <button key={n.id} className="navigation-ligne" onClick={() => ouvrir('note', n.id)} aria-current={selection === n.id ? 'page' : undefined} title={n.title}>
        <FileText size={15} /><span>{n.title || 'Sans titre'}</span>
      </button>)}</div>
    </details>)}
  </div>;
}
