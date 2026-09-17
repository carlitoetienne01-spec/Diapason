import { useEffect } from 'react';
import { ChatArea } from '../components/Chat/ChatArea';
import { SystemPanel } from '../components/Chat/SystemPanel';
import { useAppStore } from '../lib/store';
import {
  EVENEMENT_PANNEAU_OUVERT,
  demanderLeFocusDuCompositeur,
  panneauVientDeSOuvrir,
} from '../lib/panneau';
import { useTranslation } from '../i18n/useTranslation';

export function ChatPage() {
  const { t } = useTranslation();
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);

  // 17 sept. 2026, chantier « discussions dans le mini-panneau » : on ouvre
  // le panneau pour écrire, et le curseur n'était nulle part — il fallait
  // cliquer dans le champ. À chaque signal d'ouverture (Rust, ou Layout au
  // premier chargement), la page demande le focus au compositeur. Au
  // montage, elle regarde aussi si le signal vient de passer : à la
  // re-navigation depuis un autre module, Rust l'évalue AVANT que la View
  // Transition et le routeur n'aient monté cette page. La fenêtre principale
  // n'émet jamais ce signal : rien n'y change.
  useEffect(() => {
    const surOuverture = () => demanderLeFocusDuCompositeur();
    window.addEventListener(EVENEMENT_PANNEAU_OUVERT, surOuverture);
    if (panneauVientDeSOuvrir()) surOuverture();
    return () => window.removeEventListener(EVENEMENT_PANNEAU_OUVERT, surOuverture);
  }, []);

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
