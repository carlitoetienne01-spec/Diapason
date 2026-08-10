import { AudioLines, X } from 'lucide-react';
import type { VoiceLiveProvider, VoiceLiveState, TranscriptLine, ToolEventLine } from '../../hooks/useVoiceLive';

interface TalkOrbProps {
  open: boolean;
  state: VoiceLiveState;
  statusLabel: string;
  error: string | null;
  provider: VoiceLiveProvider;
  transcripts: TranscriptLine[];
  toolEvents?: ToolEventLine[];
  screenSharing?: boolean;
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
  onProviderChange,
  onStart,
  onStop,
  onInterrupt,
  onClose,
}: TalkOrbProps) {
  if (!open) return null;

  const active = state === 'listening' || state === 'speaking' || state === 'connecting';
  const pulse =
    state === 'speaking'
      ? 'scale-110 opacity-100'
      : state === 'listening'
        ? 'scale-100 opacity-90'
        : 'scale-95 opacity-70';

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
                title="Screen share active — say « arrête le partage » to stop"
              >
                Sharing screen
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-md cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)' }}
            title="Close (Esc)"
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
            className={`relative h-44 w-44 rounded-full transition-transform duration-300 cursor-pointer ${pulse}`}
            style={{
              background:
                'radial-gradient(circle at 35% 30%, #e8eaf2 0%, #8b92a8 45%, #3a3f52 100%)',
              boxShadow: state === 'speaking' ? '0 0 48px rgba(180,190,220,0.35)' : 'none',
            }}
            title={active ? 'Click or Space to interrupt' : 'Start talking'}
          >
            <span className="absolute inset-0 flex items-center justify-center">
              <AudioLines size={36} style={{ color: '#1a1c24', opacity: 0.55 }} />
            </span>
          </button>

          <p className="mt-5 text-lg font-medium" style={{ color: 'var(--color-text)' }}>
            Just speak.
          </p>
          <p className="mt-1 text-sm text-center max-w-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Realtime voice · ⌥Space toggle · Space interrupt · Esc close
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
                End
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void onStart()}
                className="text-xs px-3 py-1.5 rounded-md cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                Start
              </button>
            )}
          </div>

          {error && (
            <p className="mt-3 text-xs text-center" style={{ color: 'var(--color-error)' }}>
              {error}
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
            {toolEvents.slice(-4).map((t, i) => (
              <div key={`tool-${i}`} style={{ color: t.ok ? 'var(--color-success)' : 'var(--color-error)' }}>
                Tool · {t.name}{t.detail ? ` — ${t.detail}` : ''}
              </div>
            ))}
            {transcripts.slice(-8).map((t, i) => (
              <div key={`${t.role}-${i}`}>
                <span className="font-medium" style={{ color: 'var(--color-text)' }}>
                  {t.role === 'user' ? 'You' : 'Jarvis'}
                </span>
                {': '}
                {t.text}
              </div>
            ))}
          </div>
        )}

        <div
          className="px-4 py-2 text-[11px] text-center"
          style={{ color: 'var(--color-text-tertiary)', borderTop: '1px solid var(--color-border)' }}
        >
          Temps réel · {provider === 'gemini' ? 'Gemini Live' : 'gpt-realtime'} · tools · ⌥Space
        </div>
      </div>
    </div>
  );
}
