import { useEffect } from 'react';
import { ChatArea } from '../components/Chat/ChatArea';
import { SystemPanel } from '../components/Chat/SystemPanel';
import { useAppStore } from '../lib/store';
import {
  EVENEMENT_PANNEAU_OUVERT,
  brouillonDuCompositeur,
  demanderLeFocusDuCompositeur,
  consommerLAtterrissage,
} from '../lib/panneau';
import { choisirAtterrissage, tientLeFil } from '../lib/discussions';
import { tirer } from '../lib/convSync';
import { useTranslation } from '../i18n/useTranslation';

/**
 * 17 sept. 2026 : où le mini-panneau atterrit quand il s'ouvre. `activeId`
 * n'est jamais synchronisé et le localStorage est cloisonné par origine :
 * le panneau rouvrait toujours le fil où on l'avait laissé — la question
 * rapide posée depuis Xcode se collait à la conversation d'avant-hier. La
 * règle (choisirAtterrissage, 20 min) reprend le fil chaud, fenêtre ou mini
 * confondus, sinon une vierge par la règle commune. Jamais quand on tient le
 * fil (tientLeFil) : ni pendant un flux — on ne quitte pas une réponse en
 * cours parce que le panneau s'est rouvert — ni sur un brouillon, qui
 * partirait dans le mauvais fil (contre-revue du 17 sept. 2026).
 */
function atterrir(): void {
  const etat = useAppStore.getState();
  if (tientLeFil({ enFlux: etat.streamState.isStreaming, brouillon: brouillonDuCompositeur() })) {
    return;
  }
  const choix = choisirAtterrissage(etat.conversations, etat.activeId, Date.now());
  if (choix.type === 'reprendre') {
    etat.selectConversation(choix.id);
    etat.loadMessages(choix.id);
  } else if (choix.type === 'vierge') {
    etat.nouvelleDiscussion(etat.selectedModel);
  }
}

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
  //
  // L'atterrissage se joue deux fois : sur ce que le store a déjà, puis
  // après un tirage du serveur — au premier chargement, le fil chaud de la
  // fenêtre n'est pas encore dans le localStorage de cette origine, et
  // sans ce second passage le panneau atterrissait sur une vierge alors
  // qu'une discussion de dix minutes attendait dans l'autre vue. Le second
  // passage est sans effet quand rien n'a changé (« rester ») et s'abstient
  // si l'on a changé de fil soi-même entre-temps (sauteur, ⌘N) : un tirage
  // ne défait pas un choix.
  //
  // Seule une VRAIE ouverture (panneau caché qui se montre) atterrit.
  // Contre-revue du 17 sept. 2026 : Rust émettait le même signal à chaque
  // presenter_mini et agrandir_mini — re-cliquer « Discussion » sur le rail
  // ou déplier la pastille ramenait au fil chaud, en abandonnant le fil
  // choisi par ⌘J ; la pastille nommait un fil et en livrait un autre (§5).
  // Ces reprises émettent `diapason:panneau-repris`, que lib/panneau.ts
  // traduit en simple demande de focus.
  useEffect(() => {
    const surOuverture = () => {
      consommerLAtterrissage();
      atterrir();
      demanderLeFocusDuCompositeur();
      const avant = useAppStore.getState().activeId;
      void tirer().then(() => {
        if (useAppStore.getState().activeId === avant) atterrir();
      });
    };
    window.addEventListener(EVENEMENT_PANNEAU_OUVERT, surOuverture);
    // Montée après le signal (autre module d'abord, ou View Transition) :
    // l'ouverture attend encore son atterrissage, quel que soit le délai.
    if (consommerLAtterrissage()) surOuverture();
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
