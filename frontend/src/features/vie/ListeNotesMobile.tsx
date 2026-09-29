import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Pencil, Trash2 } from 'lucide-react';
import { installerGesteCartables, type FantomeCartable, type PlacementCartable } from './installerGesteCartables';
import { appliquerClassementNotes, rangerNoteMobile } from './classementNotesMobile';
import { grouperEnSections, type SectionDeNotes } from './notesSections';
import { NoteFolderVisual } from './NoteFolderVisual';
import { resumeDeNote, type CartableNote } from './notesResume';
import type { VieProject } from './types';
import './cartablesMobile.css';

type Props = {
  notes: CartableNote[];
  categories: string[];
  projets: VieProject[];
  occupe: boolean;
  filtre: boolean;
  ouvertureId: string | null;
  entete: (section: SectionDeNotes<CartableNote>) => ReactNode;
  ouvrir: (note: CartableNote) => void;
  modifier: (note: CartableNote) => void;
  supprimer: (note: CartableNote) => void;
  ranger: (ids: string[], placement: PlacementCartable) => Promise<void>;
};

export function ListeNotesMobile(props: Props) {
  const racine = useRef<HTMLDivElement>(null);
  const courant = useRef(props);
  courant.current = props;
  const [selection, choisir] = useState<string | null>(null);
  const [apercu, poserApercu] = useState<{ ids: string[]; placement: PlacementCartable } | null>(null);
  const [fantome, poserFantome] = useState<FantomeCartable | null>(null);
  const clicMuet = useRef(0);

  useEffect(() => {
    if (!racine.current) return;
    return installerGesteCartables(racine.current, {
      attributCarte: 'data-note-mobile', attributActions: 'data-actions-note', attributZone: 'data-categorie-note',
      courant: () => ({ ids: courant.current.notes.map(n => n.id), occupe: courant.current.occupe, filtre: courant.current.filtre }),
      classer: (ids, id, cible, zone) => rangerNoteMobile(courant.current.notes, ids, id, cible, zone),
      choisir, poserFantome,
      poserOrdre: (ids, placement) => poserApercu(ids && placement ? { ids, placement } : null),
      taireClic: jusqua => { clicMuet.current = jusqua; },
      ranger: (ids, placement) => { void courant.current.ranger(ids, placement); },
    });
  }, []);

  // Android attache les événements à la carte touchée : la changer de section
  // pendant le glissé la démonterait et ferait perdre touchend. La destination
  // s'allume, mais le changement de catégorie attend le relâchement.
  const notes = apercu ? appliquerClassementNotes(props.notes, apercu.ids, { id: apercu.placement.id }) : props.notes;
  const sections = grouperEnSections(notes, props.categories);
  // La dernière note d'une catégorie peut être reprise pendant le glissé.
  // Garder les destinations vides évite qu'elles disparaissent sous le doigt.
  for (const nom of [...props.categories, ...props.notes.map(n => n.category || ''), '']) {
    if (!sections.some(s => s.nom === nom) && (nom || props.categories.length)) sections.push({ nom, notes: [] });
  }
  const flottant = props.notes.find(n => n.id === fantome?.id);
  return <div ref={racine} className="notes-mobile" onContextMenu={e => e.preventDefault()}>
    {sections.map(section => <section key={section.nom} data-categorie-note={section.nom} data-cible-categorie={apercu?.placement.zone === section.nom || undefined} aria-label={section.nom || 'Sans catégorie'}>
      {(section.nom || props.categories.length > 0) && props.entete(section)}
      <div className="cartables-mobile">
        {section.notes.map(note => {
          const pages = resumeDeNote(note).pageCountEstimate;
          const projet = props.projets.find(p => p.id === note.projectId);
          return <article key={note.id} data-note-mobile={note.id} data-selectionne={selection === note.id || undefined} data-pris={fantome?.id === note.id || undefined}>
            <button type="button" className="cartable-mobile-ouvrir" aria-label={`Ouvrir ${note.title || 'Sans titre'}`} aria-busy={props.ouvertureId === note.id}
              onClick={() => {
                if (performance.now() < clicMuet.current) return;
                choisir(null); props.ouvrir(note);
              }}
              onKeyDown={e => {
                if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); choisir(note.id); }
              }}>
              <NoteFolderVisual color={note.color || '#6366f1'} sheets={Math.min(3, pages)} height="h-[130px]" />
              <h2>{props.ouvertureId === note.id ? 'Ouverture…' : note.title || 'Sans titre'}</h2>
              {projet && <p className="note-mobile-projet">{projet.name}</p>}
              <p>{note.updatedAt && <><time dateTime={note.updatedAt}>{new Date(`${note.updatedAt}T12:00:00`).toLocaleDateString('fr-CA', { day: 'numeric', month: 'short', year: 'numeric' })}</time><br /></>}
                ≈ {pages} page{pages === 1 ? '' : 's'}</p>
            </button>
            {selection === note.id && <div data-actions-note="" className="cartable-mobile-actions">
              <button type="button" disabled={props.occupe} aria-label={`Modifier ${note.title}`} onClick={() => props.modifier(note)}><Pencil size={20} /></button>
              <button type="button" disabled={props.occupe} aria-label={`Supprimer ${note.title}`} onClick={() => props.supprimer(note)}><Trash2 size={20} /></button>
            </div>}
          </article>;
        })}
      </div>
      {section.notes.length === 0 && <p className="note-mobile-depot">Déposer une note ici</p>}
    </section>)}
    {flottant && fantome && createPortal(<div aria-hidden="true" className="cartable-mobile-fantome" style={{ width: fantome.largeur, left: fantome.x - fantome.largeur / 2, top: fantome.y - 70 }}>
      <NoteFolderVisual color={flottant.color || '#6366f1'} sheets={Math.min(3, resumeDeNote(flottant).pageCountEstimate)} height="h-[130px]" /><span>{flottant.title}</span>
    </div>, document.body)}
  </div>;
}
