import { useRef, useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { MessageBubble } from './MessageBubble';
import { InputArea } from './InputArea';
import { StreamingDots } from './StreamingDots';
import { EnteteDiscussion } from './EnteteDiscussion';
import { useAppStore } from '../../lib/store';
import { Database, MessageSquare, X } from 'lucide-react';
import { MatrixRain } from './MatrixRain';
import { listConnectors } from '../../lib/connectors-api';
import { useTranslation } from '../../i18n/useTranslation';
import {
  EVENEMENT_MONTRER_MESSAGE,
  EVENEMENT_OUVRIR_SAUTEUR,
  consommerLeMessageAMontrer,
} from '../../lib/panneau';

// 800 ms de halo sur la bulle qu'un résultat de recherche vient d'ouvrir :
// voir .bulle-cible dans index.css, qui porte le même nombre.
const HALO_MS = 800;

// The greeting picks a catalogue key rather than a sentence: a hook cannot be
// called out here, so the wording is resolved at render time.
function greetingKey():
  | 'chat.greeting.morning'
  | 'chat.greeting.afternoon'
  | 'chat.greeting.evening' {
  const hour = new Date().getHours();
  if (hour < 12) return 'chat.greeting.morning';
  if (hour < 18) return 'chat.greeting.afternoon';
  return 'chat.greeting.evening';
}

export function ChatArea() {
  const { t } = useTranslation();
  const messages = useAppStore((s) => s.messages);
  const streamState = useAppStore((s) => s.streamState);
  const activeId = useAppStore((s) => s.activeId);
  const navigate = useNavigate();
  // 17 sept. 2026 : l'état d'ouverture du sauteur de discussions (⌘J) vit
  // ici — state local, jamais une route (le rail réécrit l'URL). L'en-tête
  // l'ouvre au clic ; ⌘J arrive d'App.tsx par un événement, la touche est
  // reçue là-bas et le fil n'y est pas connu.
  const [sauteurOuvert, setSauteurOuvert] = useState(false);
  useEffect(() => {
    const ouvrir = () => setSauteurOuvert(true);
    window.addEventListener(EVENEMENT_OUVRIR_SAUTEUR, ouvrir);
    return () => window.removeEventListener(EVENEMENT_OUVRIR_SAUTEUR, ouvrir);
  }, []);
  const listRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);
  const wasStreaming = useRef(false);
  const lastScrollTop = useRef(0);

  // 17 sept. 2026 : un résultat de recherche venu d'un MESSAGE (sauteur,
  // barre latérale) ouvre le fil au message, pas en bas. La demande arrive
  // par événement après la sélection — ou, depuis la barre latérale, AVANT
  // que cette vue soit montée : on la relit alors au montage. Le défilement
  // se fait dans l'effet ci-dessous, une fois les bulles rendues.
  const [messageCible, setMessageCible] = useState<string | null>(() =>
    consommerLeMessageAMontrer(),
  );
  useEffect(() => {
    const montrer = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      if (typeof id === 'string' && id) setMessageCible(id);
    };
    window.addEventListener(EVENEMENT_MONTRER_MESSAGE, montrer);
    return () => window.removeEventListener(EVENEMENT_MONTRER_MESSAGE, montrer);
  }, []);

  // Check if any data sources are connected
  const [hasConnectedSources, setHasConnectedSources] = useState<boolean | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    listConnectors()
      .then((list) => setHasConnectedSources(list.some((c) => c.connected)))
      .catch(() => setHasConnectedSources(null));
  }, []);

  useEffect(() => {
    // Sending a message always pins the view to the bottom, even if the
    // user had scrolled up to read earlier messages.
    if (streamState.isStreaming && !wasStreaming.current) {
      shouldAutoScroll.current = true;
    }
    wasStreaming.current = streamState.isStreaming;
    if (shouldAutoScroll.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, streamState.content, streamState.isStreaming]);

  // Déclaré APRÈS l'effet d'auto-défilement : les deux courent au même
  // commit, et celui-ci doit avoir le dernier mot. Le défilement est
  // désarmé pour que le prochain rendu ne ramène pas la vue en bas.
  useEffect(() => {
    if (!messageCible) return;
    const bulle = listRef.current?.querySelector<HTMLElement>(
      `[data-message-id="${CSS.escape(messageCible)}"]`,
    );
    if (bulle) {
      shouldAutoScroll.current = false;
      const sansMouvement = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      bulle.scrollIntoView({ block: 'center', behavior: sansMouvement ? 'auto' : 'smooth' });
    }
    // Le halo se retire au bout de HALO_MS, cible trouvée ou non : une cible
    // absente (message supprimé dans l'autre vue) ne doit pas rester armée
    // jusqu'à ce qu'un id identique réapparaisse.
    const timer = window.setTimeout(() => setMessageCible(null), HALO_MS);
    return () => window.clearTimeout(timer);
  }, [messageCible, messages]);

  const handleScroll = () => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    const distance = scrollHeight - scrollTop - clientHeight;
    const scrolledUp = scrollTop < lastScrollTop.current;
    lastScrollTop.current = scrollTop;
    if (scrolledUp && distance >= 1) {
      // Any upward scroll away from the bottom stops autoscroll immediately,
      // so streaming content never fights the user (no jitter). Sub-1px
      // upward movement (elastic bounce settling at the bottom) is ignored.
      shouldAutoScroll.current = false;
    } else if (!scrolledUp) {
      // Re-engage when scrolled back to the bottom. < 2 rather than < 1:
      // at fractional zoom levels the at-bottom residual can reach 1px,
      // which would otherwise leave autoscroll permanently disengaged.
      shouldAutoScroll.current = distance < 2;
    }
  };

  const isEmpty = messages.length === 0 && !streamState.isStreaming;

  return (
    <div className="flex flex-col h-full">
      {/* 17 sept. 2026 : la rangée du haut ne portait que l'icône du panneau
          système ; elle porte maintenant le nom du fil et, en compact, de quoi
          en changer — dans les mêmes 40 px (EnteteDiscussion). */}
      <EnteteDiscussion
        sauteurOuvert={sauteurOuvert}
        onOuvrirSauteur={() => setSauteurOuvert(true)}
        onFermerSauteur={() => setSauteurOuvert(false)}
      />

      {/* Data sources banner. 16 sept. 2026, audit du mini-panneau : à 420 px
          il occupait trois lignes (texte + deux boutons) au-dessus d'un fil
          déjà court ; sous sm il disparaît — les connecteurs se règlent dans
          la fenêtre principale, l'état vide offre encore le raccourci. */}
      {hasConnectedSources === false && !bannerDismissed && (
        <div
          className="mx-4 mb-2 hidden sm:flex items-center gap-3 px-4 py-3 rounded-lg text-sm shrink-0"
          style={{
            background: 'var(--color-accent-subtle)',
            border: '1px solid var(--color-border)',
          }}
        >
          <Database size={16} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
          <span style={{ color: 'var(--color-text-secondary)', flex: 1 }}>
            {t('chat.sources.banner')}
          </span>
          <button
            onClick={() => navigate('/data-sources')}
            className="px-3 py-1 rounded text-xs font-medium cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', border: 'none' }}
          >
            {t('common.connect')}
          </button>
          <button
            onClick={() => setBannerDismissed(true)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)', background: 'transparent', border: 'none' }}
            aria-label={t('common.dismiss')}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {/* 12 septembre 2026 : la pluie s'arrêtait avant le compositeur ; une
          vitre sur un fond uni ressemblait donc à une plaque beige. Le même
          canevas passe maintenant derrière les deux, sans suivre le scroll. */}
      <div className="relative isolate flex flex-1 min-h-0 flex-col">
      <div className="absolute inset-0 -z-10 overflow-hidden pointer-events-none" aria-hidden="true">
        <MatrixRain />
      </div>
      <div className="flex-1 relative overflow-hidden">
        <div
          ref={listRef}
          onScroll={handleScroll}
          className="absolute inset-0 overflow-y-auto"
        >
          {/* Clé = fil actif : changer de discussion (⌘N, ＋, sauteur) fait
              naître le nouveau contenu en fondu (.fil-fondu, 180 ms) ; le
              conteneur de défilement, lui, reste en place. */}
          <div key={activeId ?? 'aucune'} className="fil-fondu h-full">
          {isEmpty ? (
            <div className="flex flex-col items-center justify-center h-full px-4">
              <h2 className="text-xl font-semibold mb-2" style={{ color: 'var(--color-text)' }}>
                {t(greetingKey())}
              </h2>
              <p className="text-sm text-center max-w-sm mb-6" style={{ color: 'var(--color-text-secondary)' }}>
                {t('chat.empty.subtitle')}
              </p>

              {/* Quick action hints. Sans wrap, les deux boutons débordaient
                  du panneau sous ~390 px (16 sept. 2026). */}
              <div className="flex flex-wrap justify-center gap-3">
                <button
                  onClick={() => navigate('/data-sources')}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-xs cursor-pointer transition-colors"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-secondary)',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-accent)')}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-border)')}
                >
                  <Database size={14} style={{ color: 'var(--color-accent)' }} />
                  {t('chat.empty.connectSources')}
                </button>
                <button
                  onClick={() => { navigate('/data-sources'); setTimeout(() => window.dispatchEvent(new CustomEvent('switch-tab', { detail: 'messaging' })), 100); }}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-xs cursor-pointer transition-colors"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-secondary)',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-accent)')}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-border)')}
                >
                  <MessageSquare size={14} style={{ color: 'var(--color-accent)' }} />
                  {t('chat.empty.setupMessaging')}
                </button>
              </div>
            </div>
          ) : (
            <div className="max-w-[var(--chat-max-width)] mx-auto px-4 py-6">
              {messages.map((msg, i) => {
                const isLastAssistant =
                  i === messages.length - 1 && msg.role === 'assistant';
                return (
                  <MessageBubble
                    key={msg.id}
                    message={msg}
                    isLive={isLastAssistant && streamState.isStreaming}
                    cible={msg.id === messageCible}
                  />
                );
              })}
              {(() => {
                if (!streamState.isStreaming || streamState.content !== '') return null;
                // For research messages the ResearchTimeline handles its own
                // pre-content loading state — suppress the generic dots.
                const last = messages[messages.length - 1];
                if (last?.role === 'assistant' && last.isResearch) return null;
                return (
                  <div className="flex justify-start mb-4">
                    <StreamingDots phase={streamState.phase} />
                  </div>
                );
              })()}
            </div>
          )}
          </div>
        </div>
      </div>
      <InputArea />
      </div>
    </div>
  );
}
