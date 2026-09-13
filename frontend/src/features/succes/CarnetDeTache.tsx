// Le carnet d'une tâche — ce qu'on écrit PENDANT, pas avant.
//
// Demandé le 30 août 2026 : « une petite icône de notes, un pop-up, je pourrais
// prendre des notes pour chaque tâche ».
//
// Distinct de `notes`, qui décrit l'étape et s'affiche sous son titre. Les
// mélanger obligerait à effacer la consigne pour noter un doute.

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, Check, Loader2, NotebookPen, X } from 'lucide-react';

import { ouvrirLienExterne } from '../../lib/lienExterne';
import { linkifier } from './ligne';
import type { SuccesTask } from './types';

/**
 * Le carnet a-t-il quelque chose dedans ?
 *
 * Des espaces ne sont pas des notes : sans ce filtre, l'icône s'allumerait
 * pour une tâche où l'on a ouvert le carnet puis tout effacé, et le repère
 * « j'ai écrit ici » cesserait de vouloir dire quoi que ce soit.
 */
export function carnetRempli(journal: string | undefined | null): boolean {
  return String(journal ?? '').trim().length > 0;
}

/** Combien de lignes non vides — pour le dire sans ouvrir. */
export function lignesDuCarnet(journal: string | undefined | null): number {
  return String(journal ?? '')
    .split('\n')
    .filter((l) => l.trim().length > 0).length;
}

/** Le délai avant d'enregistrer, après la dernière frappe. */
const REPOS_MS = 700;

interface Props {
  tache: SuccesTask;
  onFermer: () => void;
  onEnregistrer: (journal: string) => Promise<void>;
}

