import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';

export type ConfirmTone = 'danger' | 'warning' | 'default';

export interface ConfirmOptions {
  title: string;
  description?: string;
  /** Primary action label — e.g. « Supprimer », « Retirer ». */
  confirmLabel: string;
  /** Secondary action that aborts — default « Garder ». */
  keepLabel?: string;
  tone?: ConfirmTone;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

const TONE_STYLES: Record<ConfirmTone, { background: string; color: string }> = {
  danger: {
    background: 'var(--color-error, #ef4444)',
    color: '#fff',
  },
  warning: {
    background: 'var(--color-accent)',
    color: '#fff',
  },
  default: {
    background: 'var(--color-accent)',
    color: '#fff',
  },
};

function ConfirmModal({
  options,
  onResolve,
}: {
  options: ConfirmOptions;
  onResolve: (value: boolean) => void;
}) {
  const tone = options.tone ?? 'danger';
  const keepLabel = options.keepLabel ?? 'Garder';
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    confirmRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onResolve(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onResolve]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby={options.description ? 'confirm-dialog-desc' : undefined}
      onClick={() => onResolve(false)}
      className="fixed inset-0 z-[100] flex items-center justify-center p-5 backdrop-blur-md"
      style={{ background: 'color-mix(in srgb, #000 55%, transparent)' }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-sm rounded-2xl p-5"
        style={{
          background: 'color-mix(in srgb, var(--color-surface) 92%, transparent)',
          border: '1px solid var(--color-border)',
          boxShadow: '0 24px 60px rgba(0,0,0,0.45)',
        }}
      >
        <h2
          id="confirm-dialog-title"
          className="text-base font-semibold"
          style={{ color: 'var(--color-text)' }}
        >
          {options.title}
        </h2>
        {options.description ? (
          <p
            id="confirm-dialog-desc"
            className="text-sm mt-2 leading-6 whitespace-pre-line"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {options.description}
          </p>
        ) : null}
        <div className="grid gap-2 mt-5">
          <button
            ref={confirmRef}
            type="button"
            onClick={() => onResolve(true)}
            className="w-full px-4 py-2.5 rounded-xl text-sm font-medium cursor-pointer"
            style={TONE_STYLES[tone]}
          >
            {options.confirmLabel}
          </button>
          <button
            type="button"
            onClick={() => onResolve(false)}
            className="w-full px-4 py-2.5 rounded-xl text-sm font-medium cursor-pointer"
            style={{
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
          >
            {keepLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<{
    options: ConfirmOptions;
    resolve: (value: boolean) => void;
  } | null>(null);

  const confirm = useCallback<ConfirmFn>((options) => {
    return new Promise<boolean>((resolve) => {
      setPending({ options, resolve });
    });
  }, []);

  const settle = useCallback((value: boolean) => {
    setPending((current) => {
      current?.resolve(value);
      return null;
    });
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending ? (
        <ConfirmModal options={pending.options} onResolve={settle} />
      ) : null}
    </ConfirmContext.Provider>
  );
}

/** Ask for confirmation with the shared blurred modal. Returns true if the user confirms. */
export function useConfirm(): ConfirmFn {
  const confirm = useContext(ConfirmContext);
  if (!confirm) {
    throw new Error('useConfirm must be used within ConfirmProvider');
  }
  return confirm;
}
