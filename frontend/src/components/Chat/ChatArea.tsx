import { useRef, useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { MessageBubble } from './MessageBubble';
import { InputArea } from './InputArea';
import { StreamingDots } from './StreamingDots';
import { useAppStore } from '../../lib/store';
import { PanelRightOpen, PanelRightClose, Database, MessageSquare, X } from 'lucide-react';
import { MatrixRain } from './MatrixRain';
import { listConnectors } from '../../lib/connectors-api';
import { useTranslation } from '../../i18n/useTranslation';

/** Horizontal room the window's floating top-right cluster needs: its measured
 * width, its 12px offset from the edge, and a little air. */
const CLUSTER_CLEARANCE = 'calc(var(--top-right-cluster, 33px) + 20px)';

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
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);
  const wasStreaming = useRef(false);
  const lastScrollTop = useRef(0);

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

  const PanelIcon = systemPanelOpen ? PanelRightClose : PanelRightOpen;

  return (
    <div className="flex flex-col h-full">
      {/* Toggle bar */}
      <div
        className="flex items-center justify-end gap-1 pl-3 py-1.5 shrink-0"
        style={{
          // Talk and the approval bell are pinned to the window's top-right
          // corner. With the system panel open the panel sits beneath them;
          // closed, this bar reaches that same edge, so it has to yield their
          // footprint or the controls land on top of one another.
          paddingRight: systemPanelOpen ? 12 : CLUSTER_CLEARANCE,
        }}
      >
        <button
          onClick={toggleSystemPanel}
          className="p-1.5 rounded-md transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          title={
            systemPanelOpen
              ? t('chat.system.hidePanel', {
                  shortcut: `${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+I`,
                })
              : t('chat.system.showPanel', {
                  shortcut: `${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+I`,
                })
          }
        >
          <PanelIcon size={16} />
        </button>
      </div>

      {/* Data sources banner */}
      {hasConnectedSources === false && !bannerDismissed && (
        <div
          className="mx-4 mb-2 flex items-center gap-3 px-4 py-3 rounded-lg text-sm shrink-0"
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
      {/* The rain is a sibling of the scroller, not a child: inside it the
          canvas would slide away with the messages. */}
      <div className="flex-1 relative overflow-hidden">
        <MatrixRain />
        <div
          ref={listRef}
          onScroll={handleScroll}
          className="absolute inset-0 overflow-y-auto"
        >
          {isEmpty ? (
            <div className="flex flex-col items-center justify-center h-full px-4">
              <h2 className="text-xl font-semibold mb-2" style={{ color: 'var(--color-text)' }}>
                {t(greetingKey())}
              </h2>
              <p className="text-sm text-center max-w-sm mb-6" style={{ color: 'var(--color-text-secondary)' }}>
                {t('chat.empty.subtitle')}
              </p>

              {/* Quick action hints */}
              <div className="flex gap-3">
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
      <InputArea />
    </div>
  );
}