export function CarnetDeTache({ tache, onFermer, onEnregistrer }: Props) {
  const [texte, setTexte] = useState(tache.journal || '');
  const [etat, setEtat] = useState<'a-jour' | 'en-cours' | 'echec'>('a-jour');
  const zone = useRef<HTMLTextAreaElement>(null);
  /** Ce qui est RÉELLEMENT sur le disque — pas ce qu'on a tapé. */
  const enregistre = useRef(tache.journal || '');
  const minuteur = useRef<number | null>(null);
  const dernier = useRef(tache.journal || '');
  dernier.current = texte;

  useEffect(() => {
    // Le curseur À LA FIN, pas au début : on ouvre un carnet pour ajouter une
    // séance, pas pour réécrire la première.
    const el = zone.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);

  /**
   * Enregistrer, et ne dire « à jour » que si ça a marché.
   *
   * `enregistre` ne bouge qu'APRÈS le retour du serveur : c'est ce qui
   * distingue « écrit sur le disque » de « tapé au clavier ». Sans cette
   * distinction, un échec réseau laisserait la fenêtre annoncer « Enregistré »
   * sur un texte que personne n'a reçu.
   */
  const sauver = async (valeur: string) => {
    if (valeur === enregistre.current) return;
    setEtat('en-cours');
    try {
      await onEnregistrer(valeur);
      enregistre.current = valeur;
      // Une frappe arrivée pendant l'aller-retour : on ne dit pas « à jour »
      // pour un texte qui a déjà changé depuis.
      setEtat(dernier.current === valeur ? 'a-jour' : 'en-cours');
    } catch {
      setEtat('echec');
    }
  };

  // Enregistrer tout seul, une fois la frappe retombée.
  useEffect(() => {
    if (texte === enregistre.current) {
      setEtat('a-jour');
      return;
    }
    setEtat('en-cours');
    if (minuteur.current) window.clearTimeout(minuteur.current);
    minuteur.current = window.setTimeout(() => {
      minuteur.current = null;
      void sauver(texte);
    }, REPOS_MS);
    return () => {
      if (minuteur.current) window.clearTimeout(minuteur.current);
    };
  }, [texte]); // eslint-disable-line react-hooks/exhaustive-deps -- `sauver` lit ses refs

  /**
   * Fermer, mais pas avant d'avoir écrit.
   *
   * On ferme un carnet dans la seconde qui suit la dernière lettre : sans ce
   * vidage, les sept cents millisecondes d'attente emporteraient la fin de ce
   * qu'on vient d'écrire.
   */
  const fermer = () => {
    if (minuteur.current) {
      window.clearTimeout(minuteur.current);
      minuteur.current = null;
    }
    if (dernier.current !== enregistre.current) void sauver(dernier.current);
    onFermer();
  };

  // MONTÉ SUR `document.body`, PAS LÀ OÙ IL EST ÉCRIT.
  //
  // La Ligne vit dans un `div` en `z-index: 2`, lui-même dans un `z-index: 10`.
  // Un `z-50` posé là-dedans ne vaut pas 50 face au reste de la page : il vaut
  // 2, celui de la boîte qui l'enferme. La barre latérale, elle, est en
  // `z-index: 30` dans le même contexte — elle passait donc PAR-DESSUS le
  // carnet. Mesuré sur une fenêtre de 1 100 px : barre large de 260 px,
  // carnet commençant à 214, soit 46 px de recouvrement ; sur une fenêtre plus
  // étroite, tout le côté gauche disparaissait derrière elle.
  //
  // Un portail sort le carnet de cette boîte : son `z-50` se compare alors à
  // la racine du document, où il gagne.
  //
  // Cela règle du même coup un second piège, latent : l'ancêtre porte un
  // `backdrop-filter: blur(3px)`, et un filtre suffit à faire d'un élément le
  // référent des `position: fixed` qu'il contient. Le carnet aurait cessé
  // d'être calé sur l'écran le jour où cet ancêtre n'aurait plus couvert
  // exactement l'écran.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.55)' }}
      onClick={fermer}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Carnet — ${tache.title}`}
        className="w-full max-w-2xl rounded-2xl flex flex-col overflow-hidden"
        style={{
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
          maxHeight: 'min(80vh, 640px)',
        }}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          // Échap ferme, et écrit d'abord. Il n'y a plus de bouton Annuler :
          // ce qui est tapé est gardé, donc Échap ne peut plus vouloir dire
          // « jette ». Le faire jeter en silence serait le pire des deux.
          if (e.key === 'Escape') {
            e.stopPropagation();
            fermer();
          }
        }}
      >
        <div
          className="flex items-start gap-3 px-4 py-3 shrink-0"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <NotebookPen size={16} className="mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
              {tache.title}
            </div>
            <div className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
              Carnet — ce que vous comprenez, où vous bloquez, ce que vous essayez
            </div>
          </div>
          <button
            type="button"
            onClick={fermer}
            aria-label="Fermer le carnet"
            className="size-7 rounded-lg flex items-center justify-center cursor-pointer shrink-0"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <X size={15} />
          </button>
        </div>

        <textarea
          ref={zone}
          value={texte}
          onChange={(e) => setTexte(e.target.value)}
          placeholder="Séance du… — ce qui est acquis, ce qui résiste, la prochaine chose à essayer."
          // 13 px figés : « c'est petit et j'ai du mal à comprendre » (13 septembre
          // 2026). 1rem suit le réglage Taille du texte, et le zoom fait le reste.
          className="flex-1 min-h-[220px] w-full resize-none px-4 py-3 text-base leading-relaxed outline-none bg-transparent"
          style={{ color: 'var(--color-text)' }}
        />

        {/* Les liens déjà écrits, cliquables sans quitter le carnet. Un lien
            qu'on doit recopier ailleurs pour l'ouvrir n'est pas un lien. */}
        {(() => {
          const liens = linkifier(texte)
            .filter((s) => s.type === 'lien')
            .map((s) => s.valeur);
          const uniques = [...new Set(liens)];
          if (uniques.length === 0) return null;
          return (
            <div
              className="px-4 py-2 flex flex-wrap gap-x-3 gap-y-1 shrink-0"
              style={{ borderTop: '1px solid var(--color-border)' }}
            >
              {uniques.map((url) => (
                <button
                  key={url}
                  type="button"
                  onClick={() => void ouvrirLienExterne(url)}
                  className="text-[11px] underline underline-offset-2 truncate max-w-full cursor-pointer"
                  style={{ color: 'var(--color-accent)' }}
                  title={url}
                >
                  {url}
                </button>
              ))}
            </div>
          );
        })()}

        {/* Plus de boutons : le carnet s'écrit tout seul. Ce qui reste est le
            SEUL endroit qui dise si c'est vraiment sur le disque — et il doit
            le dire honnêtement, y compris quand ça rate. */}
        <div
          className="flex items-center gap-2 px-4 py-2.5 shrink-0 text-[11px]"
          style={{
            borderTop: '1px solid var(--color-border)',
            color:
              etat === 'echec' ? 'var(--color-danger, #f87171)' : 'var(--color-text-tertiary)',
          }}
        >
          {etat === 'en-cours' ? (
            <>
              <Loader2 size={12} className="animate-spin" />
              Enregistrement…
            </>
          ) : etat === 'echec' ? (
            <>
              <AlertTriangle size={12} />
              Pas enregistré — votre texte est encore là, il repartira à la
              prochaine frappe
            </>
          ) : (
            <>
              <Check size={12} />
              Enregistré · Échap ferme
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
