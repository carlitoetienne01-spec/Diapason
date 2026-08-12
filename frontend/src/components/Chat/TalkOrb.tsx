import { Suspense, lazy } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from '../../i18n/useTranslation';
import type { AIState } from '../AIEntity/types';

// Three.js is half a megabyte and is needed only once this panel opens, so it
// is fetched then rather than on every cold start of the app.
const AIEntity = lazy(() =>
  import('../AIEntity/AIEntity').then((m) => ({ default: m.AIEntity })),
);
import type { VoiceLiveProvider, VoiceLiveState, TranscriptLine, ToolEventLine } from '../../hooks/useVoiceLive';

/**
 * The session has five states; the entity has four. `connecting` is the one
 * moment the assistant is working without hearing or answering, which is
 * exactly what "thinking" depicts, and an error should stop the field acting
 * as though a conversation were still running.
 */
function entityState(state: VoiceLiveState): AIState {
  switch (state) {
    case 'listening':
      return 'listening';
    case 'speaking':
      return 'speaking';
    case 'connecting':
      return 'thinking';
    default:
      return 'idle';
  }
}

interface TalkOrbProps {
  open: boolean;
  state: VoiceLiveState;
  statusLabel: string;
  error: string | null;
  provider: VoiceLiveProvider;
  transcripts: TranscriptLine[];
  toolEvents?: ToolEventLine[];
  screenSharing?: boolean;
  /** The assistant's own voice, so SPEAKING is driven by what is actually
   * heard rather than by a timer. Optional: the entity is fully alive without it. */
  audioSource?: AudioNode | null;
  onProviderChange: (p: VoiceLiveProvider) => void;
  onStart: () => void;
  onStop: () => void;
  onInterrupt: () => void;
  onClose: () => void;
}

export function TalkOrb({
  open,
  state,
  statusLabel,
  error,
  provider,
  transcripts,
  toolEvents = [],
  screenSharing = false,
  audioSource = null,
  onProviderChange,
  onStart,
  onStop,
  onInterrupt,
  onClose,
}: TalkOrbProps) {
  const { t } = useTranslation();

  if (!open) return null;

  const active = state === 'listening' || state === 'speaking' || state === 'connecting';
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.72)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="relative w-full max-w-lg mx-4 rounded-2xl overflow-hidden"
        style={{
          background: 'var(--color-bg-secondary, #12141a)',
          border: '1px solid var(--color-border, #2a2d36)',
        }}
      >
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="text-xs tracking-widest uppercase" style={{ color: 'var(--color-text-tertiary)' }}>
              {statusLabel}
            </div>
            {screenSharing && (
              <span
                className="text-[10px] tracking-wide uppercase px-2 py-0.5 rounded"
                style={{
                  background: 'rgba(220, 80, 60, 0.2)',
                  color: '#e8a090',
                  border: '1px solid rgba(220, 80, 60, 0.35)',
                }}
                title={t('chat.talk.screenShareTooltip')}
              >
                {t('chat.talk.sharingScreen')}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-md cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)' }}
            title={t('chat.talk.close')}
            aria-label={t('chat.talk.close')}
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex flex-col items-center px-6 pb-4 pt-2">
          <button
            type="button"
            onClick={() => {
              if (active) onInterrupt();
              else void onStart();
            }}
            className="relative w-full cursor-pointer"
            style={{
              height: 200,
              background: 'none',
              border: 'none',
              padding: 0,
            }}
            title={active ? t('chat.talk.interruptHint') : t('chat.talk.startHint')}
          >
            {/* No fallback: an empty box for a few hundred milliseconds reads
                as loading, a placeholder shape reads as a glitch. */}
            <Suspense fallback={null}>
              <AIEntity
                state={entityState(state)}
                // Dimmer when there is nothing to say: present, not performing.
                intensity={active ? 1 : 0.62}
                audioSource={audioSource}
                style={{ position: 'absolute', inset: 0 }}
              />
            </Suspense>
          </button>

          <p className="mt-5 text-lg font-medium" style={{ color: 'var(--color-text)' }}>
            {t('chat.talk.justSpeak')}
          </p>
          <p className="mt-1 text-sm text-center max-w-sm" style={{ color: 'var(--color-text-secondary)' }}>
            {t('chat.talk.shortcuts')}
          </p>

          <div className="mt-4 flex items-center gap-2">
            <select
              value={provider}
              disabled={active}
              onChange={(e) => onProviderChange(e.target.value as VoiceLiveProvider)}
              className="text-xs rounded-md px-2 py-1.5"
              style={{
                background: 'var(--color-bg-tertiary)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
            >
              <option value="local">{t('talk.providerLocal')}</option>
              <option value="gemini">Gemini Live</option>
              <option value="openai">OpenAI Realtime</option>
            </select>
            {active ? (
              <button
                type="button"
                onClick={onStop}
                className="text-xs px-3 py-1.5 rounded-md cursor-pointer"
                style={{ background: 'var(--color-error)', color: '#fff' }}
              >
                {t('chat.talk.end')}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void onStart()}
                className="text-xs px-3 py-1.5 rounded-md cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                {t('chat.talk.start')}
              </button>
            )}
          </div>

          {error && (
            <p className="mt-3 text-xs text-center" style={{ color: 'var(--color-error)' }}>
              {error === 'missing-key-gemini'
                ? t('talk.missingKeyGemini')
                : error === 'missing-key-openai'
                  ? t('talk.missingKeyOpenai')
                  : error === 'local-not-ready'
                    ? t('talk.localNotReady')
                    : error}
            </p>
          )}
        </div>

        {(transcripts.length > 0 || toolEvents.length > 0) && (
          <div
            className="max-h-40 overflow-y-auto px-4 py-3 text-sm space-y-2"
            style={{
              borderTop: '1px solid var(--color-border)',
              color: 'var(--color-text-secondary)',
            }}
          >
            {toolEvents.slice(-4).map((ev, i) => (
              <div key={`tool-${i}`} style={{ color: ev.ok ? 'var(--color-success)' : 'var(--color-error)' }}>
                {t('chat.talk.tool')} · {ev.name}{ev.detail ? ` — ${ev.detail}` : ''}
              </div>
            ))}
            {transcripts.slice(-8).map((line, i) => (
              <div key={`${line.role}-${i}`}>
                <span className="font-medium" style={{ color: 'var(--color-text)' }}>
                  {line.role === 'user' ? t('common.you') : 'Diapason'}
                </span>
                {': '}
                {line.text}
              </div>
            ))}
          </div>
        )}

        <div
          className="px-4 py-2 text-[11px] text-center"
          style={{ color: 'var(--color-text-tertiary)', borderTop: '1px solid var(--color-border)' }}
        >
          {provider === 'local'
            ? t('talk.footerLocal')
            : t('chat.talk.footer', {
                provider: provider === 'gemini' ? 'Gemini Live' : 'gpt-realtime',
              })}
        </div>
      </div>
    </div>
  );
}
