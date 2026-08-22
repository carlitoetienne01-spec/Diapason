import { AudioLines } from 'lucide-react';
import { openTalkToDiapason } from './TalkToDiapasonHost';
import { useTranslation } from '../i18n/useTranslation';

/** Voice is reachable from anywhere, so this rides in the window's top-right
 * cluster rather than inside any one page. */
export function TalkButton() {
  const { t } = useTranslation();

  return (
    <button
      onClick={() => openTalkToDiapason()}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-opacity cursor-pointer"
      style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent, #fff)' }}
      title={t('chat.talk.buttonTooltip')}
      onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.88')}
      onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
    >
      <AudioLines size={14} />
      {t('chat.talk.button')}
    </button>
  );
}
