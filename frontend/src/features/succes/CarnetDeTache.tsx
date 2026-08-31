// Le carnet d'une tâche — ce qu'on écrit PENDANT, pas avant.
//
// Demandé le 30 août 2026 : « une petite icône de notes, un pop-up, je pourrais
// prendre des notes pour chaque tâche ».
//
// Distinct de `notes`, qui décrit l'étape et s'affiche sous son titre. Les
// mélanger obligerait à effacer la consigne pour noter un doute.

import { useEffect, useRef, useState } from 'react';
import { Loader2, NotebookPen, X } from 'lucide-react';

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

interface Props {
  tache: SuccesTask;
  saving: boolean;
  onFermer: () => void;
  onEnregistrer: (journal: string) => Promise<void>;
}

export function CarnetDeTache({ tache, saving, onFermer, onEnregistrer }: Props) {
  const [texte, setTexte] = useState(tache.journal || '');
  const [enCours, setEnCours] = useState(false);
  const zone = useRef<HTMLTextAreaElement>(null);
  const initial = useRef(tache.journal || '');

  useEffect(() => {
    // Le curseur À LA FIN, pas au début : on ouvre un carnet pour ajouter une
    // séance, pas pour réécrire la première.
    const el = zone.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);

  const modifie = texte !== initial.current;

  const enregistrer = async () => {
    if (!modifie) {
      onFermer();
      return;
    }
    setEnCours(true);
    try {
      await onEnregistrer(texte);
      onFermer();
    } finally {
      setEnCours(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.55)' }}
      onClick={onFermer}
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
          // Échap ferme SANS enregistrer — c'est ce qu'on attend d'Échap.
          // Cmd/Ctrl+Entrée enregistre, comme partout ailleurs dans l'app.
          if (e.key === 'Escape') {
            e.stopPropagation();
            onFermer();
          }
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void enregistrer();
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
            onClick={onFermer}
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
          className="flex-1 min-h-[220px] w-full resize-none px-4 py-3 text-[13px] leading-relaxed outline-none bg-transparent"
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

        <div
          className="flex items-center justify-between gap-3 px-4 py-2.5 shrink-0"
          style={{ borderTop: '1px solid var(--color-border)' }}
        >
          <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
            {modifie ? 'Non enregistré' : 'À jour'} · Échap ferme · ⌘↵ enregistre
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onFermer}
              className="h-8 px-3 rounded-lg text-xs cursor-pointer"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={() => void enregistrer()}
              disabled={enCours || saving}
              className="h-8 px-3 rounded-lg text-xs flex items-center gap-1.5 cursor-pointer"
              style={{ background: 'var(--color-accent)', color: 'var(--color-bg)' }}
            >
              {enCours ? <Loader2 size={13} className="animate-spin" /> : null}
              Enregistrer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
