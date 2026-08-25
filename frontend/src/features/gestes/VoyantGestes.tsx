/**
 * Le voyant : dire que la caméra tourne, même quand on regarde ailleurs.
 *
 * Le mode gestes survit désormais au changement de page — c'est ce qui le
 * rend utilisable. Mais un mode qui tourne sans qu'on le voie est un mode
 * qu'on oublie, et une caméra oubliée est exactement ce que le voyant vert
 * de macOS existe pour empêcher. Ce point discret dit la même chose, dans
 * l'application, avec le moyen de couper en un clic.
 */

import { Hand } from 'lucide-react';

import { useModeGestesPartage } from './ModeGestesContexte';

const PHRASES: Record<string, string> = {
  PAUME_STABLE: 'ferme le poing pour attraper',
  SAISI: 'ouvre la main pour déposer',
  RELACHE: 'déposé',
};

export function VoyantGestes() {
  const { actif, etat, diagnostic, basculer } = useModeGestesPartage();
  if (!actif) return null;

  const tenu = diagnostic?.held?.title;
  const indice = etat ? PHRASES[etat] : undefined;

  return (
    <div className="fixed bottom-4 left-4 z-40 flex items-center gap-2 rounded-full border border-border bg-card/95 px-3 py-1.5 text-xs shadow-lg backdrop-blur">
      <span
        aria-hidden
        className="h-2 w-2 animate-pulse rounded-full bg-emerald-500"
      />
      <Hand className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      <span className="text-muted-foreground">
        {tenu ? (
          <>
            Dans ta main&nbsp;: <span className="text-foreground">{tenu}</span>
          </>
        ) : (
          (indice ?? 'gestes actifs')
        )}
      </span>
      <button
        type="button"
        onClick={basculer}
        className="ml-1 rounded-full px-2 py-0.5 text-muted-foreground underline underline-offset-2 hover:text-foreground"
      >
        arrêter
      </button>
    </div>
  );
}
