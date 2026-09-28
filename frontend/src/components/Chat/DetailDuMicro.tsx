import type { MicroEnEchec } from '../../hooks/useVoiceLive';
import { useTranslation } from '../../i18n/useTranslation';

/**
 * Sous la phrase d'un micro qui ne s'est pas ouvert : le détail technique et
 * le bouton des réglages d'Android. Le même rendu dans la barre de la
 * Discussion et dans l'orbe, qui partagent le hook de la voix.
 *
 * 28/09/2026 : la capture d'écran de Carlito ne disait que « Micro fermé » et
 * la phrase des Réglages Système du Mac ; le nom de l'erreur n'était qu'en
 * console, sur un téléphone sans console. Le détail n'existe qu'au
 * téléphone (le hook le retient au bureau), le bouton qu'avec une coquille
 * qui sait ouvrir ses réglages. Cible de 40 px au doigt, rien au survol
 * seul (CLAUDE.md §3).
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
  if (!micro || (!micro.technique && !micro.reglages && !micro.avis)) return null;
  return (
    <div className={`detail-du-micro mt-2 flex flex-col items-start gap-2 ${classeConteneur}`}>
      {micro.technique && (
        <p className="text-[11px] leading-snug opacity-80" style={{ overflowWrap: 'anywhere' }}>
          {t('talk.micro.detail', { technique: micro.technique })}
        </p>
      )}
      {micro.reglages && (
        <button
          type="button"
          onClick={onOuvrirReglages}
          className={classeBouton ?? 'min-h-10 px-4 rounded-full text-sm cursor-pointer'}
          style={classeBouton ? undefined : { border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
        >
          {t('talk.micro.ouvrirReglages')}
        </button>
      )}
      {micro.avis && (
        <p role="status" className="text-xs">
          {'cle' in micro.avis ? t(micro.avis.cle) : micro.avis.texte}
        </p>
      )}
    </div>
  );
}
