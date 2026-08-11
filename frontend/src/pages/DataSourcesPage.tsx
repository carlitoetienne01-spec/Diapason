import { useEffect, useState, useCallback, useRef } from 'react';
import { motion } from 'motion/react';
import { useAppStore } from '../lib/store';
import {
  fetchManagedAgents,
  fetchAgentChannels,
  bindAgentChannel,
  unbindAgentChannel,
  createManagedAgent,
  sendblueRegisterWebhook,
  sendblueHealth,
  getMemoryStats,
  searchMemory,
  storeMemory,
  indexMemoryPath,
} from '../lib/api';
import type { ChannelBinding, ManagedAgent, MemoryStats, MemorySearchResult } from '../lib/api';
import { getBase, isTauri } from '../lib/api';
import {
  Database, MessageSquare, Loader2, Brain, Search, FolderOpen, FileText,
  Mail, Hash, MessageCircle, CalendarDays, Contact, StickyNote, BookText,
  Package, Upload, Link2, PhoneCall,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { SOURCE_CATALOG } from '../types/connectors';
import type { ConnectRequest } from '../types/connectors';
import { listConnectors, connectSource, disconnectSource, getSyncStatus, triggerSync, startServerOAuth } from '../lib/connectors-api';
import type { SyncStatus } from '../types/connectors';
import { useTranslation } from '../i18n/useTranslation';

/** The `t` returned by useTranslation, so module-level helpers can be handed
 *  one instead of illegally calling the hook outside a component. */
type Translate = ReturnType<typeof useTranslation>['t'];
type TranslationKey = Parameters<Translate>[0];

// ---------------------------------------------------------------------------
// Inline connect form (reused from AgentsPage pattern)
// ---------------------------------------------------------------------------

function InlineConnectForm({
  fields,
  loading,
  onSubmit,
}: {
  fields: Array<{ name: string; placeholder: string; type?: string }>;
  loading: boolean;
  onSubmit: (req: ConnectRequest) => void;
}) {
  const { t } = useTranslation();
  const [inputs, setInputs] = useState<Record<string, string>>({});

  const update = (name: string, value: string) =>
    setInputs((p) => ({ ...p, [name]: value }));

  const allFilled = fields.every((f) => inputs[f.name]?.trim());

  const submit = () => {
    const req: ConnectRequest = {};
    for (const f of fields) {
      if (f.name === 'email') req.email = inputs.email;
      else if (f.name === 'password') req.password = inputs.password;
      else if (f.name === 'token') req.token = inputs.token;
      else if (f.name === 'path') req.path = inputs.path;
    }
    if (req.email && req.password) {
      req.token = `${req.email}:${req.password}`;
      req.code = req.token;
    }
    if (req.token && !req.code) req.code = req.token;
    onSubmit(req);
  };

  return (
    <div>
      {fields.map((f) => (
        <input
          key={f.name}
          value={inputs[f.name] || ''}
          onChange={(e) => update(f.name, e.target.value)}
          placeholder={f.placeholder}
          type={f.type || 'text'}
          style={{
            width: '100%', padding: '7px 10px',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 4, color: 'var(--color-text)',
            fontSize: 12, marginBottom: 6,
            boxSizing: 'border-box',
          }}
        />
      ))}
      <button
        onClick={submit}
        disabled={loading || !allFilled}
        style={{
          width: '100%', padding: 8,
          background: loading || !allFilled ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
          color: 'var(--color-on-accent)', border: 'none',
          borderRadius: 6, fontSize: 12, cursor: 'pointer',
        }}
      >
        {t('common.connect')}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upload / Paste form
// ---------------------------------------------------------------------------

const ACCEPTED_EXTENSIONS = '.txt,.md,.pdf,.docx,.csv';

function UploadForm({ onDone }: { onDone?: () => void }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<'paste' | 'upload'>('paste');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState('');
  const [error, setError] = useState('');

  const handlePaste = async () => {
    if (!content.trim()) return;
    setBusy(true);
    setError('');
    setResult('');
    try {
      const res = await fetch(`${getBase()}/v1/connectors/upload/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), content }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || t('sources.upload.failedStatus', { status: res.status }));
      }
      const data = await res.json();
      setResult(t('sources.upload.added', { count: data.chunks_added }));
      setTitle('');
      setContent('');
      onDone?.();
    } catch (err: any) {
      setError(err.message || t('sources.upload.failed'));
    } finally {
      setBusy(false);
    }
  };

  const handleUpload = async () => {
    if (files.length === 0) return;
    setBusy(true);
    setError('');
    setResult('');
    try {
      const formData = new FormData();
      for (const f of files) formData.append('files', f);
      if (title.trim()) formData.append('title', title.trim());

      const res = await fetch(`${getBase()}/v1/connectors/upload/ingest/files`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || t('sources.upload.failedStatus', { status: res.status }));
      }
      const data = await res.json();
      setResult(
        t('sources.upload.addedFromFiles', {
          count: data.chunks_added,
          files: t('sources.upload.fileCount', { count: files.length }),
        }),
      );
      setFiles([]);
      setTitle('');
      onDone?.();
    } catch (err: any) {
      setError(err.message || t('sources.upload.failed'));
    } finally {
      setBusy(false);
    }
  };

  const tabStyle = (active: boolean): React.CSSProperties => ({
    flex: 1, padding: '6px 0', textAlign: 'center',
    fontSize: 12, fontWeight: 600, cursor: 'pointer',
    background: active ? 'var(--color-accent-purple)' : 'transparent',
    color: active ? 'white' : 'var(--color-text-secondary)',
    border: 'none', borderRadius: 4,
  });

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '7px 10px',
    background: 'var(--color-bg)',
    border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)',
    fontSize: 12, marginBottom: 6,
    boxSizing: 'border-box' as const,
  };

  return (
    <div>
      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 10,
        background: 'var(--color-bg)', borderRadius: 6, padding: 2 }}>
        <button style={tabStyle(tab === 'paste')} onClick={() => setTab('paste')}>
          {t('sources.upload.tabPaste')}
        </button>
        <button style={tabStyle(tab === 'upload')} onClick={() => setTab('upload')}>
          {t('sources.upload.tabUpload')}
        </button>
      </div>

      {/* Title input (shared) */}
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={t('sources.upload.titlePlaceholder')}
        style={inputStyle}
      />

      {tab === 'paste' && (
        <>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={t('sources.upload.contentPlaceholder')}
            rows={6}
            style={{
              ...inputStyle,
              resize: 'vertical',
              fontFamily: 'inherit',
              minHeight: 100,
            }}
          />
          <button
            onClick={handlePaste}
            disabled={busy || !content.trim()}
            style={{
              width: '100%', padding: 8,
              background: busy || !content.trim() ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)', border: 'none',
              borderRadius: 6, fontSize: 12, cursor: 'pointer',
            }}
          >
            {busy ? t('sources.upload.adding') : t('sources.upload.addToKb')}
          </button>
        </>
      )}

      {tab === 'upload' && (
        <>
          <input
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS}
            onChange={(e) => {
              const selected = Array.from(e.target.files || []);
              setFiles(selected);
            }}
            style={{ ...inputStyle, padding: 6 }}
          />
          {files.length > 0 && (
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 6 }}>
              {files.map((f) => f.name).join(', ')}
            </div>
          )}
          <button
            onClick={handleUpload}
            disabled={busy || files.length === 0}
            style={{
              width: '100%', padding: 8,
              background: busy || files.length === 0 ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)', border: 'none',
              borderRadius: 6, fontSize: 12, cursor: 'pointer',
            }}
          >
            {busy ? t('sources.upload.uploading') : t('sources.upload.uploadAndIndex')}
          </button>
        </>
      )}

      {result && (
        <div style={{ fontSize: 12, color: 'var(--color-success)', marginTop: 8 }}>
          {result}
        </div>
      )}
      {error && (
        <div style={{ fontSize: 12, color: 'var(--color-error)', marginTop: 8 }}>
          {error}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Icon map
// ---------------------------------------------------------------------------

const iconMap: Record<string, LucideIcon> = {
  gmail: Mail,
  gmail_imap: Mail,
  gmail_api: Mail,
  outlook: Mail,
  slack: Hash,
  imessage: MessageCircle,
  whatsapp: PhoneCall,
  gdrive: FolderOpen,
  dropbox: Package,
  notion: BookText,
  obsidian: FileText,
  apple_notes: StickyNote,
  granola: FileText,
  gcalendar: CalendarDays,
  gcontacts: Contact,
  apple_contacts: Contact,
  upload: Upload,
};

const IconFor = ({ id, size = 18 }: { id: string; size?: number }) => {
  const Ico = iconMap[id] ?? Link2;
  return <Ico size={size} />;
};

// The Gmail card unifies the OAuth (`gmail`) and IMAP (`gmail_imap`) backend
// connectors — both should resolve to the gmail_imap catalog entry so the
// connected card shows the same name, unit label, and troubleshooting tips
// regardless of which underlying flow the user picked.
function metaFor(connectorId: string) {
  const id = connectorId === 'gmail' ? 'gmail_imap' : connectorId;
  return SOURCE_CATALOG.find((s) => s.connector_id === id);
}

// Advanced OAuth disclosure for the unified Gmail card. Hidden by default;
// expands to a Client ID + Client Secret form that POSTs to the OAuth
// `gmail` backend connector. Lives here rather than in SOURCE_CATALOG
// because the Gmail card is the only one with a dual-flow shape.
function GmailOAuthAdvanced({
  loading,
  onConnect,
}: {
  loading: boolean;
  onConnect: (req: ConnectRequest) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 12 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          background: 'transparent',
          border: 'none',
          padding: 0,
          fontSize: 11,
          color: 'var(--color-text-tertiary)',
          cursor: 'pointer',
          textDecoration: 'underline',
        }}
      >
        {open ? t('sources.gmail.hideAdvanced') : t('sources.gmail.showAdvanced')}
      </button>
      {open && (
        <div
          style={{
            marginTop: 8,
            padding: 10,
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
          }}
        >
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>
            {t('sources.gmail.oauthIntro')}{' '}
            <a
              href="https://console.cloud.google.com/apis/credentials"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}
            >
              {t('sources.gmail.oauthLinkLabel')}
            </a>{' '}
            {t('sources.gmail.oauthOutro')}
          </div>
          <InlineConnectForm
            fields={[
              { name: 'email', placeholder: 'Client ID', type: 'text' },
              { name: 'password', placeholder: 'Client Secret', type: 'password' },
            ]}
            loading={loading}
            onSubmit={onConnect}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Data Sources section
// ---------------------------------------------------------------------------

// Sync status display component with progress bar
function formatTimeAgo(iso: string | null | undefined, t: Translate): string | null {
  if (!iso) return null;
  const stamp = new Date(iso).getTime();
  if (Number.isNaN(stamp)) return null;
  const diffSec = (Date.now() - stamp) / 1000;
  if (diffSec < 30) return t('common.justNow');
  if (diffSec < 60) return t('common.lessThanMinuteAgo');
  if (diffSec < 3600) {
    return t('common.minutesAgo', { count: Math.round(diffSec / 60) });
  }
  if (diffSec < 86400) {
    return t('common.hoursAgo', { count: Math.round(diffSec / 3600) });
  }
  return t('common.daysAgo', { count: Math.round(diffSec / 86400) });
}

/** Render how far back the corpus extends, given the oldest indexed
 *  item's timestamp. Returns null when there isn't enough data yet. */
function formatBacklogRange(iso: string | null | undefined, t: Translate): string | null {
  if (!iso) return null;
  const stamp = new Date(iso).getTime();
  if (Number.isNaN(stamp)) return null;
  const days = (Date.now() - stamp) / 86400_000;
  if (days < 7) return t('sources.range.days');
  if (days < 30) return t('sources.range.month');
  if (days < 90) return t('sources.range.months3');
  if (days < 365) return t('sources.range.year');
  return t('sources.range.years', { count: Math.round(days / 365) });
}

function SyncStatusDisplay({
  chunks,
  sync,
  unitLabel,
  connectorId,
  onSyncTriggered,
}: {
  chunks: number;
  sync: SyncStatus | undefined;
  unitLabel: string;
  connectorId: string;
  onSyncTriggered: () => void;
}) {
  const { t } = useTranslation();
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState('');

  const handleSync = async () => {
    setSyncing(true);
    setSyncError('');
    try {
      await triggerSync(connectorId);
      onSyncTriggered();
    } catch (err: any) {
      setSyncError(err.message || t('sources.sync.failed'));
    } finally {
      setSyncing(false);
    }
  };

  // Error state
  if (sync?.error) {
    return (
      <div>
        <div style={{ fontSize: 12, color: 'var(--color-error)', marginBottom: 4 }}>
          {t('sources.sync.error', { message: sync.error })}
        </div>
        <button
          onClick={handleSync}
          disabled={syncing}
          style={{
            fontSize: 10, padding: '2px 10px',
            background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
            border: 'none', borderRadius: 3,
            cursor: 'pointer', fontWeight: 600,
            opacity: syncing ? 0.5 : 1,
          }}
        >{syncing ? t('common.retrying') : t('sources.sync.retry')}</button>
      </div>
    );
  }

  // Treat the SyncEngine's checkpointed items_synced as the source of
  // truth for "total indexed" — `chunks` from listConnectors counts
  // embedding chunks (often != source items) and the checkpoint is what
  // both the syncing and idle branches need to display consistently.
  const totalIndexed = sync?.items_synced ?? chunks;
  const itemsTotal = sync?.items_total ?? 0;
  const backlogRange = formatBacklogRange(sync?.oldest_item_date, t);
  // "Complete inbox" — the user has indexed everything reachable. Only
  // surface this label when idle (during a sync we always show how far
  // back we've gotten so far).
  const isComplete =
    totalIndexed > 0 && itemsTotal > 0 && totalIndexed >= itemsTotal;

  // Actively syncing — single status line + reassurance line.
  if (sync?.state === 'syncing' || syncing) {
    const rangeLabel = backlogRange ?? t('sources.sync.buildingCorpus');
    return (
      <div>
        <div style={{ fontSize: 11, color: 'var(--color-warning)', marginBottom: 4 }}>
          {t('sources.sync.indexed')}{' '}
          <span key={totalIndexed} className="sync-bump">
            {totalIndexed.toLocaleString()} {unitLabel}
          </span>{' '}
          <span style={{ color: 'var(--color-text-tertiary)' }}>
            ({rangeLabel})
          </span>{' '}
          <span style={{ color: 'var(--color-text-tertiary)' }}>
            {'· '}{t('sources.sync.stillIndexing')}
          </span>
        </div>
        <div style={{ fontSize: 10.5, color: 'var(--color-text-tertiary)' }}>
          {t('sources.sync.deepResearchNote', { unit: unitLabel })}
        </div>
      </div>
    );
  }

  // Idle — already has indexed items: show the corpus size + range or
  // "complete inbox" label, plus how long ago we last refreshed it.
  if (totalIndexed > 0) {
    const lastSyncLabel = formatTimeAgo(sync?.last_sync, t);
    const rangeLabel = isComplete
      ? t('sources.sync.completeInbox')
      : backlogRange;
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--color-success)' }}>
            {t('sources.sync.indexed')} {totalIndexed.toLocaleString()} {unitLabel}
            {rangeLabel && (
              <span style={{ color: 'var(--color-text-tertiary)' }}>
                {' '}({rangeLabel})
              </span>
            )}
            {lastSyncLabel && (
              <span style={{ color: 'var(--color-text-tertiary)' }}>
                {' · '}{t('sources.sync.lastSynced', { time: lastSyncLabel })}
              </span>
            )}
          </span>
          <button
            onClick={handleSync}
            disabled={syncing}
            style={{
              fontSize: 9, padding: '1px 6px',
              background: 'transparent',
              color: 'var(--color-text-tertiary)',
              border: '1px solid var(--color-border)',
              borderRadius: 3, cursor: 'pointer',
            }}
          >{syncing ? '...' : t('sources.sync.resync')}</button>
        </div>
        {syncError && (
          <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 4 }}>
            {syncError}
          </div>
        )}
      </div>
    );
  }

  // Connected but nothing ever ingested. Mirror the original copy.
  const hasSynced = sync?.last_sync != null;
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          {hasSynced
            ? t('sources.sync.syncedNothingFound', { unit: unitLabel })
            : t('sources.sync.notSyncedYet')}
        </span>
        <button
          onClick={handleSync}
          disabled={syncing}
          style={{
            fontSize: 10, padding: '2px 10px',
            background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
            border: 'none', borderRadius: 3,
            cursor: 'pointer', fontWeight: 600,
            opacity: syncing ? 0.5 : 1,
          }}
        >{syncing ? t('sources.sync.syncing') : hasSynced ? t('sources.sync.resync') : t('sources.sync.syncNow')}</button>
      </div>
      {hasSynced && connectorId === 'slack' && (
        <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 4 }}>
          {t('sources.sync.slackTip')}
        </div>
      )}
      {syncError && (
        <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 4 }}>
          {syncError}
        </div>
      )}
    </div>
  );
}

function DataSourcesSection() {
  const { t } = useTranslation();
  const cachedConnectors = useAppStore((s) => s.cachedConnectors);
  const setCachedConnectors = useAppStore((s) => s.setCachedConnectors);
  const connectors = cachedConnectors ?? [];
  const isFirstLoad = cachedConnectors === null;
  const [syncStatuses, setSyncStatuses] = useState<Record<string, SyncStatus>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadConnectors = useCallback(() => {
    listConnectors()
      .then((list) =>
        setCachedConnectors(
          list.map((c) => ({
            connector_id: c.connector_id,
            display_name: c.display_name,
            connected: c.connected,
            chunks: (c as any).chunks || 0,
          })),
        ),
      )
      .catch(() => {});
  }, [setCachedConnectors]);

  const setConnectors = setCachedConnectors;

  // Poll sync status for connected sources
  const loadSyncStatuses = useCallback(async () => {
    const connected = connectors.filter((c) => c.connected);
    const statuses: Record<string, SyncStatus> = {};
    await Promise.all(
      connected.map(async (c) => {
        try {
          statuses[c.connector_id] = await getSyncStatus(c.connector_id);
        } catch { /* */ }
      }),
    );
    setSyncStatuses((prev) => ({ ...prev, ...statuses }));
  }, [connectors]);

  useEffect(() => {
    loadConnectors();
    const interval = setInterval(loadConnectors, 10000);
    return () => clearInterval(interval);
  }, [loadConnectors]);

  useEffect(() => {
    if (connectors.some((c) => c.connected)) {
      loadSyncStatuses();
      const interval = setInterval(loadSyncStatuses, 5000);
      return () => clearInterval(interval);
    }
  }, [connectors, loadSyncStatuses]);

  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [connectStage, setConnectStage] = useState<string>('');
  // Progress is tracked as its own number rather than sniffed out of the stage
  // label — the label is translated, so matching English words in it would
  // freeze the bar at 25% in every other language.
  const [connectProgress, setConnectProgress] = useState<number>(25);
  const [connectError, setConnectError] = useState<string>('');
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);

  const handleDisconnect = async (id: string) => {
    if (disconnectingId) return;
    setDisconnectingId(id);
    try {
      await disconnectSource(id);
      loadConnectors();
    } catch {
      // Surface failures silently — the connector list will refresh on the
      // next poll and reflect the true state regardless.
    } finally {
      setDisconnectingId(null);
    }
  };

  const handleConnect = async (id: string, req: ConnectRequest) => {
    setLoading(true);
    setConnectingId(id);
    setConnectStage(t('common.connecting'));
    setConnectProgress(25);
    setConnectError('');
    try {
      const resp = await connectSource(id, req);

      // OAuth connectors (Google Drive/Calendar/Contacts/Gmail/Tasks): pasting
      // a Client ID / Secret only registers the app credentials. The backend
      // returns `oauth_required` with the path to the in-process consent flow,
      // which is the only path that actually mints an access token. Open it now
      // and wait for the callback to flip the connector to connected. Without
      // this the connector would stay "pending" forever — the exact #512 bug.
      if (resp.status === 'oauth_required') {
        setConnectStage(t('sources.connect.openingGoogle'));
        setConnectProgress(25);
        await startServerOAuth(id, resp.oauth_start);
      }

      setConnectStage(t('sources.connect.startingSync'));
      setConnectProgress(50);

      // Wait for connector to show as connected
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const updated = await listConnectors();
        const target = updated.find((c) => c.connector_id === id);
        if (target?.connected) {
          setConnectors(updated.map((c) => ({
            connector_id: c.connector_id,
            display_name: c.display_name,
            connected: c.connected,
            chunks: (c as any).chunks || 0,
          })));
          break;
        }
        setConnectStage(
          i < 5 ? t('sources.connect.authenticating') : t('sources.connect.waiting'),
        );
        setConnectProgress(25);
      }

      // Trigger sync
      setConnectStage(t('sources.connect.syncingData'));
      setConnectProgress(75);
      try {
        await triggerSync(id);
      } catch { /* sync may already be running */ }

      // Close form after a brief moment
      await new Promise((r) => setTimeout(r, 1500));
      setExpandedId(null);
      loadConnectors();
      loadSyncStatuses();
    } catch (err: any) {
      let errorMsg = err.message || t('common.connectionFailed');
      if (id === 'gmail_imap' && (errorMsg.includes('auth') || errorMsg.includes('credentials') || errorMsg.includes('LOGIN'))) {
        errorMsg = t('sources.connect.gmailBadCredentials');
      }
      setConnectError(errorMsg);
      setConnectStage('');
    } finally {
      setLoading(false);
      setConnectingId(null);
      setConnectStage('');
    }
  };

  // Merge the OAuth Gmail (`gmail`) and IMAP Gmail (`gmail_imap`) backend
  // connectors into a single user-facing Gmail card. IMAP is the default
  // flow (no Google Cloud setup needed); OAuth lives behind an "Advanced"
  // disclosure when the card is expanded. If both happen to be connected,
  // keep whichever has more indexed chunks so the active source still
  // surfaces its sync state.
  const unifiedConnectors = (() => {
    const gmail = connectors.find((c) => c.connector_id === 'gmail');
    const gmailImap = connectors.find((c) => c.connector_id === 'gmail_imap');
    if (!gmail || !gmailImap) return connectors;
    if (gmail.connected && !gmailImap.connected) {
      return connectors.filter((c) => c.connector_id !== 'gmail_imap');
    }
    if (gmailImap.connected && !gmail.connected) {
      return connectors.filter((c) => c.connector_id !== 'gmail');
    }
    if (gmail.connected && gmailImap.connected) {
      const dropId = gmail.chunks >= gmailImap.chunks ? 'gmail_imap' : 'gmail';
      return connectors.filter((c) => c.connector_id !== dropId);
    }
    // Neither connected — show only the IMAP card as the default flow.
    return connectors.filter((c) => c.connector_id !== 'gmail');
  })();

  const connected = unifiedConnectors.filter((c) => c.connected);
  const notConnectedBase = unifiedConnectors.filter((c) => !c.connected);
  // Always show the upload card in the not-connected list (it has no backend connector)
  const uploadEntry = { connector_id: 'upload', display_name: 'Upload / Paste', connected: false, chunks: 0 };
  const notConnected = notConnectedBase.some((c) => c.connector_id === 'upload')
    ? notConnectedBase
    : [...notConnectedBase, uploadEntry];

  if (isFirstLoad) {
    return (
      <div className="flex flex-col gap-5">
        <section>
          <div className="hud-label mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('sources.loading')}
          </div>
          <div className="flex flex-col gap-2">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="hud-panel data-skeleton"
                style={{
                  padding: '14px 18px',
                  height: 60,
                  opacity: 0.6 - i * 0.08,
                }}
              />
            ))}
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Connected sources */}
      {connected.length > 0 && (
        <section>
          <div className="hud-label mb-2 flex items-center gap-2">
            <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: 999, background: 'var(--color-success)' }} />
            {t('sources.connectedCount', { count: connected.length })}
          </div>
          <div className="flex flex-col gap-2">
          {connected.map((c) => {
            const meta = metaFor(c.connector_id);
            const unit = meta?.unitLabel || 'items';
            const sync = syncStatuses[c.connector_id];
            const hasError = !!sync?.error;
            return (
              <div
                key={c.connector_id}
                className="hud-panel"
                style={{
                  borderColor: hasError
                    ? 'color-mix(in srgb, var(--color-error) 28%, transparent)'
                    : 'var(--color-border)',
                }}
              >
                <div style={{
                  padding: '14px 18px',
                  display: 'flex', alignItems: 'center', gap: 14,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="font-semibold" style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)' }}>
                      {meta?.display_name ?? c.display_name}
                    </div>
                    <SyncStatusDisplay
                      chunks={c.chunks}
                      sync={sync}
                      unitLabel={unit}
                      connectorId={c.connector_id}
                      onSyncTriggered={loadConnectors}
                    />
                  </div>
                  <button
                    onClick={() => handleDisconnect(c.connector_id)}
                    disabled={disconnectingId === c.connector_id}
                    className="hud-label"
                    style={{
                      padding: '6px 12px',
                      background: 'transparent',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 4,
                      cursor: disconnectingId === c.connector_id ? 'default' : 'pointer',
                      letterSpacing: '0.15em',
                      opacity: disconnectingId === c.connector_id ? 0.5 : 1,
                    }}
                  >
                    {disconnectingId === c.connector_id ? t('sources.disconnecting') : t('sources.disconnect')}
                  </button>
                </div>
              </div>
            );
          })}
          </div>
        </section>
      )}

      {/* Not connected list */}
      {notConnected.length > 0 && (
        <section>
          <div className="hud-label mb-2 flex items-center gap-2">
            <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: 999, background: 'var(--color-text-tertiary)' }} />
            {t('sources.availableCount', { count: notConnected.length })}
          </div>
          <div className="grid grid-cols-2 gap-2">
          {notConnected.map((c) => {
            const meta = metaFor(c.connector_id);
            const isExpanded = expandedId === c.connector_id;

            return (
              <div
                key={c.connector_id}
                className="hud-panel"
                style={{
                  gridColumn: isExpanded ? '1 / -1' : undefined,
                  opacity: isExpanded ? 1 : 0.85,
                  borderStyle: isExpanded ? 'solid' : 'dashed',
                }}
              >
                <div
                  style={{
                    padding: '12px 14px', display: 'flex',
                    alignItems: 'center', gap: 12,
                    cursor: 'pointer',
                  }}
                  onClick={() => setExpandedId(isExpanded ? null : c.connector_id)}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="font-semibold" style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)' }}>
                      {meta?.display_name ?? c.display_name}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 2 }}>
                      {meta?.description ?? t('sources.notConnected')}
                    </div>
                  </div>
                  <span style={{ color: 'var(--color-text-secondary)', fontSize: 12, fontWeight: 500 }}>
                    {isExpanded ? `× ${t('common.close')}` : `+ ${t('common.add')}`}
                  </span>
                </div>

                {isExpanded && c.connector_id === 'upload' && (
                  <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
                    <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
                      {t('sources.upload.description')}
                    </div>
                    <UploadForm onDone={loadConnectors} />
                  </div>
                )}

                {isExpanded && c.connector_id !== 'upload' && meta?.steps && (
                  <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
                    {meta.steps.map((step, i) => (
                      <div
                        key={i}
                        style={{
                          background: 'var(--color-bg)',
                          border: '1px solid var(--color-border)',
                          borderRadius: 6, padding: 10,
                          marginBottom: 8,
                        }}
                      >
                        <div style={{ color: 'var(--color-accent-purple)', fontSize: 10, fontWeight: 600, marginBottom: 3 }}>
                          {t('sources.stepNumber', { number: i + 1 })}
                        </div>
                        <div style={{ fontSize: 12, marginBottom: step.url ? 4 : 0 }}>{step.label}</div>
                        {step.url && (
                          <a
                            href={step.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: 'var(--color-accent)', fontSize: 11, textDecoration: 'underline' }}
                          >
                            {step.urlLabel || t('common.open')} &rarr;
                          </a>
                        )}
                      </div>
                    ))}
                    {meta?.inputFields && (
                      <InlineConnectForm
                        fields={meta.inputFields}
                        loading={loading && connectingId === c.connector_id}
                        onSubmit={(req) => handleConnect(c.connector_id, req)}
                      />
                    )}
                    {c.connector_id === 'gmail_imap' && (
                      <GmailOAuthAdvanced
                        loading={loading && connectingId === 'gmail'}
                        onConnect={(req) => handleConnect('gmail', req)}
                      />
                    )}
                    {meta?.troubleshooting && (
                      <details className="mt-2">
                        <summary className="text-[11px] cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}>
                          {t('sources.havingTrouble')}
                        </summary>
                        <ul className="mt-1 space-y-1">
                          {meta.troubleshooting.map((tip: string, i: number) => (
                            <li key={i} className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                              {tip}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                    {/* Connection progress */}
                    {connectingId === c.connector_id && connectStage && (
                      <div style={{ marginTop: 8 }}>
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: 6,
                          fontSize: 12, color: 'var(--color-warning)',
                        }}>
                          <div className="animate-spin" style={{
                            width: 12, height: 12, borderRadius: '50%',
                            border: '2px solid var(--color-warning)',
                            borderTopColor: 'transparent',
                          }} />
                          {connectStage}
                        </div>
                        <div style={{
                          height: 3, borderRadius: 2, marginTop: 6,
                          background: 'var(--color-bg-tertiary)',
                          overflow: 'hidden',
                        }}>
                          <div style={{
                            height: '100%', borderRadius: 2, background: 'var(--color-warning)',
                            width: `${connectProgress}%`,
                            transition: 'width 0.5s ease',
                          }} />
                        </div>
                      </div>
                    )}
                    {/* Connection error */}
                    {connectError && connectingId === null && expandedId === c.connector_id && (
                      <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
                        {connectError}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Messaging channels section
// ---------------------------------------------------------------------------

interface ChannelField {
  key: string;
  /** Slack's own field names \u2014 deliberately not translated, so they match
   *  what the user reads in the Slack admin UI. */
  label: string;
  placeholder: string;
  type?: 'text' | 'password';
  required?: boolean;
}

/** A setup step is either prose to translate, or a verbatim blob (the Slack
 *  app manifest) that must be copied byte-for-byte and so is never localised. */
type ChannelSetupStep =
  | { kind: 'text'; key: TranslationKey }
  | { kind: 'copyable'; text: string };

interface MessagingChannelConfig {
  type: string;
  name: string;
  icon: string;
  descriptionKey: TranslationKey;
  setupSteps: ChannelSetupStep[];
  fields: ChannelField[];
  activeLabelKey: TranslationKey;
  howToUseKey: TranslationKey;
}

const MESSAGING_CHANNELS: MessagingChannelConfig[] = [
  {
    type: 'slack',
    name: 'Slack',
    icon: '#',
    descriptionKey: 'channels.slack.description',
    setupSteps: [
      { kind: 'text', key: 'channels.slack.step1' },
      { kind: 'text', key: 'channels.slack.step2' },
      { kind: 'copyable', text: '{"display_information":{"name":"Diapason"},"features":{"app_home":{"home_tab_enabled":true,"messages_tab_enabled":true,"messages_tab_read_only_enabled":false},"bot_user":{"display_name":"Diapason","always_online":true}},"oauth_config":{"scopes":{"bot":["chat:write","im:write","im:read","im:history","mpim:read","mpim:history","users:read","channels:read","channels:history","channels:join","groups:read","groups:history","app_mentions:read"]}},"settings":{"event_subscriptions":{"bot_events":["message.im"]},"socket_mode_enabled":true}}' },
      { kind: 'text', key: 'channels.slack.step3' },
      { kind: 'text', key: 'channels.slack.step4' },
      { kind: 'text', key: 'channels.slack.step5' },
      { kind: 'text', key: 'channels.slack.step6' },
      { kind: 'text', key: 'channels.slack.step7' },
    ],
    fields: [
      { key: 'bot_token', label: 'Bot Token', placeholder: 'xoxb-...', type: 'password', required: true },
      { key: 'app_token', label: 'App Token', placeholder: 'xapp-...', type: 'password', required: true },
    ],
    activeLabelKey: 'channels.slack.active',
    howToUseKey: 'channels.slack.howToUse',
  },
];

// SendBlue wizard — simplified for standalone page
function SendBlueSection({
  agentId,
  binding,
  onDone,
  onRemove,
}: {
  agentId: string;
  binding?: ChannelBinding;
  onDone: () => void;
  onRemove: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [step, setStep] = useState(0);
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [phone, setPhone] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookStatus, setWebhookStatus] = useState<'idle' | 'registering' | 'done' | 'error'>('idle');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    if (binding) {
      sendblueHealth().then(setHealth).catch(() => {});
    }
  }, [agentId, binding]);

  const registerWebhook = async () => {
    if (!webhookUrl.trim()) return;
    setWebhookStatus('registering');
    try {
      const url = webhookUrl.trim().replace(/\/+$/, '') + '/v1/channels/sendblue/webhook';
      await sendblueRegisterWebhook(apiKey.trim(), apiSecret.trim(), url);
      setWebhookStatus('done');
    } catch {
      setWebhookStatus('error');
    }
  };

  if (binding) {
    const cfg = (binding.config || {}) as Record<string, unknown>;
    return (
      <div style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
        borderRadius: 8, marginBottom: 10,
        overflow: 'hidden',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
          <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCF1'}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage + SMS</div>
            <div style={{ fontSize: 11, color: 'var(--color-success)' }}>
              {t('channels.sendblue.activeLabel', {
                phone: (cfg.phone_number as string) || t('channels.sendblue.yourNumber'),
              })}
            </div>
          </div>
          <button
            onClick={() => onRemove(binding.id)}
            style={{
              fontSize: 10, padding: '2px 8px',
              background: 'transparent',
              color: 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
              borderRadius: 4, cursor: 'pointer',
            }}
          >{t('common.remove')}</button>
        </div>
        {health && (
          <div style={{
            borderTop: '1px solid var(--color-border)',
            padding: '8px 14px', fontSize: 11,
            color: 'var(--color-text-secondary)',
          }}>
            {t('channels.sendblue.webhookStatus', {
              status: health.webhook_registered
                ? t('channels.sendblue.registeredState')
                : t('channels.sendblue.notRegisteredState'),
            })}
            {health.phone_number && ` \u2022 ${health.phone_number}`}
          </div>
        )}
      </div>
    );
  }

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '6px 10px',
    background: 'var(--color-bg)', border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)', fontSize: 12,
    boxSizing: 'border-box',
  };

  // Not active — setup wizard
  const steps = [
    {
      title: t('channels.sendblue.step1Title'),
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            {t('channels.sendblue.step1Intro')}
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <a
              href="https://sendblue.co"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', fontSize: 12, textDecoration: 'underline' }}
            >
              {t('channels.sendblue.signUpLink')} &rarr;
            </a>
          </div>
          <div style={{ marginBottom: 8 }}>
            <a
              href="https://dashboard.sendblue.co/api-credentials"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', fontSize: 12, textDecoration: 'underline' }}
            >
              {t('channels.sendblue.credentialsLink')} &rarr;
            </a>
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 6 }}>
            {t('channels.sendblue.copyKeys')}
          </div>
          <input value={apiKey} onChange={(e) => setApiKey(e.target.value)}
            placeholder="API Key" style={{ ...inputStyle, marginTop: 4 }} />
          <input value={apiSecret} onChange={(e) => setApiSecret(e.target.value)}
            placeholder="API Secret" type="password" style={{ ...inputStyle, marginTop: 4 }} />
        </div>
      ),
      canAdvance: apiKey.trim() && apiSecret.trim(),
    },
    {
      title: t('channels.sendblue.step2Title'),
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            {t('channels.sendblue.step2Intro')}
          </div>
          <input value={phone} onChange={(e) => setPhone(e.target.value)}
            placeholder="+1XXXXXXXXXX" style={inputStyle} />
        </div>
      ),
      canAdvance: phone.trim().length >= 10,
    },
    {
      title: t('channels.sendblue.step3Title'),
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            {t('channels.sendblue.step3Intro')}
          </div>
          <div style={{
            fontSize: 11, lineHeight: 1.6,
            color: 'var(--color-text-secondary)',
            padding: '8px 10px', marginBottom: 10,
            background: 'var(--color-bg-secondary)',
            borderRadius: 6,
            borderLeft: '3px solid var(--color-accent, var(--color-accent-purple))',
          }}>
            <div><strong>1.</strong> {t('channels.sendblue.ngrok1')} <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>ngrok http 8000</code></div>
            <div style={{ marginTop: 4 }}><strong>2.</strong> {t('channels.sendblue.ngrok2Before')} <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>https://</code> {t('channels.sendblue.ngrok2After')}</div>
            <div style={{ marginTop: 4 }}><strong>3.</strong> {t('channels.sendblue.ngrok3')}</div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={webhookUrl}
              onChange={(e) => { setWebhookUrl(e.target.value); setWebhookStatus('idle'); }}
              placeholder="https://abc123.ngrok-free.app"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button
              onClick={registerWebhook}
              disabled={!webhookUrl.trim() || webhookStatus === 'registering'}
              style={{
                fontSize: 11, padding: '6px 12px', whiteSpace: 'nowrap',
                background: webhookStatus === 'done' ? 'var(--color-success)' : 'var(--color-accent-purple)',
                color: 'var(--color-on-accent)', border: 'none', borderRadius: 4,
                cursor: 'pointer', fontWeight: 600,
                opacity: !webhookUrl.trim() || webhookStatus === 'registering' ? 0.5 : 1,
              }}
            >
              {webhookStatus === 'registering' ? t('channels.sendblue.registering')
                : webhookStatus === 'done' ? t('channels.sendblue.registeredDone')
                : webhookStatus === 'error' ? t('common.retry')
                : t('channels.sendblue.registerWebhook')}
            </button>
          </div>
          {webhookStatus === 'done' && (
            <div style={{ fontSize: 11, color: 'var(--color-success)', marginTop: 6 }}>
              {t('channels.sendblue.registerSuccess')}
            </div>
          )}
          {webhookStatus === 'error' && (
            <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
              {t('channels.sendblue.registerError')}
            </div>
          )}
          <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
            {t('channels.sendblue.noNgrok')} <a href="https://ngrok.com/download" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>{t('channels.sendblue.downloadNgrok')}</a>. {t('channels.sendblue.skipWebhook')}
          </div>
        </div>
      ),
      canAdvance: true, // webhook is optional — user can skip
    },
  ];

  const handleFinish = async () => {
    setLoading(true);
    setError('');
    try {
      await bindAgentChannel(agentId, 'sendblue', {
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim(),
        phone_number: phone.trim(),
      });
      // If webhook was registered in the wizard, that's already done.
      // If not, try a best-effort registration with the provided URL.
      if (webhookUrl.trim() && webhookStatus !== 'done') {
        try {
          const url = webhookUrl.trim().replace(/\/+$/, '') + '/v1/channels/sendblue/webhook';
          await sendblueRegisterWebhook(apiKey.trim(), apiSecret.trim(), url);
        } catch { /* */ }
      }
      onDone();
      setStep(0);
      setApiKey('');
      setApiSecret('');
      setPhone('');
      setWebhookUrl('');
      setWebhookStatus('idle');
    } catch (err: any) {
      setError(err.message || t('common.connectionFailed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      background: 'var(--color-bg-secondary)',
      border: '1px dashed var(--color-border)',
      borderRadius: 8, marginBottom: 10,
      overflow: 'hidden',
    }}>
      <div
        style={{
          display: 'flex', alignItems: 'center',
          padding: '12px 14px', cursor: 'pointer',
        }}
        onClick={() => setStep(step === 0 && !apiKey ? -1 : 0)}
      >
        <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCF1'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage + SMS (SendBlue)</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
            {t('channels.sendblue.tagline')}
          </div>
        </div>
        <span style={{ color: 'var(--color-accent-purple)', fontSize: 11, fontWeight: 500 }}>
          {step >= 0 ? t('common.setUp') : `+ ${t('common.add')}`}
        </span>
      </div>

      {step >= 0 && (
        <div style={{ borderTop: '1px solid var(--color-border)', padding: 14 }}>
          {/* Step indicator */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
            {steps.map((_, i) => (
              <div
                key={i}
                style={{
                  flex: 1, height: 3, borderRadius: 2,
                  background: i <= step ? 'var(--color-accent-purple)' : 'var(--color-border)',
                }}
              />
            ))}
          </div>

          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
            {steps[step]?.title}
          </div>
          {steps[step]?.content}

          {error && (
            <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>{error}</div>
          )}

          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            {step > 0 && (
              <button
                onClick={() => setStep(step - 1)}
                style={{
                  fontSize: 12, padding: '6px 16px',
                  background: 'var(--color-bg)',
                  color: 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 5, cursor: 'pointer',
                }}
              >{t('common.back')}</button>
            )}
            {step < steps.length - 1 ? (
              <button
                onClick={() => setStep(step + 1)}
                disabled={!steps[step]?.canAdvance}
                style={{
                  fontSize: 12, padding: '6px 16px',
                  background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                  border: 'none', borderRadius: 5,
                  cursor: 'pointer', fontWeight: 600,
                  opacity: steps[step]?.canAdvance ? 1 : 0.5,
                }}
              >{t('common.next')}</button>
            ) : (
              <button
                onClick={handleFinish}
                disabled={loading || !steps[step]?.canAdvance}
                style={{
                  fontSize: 12, padding: '6px 16px',
                  background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                  border: 'none', borderRadius: 5,
                  cursor: 'pointer', fontWeight: 600,
                  opacity: loading || !steps[step]?.canAdvance ? 0.5 : 1,
                }}
              >{loading ? t('common.connecting') : t('common.connect')}</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MessagingSection({ agentId }: { agentId: string }) {
  const { t } = useTranslation();
  const [bindings, setBindings] = useState<ChannelBinding[]>([]);
  const [setupType, setSetupType] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const loadBindings = useCallback(() => {
    fetchAgentChannels(agentId).then(setBindings).catch(() => setBindings([]));
  }, [agentId]);

  useEffect(() => { loadBindings(); }, [loadBindings]);

  const setField = (key: string, value: string) =>
    setFormValues((prev) => ({ ...prev, [key]: value }));

  const handleSetup = async (ch: MessagingChannelConfig) => {
    const missing = ch.fields.filter((f) => f.required && !formValues[f.key]?.trim());
    if (missing.length > 0) return;
    setLoading(true);
    try {
      const config: Record<string, string> = {};
      for (const f of ch.fields) {
        const v = formValues[f.key]?.trim();
        if (v) config[f.key] = v;
      }
      await bindAgentChannel(agentId, ch.type, config);
      setSetupType(null);
      setFormValues({});
      loadBindings();
    } catch { /* */ } finally { setLoading(false); }
  };

  const handleRemove = async (bindingId: string) => {
    try {
      await unbindAgentChannel(agentId, bindingId);
      loadBindings();
    } catch { /* */ }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '6px 10px',
    background: 'var(--color-bg-secondary)',
    border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)',
    fontSize: 12, boxSizing: 'border-box',
  };

  return (
    <div>
      {/* SendBlue */}
      <SendBlueSection
        agentId={agentId}
        binding={bindings.find((b) => b.channel_type === 'sendblue')}
        onDone={loadBindings}
        onRemove={(id) => { unbindAgentChannel(agentId, id).then(loadBindings).catch(() => {}); }}
      />

      {/* Other messaging channels */}
      {MESSAGING_CHANNELS.map((ch) => {
        const binding = bindings.find((b) => b.channel_type === ch.type);
        const isSetup = setupType === ch.type;
        const canConnect = ch.fields.every((f) => !f.required || formValues[f.key]?.trim());

        return (
          <div
            key={ch.type}
            style={{
              background: 'var(--color-bg-secondary)',
              border: binding ? '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)' : '1px dashed var(--color-border)',
              borderRadius: 8, marginBottom: 10, overflow: 'hidden',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
              <span style={{ fontSize: 18, marginRight: 10 }}>{ch.icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{ch.name}</div>
                <div style={{
                  fontSize: 11,
                  color: binding ? 'var(--color-success)' : 'var(--color-text-secondary)',
                }}>
                  {binding ? t(ch.activeLabelKey) : t(ch.descriptionKey)}
                </div>
              </div>
              {binding ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    background: 'color-mix(in srgb, var(--color-success) 22%, transparent)', color: 'var(--color-success)',
                    padding: '2px 8px', borderRadius: 10,
                    fontSize: 10, fontWeight: 600,
                  }}>{t('common.active')}</span>
                  <button
                    onClick={() => handleRemove(binding.id)}
                    style={{
                      fontSize: 10, padding: '2px 8px', background: 'transparent',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 4, cursor: 'pointer',
                    }}
                  >{t('common.remove')}</button>
                </div>
              ) : (
                <button
                  onClick={() => { setSetupType(isSetup ? null : ch.type); setFormValues({}); }}
                  style={{
                    fontSize: 10, padding: '3px 12px', background: 'var(--color-accent-purple)',
                    color: 'var(--color-on-accent)', border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                  }}
                >{isSetup ? t('common.cancel') : t('common.setUp')}</button>
              )}
            </div>

            {binding && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '10px 14px', background: 'var(--color-bg)',
              }}>
                <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'flex-start', gap: 6 }}>
                  <span style={{ flexShrink: 0 }}>{'\u2192'}</span>
                  <span>{t(ch.howToUseKey)}</span>
                </div>
              </div>
            )}

            {isSetup && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: 14, background: 'var(--color-bg)',
              }}>
                <div style={{
                  fontSize: 11, lineHeight: 1.5,
                  color: 'var(--color-text-secondary)',
                  marginBottom: 12, padding: '8px 10px',
                  background: 'var(--color-bg-secondary)',
                  borderRadius: 6,
                  borderLeft: '3px solid var(--color-accent, var(--color-accent-purple))',
                }}>
                  {ch.setupSteps.map((s, i) => {
                    if (s.kind === 'copyable') {
                      const text = s.text;
                      return (
                        <div key={i} style={{ marginBottom: 6, marginTop: 4 }}>
                          <div style={{
                            position: 'relative',
                            background: 'var(--color-bg)',
                            border: '1px solid var(--color-border)',
                            borderRadius: 4, padding: '8px 10px',
                            fontSize: 10, fontFamily: 'monospace',
                            wordBreak: 'break-all', lineHeight: 1.4,
                            maxHeight: 80, overflowY: 'auto',
                          }}>
                            {text}
                            <button
                              onClick={() => { navigator.clipboard.writeText(text); }}
                              style={{
                                position: 'sticky', float: 'right', top: 0,
                                fontSize: 10, padding: '2px 8px',
                                background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                                border: 'none', borderRadius: 3,
                                cursor: 'pointer', fontWeight: 600,
                              }}
                            >{t('common.copy')}</button>
                          </div>
                        </div>
                      );
                    }
                    return (
                      <div key={i} style={{ marginBottom: i < ch.setupSteps.length - 1 ? 4 : 0 }}>{t(s.key)}</div>
                    );
                  })}
                </div>
                {ch.fields.map((field) => (
                  <div key={field.key} style={{ marginBottom: 8 }}>
                    <label style={{
                      display: 'block', fontSize: 11,
                      color: 'var(--color-text-secondary)',
                      marginBottom: 3, fontWeight: 500,
                    }}>
                      {field.label}{field.required ? ' *' : ''}
                    </label>
                    <input
                      type={field.type || 'text'}
                      value={formValues[field.key] || ''}
                      onChange={(e) => setField(field.key, e.target.value)}
                      placeholder={field.placeholder}
                      style={inputStyle}
                    />
                  </div>
                ))}
                <button
                  onClick={() => handleSetup(ch)}
                  disabled={loading || !canConnect}
                  style={{
                    fontSize: 12, padding: '7px 20px', background: 'var(--color-accent-purple)',
                    color: 'var(--color-on-accent)', border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                    opacity: loading || !canConnect ? 0.5 : 1, marginTop: 4,
                  }}
                >{loading ? t('common.connecting') : t('common.connect')}</button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Memory section
// ---------------------------------------------------------------------------

function MemorySection() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [statsError, setStatsError] = useState('');

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<MemorySearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchDone, setSearchDone] = useState(false);

  // Index
  const [indexPath, setIndexPath] = useState('');
  const [indexing, setIndexing] = useState(false);
  const [indexResult, setIndexResult] = useState('');
  const [indexError, setIndexError] = useState('');

  // Store
  const [storeContent, setStoreContent] = useState('');
  const [storing, setStoring] = useState(false);
  const [storeResult, setStoreResult] = useState('');
  const [storeError, setStoreError] = useState('');

  const statsInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadStats = useCallback(() => {
    getMemoryStats()
      .then((s) => { setStats(s); setStatsError(''); })
      .catch(() => setStatsError(t('memory.backendUnreachable')));
  }, [t]);

  useEffect(() => {
    loadStats();
    statsInterval.current = setInterval(loadStats, 10000);
    return () => { if (statsInterval.current) clearInterval(statsInterval.current); };
  }, [loadStats]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchDone(false);
    try {
      const results = await searchMemory(searchQuery.trim());
      setSearchResults(results || []);
      setSearchDone(true);
    } catch {
      setSearchResults([]);
      setSearchDone(true);
    } finally {
      setSearching(false);
    }
  };

  const handleBrowse = async () => {
    if (isTauri()) {
      try {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const selected = await open({ directory: true, multiple: false, title: t('memory.selectFolderTitle') });
        if (selected) setIndexPath(selected as string);
        return;
      } catch {
        // fall through to browser picker
      }
    }
    const input = document.createElement('input');
    input.type = 'file';
    input.setAttribute('webkitdirectory', '');
    input.onchange = () => {
      const files = input.files;
      if (files && files.length > 0) {
        const rel = (files[0] as any).webkitRelativePath || '';
        const folder = rel.split('/')[0];
        if (folder) setIndexPath(folder);
      }
    };
    input.click();
  };

  const handleIndex = async () => {
    if (!indexPath.trim()) return;
    setIndexing(true);
    setIndexResult('');
    setIndexError('');
    try {
      const res = await indexMemoryPath(indexPath.trim());
      setIndexResult(t('memory.indexedChunks', { count: res.chunks_indexed }));
      setIndexPath('');
      loadStats();
    } catch (err: any) {
      setIndexError(err.message || t('memory.indexFailed'));
    } finally {
      setIndexing(false);
    }
  };

  const handleStore = async () => {
    if (!storeContent.trim()) return;
    setStoring(true);
    setStoreResult('');
    setStoreError('');
    try {
      await storeMemory(storeContent.trim());
      setStoreResult(t('memory.storeSuccess'));
      setStoreContent('');
      loadStats();
    } catch (err: any) {
      setStoreError(err.message || t('memory.storeFailed'));
    } finally {
      setStoring(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Stats overview */}
      <div
        className="rounded-xl p-5 relative overflow-hidden"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        {/* Subtle gradient accent along top edge */}
        <div className="absolute top-0 left-0 right-0 h-[2px]" style={{
          background: 'linear-gradient(90deg, var(--color-accent-purple), var(--color-accent), transparent)',
        }} />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{
              background: 'var(--color-accent-purple-subtle)',
            }}>
              <Brain size={18} style={{ color: 'var(--color-accent-purple)' }} />
            </div>
            <div>
              <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>{t('memory.backendTitle')}</h3>
              {statsError ? (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{statsError}</p>
              ) : stats ? (
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="w-1.5 h-1.5 rounded-full" style={{
                    background: stats.entries > 0 ? 'var(--color-success)' : 'var(--color-text-tertiary)',
                  }} />
                  <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    {stats.backend} &middot; {t('memory.chunkCount', {
                      count: stats.entries,
                      n: stats.entries.toLocaleString(),
                    })}
                  </span>
                </div>
              ) : (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{t('common.connecting')}</p>
              )}
            </div>
          </div>
          {stats && stats.entries > 0 && (
            <div className="text-right">
              <div className="text-lg font-bold tabular-nums" style={{ color: 'var(--color-text)' }}>
                {stats.entries.toLocaleString()}
              </div>
              <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--color-text-tertiary)' }}>
                {t('memory.indexedLabel')}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Search */}
      <div
        className="rounded-xl p-5"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-2 mb-3">
          <Search size={14} style={{ color: 'var(--color-accent-purple)' }} />
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>{t('memory.searchTitle')}</h3>
        </div>
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
              placeholder={t('memory.searchPlaceholder')}
              className="w-full text-sm px-3 py-2 rounded-lg outline-none transition-colors"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={searching || !searchQuery.trim()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer whitespace-nowrap"
            style={{
              background: searching || !searchQuery.trim() ? 'var(--color-bg-tertiary)' : 'var(--color-accent-purple)',
              color: searching || !searchQuery.trim() ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
              opacity: searching || !searchQuery.trim() ? 0.6 : 1,
            }}
          >
            {searching ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
            {searching ? t('common.searching') : t('common.search')}
          </button>
        </div>

        {/* Results */}
        {searchDone && searchResults.length === 0 && (
          <div className="flex flex-col items-center py-6 gap-2">
            <Search size={20} style={{ color: 'var(--color-text-tertiary)', opacity: 0.4 }} />
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{t('memory.noResults')}</p>
          </div>
        )}
        {searchResults.length > 0 && (
          <div className="mt-3 space-y-2">
            {searchResults.map((r, i) => (
              <div
                key={i}
                className="rounded-lg p-3 transition-colors"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text)' }}>
                  {r.content.length > 250 ? r.content.slice(0, 250) + '...' : r.content}
                </p>
                <div className="flex items-center gap-3 mt-2">
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium" style={{
                    background: r.score > 0.5
                      ? 'rgba(74, 222, 128, 0.1)'
                      : r.score > 0.2
                        ? 'var(--color-accent-amber-subtle)'
                        : 'var(--color-bg-tertiary)',
                    color: r.score > 0.5
                      ? 'var(--color-success)'
                      : r.score > 0.2
                        ? 'var(--color-warning)'
                        : 'var(--color-text-tertiary)',
                  }}>
                    {t('memory.matchPercent', { percent: (r.score * 100).toFixed(0) })}
                  </span>
                  {r.metadata?.source != null && (
                    <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
                      {String(r.metadata.source)}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add to Memory — two-column grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Index folder */}
        <div
          className="rounded-xl p-5"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center gap-2 mb-3">
            <FolderOpen size={14} style={{ color: 'var(--color-accent-purple)' }} />
            <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>{t('memory.indexFolderTitle')}</h3>
          </div>
          <p className="text-xs mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('memory.indexFolderDescription')}
          </p>
          <div className="flex gap-2 mb-2">
            <input
              value={indexPath}
              onChange={(e) => setIndexPath(e.target.value)}
              placeholder="~/Documents/notes"
              className="flex-1 text-sm px-3 py-2 rounded-lg outline-none"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
            {isTauri() && (
              <button
                onClick={handleBrowse}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium cursor-pointer transition-colors whitespace-nowrap"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-secondary)',
                }}
              >
                <FolderOpen size={12} />
                {t('common.browse')}
              </button>
            )}
          </div>
          <button
            onClick={handleIndex}
            disabled={indexing || !indexPath.trim()}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium cursor-pointer transition-all"
            style={{
              background: indexing || !indexPath.trim() ? 'var(--color-bg-tertiary)' : 'var(--color-accent-purple)',
              color: indexing || !indexPath.trim() ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
              opacity: indexing || !indexPath.trim() ? 0.6 : 1,
            }}
          >
            {indexing && <Loader2 size={13} className="animate-spin" />}
            {indexing ? t('memory.indexing') : t('memory.index')}
          </button>
          {indexResult && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-success)' }}>{indexResult}</p>
          )}
          {indexError && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-error)' }}>{indexError}</p>
          )}
        </div>

        {/* Paste content */}
        <div
          className="rounded-xl p-5"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center gap-2 mb-3">
            <FileText size={14} style={{ color: 'var(--color-accent-purple)' }} />
            <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>{t('memory.storeTitle')}</h3>
          </div>
          <p className="text-xs mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('memory.storeDescription')}
          </p>
          <textarea
            value={storeContent}
            onChange={(e) => setStoreContent(e.target.value)}
            placeholder={t('memory.storePlaceholder')}
            rows={4}
            className="w-full text-sm px-3 py-2 rounded-lg outline-none resize-y"
            style={{
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
              fontFamily: 'inherit',
              minHeight: 80,
              marginBottom: 8,
            }}
          />
          <button
            onClick={handleStore}
            disabled={storing || !storeContent.trim()}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium cursor-pointer transition-all"
            style={{
              background: storing || !storeContent.trim() ? 'var(--color-bg-tertiary)' : 'var(--color-accent-purple)',
              color: storing || !storeContent.trim() ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
              opacity: storing || !storeContent.trim() ? 0.6 : 1,
            }}
          >
            {storing && <Loader2 size={13} className="animate-spin" />}
            {storing ? t('memory.storing') : t('memory.store')}
          </button>
          {storeResult && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-success)' }}>{storeResult}</p>
          )}
          {storeError && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-error)' }}>{storeError}</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function DataSourcesPage() {
  const { t } = useTranslation();
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [activeTab, setActiveTab] = useState<'sources' | 'messaging' | 'memory'>('sources');
  const [creatingAgent, setCreatingAgent] = useState(false);

  const loadAgents = useCallback(() => {
    fetchManagedAgents().then(setAgents).catch(() => {});
  }, []);

  useEffect(() => { loadAgents(); }, [loadAgents]);

  // Pick the first agent for messaging channel bindings.
  // If none exists and user opens Messaging tab, auto-create a default one.
  const firstAgent = agents[0];

  const ensureAgent = useCallback(async (): Promise<string | null> => {
    if (firstAgent) return firstAgent.id;
    setCreatingAgent(true);
    try {
      const agent = await createManagedAgent({
        name: t('agents.defaultAssistantName'),
        template_id: "personal_deep_research",
      });
      setAgents((prev) => [...prev, agent]);
      return agent.id;
    } catch {
      return null;
    } finally {
      setCreatingAgent(false);
    }
  }, [firstAgent, t]);

  // Auto-create agent when switching to messaging tab
  useEffect(() => {
    if (activeTab === 'messaging' && !firstAgent && !creatingAgent) {
      ensureAgent();
    }
  }, [activeTab, firstAgent, creatingAgent, ensureAgent]);

  const tabs = [
    { id: 'sources' as const, label: t('sources.tab.sources'), icon: Database },
    { id: 'messaging' as const, label: t('sources.tab.messaging'), icon: MessageSquare },
    { id: 'memory' as const, label: t('sources.tab.memory'), icon: Brain },
  ];

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-5xl mx-auto">
      <header className="mb-6">
        <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
          {t('sources.pageTitle')}
        </h1>
        <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
          {t('sources.pageSubtitle')}
        </p>
      </header>

      <div
        className="flex gap-1 mb-6"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className="relative px-4 py-2.5 text-sm transition-colors cursor-pointer"
              style={{
                color: isActive ? 'var(--color-text)' : 'var(--color-text-secondary)',
                fontWeight: isActive ? 600 : 400,
              }}
            >
              {tab.label}
              {isActive && (
                <motion.span
                  layoutId="data-sources-tab-indicator"
                  className="absolute left-0 right-0 -bottom-px h-[2px]"
                  style={{ background: 'var(--color-text)' }}
                  transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                />
              )}
            </button>
          );
        })}
      </div>

      <div>
        {activeTab === 'sources' && <DataSourcesSection />}
        {activeTab === 'messaging' && (
          firstAgent ? (
            <MessagingSection agentId={firstAgent.id} />
          ) : creatingAgent ? (
            <div className="flex items-center gap-3 p-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              <Loader2 size={16} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
              {t('sources.settingUpAssistant')}
            </div>
          ) : null
        )}
        {activeTab === 'memory' && <MemorySection />}
      </div>
      </div>
    </div>
  );
}
