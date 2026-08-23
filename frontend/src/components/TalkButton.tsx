import { AudioLines } from 'lucide-react';
import { openTalkToDiapason } from './TalkToDiapasonHost';
import { useTranslation } from '../i18n/useTranslation';

/** Voice entry in the sidebar footer, next to Réglages. Same quiet chrome as
 * the settings row so it does not shout over the workspace. */
export function TalkButton() {
  const { t } = useTranslation();

  return (
    <button
      type="button"
      onClick={() => openTalkToDiapason()}
      className="flex flex-1 items-center gap-2 px-4 py-3 text-sm transition-colors cursor-pointer min-w-0"
      style={{
        color: 'var(--color-text-secondary)',
        background: 'transparent',
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      title={t('chat.talk.buttonTooltip')}
    >
      <AudioLines size={16} className="shrink-0" />
      <span className="truncate">{t('chat.talk.navLabel')}</span>
    </button>
  );
}
