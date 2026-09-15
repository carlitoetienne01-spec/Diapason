import { useEffect, useRef, useState } from 'react';

const HABIT_EMOJIS = [
  '✨', '🔥', '💪', '🏃', '🧘', '🙏', '❤️', '🧠',
  '📚', '✍️', '💻', '🎯', '✅', '⭐', '🌟', '💡',
  '🌅', '🌙', '💧', '🥗', '🍎', '🥤', '😴', '🛏️',
  '🧹', '🧼', '🪴', '🌳', '🚴', '🏋️', '⚽', '🎵',
  '🎸', '🎹', '🎨', '📷', '📱', '💰', '📈', '🗓️',
  '⏰', '☕', '🍵', '🦷', '🧴', '🚶', '🗣️', '📝',
] as const;

type Props = {
  value: string;
  onChange: (emoji: string) => void;
  'aria-label'?: string;
};

export function EmojiPicker({ value, onChange, 'aria-label': ariaLabel = 'Choisir un emoji' }: Props) {
  const [open, setOpen] = useState(false);
  /** Mesuré à l'ouverture : dans une petite fenêtre (le mini-panneau de la
      réglette), un panneau toujours ancré bas-gauche partait sous le bord
      visible ou sortait à droite — « s'ouvre en bas, caché » (15 sept. 2026).
      On retourne vers le haut et on s'ancre à droite quand la place manque. */
  const [placement, setPlacement] = useState({ haut: false, droite: false });
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    // Le panneau se redimensionne en continu : une ancre mesurée à
    // l'ouverture devient fausse — on referme plutôt que de flotter à côté.
    const onResize = () => setOpen(false);
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
    };
  }, [open]);

  const basculer = () => {
    setOpen((current) => {
      if (!current) {
        const rect = rootRef.current?.getBoundingClientRect();
        if (rect) {
          setPlacement({
            haut: rect.bottom + 240 > window.innerHeight && rect.top > 240,
            droite: rect.left + 256 > window.innerWidth - 8,
          });
        }
      }
      return !current;
    });
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={basculer}
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="size-full min-h-[46px] rounded-xl text-lg cursor-pointer flex items-center justify-center"
        style={{
          border: '1px solid var(--color-border)',
          color: 'var(--color-text)',
          background: open
            ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)'
            : 'transparent',
        }}
      >
        <span aria-hidden>{value || '✨'}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Liste d’emojis"
          className={`absolute z-50 w-[248px] max-w-[calc(100vw-1rem)] max-h-[min(40vh,240px)] overflow-y-auto rounded-xl p-2 shadow-lg ${
            placement.haut ? 'bottom-[calc(100%+6px)]' : 'top-[calc(100%+6px)]'
          } ${placement.droite ? 'right-0' : 'left-0'}`}
          style={{
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            backdropFilter: 'blur(12px)',
          }}
        >
          <div className="grid grid-cols-8 gap-0.5">
            {HABIT_EMOJIS.map((emoji) => {
              const selected = value === emoji;
              return (
                <button
                  key={emoji}
                  type="button"
                  onClick={() => {
                    onChange(emoji);
                    setOpen(false);
                  }}
                  aria-label={`Emoji ${emoji}`}
                  aria-pressed={selected}
                  className="size-7 rounded-md text-base cursor-pointer flex items-center justify-center hover:opacity-100"
                  style={{
                    background: selected
                      ? 'color-mix(in srgb, var(--color-accent) 22%, transparent)'
                      : 'transparent',
                    outline: selected ? '1px solid var(--color-accent)' : undefined,
                  }}
                >
                  {emoji}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
