/**
 * Le bandeau du compte (compte-chiffre.md §3.11, « Place dans
 * l'interface ») : un appareil verrouillé, une session perdue, une
 * réinitialisation prévue, un compte réinitialisé, un serveur revenu en
 * arrière ou perdu. Rien quand tout va bien, rien sans compte.
 *
 * Deux formes, choisies par Layout — le seul lecteur du mode compact :
 * - fenêtre : une ligne sous le pouls, comme « serveur injoignable », et
 *   l'écran du compte en voile au clic ;
 * - mini-panneau (D14) : l'état, et le déverrouillage en place. Rien
 *   d'autre : ni inscription ni récupération dans une surface de 340 px.
 */

import { useCallback, useState } from 'react';
import { useTranslation } from '../../i18n/useTranslation';
import { bandeauCompte } from '../../lib/compte';
import { reinitAnnuler, estErreurCompte } from './api';
import { EcranCompte, FormulaireDeverrouillage, MessageErreur, useStatutCompte } from './EcranCompte';
import type { Bandeau, ErreurLue, Parcours, StatutCompte } from '../../lib/compte';

// La fenêtre sonde toutes les 30 s, comme la santé du serveur (Layout). Le
// mini-panneau, qu'on ouvre et referme sans cesse, relit à chaque reprise
// (`diapason:panneau-repris`) : une minute suffit entre deux.
const SONDE_FENETRE_MS = 30_000;
const SONDE_PANNEAU_MS = 60_000;

export function BandeauCompte({ compact = false }: { compact?: boolean }) {
  const { locale } = useTranslation();
  const { statut } = useStatutCompte(compact ? SONDE_PANNEAU_MS : SONDE_FENETRE_MS);
  const [ecran, setEcran] = useState<Parcours | null>(null);
  const bandeau = bandeauCompte(statut, locale);
  const fermerEcran = useCallback(() => setEcran(null), []);
  // L'écran du compte reste à la MÊME place de l'arbre, bandeau ou non
  // (24/09/2026). Rendu nu quand le bandeau disparaissait, en second enfant
  // d'un fragment sinon, il était démonté puis remonté au déverrouillage :
  // la clé de récupération neuve rendue par /recover ou /reset/complete
  // (D22) était perdue, la confirmation en ton danger de « Plus tard »
  // sautée (D4), et le voile se refermait sans rien dire. Aucun test de
  // composant dans ce dépôt : reproduit avec jsdom et react-dom — deux
  // montages avant, un seul après.
  const voile = ecran ? <EcranCompte contexte="reglages" parcoursInitial={ecran} onFermer={fermerEcran} /> : null;
  return (
    <>
      {statut && bandeau && (compact ? <BarreCompacte statut={statut} bandeau={bandeau} /> : <BarreFenetre bandeau={bandeau} ouvrir={() => setEcran('accueil')} />)}
      {voile}
    </>
  );
}

function teintes(bandeau: Bandeau) {
  const couleur = bandeau.ton === 'alerte' ? 'var(--color-error)' : 'var(--color-warning)';
  const fond = {
    background: `color-mix(in srgb, ${couleur} 8%, transparent)`,
    borderBottom: `1px solid color-mix(in srgb, ${couleur} 18%, transparent)`,
    color: 'var(--color-text)',
  };
  return { couleur, fond };
}

function BarreCompacte({ statut, bandeau }: { statut: StatutCompte; bandeau: Bandeau }) {
  const { t } = useTranslation();
  const { couleur, fond } = teintes(bandeau);
  return (
    <div className="flex flex-col gap-2 px-3 py-2 text-sm shrink-0 min-w-0" style={fond} role="status">
      <div className="flex items-center gap-2 min-w-0">
        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: couleur }} />
        <span className="min-w-0" style={{ overflowWrap: 'anywhere' }}>
          {t(bandeau.cle, bandeau.vars)}
        </span>
      </div>
      {bandeau.action === 'deverrouiller' ? (
        // D14 : déverrouiller, sans la case de mémorisation — ce choix-là
        // demande de lire le §2.11, qui a sa place dans la fenêtre.
        <FormulaireDeverrouillage statut={statut} avecMemorisation={false} compact />
      ) : (
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {t('compte.section.fenetre')}
        </span>
      )}
    </div>
  );
}

function BarreFenetre({ bandeau, ouvrir }: { bandeau: Bandeau; ouvrir: () => void }) {
  const { t } = useTranslation();
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<ErreurLue | null>(null);
  const { couleur, fond } = teintes(bandeau);
  const agir = () => {
    if (bandeau.action === 'annulerReinit') {
      setOccupe(true);
      setErreur(null);
      void reinitAnnuler()
        .catch((e) => setErreur(estErreurCompte(e) ? e : { code: 'localServerUnreachable' }))
        .finally(() => setOccupe(false));
      return;
    }
    ouvrir();
  };
  const libelleAction =
    bandeau.action === 'deverrouiller'
      ? t('compte.deverrouiller')
      : bandeau.action === 'reconnecter'
        ? t('compte.bandeau.reconnecter')
        : bandeau.action === 'annulerReinit'
          ? t('compte.reinit.annuler')
          : t('compte.bandeau.ouvrir');

  return (
    <>
      {/* Les marges dégagent les deux boutons fixes qui flottent sur toute
          page : la barre latérale à gauche, la grappe (cloche) à droite, dont
          Layout publie la largeur dans --top-right-cluster. Sans elles,
          « Déverrouiller » passait sous la cloche. */}
      <div
        className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm shrink-0"
        style={{ ...fond, paddingLeft: '3rem', paddingRight: 'calc(var(--top-right-cluster, 0px) + 1.25rem)' }}
        role="status"
      >
        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: couleur }} />
        <span className="min-w-0 flex-1" style={{ overflowWrap: 'anywhere' }}>
          {t(bandeau.cle, bandeau.vars)}
        </span>
        {erreur && (
          <span className="basis-full">
            <MessageErreur erreur={erreur} />
          </span>
        )}
        {bandeau.action === 'annulerReinit' && (
          <button
            type="button"
            onClick={ouvrir}
            className="text-sm underline cursor-pointer shrink-0"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {t('compte.bandeau.details')}
          </button>
        )}
        <button
          type="button"
          onClick={agir}
          disabled={occupe}
          className="text-sm underline cursor-pointer ml-auto shrink-0 disabled:opacity-50"
          style={{ color: 'var(--color-accent)' }}
        >
          {libelleAction}
        </button>
      </div>
    </>
  );
}
