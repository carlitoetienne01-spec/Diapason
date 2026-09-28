import { useEffect, useRef } from 'react';
import type { MicroEnEchec } from '../../hooks/useVoiceLive';
import { useTranslation } from '../../i18n/useTranslation';
import { doitReprendreLeFocus, vueDuDetailDuMicro } from './vueDuMicro';

/**
 * Sous la phrase d'un micro qui ne s'est pas ouvert : le détail technique et
 * le bouton des réglages d'Android. Le même rendu dans la barre de la
 * Discussion et dans l'orbe, qui partagent le hook de la voix.
 *
 * 28/09/2026 : la capture d'écran de Carlito ne disait que « Micro fermé » et
 * la phrase des Réglages Système du Mac ; le nom de l'erreur n'était qu'en
 * console, sur un téléphone sans console. Le détail n'existe qu'au
 * téléphone (le hook le retient au bureau), le bouton qu'avec une coquille
 * qui sait ouvrir ses réglages — décidé par `vueDuDetailDuMicro`, testée
 * seule. Cible de 40 px au doigt, rien au survol seul (CLAUDE.md §3).
 */
export function DetailDuMicro({
  micro,
  onOuvrirReglages,
  classeBouton,
  classeConteneur = '',
}: {
  micro: MicroEnEchec | null;
  onOuvrirReglages: () => void;
  classeBouton?: string;
  /** Pour s'aligner sur la phrase d'erreur de l'hôte. */
  classeConteneur?: string;
}) {
  const { t } = useTranslation();
  const vue = vueDuDetailDuMicro(micro, t);
  // Le bouton retiré au retour des Paramètres emportait le focus avec lui :
  // le détail, juste sous la phrase annoncée, le reprend.
  const conteneur = useRef<HTMLDivElement>(null);
  const avaitUnBouton = useRef(false);
  const bouton = !!vue?.bouton;
  useEffect(() => {
    const avant = avaitUnBouton.current;
    avaitUnBouton.current = bouton;
    if (doitReprendreLeFocus(avant, bouton, document.activeElement, document.body)) conteneur.current?.focus();
  }, [bouton]);
  if (!vue) return null;
  return (
    <div ref={conteneur} tabIndex={-1}
      className={`detail-du-micro mt-2 flex flex-col items-start gap-2 focus:outline-none ${classeConteneur}`}>
      {vue.detail && (
        <p className="text-[11px] leading-snug opacity-80" style={{ overflowWrap: 'anywhere' }}>
          {vue.detail}
        </p>
      )}
      {vue.bouton && (
        <button
          type="button"
          onClick={onOuvrirReglages}
          className={classeBouton ?? 'min-h-10 px-4 rounded-full text-sm cursor-pointer'}
          style={classeBouton ? undefined : { border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
        >
          {vue.bouton}
        </button>
      )}
      {vue.avis && (
        <p role="status" className="text-xs">
          {vue.avis}
          {vue.reponse && (
            <span className="mt-1 block text-[11px] opacity-80" style={{ overflowWrap: 'anywhere' }}>
              {vue.reponse}
            </span>
          )}
        </p>
      )}
    </div>
  );
}
