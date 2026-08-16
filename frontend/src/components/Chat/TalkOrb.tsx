import { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from '../../i18n/useTranslation';
import { useLiveDictation } from '../../hooks/useLiveDictation';
import type { AIState } from '../AIEntity/types';

// Three.js is half a megabyte and is needed only once this panel opens, so it
// is fetched then rather than on every cold start of the app.
const VoiceTerrain = lazy(() =>
  import('../VoiceTerrain/VoiceTerrain').then((m) => ({ default: m.VoiceTerrain })),
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
  serviceReady: boolean;
  checkingService: boolean;
  provider: VoiceLiveProvider;
  transcripts: TranscriptLine[];
  toolEvents?: ToolEventLine[];
  screenSharing?: boolean;
  /** The assistant's own voice, so SPEAKING is driven by what is actually
   * heard rather than by a timer. Optional: the entity is fully alive without it. */
  audioSource?: AudioNode | null;
  /** The user's microphone: LISTENING vibrates with their voice. */
  micSource?: AudioNode | null;
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
  serviceReady,
  checkingService,
  provider,
  transcripts,
  toolEvents = [],
  screenSharing = false,
  audioSource = null,
  micSource = null,
  onProviderChange,
  onStart,
  onStop,
  onInterrupt,
  onClose,
}: TalkOrbProps) {
  const { t, locale } = useTranslation();
  const active = state === 'listening' || state === 'speaking' || state === 'connecting';

  // Captions come from Apple's on-device recogniser rather than from the voice
  // session, because the local provider only reports a transcript once the
  // turn is over — too late to read along with. This listens in parallel and
  // costs nothing but a second tap on the same microphone.
  const {
    supported: captionsSupported,
    transcript: heard,
    start: startCaptions,
    stop: stopCaptions,
  } = useLiveDictation(locale);
  const [caption, setCaption] = useState('');

  useEffect(() => {
    if (!captionsSupported) return;
    if (!open || state !== 'listening') return;
    void startCaptions();
    return () => {
      void stopCaptions();
    };
  }, [captionsSupported, open, state, startCaptions, stopCaptions]);

  // Held after the user stops talking so their last sentence stays readable
  // while Diapason answers, instead of blinking out mid-thought.
  useEffect(() => {
    if (heard) setCaption(heard);
  }, [heard]);
  useEffect(() => {
    if (!active) setCaption('');
  }, [active]);

  // Readouts, kept deliberately few: the loudness driving the relief, and how
  // long the session has been open. Both are measured, never decorative.
  const [level, setLevel] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      startedAt.current = null;
      setElapsed(0);
      return;
    }
    startedAt.current ??= Date.now();
    const timer = window.setInterval(() => {
      if (startedAt.current) {
        setElapsed(Math.floor((Date.now() - startedAt.current) / 1000));
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [active]);

  if (!open) return null;

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
            className="relative w-full cursor-pointer overflow-hidden"
            style={{
              // The summit needs headroom: too flat a frame and a loud syllable
              // throws the spire straight off the top edge.
              height: 'clamp(340px, 50vh, 440px)',
              // Deliberately dark in BOTH themes, like a video player: the
              // luminous relief and its survey grid are additive light and
              // would vanish on a pale surface. Not #000 but the palette's
              // deep blue, so the stage belongs to the product rather than
              // punching a raw black hole through a light interface.
              background: 'var(--color-stage, #05070d)',
              border: 'none',
              borderRadius: 8,
              padding: 0,
            }}
            title={active ? t('chat.talk.interruptHint') : t('chat.talk.startHint')}
          >
            {/* Survey grid: a faint horizon behind the relief, so the massif
                reads as standing on something. */}
            <div
              aria-hidden="true"
              className="absolute inset-0 pointer-events-none"
              style={{
                backgroundImage:
                  'linear-gradient(to right, rgba(255,255,255,0.05) 1px, transparent 1px),' +
                  'linear-gradient(to bottom, rgba(255,255,255,0.05) 1px, transparent 1px)',
                backgroundSize: '48px 48px',
                maskImage: 'radial-gradient(ellipse at 50% 60%, #000 30%, transparent 78%)',
                WebkitMaskImage:
                  'radial-gradient(ellipse at 50% 60%, #000 30%, transparent 78%)',
              }}
            />

            {/* No fallback: an empty box for a few hundred milliseconds reads
                as loading, a placeholder shape reads as a glitch. */}
            <Suspense fallback={null}>
              <VoiceTerrain
                state={entityState(state)}
                // Dimmer when there is nothing to say: present, not performing.
                intensity={active ? 1 : 0.9}
                audioSource={audioSource}
                micSource={micSource}
                onLevel={setLevel}
                style={{ position: 'absolute', inset: 0 }}
              />
            </Suspense>

            <div
              className="absolute inset-x-0 bottom-0 flex items-center justify-between px-3 py-2 pointer-events-none"
              style={{
                fontFamily: 'var(--font-hud)',
                fontSize: 10,
                letterSpacing: '0.14em',
                color: 'var(--color-text-tertiary)',
              }}
            >
              {/* The state already reads in the header, so it is not repeated
                  here — these two are what the header cannot show. */}
              <span>
                {t('chat.talk.hudLevel')} {Math.round(level * 100).toString().padStart(2, '0')}
              </span>
              <span>
                {String(Math.floor(elapsed / 60)).padStart(2, '0')}:
                {String(elapsed % 60).padStart(2, '0')}
              </span>
            </div>
          </button>

          {caption ? (
            <p
              className="mt-3 text-lg font-medium text-center max-w-md talk-caption"
              style={{
                // Dimmed once the user has stopped: still legible, but plainly
                // no longer the live line.
                color: state === 'listening' ? 'var(--color-text)' : 'var(--color-text-secondary)',
              }}
              aria-live="polite"
            >
              {caption}
            </p>
          ) : (
            <>
              <p className="mt-3 text-lg font-medium" style={{ color: 'var(--color-text)' }}>
                {t('chat.talk.justSpeak')}
              </p>
              <p className="mt-1 text-sm text-center max-w-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {t('chat.talk.shortcuts')}
              </p>
            </>
          )}

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
                disabled={!serviceReady || checkingService}
                className="text-xs px-3 py-1.5 rounded-md disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                {checkingService ? t('talk.checkingService') : t('chat.talk.start')}
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
                    : error === 'local-components-missing'
                      ? t('talk.localComponentsMissing')
                    : error === 'voice-auth-unavailable'
                      ? t('talk.authUnavailable')
                      : error === 'voice-service-unavailable'
                        ? t('talk.serviceUnavailable')
                        : error === 'voice-connection-failed'
                          ? t('talk.connectionFailed')
                          : error === 'microphone-denied'
                            ? t('talk.microphoneDenied')
                            : error === 'voice-session-failed'
                              ? t('talk.sessionFailed')
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
