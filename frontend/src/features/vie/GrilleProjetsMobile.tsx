import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Pencil, Trash2 } from 'lucide-react';
import type { VieProject } from './types';
import { installerGesteProjets } from './installerGesteProjets';
import './cartablesMobile.css';

type Props = {
  projets: VieProject[];
  occupe: boolean;
  filtre: boolean;
  dossier: (projet: VieProject) => ReactNode;
  ouvrir: (projet: VieProject) => void;
  modifier: (projet: VieProject) => void;
  supprimer: (projet: VieProject) => void;
  ranger: (ids: string[]) => Promise<void>;
};

/** Le doigt ne bloque le défilement qu'APRÈS l'appui long. Un touchmove
 * non passif est nécessaire : changer touch-action après pointerdown
 * arrive trop tard dans Android WebView. Aucun menu natif de texte ici. */
export function GrilleProjetsMobile(props: Props) {
  const racine = useRef<HTMLDivElement>(null);
  const courant = useRef(props);
  courant.current = props;
  const [selection, choisir] = useState<string | null>(null);
  const [ordre, poserOrdre] = useState<string[] | null>(null);
  const [fantome, poserFantome] = useState<{ id: string; x: number; y: number; largeur: number } | null>(null);
  const clicMuet = useRef(0);

  useEffect(() => {
    const grille = racine.current;
    if (!grille) return;
    return installerGesteProjets(grille, {
      courant: () => ({ ids: courant.current.projets.map(p => p.id), occupe: courant.current.occupe, filtre: courant.current.filtre }),
      choisir, poserOrdre, poserFantome,
      taireClic: jusqua => { clicMuet.current = jusqua; },
      ranger: ids => { void courant.current.ranger(ids); },
    });
  }, []);

  const projets = ordre ? ordre.map(id => props.projets.find(p => p.id === id)).filter((p): p is VieProject => Boolean(p)) : props.projets;
  const flottant = props.projets.find(p => p.id === fantome?.id);
  return <div ref={racine} className="cartables-mobile" onContextMenu={e => e.preventDefault()}>
    {projets.map(projet => <article key={projet.id} data-projet-mobile={projet.id} data-selectionne={selection === projet.id || undefined} data-pris={fantome?.id === projet.id || undefined}>
      <button type="button" className="cartable-mobile-ouvrir" aria-label={`Ouvrir ${projet.name}`} onClick={() => {
        if (performance.now() < clicMuet.current) return;
        choisir(null); props.ouvrir(projet);
      }} onKeyDown={e => {
        if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); choisir(projet.id); }
      }}>
        {props.dossier(projet)}
        <h2>{projet.name}</h2>
        <p>{projet.taskCompleted}/{projet.taskTotal} · {projet.taskTotal ? Math.round(projet.taskCompleted / projet.taskTotal * 100) : 0}%</p>
      </button>
      {selection === projet.id && <div data-actions-projet="" className="cartable-mobile-actions">
        <button type="button" disabled={props.occupe} aria-label={`Modifier ${projet.name}`} onClick={() => props.modifier(projet)}><Pencil size={20} /></button>
        <button type="button" disabled={props.occupe} aria-label={`Supprimer ${projet.name}`} onClick={() => props.supprimer(projet)}><Trash2 size={20} /></button>
      </div>}
    </article>)}
    {flottant && fantome && createPortal(<div aria-hidden="true" className="cartable-mobile-fantome" style={{ width: fantome.largeur, left: fantome.x - fantome.largeur / 2, top: fantome.y - 70 }}>{props.dossier(flottant)}<span>{flottant.name}</span></div>, document.body)}
  </div>;
}
