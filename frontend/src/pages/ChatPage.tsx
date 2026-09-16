import { ChatArea } from '../components/Chat/ChatArea';
import { SystemPanel } from '../components/Chat/SystemPanel';
import { useAppStore } from '../lib/store';
import { useTranslation } from '../i18n/useTranslation';

export function ChatPage() {
  const { t } = useTranslation();
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);

  return (
    <div className="relative flex h-full overflow-hidden">
      <div className="flex-1 min-w-0">
        <ChatArea />
      </div>
      {/* 16 sept. 2026, audit du mini-panneau : sous sm le SystemPanel se
          superpose au fil (voir son commentaire) ; sans voile, le fil restait
          cliquable derrière et rien ne refermait le panneau d'un geste. Le
          voile est un bouton : atteignable au clavier, nommé — §82. */}
      {systemPanelOpen && (
        <button
          type="button"
          onClick={toggleSystemPanel}
          aria-label={t('chat.system.closePanel')}
          className="absolute inset-0 z-30 cursor-default sm:hidden"
          style={{ background: 'rgba(0, 0, 0, 0.35)', border: 'none' }}
        />
      )}
      {systemPanelOpen && <SystemPanel />}
    </div>
  );
}
