/**
 * Le voyant : dire que la caméra tourne, même quand on regarde ailleurs.
 *
 * Le mode gestes survit désormais au changement de page — c'est ce qui le
 * rend utilisable. Mais un mode qui tourne sans qu'on le voie est un mode
 * qu'on oublie, et une caméra oubliée est exactement ce que le voyant vert
 * de macOS existe pour empêcher. Ce point discret dit la même chose, dans
 * l'application, avec le moyen de couper en un clic.
 *
 * C'est aussi le SEUL élément du mode gestes monté sur toutes les pages
 * (App.tsx) : le panneau, lui, ne vit que dans la page Appareils. Or on
 * attrape un projet depuis la page des projets. Tout ce qui doit être vu au
 * moment du geste — la question « vers lequel ? » et la réponse qu'elle
 * finit par recevoir — doit donc passer par ici, ou n'être jamais vu.
 */

import { useEffect, useState } from 'react';

import { Hand } from 'lucide-react';

import { useModeGestesPartage } from './ModeGestesContexte';

const PHRASES: Record<string, string> = {
  PAUME_STABLE: 'ferme le poing pour attraper',
  SAISI: 'ouvre la main pour déposer',
  RELACHE: 'déposé',
};

// Le temps pendant lequel l'issue d'un dépôt reste affichée. Assez pour la
// lire en levant les yeux, assez peu pour ne pas devenir un décor qu'on
// cesse de voir — et donc de croire.
const ANNONCE_MS = 6000;

export function VoyantGestes() {
  const { actif, etat, diagnostic, basculer, choisir, renoncer } =
    useModeGestesPartage();

  // L'issue du dernier dépôt, le temps de la lire. On dépend du MESSAGE et
  // non de l'objet : le sondage rend un objet neuf chaque seconde, et s'y
  // fier relancerait le minuteur sans fin — l'annonce ne partirait jamais.
  const message = diagnostic?.lastDrop?.message ?? '';
  const reussi = diagnostic?.lastDrop?.done ?? false;
  const [annonce, setAnnonce] = useState<string | null>(null);
  useEffect(() => {
    if (!message) {
      setAnnonce(null);
      return;
    }
    setAnnonce(message);
    const t = window.setTimeout(() => setAnnonce(null), ANNONCE_MS);
    return () => window.clearTimeout(t);
  }, [message]);

  if (!actif) return null;

  const attente = diagnostic?.pendingDrop ?? null;
  const tenu = diagnostic?.held?.title;
  const indice = etat ? PHRASES[etat] : undefined;

  // §34 et §81 : aucun capteur de cette flotte ne mesure une direction. Le
  // serveur a donc posé la question plutôt que de tirer au sort — et c'est
  // ici qu'elle devient répondable.
  if (attente) {
    return (
      <div className="fixed bottom-4 left-4 z-40 max-w-sm rounded-xl border border-border bg-card/95 px-4 py-3 text-xs shadow-lg backdrop-blur">
        <div className="flex items-center gap-2">
          <Hand className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
          <span className="text-foreground">
            «&nbsp;{attente.object.title}&nbsp;» — vers lequel&nbsp;?
          </span>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {attente.candidates.map((candidat) => (
            <button
              key={candidat.deviceId}
              type="button"
              onClick={() => choisir(candidat.deviceId)}
              className="rounded-full border border-border px-2.5 py-1 text-foreground hover:bg-accent"
            >
              {candidat.name}
            </button>
          ))}
          <button
            type="button"
            onClick={renoncer}
            className="rounded-full px-2.5 py-1 text-muted-foreground underline underline-offset-2 hover:text-foreground"
          >
            laisse tomber
          </button>
        </div>
        <p className="mt-1.5 text-muted-foreground">
          {Math.round(attente.secondsLeft)}&nbsp;s pour répondre — passé ce
          délai, rien ne part.
        </p>
      </div>
    );
  }

  return (
    <div className="fixed bottom-4 left-4 z-40 flex items-center gap-2 rounded-full border border-border bg-card/95 px-3 py-1.5 text-xs shadow-lg backdrop-blur">
      <span
        aria-hidden
        className="h-2 w-2 animate-pulse rounded-full bg-emerald-500"
      />
      <Hand className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      <span
        className={
          annonce
            ? reussi
              ? 'text-emerald-600 dark:text-emerald-400'
              : 'text-foreground'
            : 'text-muted-foreground'
        }
        aria-live="polite"
      >
        {annonce ??
          (tenu ? (
            <>
              Dans ta main&nbsp;: <span className="text-foreground">{tenu}</span>
            </>
          ) : (
            (indice ?? 'gestes actifs')
          ))}
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
