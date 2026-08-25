/**
 * Le panneau du mode gestes — et son voyant, qui dit la vérité.
 *
 * §78 : rien ne guette en permanence. Le bouton arme, le bouton désarme, et
 * l'état affiché est celui que le serveur a réellement reconnu — jamais une
 * animation qui masquerait une absence de reconnaissance (§5).
 */

import { Hand, Video, VideoOff } from 'lucide-react';

import { useCalibration } from './useCalibration';
import { useModeGestes } from './useModeGestes';

const PHRASES: Record<string, string> = {
  REPOS: 'Aucune main devant la caméra.',
  MAIN_VUE: 'Je vois une main.',
  PAUME_STABLE: 'Main ouverte — ferme le poing pour attraper.',
  FERMETURE: 'La main se ferme…',
  SAISI: 'Attrapé. Ouvre la main pour déposer.',
  RELACHEMENT: 'La main s’ouvre…',
  RELACHE: 'Déposé.',
  PERDU: 'J’ai perdu ta main de vue — le geste est annulé.',
  ANNULE: 'Geste annulé.',
};

export function PanneauGestes() {
  const { actif, etat, mainVue, erreur, diagnostic, basculer } = useModeGestes();
  const calibration = useCalibration(actif);

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <header className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Hand className="h-4 w-4 text-muted-foreground" aria-hidden />
          <h2 className="text-sm font-medium">Gestes de la main</h2>
        </div>
        <button
          type="button"
          onClick={basculer}
          className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-accent"
        >
          {actif ? (
            <>
              <VideoOff className="h-4 w-4" aria-hidden />
              Arrêter
            </>
          ) : (
            <>
              <Video className="h-4 w-4" aria-hidden />
              Activer
            </>
          )}
        </button>
      </header>

      <p className="mt-2 text-sm text-muted-foreground">
        {actif
          ? 'La caméra est allumée. Les images sont analysées sur ce Mac, ne sont jamais enregistrées et ne quittent pas l’ordinateur.'
          : 'La caméra reste éteinte tant que tu n’actives pas ce mode.'}
      </p>

      {actif && (
        <div className="mt-3 flex items-center gap-3 rounded-lg bg-muted/50 px-3 py-2">
          <span
            aria-hidden
            className={`h-2 w-2 rounded-full ${mainVue ? 'bg-emerald-500' : 'bg-muted-foreground/40'}`}
          />
          <span className="text-sm">
            {etat ? (PHRASES[etat] ?? etat) : 'En attente d’une première image…'}
          </span>
        </div>
      )}

      {actif && diagnostic?.armed && (
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted-foreground sm:grid-cols-4">
          {/* Ce qui permet de JUGER la fiabilité (§141) : le serveur compte
              ce qui s'est produit, c'est toi qui sais ce que tu voulais. */}
          <div>
            <dt className="inline">Saisies&nbsp;:&nbsp;</dt>
            <dd className="inline tabular-nums text-foreground">{diagnostic.grabs ?? 0}</dd>
          </div>
          <div>
            <dt className="inline">Dépôts&nbsp;:&nbsp;</dt>
            <dd className="inline tabular-nums text-foreground">{diagnostic.releases ?? 0}</dd>
          </div>
          <div>
            <dt className="inline">Pertes&nbsp;:&nbsp;</dt>
            <dd className="inline tabular-nums text-foreground">{diagnostic.losses ?? 0}</dd>
          </div>
          <div>
            <dt className="inline">Main vue&nbsp;:&nbsp;</dt>
            <dd className="inline tabular-nums text-foreground">
              {Math.round((diagnostic.handRatio ?? 0) * 100)}&nbsp;%
            </dd>
          </div>
        </dl>
      )}

      {actif && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {/* La calibration (§16) : deux poses mesurées valent mieux que
              des seuils choisis à l'aveugle pour des mains inconnues. */}
          <button
            type="button"
            onClick={calibration.demarrer}
            disabled={calibration.etape !== 'repos' && calibration.etape !== 'terminee'}
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
          >
            Calibrer sur ma main
          </button>
          {calibration.etape === 'terminee' && (
            <button
              type="button"
              onClick={calibration.reinitialiser}
              className="text-xs text-muted-foreground underline underline-offset-2"
            >
              revenir aux réglages d’usine
            </button>
          )}
          {calibration.message && (
            <span className="text-sm text-muted-foreground">{calibration.message}</span>
          )}
          {calibration.erreur && (
            <span className="text-sm text-destructive">{calibration.erreur}</span>
          )}
        </div>
      )}

      {erreur && (
        <p className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {erreur}
        </p>
      )}
    </section>
  );
}
