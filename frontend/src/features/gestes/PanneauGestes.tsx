/**
 * Le panneau du mode gestes — et son voyant, qui dit la vérité.
 *
 * §78 : rien ne guette en permanence. Le bouton arme, le bouton désarme, et
 * l'état affiché est celui que le serveur a réellement reconnu — jamais une
 * animation qui masquerait une absence de reconnaissance (§5).
 */

import { useState } from 'react';

import { FileUp, Hand, Video, VideoOff } from 'lucide-react';

import { mesurerLaPiece, mesurerLesClaps } from './api';
import { useCalibration } from './useCalibration';
import { useModeGestesPartage } from './ModeGestesContexte';

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
  // L'état vient du contexte : le mode doit survivre au changement de
  // page, sinon il s'éteint au moment où l'on va chercher ce qu'on veut
  // attraper.
  const {
    actif,
    mode,
    etat,
    mainVue,
    erreur,
    diagnostic,
    clapsEcoutent,
    basculerLesClaps,
    basculer,
    changerMode,
    choisir,
    renoncer,
    preparerUnFichier,
    annulerFichierPrepare,
  } = useModeGestesPartage();
  const calibration = useCalibration(actif);
  const progressionPince = Math.max(
    0,
    Math.min(1, diagnostic?.pointer?.pinchProgress ?? 0),
  );

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
          ? mode === 'POINTER'
            ? 'La caméra suit uniquement ton index sur ce Mac. Les images ne sont jamais enregistrées et ne quittent pas l’ordinateur.'
            : 'La caméra est allumée et le reste quand tu changes de page — va ouvrir un projet, puis ferme le poing. Les images sont analysées sur ce Mac, ne sont jamais enregistrées et ne quittent pas l’ordinateur.'
          : 'La caméra reste éteinte tant que tu n’actives pas ce mode.'}
      </p>

      <div
        className="mt-3 grid grid-cols-2 gap-2"
        role="group"
        aria-label="Fonction des gestes"
      >
        <button
          type="button"
          aria-pressed={mode === 'TRANSFER'}
          onClick={() => changerMode('TRANSFER')}
          className={`rounded-lg border px-3 py-2 text-left text-sm ${
            mode === 'TRANSFER'
              ? 'border-emerald-400 bg-emerald-500/10 text-foreground'
              : 'border-border text-muted-foreground hover:bg-accent'
          }`}
        >
          <span className="block font-medium">Transférer</span>
          <span className="block text-xs">poing, choix, paume ouverte</span>
        </button>
        <button
          type="button"
          aria-pressed={mode === 'POINTER'}
          onClick={() => changerMode('POINTER')}
          className={`rounded-lg border px-3 py-2 text-left text-sm ${
            mode === 'POINTER'
              ? 'border-emerald-400 bg-emerald-500/10 text-foreground'
              : 'border-border text-muted-foreground hover:bg-accent'
          }`}
        >
          <span className="block font-medium">Contrôler le curseur</span>
          <span className="block text-xs">index, pincement, défilement</span>
        </button>
      </div>

      {actif && (
        <div className="mt-3 flex items-center gap-3 rounded-lg bg-muted/50 px-3 py-2">
          <span
            aria-hidden
            className={`h-2 w-2 rounded-full ${mainVue ? 'bg-emerald-500' : 'bg-muted-foreground/40'}`}
          />
          <span className="text-sm">
            {mode === 'POINTER'
              ? diagnostic?.pointer?.active
                ? diagnostic.pointer.pinching
                  ? 'Contact reconnu — relâche pour cliquer ou maintiens pour défiler.'
                  : progressionPince >= 0.4
                    ? 'Rapproche encore le pouce et l’index.'
                    : 'Index suivi — le curseur te suit.'
                : mainVue
                  ? 'Garde seulement l’index tendu.'
                  : 'Montre ta main puis tends seulement l’index.'
              : etat
                ? (PHRASES[etat] ?? etat)
                : 'En attente d’une première image…'}
          </span>
        </div>
      )}

      {actif && mode === 'POINTER' && (
        <div className="mt-3 rounded-lg border border-border bg-muted/30 px-3 py-3 text-sm">
          <p className="font-medium text-foreground">Commandes du pointeur</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Index tendu&nbsp;: déplacer · pincement bref&nbsp;: cliquer · deux
            pincements&nbsp;: ouvrir · pincement maintenu puis mouvement vertical&nbsp;:
            défiler. Ferme le poing ou retire la main pour figer le curseur.
          </p>
          <div className="mt-3 flex items-center gap-3">
            <span className="shrink-0 text-xs text-muted-foreground">
              Contact pouce-index
            </span>
            <div
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label="Proximité entre le pouce et l’index"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progressionPince * 100)}
            >
              <div
                className={`h-full rounded-full transition-[width,background-color] duration-75 ${
                  diagnostic?.pointer?.pinching
                    ? 'bg-emerald-400'
                    : 'bg-amber-400'
                }`}
                style={{ width: `${Math.round(progressionPince * 100)}%` }}
              />
            </div>
            <span className="w-8 text-right text-xs tabular-nums text-muted-foreground">
              {Math.round(progressionPince * 100)}%
            </span>
          </div>
        </div>
      )}

      {actif && mode === 'TRANSFER' && !diagnostic?.held && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={preparerUnFichier}
            className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-accent"
          >
            <FileUp className="h-4 w-4" aria-hidden />
            Choisir un fichier, une photo ou une vidéo
          </button>
          {diagnostic?.preparedFile && (
            <>
              <span className="text-sm text-muted-foreground">
                Prêt à attraper&nbsp;:{' '}
                <span className="font-medium text-foreground">
                  {diagnostic.preparedFile.title}
                </span>
              </span>
              <button
                type="button"
                onClick={annulerFichierPrepare}
                className="text-xs text-muted-foreground underline underline-offset-2"
              >
                retirer
              </button>
            </>
          )}
        </div>
      )}

      {mode === 'TRANSFER' && (
        <label className="mt-3 flex cursor-pointer items-start gap-2 text-sm">
          {/* §78 : une quatrième voie d'armement, au coût explicite. Le
              bouton n'ouvre rien tant qu'on ne clique pas ; entendre un clap
              suppose un micro OUVERT, et cela se choisit. */}
          <input
            type="checkbox"
            checked={clapsEcoutent}
            onChange={basculerLesClaps}
            className="mt-0.5"
          />
          <span>
            <span className="text-foreground">Activer par un double clap</span>
            <span className="block text-xs text-muted-foreground">
              {clapsEcoutent
                ? 'Le micro écoute en continu, uniquement le niveau sonore : deux claps activent les gestes, deux autres les arrêtent. Rien n’est transcrit ni enregistré.'
                : 'Demande d’ouvrir le micro en continu pour entendre deux claps. Rien n’est transcrit ni enregistré.'}
              {clapsEcoutent && (
                <span className="mt-1 block">
                  {/* Sans ce compte, on peut claper une heure sans savoir si
                      le micro entend, si le seuil est trop haut, ou si c'est
                      l'écart entre les deux claps qui ne convient pas. */}
                  Claps entendus&nbsp;:{' '}
                  <span className="tabular-nums text-foreground">
                    {diagnostic?.clapsHeard ?? 0}
                  </span>
                  {/* La raison d'un armement raté prime sur le conseil
                      générique : avalée, elle laissait conseiller de
                      rapprocher ses claps à quelqu'un qui clapait
                      parfaitement mais dont la caméra refusait de s'ouvrir. */}
                  {diagnostic?.clapFailure
                    ? ` — tes claps ont été entendus, mais : ${diagnostic.clapFailure}`
                    : (diagnostic?.clapsHeard ?? 0) === 0
                      ? ' — tape plus fort ou rapproche-toi du Mac.'
                      : ' — si les gestes ne s’activent pas, rapproche tes deux claps (moins d’une demi-seconde).'}
                </span>
              )}
            </span>
          </span>
        </label>
      )}

      {mode === 'TRANSFER' && clapsEcoutent && (
        <MesureDesClaps
          seuil={diagnostic?.clapThreshold}
          mesure={diagnostic?.clapCalibrated}
          fond={diagnostic?.clapNoiseFloor}
        />
      )}

      {actif && mode === 'TRANSFER' && diagnostic?.held && (
        <div className="mt-3 rounded-lg border border-dashed border-border px-3 py-2 text-sm">
          {/* Le retour visuel (§47) : ce que la main tient doit se VOIR,
              sinon le geste est un pari. */}
          <span className="text-muted-foreground">Dans ta main&nbsp;: </span>
          <span className="font-medium">{diagnostic.held.title}</span>
        </div>
      )}

      {actif && mode === 'TRANSFER' && diagnostic?.pendingDrop && (
        <div className="mt-3 rounded-lg border border-border px-3 py-2 text-sm">
          {/* §34 et §81 : aucune direction n'est mesurée, donc rien n'est
              tiré au sort. La question posée par le serveur se répond ici —
              et aussi dans le voyant, qui est visible depuis toute page. */}
          <p>
            «&nbsp;{diagnostic.pendingDrop.object.title}&nbsp;» — vers
            lequel&nbsp;?
          </p>
          {diagnostic.pendingDrop.gestureControlled && (
            <p className="mt-1 text-xs text-muted-foreground">
              Déplace le poing à gauche, à droite, en haut ou en bas. Ouvre la
              main quand le bon appareil est surligné.
            </p>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {diagnostic.pendingDrop.candidates.map((candidat, index) => (
              <button
                key={candidat.deviceId}
                type="button"
                onClick={() => choisir(candidat.deviceId)}
                aria-current={
                  diagnostic.pendingDrop?.selectedIndex === index
                    ? 'true'
                    : undefined
                }
                className={`rounded-md border px-2.5 py-1 text-xs hover:bg-accent ${
                  diagnostic.pendingDrop?.selectedIndex === index
                    ? 'border-emerald-400 bg-emerald-500/10 text-foreground'
                    : 'border-border'
                }`}
              >
                {candidat.name}
              </button>
            ))}
            <button
              type="button"
              onClick={renoncer}
              className="rounded-md px-2.5 py-1 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
            >
              laisse tomber
            </button>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            {Math.round(diagnostic.pendingDrop.secondsLeft)}&nbsp;s pour
            répondre — passé ce délai, rien ne part.
          </p>
        </div>
      )}

      {actif &&
        mode === 'TRANSFER' &&
        !diagnostic?.pendingDrop &&
        diagnostic?.lastDrop?.message && (
          <p
            className={`mt-2 text-sm ${diagnostic.lastDrop.done ? 'text-emerald-500' : 'text-muted-foreground'}`}
          >
            {diagnostic.lastDrop.message}
          </p>
        )}

      {actif && mode === 'TRANSFER' && diagnostic?.armed && (
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

      {actif && mode === 'TRANSFER' && (
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

      {actif && mode === 'TRANSFER' && (diagnostic?.journal?.length ?? 0) > 0 && (
        <ol className="mt-3 space-y-1 border-t border-border pt-3 text-xs">
          {/* Ce qui s'est VRAIMENT passé. Sans cette trace, un geste réussi
              dont le message disparaît laisse dire « je pense que ça a
              marché » — et le supposer est déjà un échec. */}
          {diagnostic!.journal!.map((ligne, i) => (
            <li key={`${ligne.at}-${i}`} className="flex gap-2">
              <span className="tabular-nums text-muted-foreground">{ligne.at}</span>
              <span className={ligne.ok ? 'text-emerald-500' : 'text-muted-foreground'}>
                {ligne.what}
              </span>
              <span className="text-muted-foreground">{ligne.detail}</span>
            </li>
          ))}
        </ol>
      )}

      {erreur && (
        <p className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {erreur}
        </p>
      )}
    </section>
  );
}

/**
 * Mesurer plutôt que supposer — en deux temps, pour ne rien deviner.
 *
 * Le seuil d'usine était réglé pour une pièce imaginaire : celle de Carlito
 * vit au-dessus, et le silence déclenchait tout seul. Un seuil juste se
 * mesure dans la pièce où l'on clape, avec les mains qu'on a.
 *
 * La première version enchaînait les deux phases dans un seul appel et
 * affichait « Maintenant ! Clape » sur un minuteur armé AVANT l'envoi de la
 * requête — donc pendant que le serveur écoutait encore le silence. Trois
 * mesures sur quatre échouaient, et le message d'erreur accusait les claps.
 * Ici, l'ordre de claper n'est donné qu'une fois la pièce réellement
 * mesurée, et la seconde requête part dans la foulée.
 */
function MesureDesClaps({
  seuil,
  mesure,
  fond,
}: {
  seuil?: number;
  mesure?: boolean;
  fond?: number;
}) {
  const [phase, setPhase] = useState<'repos' | 'piece' | 'claps'>('repos');
  const [resultat, setResultat] = useState<string | null>(null);
  const [souci, setSouci] = useState<string | null>(null);

  async function mesurer() {
    setSouci(null);
    setResultat(null);
    try {
      setPhase('piece');
      await mesurerLaPiece();
      setPhase('claps');
      const vu = await mesurerLesClaps();
      const n = vu.clapPeaks.length;
      const ecartes = vu.discarded.length
        ? ` ${vu.discarded.length} bruit${vu.discarded.length > 1 ? 's' : ''} écarté${
            vu.discarded.length > 1 ? 's' : ''
          }.`
        : '';
      setResultat(
        `${n} clap${n > 1 ? 's' : ''} entendu${n > 1 ? 's' : ''} — seuil posé à ` +
          `${vu.threshold.toFixed(3)}, soit ${(vu.threshold / Math.max(vu.roomLoudest, 1e-6)).toFixed(
            0,
          )} fois le plus fort que ta pièce ait fait toute seule.${ecartes}`,
      );
    } catch (e) {
      setSouci(e instanceof Error ? e.message : 'La mesure a échoué.');
    } finally {
      setPhase('repos');
    }
  }

  const enCours = phase !== 'repos';
  // La marge se lit, elle ne se devine pas : c'est le rapport du seuil au
  // fond réellement appris qui dit si la pièce risque de déclencher seule.
  const marge = seuil && fond ? seuil / fond : null;
  return (
    <div className="mt-2 rounded-lg border border-dashed border-border px-3 py-2 text-xs">
      <div className="flex items-center justify-between gap-3">
        <span className="text-muted-foreground">
          Seuil&nbsp;:{' '}
          <span className="tabular-nums text-foreground">
            {seuil ? seuil.toFixed(3) : '—'}
          </span>
          {mesure ? ' (mesuré ici)' : ' (réglage d’usine)'}
          {marge && (
            <>
              {' · '}
              <span className="tabular-nums text-foreground">
                ×{marge.toFixed(0)}
              </span>{' '}
              au-dessus du bruit
            </>
          )}
        </span>
        <button
          type="button"
          onClick={mesurer}
          disabled={enCours}
          className="shrink-0 rounded-md border border-border px-2 py-1 text-foreground disabled:opacity-60"
        >
          {enCours ? 'Mesure en cours…' : 'Mesurer mes claps'}
        </button>
      </div>
      {phase === 'piece' && (
        <p className="mt-2 text-foreground">
          Ne bouge pas, ne clape pas encore — j’écoute ta pièce.
        </p>
      )}
      {phase === 'claps' && (
        <p className="mt-2 font-medium text-foreground">
          Maintenant&nbsp;! Clape trois fois, normalement, là où tu es
          d’habitude.
        </p>
      )}
      {resultat && <p className="mt-2 text-muted-foreground">{resultat}</p>}
      {souci && <p className="mt-2 text-destructive">{souci}</p>}
    </div>
  );
}
