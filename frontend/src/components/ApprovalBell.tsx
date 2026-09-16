import { useCallback, useEffect, useRef, useState } from 'react';
import { Bell, CheckCircle, ChevronDown, ChevronUp, Clock, XCircle } from 'lucide-react';
import { approveAction, denyAction, fetchPendingApprovals } from '../lib/api';
import type { PendingApproval } from '../lib/api';
import { useTranslation } from '../i18n/useTranslation';
import type { MessageKey } from '../i18n/translate';

// The tier holds a catalogue key, not a word: this constant sits at module
// scope, where a hook cannot run, so the label is resolved at render time.
const TIER_STYLES: Record<string, { labelKey: MessageKey; color: string; bg: string }> = {
  trivial: { labelKey: 'agents.tier.trivial', color: 'var(--color-text-secondary)', bg: 'color-mix(in srgb, var(--color-text-secondary) 10%, transparent)' },
  low:     { labelKey: 'agents.tier.low',     color: '#3b82f6',                    bg: 'rgba(59,130,246,0.12)' },
  medium:  { labelKey: 'agents.tier.medium',  color: 'var(--color-warning)',       bg: 'color-mix(in srgb, var(--color-warning) 12%, transparent)' },
  high:    { labelKey: 'agents.tier.high',    color: 'var(--color-error)',         bg: 'color-mix(in srgb, var(--color-error) 12%, transparent)' },
};

type Translate = ReturnType<typeof useTranslation>['t'];

/** Le menu portait `width: 340px` et `maxHeight: 500px` EN DUR sous un
    `top-full` sans mesure : sous ~560 px de haut le bas était coupé (les
    boutons Approuver/Refuser inatteignables — §82), sous ~360 px de large il
    sortait à gauche. Audit du mini-panneau, 16 sept. 2026. La hauteur se
    mesure à l'ouverture ; on retourne vers le haut quand la place manque
    dessous et qu'il y en a plus dessus. */
export type PlacementMenu = { haut: boolean; hauteurMax: number };

const MENU_HAUTEUR_MAX = 500;
/* 160 px = l'en-tête (44) + une demande repliée (~110) : sous ce plancher un
   menu déroulé ne montre même pas la première décision. */
const MENU_HAUTEUR_MIN = 160;
const MENU_MARGE = 12;

export function placerMenu(
  ancre: { top: number; bottom: number },
  hauteurFenetre: number,
): PlacementMenu {
  const dessous = hauteurFenetre - ancre.bottom - MENU_MARGE;
  const dessus = ancre.top - MENU_MARGE;
  const haut = dessous < MENU_HAUTEUR_MIN && dessus > dessous;
  const place = haut ? dessus : dessous;
  return { haut, hauteurMax: Math.max(MENU_HAUTEUR_MIN, Math.min(MENU_HAUTEUR_MAX, place)) };
}

function timeAgo(iso: string, t: Translate): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return t('common.time.justNow');
  if (m < 60) return t('common.time.minutesAgo', { count: m });
  const h = Math.floor(m / 60);
  if (h < 24) return t('common.time.hoursAgo', { count: h });
  return t('common.time.daysAgo', { count: Math.floor(h / 24) });
}

