import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Cloud, Cpu, Loader2, SlidersHorizontal } from 'lucide-react';
import { useAppStore } from '../../lib/store';
import { fetchServerConfig, preloadModel, setServerConfigKey } from '../../lib/api';
import { isCloudModel } from '../../lib/cloud-models';
import { useTranslation } from '../../i18n/useTranslation';

/* The composer's bottom toolbar: tool-permission mode on the left, the
 * active model and a context-window ring on the right. Everything here
 * reflects a REAL wire: the mode chip reads/writes agent.tool_approval
 * (answered by the approval bell), the model chip drives the same
 * setSelectedModel/preload path as the ⌘K palette, and the ring divides
 * actual token usage by the window the server reports. */

// ---------------------------------------------------------------------------
// Shared upward-opening portal menu
// ---------------------------------------------------------------------------

interface Anchor {
  rect: DOMRect;
  el: HTMLElement;
}

interface MenuProps {
  anchor: Anchor;
  width?: number;
  role?: string;
  onClose: () => void;
  children: React.ReactNode;
}

function ChipMenu({ anchor, width = 280, role = 'menu', onClose, children }: MenuProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  // Latest-ref: the parent re-renders on every keystroke, and a raw
  // [onClose] dep would tear the document listeners down each time.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as Node;
      // The anchor button is NOT outside: closing here would race the
      // button's own onClick, which would then see a closed menu and
      // reopen it — an unclosable, flickering menu.
      if (anchor.el.contains(target)) return;
      // Null ref must close too — see the zombie-menu lesson in
      // ConversationList: `ref.current && !contains` kept state alive.
      if (!ref.current || !ref.current.contains(target)) onCloseRef.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current();
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [anchor]);

  // The composer sits at the bottom of the screen: menus open UPWARD,
  // anchored to the chip, and never off the horizontal edges.
  const left = Math.min(Math.max(8, anchor.rect.left), window.innerWidth - width - 8);
  const bottom = window.innerHeight - anchor.rect.top + 6;

  return createPortal(
    <div
      ref={ref}
      role={role}
      className="fixed z-50 py-1.5 px-1.5 rounded-xl overflow-y-auto"
      style={{
        left,
        bottom,
        width,
        maxHeight: '50vh',
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
        boxShadow: '0 8px 30px rgba(0,0,0,0.35)',
      }}
    >
      {children}
    </div>,
    document.body,
  );
}

const chipClass =
  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-colors cursor-pointer disabled:cursor-default disabled:opacity-50';

const chipStyle = (active: boolean): React.CSSProperties => ({
  background: active ? 'var(--color-accent-subtle)' : 'transparent',
  border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-border)'}`,
  color: active ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
});

// ---------------------------------------------------------------------------
// Mode chip — Auto / Ask, backed by agent.tool_approval
// ---------------------------------------------------------------------------

