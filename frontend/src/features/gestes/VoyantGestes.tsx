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

import { FileUp, Hand } from 'lucide-react';

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
const ETATS_TRANSFERT = new Set([
  'PREPARING',
  'WAITING_APPROVAL',
  'TRANSFERRING',
]);

function tailleLisible(octets?: number): string {
  if (octets === undefined) return '';
  if (octets < 1024) return `${octets} o`;
  if (octets < 1024 ** 2) return `${(octets / 1024).toFixed(1)} Kio`;
  if (octets < 1024 ** 3) return `${(octets / 1024 ** 2).toFixed(1)} Mio`;
  return `${(octets / 1024 ** 3).toFixed(1)} Gio`;
}

export function VoyantGestes() {
  const {
    actif,
    etat,
    diagnostic,
    basculer,
    choisir,
    renoncer,
    preparerUnFichier,
    annulerFichierPrepare,
  } = useModeGestesPartage();

  // L'issue du dernier dépôt, le temps de la lire. On dépend du MESSAGE et
  // non de l'objet : le sondage rend un objet neuf chaque seconde, et s'y
  // fier relancerait le minuteur sans fin — l'annonce ne partirait jamais.
  const message = diagnostic?.lastDrop?.message ?? '';
  const reussi = diagnostic?.lastDrop?.done ?? false;
  const transfertActif = ETATS_TRANSFERT.has(
    diagnostic?.lastDrop?.reason ?? '',
  );
  const [annonce, setAnnonce] = useState<string | null>(null);
  useEffect(() => {
    if (!message) {
      setAnnonce(null);
      return;
    }
    setAnnonce(message);
    if (transfertActif) return;
    const t = window.setTimeout(() => setAnnonce(null), ANNONCE_MS);
    return () => window.clearTimeout(t);
  }, [message, transfertActif]);

  if (!actif) return null;

  const attente = diagnostic?.pendingDrop ?? null;
  const tenu = diagnostic?.held?.title;
  const prepare = diagnostic?.preparedFile ?? null;
  const indice = etat ? PHRASES[etat] : undefined;

  if (attente?.gestureControlled) {
    const selection = Math.max(
      0,
      Math.min(
        attente.selectedIndex ?? 0,
        Math.max(0, attente.candidates.length - 1),
      ),
    );
    const position = attente.handPosition;
    return (
      <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-6 backdrop-blur-sm">
        <section
          className="pointer-events-auto w-full max-w-4xl rounded-3xl border border-white/15 bg-card/95 p-6 shadow-2xl"
          aria-label="Choisir l’appareil avec le poing"
        >
          <header className="text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-accent">
              <Hand className="h-6 w-6" aria-hidden />
            </div>
            <p className="text-xs uppercase tracking-[0.22em] text-muted-foreground">
              Dans ta main
            </p>
            <h2 className="mt-1 truncate text-xl font-semibold text-foreground">
              {attente.object.title}
            </h2>
            {attente.object.sizeBytes !== undefined && (
              <p className="mt-1 text-sm text-muted-foreground">
                {tailleLisible(attente.object.sizeBytes)}
              </p>
            )}
          </header>

          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {attente.candidates.map((candidat, index) => {
              const actif = index === selection;
              return (
                <button
                  key={candidat.deviceId}
                  type="button"
                  onClick={() => choisir(candidat.deviceId)}
                  aria-current={actif ? 'true' : undefined}
                  className={`relative min-h-28 rounded-2xl border px-4 py-4 text-left transition-all ${
                    actif
                      ? 'scale-[1.03] border-emerald-400 bg-emerald-500/10 shadow-[0_0_0_3px_rgba(52,211,153,0.16)]'
                      : 'border-border bg-muted/30 opacity-60'
                  }`}
                >
                  <span className="text-2xl" aria-hidden>
                    {candidat.deviceType === 'PHONE'
                      ? '📱'
                      : candidat.deviceType === 'TABLET'
                        ? '▭'
                        : '🖥️'}
                  </span>
                  <span className="mt-2 block font-medium text-foreground">
                    {candidat.name}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {candidat.platform ?? 'Appareil Diapason'}
                  </span>
                  {actif && (
                    <span className="absolute right-3 top-3 rounded-full bg-emerald-500 px-2 py-0.5 text-[10px] font-semibold text-white">
                      choisi
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="mt-6 grid gap-4 sm:grid-cols-[1fr_auto] sm:items-center">
            <div className="relative h-14 overflow-hidden rounded-2xl border border-border bg-muted/40">
              <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
              <div className="absolute left-0 top-1/2 h-px w-full bg-border" />
              {position && (
                <span
                  aria-hidden
                  className="absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-400 shadow-[0_0_18px_rgba(52,211,153,0.9)] transition-[left,top] duration-100"
                  style={{ left: `${position.x * 100}%`, top: `${position.y * 100}%` }}
                />
              )}
              <span className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
                gauche / haut&nbsp;: précédent · droite / bas&nbsp;: suivant
              </span>
            </div>
            <div className="text-center sm:text-right">
              <p className="font-medium text-foreground">
                Ouvre la main pour envoyer
              </p>
              <p className="text-xs text-muted-foreground">
                {Math.round(attente.secondsLeft)} s · le clic reste disponible
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={renoncer}
            className="mx-auto mt-5 block text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            laisse tomber
          </button>
        </section>
      </div>
    );
  }

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

  if (transfertActif) {
    const progression = diagnostic?.lastDrop?.progress ?? 0;
    return (
      <div className="fixed bottom-4 left-4 z-40 w-[min(26rem,calc(100vw-2rem))] rounded-2xl border border-border bg-card/95 px-4 py-3 text-xs shadow-lg backdrop-blur">
        <div className="flex items-center gap-2">
          <FileUp className="h-4 w-4 text-emerald-500" aria-hidden />
          <span className="font-medium text-foreground">{message}</span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-emerald-500 transition-[width] duration-200"
            style={{ width: `${progression}%` }}
          />
        </div>
        <p className="mt-1 text-right tabular-nums text-muted-foreground">
          {diagnostic?.lastDrop?.reason === 'WAITING_APPROVAL'
            ? 'accord demandé sur l’appareil destinataire'
            : `${progression} %`}
        </p>
      </div>
    );
  }

  return (
    <div className="fixed bottom-4 left-4 z-40 flex max-w-[calc(100vw-2rem)] items-center gap-2 rounded-full border border-border bg-card/95 px-3 py-1.5 text-xs shadow-lg backdrop-blur">
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
          ) : prepare ? (
            <>
              Prêt à attraper&nbsp;:{' '}
              <span className="text-foreground">{prepare.title}</span>
            </>
          ) : (
            (indice ?? 'gestes actifs')
          ))}
      </span>
      {!tenu && !prepare && !annonce && (
        <button
          type="button"
          onClick={preparerUnFichier}
          className="ml-1 inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-foreground hover:bg-accent"
        >
          <FileUp className="h-3 w-3" aria-hidden />
          fichier
        </button>
      )}
      {prepare && !tenu && (
        <button
          type="button"
          onClick={annulerFichierPrepare}
          className="text-muted-foreground underline underline-offset-2 hover:text-foreground"
        >
          retirer
        </button>
      )}
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