export function ApprovalBell() {
  const { t } = useTranslation();
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [processing, setProcessing] = useState<Record<string, boolean>>({});
  const [placement, setPlacement] = useState<PlacementMenu>({ haut: false, hauteurMax: MENU_HAUTEUR_MAX });
  const containerRef = useRef<HTMLDivElement>(null);

  const basculer = () => {
    setOpen(o => {
      if (!o) {
        const rect = containerRef.current?.getBoundingClientRect();
        if (rect) setPlacement(placerMenu(rect, window.innerHeight));
      }
      return !o;
    });
  };

  const load = useCallback(async () => {
    try {
      setApprovals(await fetchPendingApprovals());
    } catch {
      // backend may not be running yet
    }
  }, []);

  useEffect(() => {
    load();
    // InputArea emits this as soon as a tool call starts, so the approval is
    // normally visible immediately. Poll fast only while a decision is
    // pending; use a light safety poll otherwise.
    window.addEventListener('diapason-approval-possible', load);
    const id = setInterval(load, approvals.length > 0 ? 1000 : 5000);
    return () => {
      clearInterval(id);
      window.removeEventListener('diapason-approval-possible', load);
    };
  }, [load, approvals.length]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    // Le panneau se redimensionne en continu : une hauteur mesurée à
    // l'ouverture devient fausse — on referme plutôt que de déborder.
    const onResize = () => setOpen(false);
    document.addEventListener('mousedown', handler);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    return () => {
      document.removeEventListener('mousedown', handler);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
    };
  }, [open]);

  const handleApprove = async (id: string) => {
    setProcessing(p => ({ ...p, [id]: true }));
    try {
      await approveAction(id);
      setApprovals(prev => prev.filter(a => a.id !== id));
    } finally {
      setProcessing(p => ({ ...p, [id]: false }));
    }
  };

  const handleDeny = async (id: string) => {
    setProcessing(p => ({ ...p, [id]: true }));
    try {
      await denyAction(id);
      setApprovals(prev => prev.filter(a => a.id !== id));
    } finally {
      setProcessing(p => ({ ...p, [id]: false }));
    }
  };

  const count = approvals.length;

  return (
    <div ref={containerRef} className="relative">
      {/* Bell trigger */}
      <button
        onClick={basculer}
        className="relative p-2 rounded-lg transition-colors cursor-pointer"
        title={t('agents.approvals.bellTooltip')}
        aria-label={t('agents.approvals.bellTooltip')}
        aria-expanded={open}
        aria-haspopup="dialog"
        style={{
          color: count > 0 ? 'var(--color-text)' : 'var(--color-text-secondary)',
          background: open
            ? 'var(--color-bg-tertiary)'
            : count > 0
            ? 'color-mix(in srgb, var(--color-error) 8%, transparent)'
            : 'transparent',
        }}
      >
        <Bell size={17} />
        {count > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 flex items-center justify-center rounded-full text-[10px] font-bold px-1 leading-none"
            style={{ background: 'var(--color-error)', color: '#fff' }}
          >
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div
          role="dialog"
          aria-label={t('agents.approvals.title')}
          className={`absolute right-0 rounded-xl shadow-2xl overflow-hidden flex flex-col ${
            placement.haut ? 'bottom-full mb-1' : 'top-full mt-1'
          }`}
          style={{
            // L'ancre vit à `right-3` : 340 px ne tiennent plus sous 364 px de
            // large ; le plafond cède, la marge de 8 px reste.
            width: 'min(340px, calc(100vw - 1.25rem))',
            maxHeight: `${placement.hauteurMax}px`,
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
          }}
        >
          {/* Header */}
          <div
            className="flex items-center justify-between px-4 py-3 shrink-0"
            style={{ borderBottom: '1px solid var(--color-border)' }}
          >
            <div className="flex items-center gap-2">
              <Bell size={13} style={{ color: 'var(--color-accent)' }} />
              <span className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                {t('agents.approvals.title')}
              </span>
            </div>
            {count > 0 && (
              <span
                className="text-[11px] font-medium px-2 py-0.5 rounded-full"
                style={{
                  background: 'color-mix(in srgb, var(--color-error) 12%, transparent)',
                  color: 'var(--color-error)',
                }}
              >
                {t('agents.approvals.pending', { count })}
              </span>
            )}
          </div>

          {/* Body */}
          <div className="overflow-y-auto flex-1">
            {count === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 gap-2">
                <CheckCircle size={26} style={{ color: 'var(--color-text-secondary)', opacity: 0.35 }} />
                <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  {t('agents.approvals.empty')}
                </span>
              </div>
            ) : (
              approvals.map((action, idx) => {
                const tier = TIER_STYLES[action.tier] ?? TIER_STYLES.medium;
                const isExpanded = !!expanded[action.id];
                const isLoading = !!processing[action.id];
                const hasPayload = Object.keys(action.payload ?? {}).length > 0;
                const isFileTransfer = action.action_type === 'file_transfer';

                return (
                  <div
                    key={action.id}
                    className="px-4 py-3"
                    style={{
                      borderBottom: idx < count - 1 ? '1px solid var(--color-border)' : 'none',
                    }}
                  >
                    {/* Row 1: action type + tier + time */}
                    <div className="flex items-center justify-between mb-1.5">
                      <span
                        className="text-[11px] font-mono font-semibold"
                        style={{ color: 'var(--color-accent)' }}
                      >
                        {isFileTransfer
                          ? t('agents.approvals.fileTransfer')
                          : action.action_type}
                      </span>
                      <div className="flex items-center gap-2">
                        <span
                          className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded"
                          style={{ background: tier.bg, color: tier.color }}
                        >
                          {t(tier.labelKey)}
                        </span>
                        <span
                          className="text-[10px] flex items-center gap-0.5"
                          style={{ color: 'var(--color-text-secondary)' }}
                        >
                          <Clock size={9} />
                          {timeAgo(action.created_at, t)}
                        </span>
                      </div>
                    </div>

                    {/* Description */}
                    <p
                      className="text-[13px] mb-2.5 leading-snug"
                      style={{ color: 'var(--color-text)' }}
                    >
                      {action.description}
                    </p>

                    {/* Expandable payload */}
                    {hasPayload && (
                      <button
                        className="flex items-center gap-1 text-[11px] mb-2 cursor-pointer"
                        style={{ color: 'var(--color-text-secondary)' }}
                        onClick={() =>
                          setExpanded(e => ({ ...e, [action.id]: !e[action.id] }))
                        }
                      >
                        {isExpanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                        {isExpanded ? t('common.hideDetails') : t('common.viewDetails')}
                      </button>
                    )}

                    {isExpanded && (
                      <pre
                        className="text-[10px] rounded-lg p-2.5 mb-2.5 overflow-x-auto"
                        style={{
                          background: 'var(--color-bg-tertiary)',
                          color: 'var(--color-text-secondary)',
                          fontFamily: 'monospace',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                          lineHeight: '1.5',
                        }}
                      >
                        {JSON.stringify(action.payload, null, 2)}
                      </pre>
                    )}

                    {/* Approve / Deny */}
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleApprove(action.id)}
                        disabled={isLoading}
                        className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-semibold transition-opacity cursor-pointer disabled:opacity-40"
                        style={{
                          background: 'color-mix(in srgb, var(--color-success) 12%, transparent)',
                          color: 'var(--color-success)',
                          border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
                        }}
                      >
                        <CheckCircle size={12} />
                        {t(isFileTransfer ? 'agents.approvals.acceptFile' : 'common.approve')}
                      </button>
                      <button
                        onClick={() => handleDeny(action.id)}
                        disabled={isLoading}
                        className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-semibold transition-opacity cursor-pointer disabled:opacity-40"
                        style={{
                          background: 'color-mix(in srgb, var(--color-error) 12%, transparent)',
                          color: 'var(--color-error)',
                          border: '1px solid color-mix(in srgb, var(--color-error) 22%, transparent)',
                        }}
                      >
                        <XCircle size={12} />
                        {t(isFileTransfer ? 'agents.approvals.refuseFile' : 'common.deny')}
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