export function ModeChip({ disabled }: { disabled: boolean }) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'auto' | 'ask' | null>(null);
  const [anchor, setAnchor] = useState<Anchor | null>(null);

  useEffect(() => {
    let alive = true;
    fetchServerConfig()
      .then((c) => {
        if (alive) setMode(c.agent?.tool_approval === 'ask' ? 'ask' : 'auto');
      })
      .catch(() => {
        // Fail closed, like the backend: when the mode is unreadable the
        // server treats it as "ask" — the chip must not claim "auto".
        if (alive) setMode('ask');
      });
    return () => {
      alive = false;
    };
  }, []);

  const [writeFailed, setWriteFailed] = useState(false);

  const choose = (next: 'auto' | 'ask') => {
    const previous = mode;
    setMode(next);
    setAnchor(null);
    setServerConfigKey('agent.tool_approval', next).catch(() => {
      // A silent revert would let the user BELIEVE sensitive actions now
      // wait for approval while tools keep running in auto.
      setMode(previous);
      setWriteFailed(true);
      window.setTimeout(() => setWriteFailed(false), 5000);
    });
  };

  const label = mode === 'ask' ? t('composer.modeAsk') : t('composer.modeAuto');

  const item = (value: 'auto' | 'ask', title: string, desc: string) => (
    <button
      role="menuitem"
      className="flex w-full items-start gap-2.5 px-3 py-2 rounded-lg text-left transition-colors cursor-pointer"
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      onClick={() => choose(value)}
    >
      <div className="flex-1 min-w-0">
        <div className="text-[13px]" style={{ color: 'var(--color-text)' }}>
          {title}
        </div>
        <div className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
          {desc}
        </div>
      </div>
      {mode === value && (
        <Check size={14} className="mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
      )}
    </button>
  );

  return (
    <>
      <button
        type="button"
        disabled={disabled || mode === null}
        className={chipClass}
        style={
          writeFailed
            ? { ...chipStyle(false), borderColor: 'var(--color-error)', color: 'var(--color-error)' }
            : chipStyle(mode === 'ask')
        }
        onClick={(e) =>
          setAnchor(
            anchor
              ? null
              : { rect: e.currentTarget.getBoundingClientRect(), el: e.currentTarget },
          )
        }
        title={writeFailed ? t('composer.modeWriteFailed') : t('composer.modeTitle')}
        aria-haspopup="menu"
        aria-expanded={anchor !== null}
      >
        <SlidersHorizontal size={12} />
        {writeFailed ? t('composer.modeWriteFailed') : mode === null ? '…' : label}
        <ChevronDown size={12} />
      </button>
      {anchor && (
        <ChipMenu anchor={anchor} onClose={() => setAnchor(null)}>
          <div
            className="px-3 pt-1.5 pb-1 text-[10px] font-medium uppercase tracking-wider"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            {t('composer.modeTitle')}
          </div>
          {item('auto', t('composer.modeAuto'), t('composer.modeAutoDesc'))}
          {item('ask', t('composer.modeAsk'), t('composer.modeAskDesc'))}
        </ChipMenu>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Model chip — active model, quick switch, gateway to the full palette
// ---------------------------------------------------------------------------

export function ModelChip({ disabled }: { disabled: boolean }) {
  const { t } = useTranslation();
  const models = useAppStore((s) => s.models);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const modelLoading = useAppStore((s) => s.modelLoading);
  const setModelLoading = useAppStore((s) => s.setModelLoading);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const [anchor, setAnchor] = useState<Anchor | null>(null);

  const isCloud = isCloudModel(selectedModel);
  const Icon = modelLoading ? Loader2 : isCloud ? Cloud : Cpu;

  const pick = (id: string) => {
    setAnchor(null);
    if (id === selectedModel) return;
    setSelectedModel(id);
    // Same path as the ⌘K palette: warm the model so the first message
    // does not pay the load.
    setModelLoading(true);
    preloadModel(id)
      .catch(() => undefined)
      .finally(() => setModelLoading(false));
  };

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        className={chipClass}
        style={{ ...chipStyle(false), maxWidth: 220 }}
        onClick={(e) =>
          setAnchor(
            anchor
              ? null
              : { rect: e.currentTarget.getBoundingClientRect(), el: e.currentTarget },
          )
        }
        title={t('composer.model')}
        aria-haspopup="menu"
        aria-expanded={anchor !== null}
      >
        <Icon size={12} className={modelLoading ? 'animate-spin' : undefined} />
        <span className="truncate" style={{ color: 'var(--color-text-secondary)' }}>
          {selectedModel || t('sidebar.selectModel')}
        </span>
        <ChevronDown size={12} />
      </button>
      {anchor && (
        <ChipMenu anchor={anchor} width={260} onClose={() => setAnchor(null)}>
          {models.map((m) => (
            <button
              key={m.id}
              role="menuitem"
              className="flex w-full items-center gap-2.5 px-3 py-1.5 rounded-lg text-left text-[13px] transition-colors cursor-pointer"
              style={{ color: 'var(--color-text)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              onClick={() => pick(m.id)}
            >
              <span className="flex-1 truncate">{m.id}</span>
              {m.id === selectedModel && (
                <Check size={14} className="shrink-0" style={{ color: 'var(--color-accent)' }} />
              )}
            </button>
          ))}
          <div className="my-1 mx-2" style={{ borderTop: '1px solid var(--color-border)' }} />
          <button
            role="menuitem"
            className="flex w-full items-center gap-2.5 px-3 py-1.5 rounded-lg text-left text-[13px] transition-colors cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            onClick={() => {
              setAnchor(null);
              setCommandPaletteOpen(true);
            }}
          >
            <span className="flex-1">{t('composer.manageModels')}</span>
            <kbd
              className="text-[10px] px-1.5 py-0.5 rounded font-mono"
              style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
            >
              ⌘K
            </kbd>
          </button>
        </ChipMenu>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Context ring — how full the model's window is
// ---------------------------------------------------------------------------

export function ContextRing({ draftLength }: { draftLength: number }) {
  const { t } = useTranslation();
  const messages = useAppStore((s) => s.messages);
  const models = useAppStore((s) => s.models);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const savings = useAppStore((s) => s.savings);
  const [anchor, setAnchor] = useState<Anchor | null>(null);

  const { used, windowSize, pct } = useMemo(() => {
    let lastUsage: { prompt_tokens?: number; completion_tokens?: number } | undefined;
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role === 'assistant' && m.usage) {
        lastUsage = m.usage;
        break;
      }
    }
    // prompt_tokens is the FULL prompt of the last turn (system + history +
    // user); the reply joins the context next turn; the draft is ~4 chars
    // per token. Approximate by design — presented as such.
    const usedTokens =
      (lastUsage?.prompt_tokens ?? 0) +
      (lastUsage?.completion_tokens ?? 0) +
      Math.ceil(draftLength / 4);

    const spec = models.find((m) => m.id === selectedModel);
    const isCloud = isCloudModel(selectedModel);
    const numCtx = serverInfo?.num_ctx;
    let size: number | null = null;
    if (isCloud) {
      // Cloud windows are not surfaced by /v1/models; better honest
      // silence than an invented denominator.
      size = spec?.context_length ?? null;
    } else if (spec?.context_length) {
      size = numCtx ? Math.min(spec.context_length, numCtx) : spec.context_length;
    } else {
      size = numCtx ?? null;
    }
    return {
      used: usedTokens,
      windowSize: size,
      pct: size
        ? Math.min(
            100,
            Math.max(usedTokens > 0 ? 1 : 0, Math.round((usedTokens / size) * 100)),
          )
        : 0,
    };
  }, [messages, models, selectedModel, serverInfo, draftLength]);

  if (!windowSize) return null;

  const r = 7;
  const circumference = 2 * Math.PI * r;
  const color =
    pct > 90
      ? 'var(--color-error)'
      : pct > 70
        ? 'var(--color-warning, #e8a34c)'
        : 'var(--color-accent)';

  return (
    <>
      <button
        type="button"
        className="inline-flex items-center gap-1.5 px-1.5 py-1 rounded-full transition-colors cursor-pointer"
        style={{ color: 'var(--color-text-tertiary)' }}
        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
        onClick={(e) =>
          setAnchor(
            anchor
              ? null
              : { rect: e.currentTarget.getBoundingClientRect(), el: e.currentTarget },
          )
        }
        title={t('composer.contextWindow')}
        aria-haspopup="dialog"
        aria-expanded={anchor !== null}
      >
        <svg width={18} height={18} viewBox="0 0 18 18" aria-hidden="true">
          <circle
            cx={9}
            cy={9}
            r={r}
            fill="none"
            stroke="var(--color-border)"
            strokeWidth={2.5}
          />
          <circle
            cx={9}
            cy={9}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeDasharray={`${(pct / 100) * circumference} ${circumference}`}
            transform="rotate(-90 9 9)"
          />
        </svg>
        <span className="text-[11px] tabular-nums">{pct}%</span>
      </button>
      {anchor && (
        <ChipMenu anchor={anchor} width={280} role="dialog" onClose={() => setAnchor(null)}>
          <div className="px-3 py-2">
            <div
              className="flex items-center justify-between text-[13px]"
              style={{ color: 'var(--color-text)' }}
            >
              <span>{t('composer.contextWindow')}</span>
              <span className="tabular-nums" style={{ color: 'var(--color-text-secondary)' }}>
                {t('composer.contextTokens', {
                  used: used.toLocaleString(),
                  max: windowSize.toLocaleString(),
                  pct,
                })}
              </span>
            </div>
            <div
              className="mt-2 h-1.5 rounded-full overflow-hidden"
              style={{ background: 'var(--color-bg-tertiary)' }}
            >
              <div
                className="h-full rounded-full"
                style={{ width: `${pct}%`, background: color }}
              />
            </div>
            <div className="mt-1.5 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
              {t('composer.contextApprox')}
            </div>
            <div className="my-2" style={{ borderTop: '1px solid var(--color-border)' }} />
            <div
              className="text-[10px] font-medium uppercase tracking-wider mb-1"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              {t('composer.session')}
            </div>
            <div
              className="flex items-center justify-between text-[12px]"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <span>{t('composer.sessionRequests')}</span>
              <span className="tabular-nums">{(savings?.total_calls ?? 0).toLocaleString()}</span>
            </div>
            <div
              className="flex items-center justify-between text-[12px] mt-0.5"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <span>{t('composer.sessionTokens')}</span>
              <span className="tabular-nums">
                {(savings?.total_completion_tokens ?? 0).toLocaleString()}
              </span>
            </div>
          </div>
        </ChipMenu>
      )}
    </>
  );
}
