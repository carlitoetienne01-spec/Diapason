import { useRef, useEffect, useLayoutEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { MessageBubble } from './MessageBubble';
import { InputArea } from './InputArea';
import { StreamingDots } from './StreamingDots';
import { EnteteDiscussion } from './EnteteDiscussion';
import { useAppStore } from '../../lib/store';
import { CornerDownLeft, Database, MessageSquare, X } from 'lucide-react';
import { MatrixRain } from './MatrixRain';
import { listConnectors } from '../../lib/connectors-api';
import { useTranslation } from '../../i18n/useTranslation';
import {
  EVENEMENT_ENTREE_A_VIDE,
  EVENEMENT_FIL_GLISSE,
  EVENEMENT_MONTRER_MESSAGE,
  EVENEMENT_OUVRIR_SAUTEUR,
  consommerLeMessageAMontrer,
  demanderLeFocusDuCompositeur,
} from '../../lib/panneau';
import {
  nombreDeRecentesQuiTiennent,
  recentesPourAccueil,
  type SensVoisine,
} from '../../lib/discussions';
import { formatRelativeTime, sectionsOf } from '../Sidebar/ConversationList';

// 800 ms de halo sur la bulle qu'un résultat de recherche vient d'ouvrir :
// voir .bulle-cible dans index.css, qui porte le même nombre.
const HALO_MS = 800;

// ⌘⇧[ / ⌘⇧] : le fil glisse de 24 px dans le sens du geste — assez pour
// se lire comme un mouvement, pas assez pour qu'un fil de 340 px semble
// sortir du cadre. Le fondu dure 180 ms (.fil-fondu) ; le décalage est
// retiré à 260 — 180 plus une marge pour un minuteur qui part avant la
// première image — pour que le prochain changement de fil (⌘N, sauteur)
// ne glisse pas à son tour. Retiré trop tôt, les keyframes relisent la
// variable en cours de route et le fil saute sur ses derniers pixels.
const GLISSEMENT_PX = 24;
const GLISSEMENT_MS = 260;

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
  const conversations = useAppStore((s) => s.conversations);
  const selectConversation = useAppStore((s) => s.selectConversation);
  const loadMessages = useAppStore((s) => s.loadMessages);
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
  // Le sens annoncé par App.tsx juste avant le changement de fil ; posé en
  // variable CSS sur le conteneur re-monté, pas en classe : changer
  // `animation-name` après coup relancerait le fondu, changer une variable
  // que les keyframes ont déjà lue ne fait rien.
  const [glissement, setGlissement] = useState<SensVoisine | null>(null);
  useEffect(() => {
    const glisser = (e: Event) => {
      const sens = (e as CustomEvent<SensVoisine>).detail;
      if (sens === 'precedente' || sens === 'suivante') setGlissement(sens);
    };
    window.addEventListener(EVENEMENT_FIL_GLISSE, glisser);
    return () => window.removeEventListener(EVENEMENT_FIL_GLISSE, glisser);
  }, []);
  useEffect(() => {
    if (!glissement) return;
    const timer = window.setTimeout(() => setGlissement(null), GLISSEMENT_MS);
    return () => window.clearTimeout(timer);
  }, [glissement, activeId]);
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

  const isEmpty = messages.length === 0 && !streamState.isStreaming;

  useEffect(() => {
    // Sending a message always pins the view to the bottom, even if the
    // user had scrolled up to read earlier messages.
    if (streamState.isStreaming && !wasStreaming.current) {
      shouldAutoScroll.current = true;
    }
    wasStreaming.current = streamState.isStreaming;
    if (shouldAutoScroll.current && listRef.current) {
      // La page vide se lit par le HAUT : salut, puis « Reprendre ». Épinglée
      // en bas comme un fil (contre-revue du 17 sept. 2026, mini à 340×380 :
      // scrollTop 86,5 = max après ⌘N), elle montrait une liste de récentes
      // coupée sous l'en-tête, sans le salut ni l'invitation.
      listRef.current.scrollTop = isEmpty ? 0 : listRef.current.scrollHeight;
    }
  }, [messages, streamState.content, streamState.isStreaming, isEmpty]);

  // Combien de récentes tiennent sous « Reprendre » dans le fil tel qu'il
  // est (nombreDeRecentesQuiTiennent sur sa hauteur). Le NSPanel se
  // redimensionne en continu : observé, pas lu une fois — et c'est le
  // NOMBRE qui est gardé, pas la hauteur, pour ne pas re-rendre le fil à
  // chaque pixel d'étirement. null = pas encore mesuré : le premier rendu
  // suppose que tout tient, l'effet de mise en page corrige avant le paint.
  const [nbRecentes, setNbRecentes] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const mesurer = () => setNbRecentes(nombreDeRecentesQuiTiennent(el.clientHeight));
    mesurer();
    if (typeof ResizeObserver === 'undefined') return;
    const observateur = new ResizeObserver(mesurer);
    observateur.observe(el);
    return () => observateur.disconnect();
  }, []);

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

  // 17 sept. 2026 : en compact, la page vide vendait des connecteurs au lieu
  // d'inviter à écrire ou à reprendre. Elle propose le dernier fil
  // (« Reprendre « <titre> » — il y a 2 h ↩ ») et les suivants qui tiennent,
  // trois au plus ; rien ne s'ouvre, c'est le contenu de la page qui change.
  // Hors compact la barre latérale fait ce travail : le bloc est
  // `hidden compact:flex`.
  const accueil = isEmpty
    ? recentesPourAccueil(conversations, activeId, Date.now(), nbRecentes ?? undefined)
    : null;
  const reprendreRef = useRef<HTMLButtonElement>(null);
  // Jamais pendant un flux (comme ⌘N et le sauteur, contre-revue du 17 sept.
  // 2026) : l'invitation n'est rendue que sur un fil vide sans flux, mais
  // le ↩ à vide arrive par événement et ne doit pas dépendre du rendu.
  const reprendre = (id: string) => {
    if (useAppStore.getState().streamState.isStreaming) return;
    selectConversation(id);
    loadMessages(id);
    demanderLeFocusDuCompositeur();
  };
  // ↩ dans le compositeur vide reprend le dernier fil — SEULEMENT si
  // l'invitation est VISIBLE : `offsetParent` est null sous display:none
  // (hors compact), et le bouton doit croiser le cadre du fil — défilé hors
  // vue, `offsetParent` répondait encore « DIV » et le ↩ changeait de fil
  // sans que le libellé qui le promet soit à l'écran (contre-revue du
  // 17 sept. 2026). Le ↩ du libellé n'est pas une promesse en l'air, et la
  // fenêtre principale garde son ↩ à vide qui ne fait rien.
  const reprendreId = accueil?.reprendre?.id ?? null;
  useEffect(() => {
    if (!reprendreId) return;
    const surEntree = () => {
      const bouton = reprendreRef.current;
      const cadre = listRef.current;
      if (!bouton || !cadre || bouton.offsetParent === null) return;
      const b = bouton.getBoundingClientRect();
      const c = cadre.getBoundingClientRect();
      if (b.bottom <= c.top || b.top >= c.bottom) return;
      reprendre(reprendreId);
    };
    window.addEventListener(EVENEMENT_ENTREE_A_VIDE, surEntree);
    return () => window.removeEventListener(EVENEMENT_ENTREE_A_VIDE, surEntree);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reprendreId]);

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
          <div
            key={activeId ?? 'aucune'}
            className="fil-fondu h-full"
            style={
              glissement
                ? ({
                    '--fil-decalage': `${glissement === 'suivante' ? GLISSEMENT_PX : -GLISSEMENT_PX}px`,
                  } as React.CSSProperties)
                : undefined
            }
          >
          {isEmpty ? (
            /* `min-h-full`, pas `h-full` : centré dans 122 px, un contenu de
               209 partait pour moitié en débordement négatif, non défilable —
               le salut était inatteignable à 340×380 (17 sept. 2026). Sous sm
               le sous-titre s'efface et les marges se resserrent : le mini
               invite à écrire ou à reprendre, sans défiler. */
            <div className="flex flex-col items-center justify-center min-h-full px-4">
              <h2
                className="text-xl font-semibold mb-1 sm:mb-2"
                style={{ color: 'var(--color-text)' }}
              >
                {t(greetingKey())}
              </h2>
              <p
                className="hidden sm:block text-sm text-center max-w-sm mb-6"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {t('chat.empty.subtitle')}
              </p>

              {accueil?.reprendre && (
                <div className="hidden compact:flex flex-col w-full max-w-sm sm:mb-6">
                  <button
                    ref={reprendreRef}
                    type="button"
                    onClick={() => reprendre(accueil.reprendre!.id)}
                    className="flex items-center gap-2 px-3 h-9 rounded-lg text-[13px] text-left cursor-pointer transition-colors"
                    style={{
                      background: 'var(--color-accent-subtle)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  >
                    <span className="flex-1 min-w-0 truncate">
                      {t('chat.empty.resume', {
                        title: accueil.reprendre.title.trim() || t('sidebar.untitled'),
                      })}
                    </span>
                    <span
                      className="shrink-0 text-[11px] tabular-nums"
                      style={{ color: 'var(--color-text-tertiary)' }}
                    >
                      {formatRelativeTime(accueil.reprendre.updatedAt, t)}
                    </span>
                    <CornerDownLeft
                      size={12}
                      className="shrink-0"
                      aria-hidden="true"
                      style={{ color: 'var(--color-text-tertiary)' }}
                    />
                  </button>
                  {accueil.autres.length > 0 && (
                    <div role="list" aria-label={t('chat.empty.recent')} className="mt-1">
                      {sectionsOf(accueil.autres, t).map((section) => (
                        <div key={section.label}>
                          <div
                            className="px-3 pt-2 pb-0.5 text-[10px] font-medium uppercase tracking-wider select-none"
                            style={{ color: 'var(--color-text-tertiary)' }}
                          >
                            {section.label}
                          </div>
                          {section.items.map((c) => (
                            <button
                              key={c.id}
                              type="button"
                              role="listitem"
                              onClick={() => reprendre(c.id)}
                              className="composer-glass-menu-item flex items-center gap-2 w-full px-3 h-7 rounded-md text-[13px] text-left cursor-pointer"
                              style={{ color: 'var(--color-text)' }}
                            >
                              <span
                                className="flex-1 min-w-0 truncate"
                                style={{
                                  color: c.title.trim()
                                    ? 'var(--color-text)'
                                    : 'var(--color-text-tertiary)',
                                }}
                              >
                                {c.title.trim() || t('sidebar.untitled')}
                              </span>
                              <span
                                className="shrink-0 text-[11px] tabular-nums"
                                style={{ color: 'var(--color-text-tertiary)' }}
                              >
                                {formatRelativeTime(c.updatedAt, t)}
                              </span>
                            </button>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Quick action hints. Sans wrap, les deux boutons débordaient
                  du panneau sous ~390 px (16 sept. 2026). 17 sept. : sous
                  sm, cachés — le mini-panneau invite à écrire ou à
                  reprendre, les connecteurs se règlent dans la fenêtre. */}
              <div className="hidden sm:flex flex-wrap justify-center gap-3">
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
