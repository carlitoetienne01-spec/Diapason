import { useState, useMemo, useEffect } from 'react';
import { useNavigate } from 'react-router';
import {
  Sparkles,
  Download,
  Terminal,
  Globe,
  Monitor,
  Apple,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  Cpu,
  CheckCircle2,
  AlertCircle,
  MessageSquare,
  ArrowRight,
} from 'lucide-react';
import { isTauri, checkHealth } from '../lib/api';
import { useTranslation } from '../i18n/useTranslation';

const GITHUB_BASE =
  'https://github.com/open-diapason/Diapason/releases/latest/download';

interface Platform {
  id: string;
  label: string;
  shortLabel: string;
  file: string;
  icon: typeof Apple;
}

const PLATFORMS: Platform[] = [
  {
    id: 'mac-arm',
    label: 'macOS (Apple Silicon)',
    shortLabel: 'macOS (Apple Silicon)',
    file: 'Diapason_aarch64.dmg',
    icon: Apple,
  },
  {
    id: 'mac-intel',
    label: 'macOS (Intel)',
    shortLabel: 'macOS (Intel)',
    file: 'Diapason_x64.dmg',
    icon: Apple,
  },
  {
    id: 'windows',
    label: 'Windows (64-bit)',
    shortLabel: 'Windows (64-bit)',
    file: 'Diapason_x64-setup.msi',
    icon: Monitor,
  },
  {
    id: 'linux-deb',
    label: 'Linux (DEB)',
    shortLabel: 'Linux (DEB)',
    file: 'Diapason_amd64.deb',
    icon: Terminal,
  },
  {
    id: 'linux-rpm',
    label: 'Linux (RPM)',
    shortLabel: 'Linux (RPM)',
    file: 'Diapason_x86_64.rpm',
    icon: Terminal,
  },
];

type DeployContext = 'hosted' | 'desktop' | 'selfhosted';

function detectContext(): DeployContext {
  if (isTauri()) return 'desktop';
  const host = window.location.hostname;
  if (host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0') {
    return 'selfhosted';
  }
  return 'hosted';
}

function detectPlatform(): string {
  const ua = navigator.userAgent.toLowerCase();
  const platform = navigator.platform?.toLowerCase() || '';

  if (platform.includes('mac') || ua.includes('macintosh')) {
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl');
      if (gl) {
        const ext = gl.getExtension('WEBGL_debug_renderer_info');
        if (ext) {
          const renderer = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);
          if (renderer && /apple m/i.test(renderer)) return 'mac-arm';
        }
      }
    } catch {}
    return 'mac-arm';
  }
  if (platform.includes('win') || ua.includes('windows')) return 'windows';
  if (ua.includes('ubuntu') || ua.includes('debian')) return 'linux-deb';
  if (ua.includes('linux')) return 'linux-deb';
  return 'mac-arm';
}

function CodeBlock({ code }: { code: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className="relative group rounded-lg px-4 py-3 text-sm font-mono overflow-x-auto"
      style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)' }}
    >
      <pre className="whitespace-pre-wrap break-all">{code}</pre>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 p-1.5 rounded-md opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
        style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-tertiary)' }}
        title={t('common.copy')}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  children,
  defaultOpen = false,
}: {
  icon: typeof Terminal;
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: '1px solid var(--color-border)' }}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-3 w-full px-5 py-4 text-left cursor-pointer transition-colors"
        style={{ background: open ? 'var(--color-bg-secondary)' : 'var(--color-surface)' }}
        onMouseEnter={(e) => {
          if (!open) e.currentTarget.style.background = 'var(--color-bg-secondary)';
        }}
        onMouseLeave={(e) => {
          if (!open) e.currentTarget.style.background = 'var(--color-surface)';
        }}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
        >
          <Icon size={16} />
        </div>
        <span className="text-sm font-medium flex-1" style={{ color: 'var(--color-text)' }}>
          {title}
        </span>
        <Chevron size={16} style={{ color: 'var(--color-text-tertiary)' }} />
      </button>
      {open && (
        <div className="px-5 pb-5 pt-3 flex flex-col gap-3" style={{ background: 'var(--color-surface)' }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hosted view: visitor on a deployed website
// ---------------------------------------------------------------------------
function HostedView() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    checkHealth().then(setHealthy);
  }, []);

  return (
    <div className="text-center mb-14">
      <div
        className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5"
        style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
      >
        <Sparkles size={32} />
      </div>
      <h1 className="text-3xl font-bold mb-2" style={{ color: 'var(--color-text)' }}>
        Diapason
      </h1>
      <p
        className="text-sm mb-6 leading-relaxed max-w-md mx-auto"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {t('getstarted.tagline')}
      </p>

      {healthy === true && (
        <div className="flex flex-col items-center gap-4">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent)' }}>
            <CheckCircle2 size={16} />
            <span>{t('getstarted.serverRunning')}</span>
          </div>
          <button
            onClick={() => navigate('/')}
            className="inline-flex items-center gap-2.5 px-6 py-3 rounded-xl text-sm font-medium transition-opacity cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.9')}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
          >
            <MessageSquare size={18} />
            {t('getstarted.startChatting')}
            <ArrowRight size={16} />
          </button>
        </div>
      )}

      {healthy === false && (
        <div
          className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm"
          style={{ background: 'color-mix(in srgb, var(--color-error) 10%, transparent)', color: 'var(--color-error)' }}
        >
          {t('getstarted.serverNotResponding')}
        </div>
      )}

      {healthy === null && (
        <div className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          {t('getstarted.checkingServer')}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Desktop view: running in the Tauri app
// ---------------------------------------------------------------------------
function DesktopView() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // "All systems running" used to be written in the markup, unconditionally:
  // it said everything was fine even with the backend down. It now reflects an
  // actual probe, and re-probes on window focus so a backend started after the
  // app does not leave a stale "unreachable".
  const [healthy, setHealthy] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    const probe = () => {
      checkHealth().then((ok) => {
        if (!cancelled) setHealthy(ok);
      });
    };
    probe();
    window.addEventListener('focus', probe);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', probe);
    };
  }, []);

  return (
    <>
      <div className="text-center mb-14">
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5"
          style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
        >
          <Sparkles size={32} />
        </div>
        <h1 className="text-3xl font-bold mb-2" style={{ color: 'var(--color-text)' }}>
          Diapason Desktop
        </h1>
        <p
          className="text-sm mb-4 leading-relaxed max-w-md mx-auto"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {t('getstarted.desktopTagline')}
        </p>
        <span
          className="inline-block text-[11px] font-mono px-2.5 py-1 rounded-full"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
        >
          v{__APP_VERSION__}
        </span>
      </div>

      <div
        className="rounded-xl p-6 mb-8 text-center"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <div
          className="flex items-center justify-center gap-2 mb-2"
          style={{
            color:
              healthy === false ? 'var(--color-danger, #e5484d)' : 'var(--color-accent)',
          }}
        >
          {healthy === false ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
          <span className="text-sm font-medium">
            {healthy === null
              ? t('getstarted.checkingBackend')
              : healthy
                ? t('getstarted.backendReachable')
                : t('getstarted.backendUnreachable')}
          </span>
        </div>
        <p className="text-xs mb-5" style={{ color: 'var(--color-text-tertiary)' }}>
          {healthy === false
            ? t('getstarted.backendStartHint')
            : t('getstarted.backendOk')}
        </p>
        <button
          onClick={() => navigate('/')}
          className="inline-flex items-center gap-2.5 px-6 py-3 rounded-xl text-sm font-medium transition-opacity cursor-pointer"
          style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
          onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.9')}
          onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
        >
          <MessageSquare size={18} />
          {t('getstarted.startChatting')}
          <ArrowRight size={16} />
        </button>
      </div>

      <div className="flex flex-col gap-3 mb-8">
        <Section icon={Cpu} title={t('getstarted.shortcutsTitle')} defaultOpen>
          {/* Only shortcuts that are actually registered. "Cmd+N New chat" was
              listed here and bound nowhere — no handler exists for KeyN. */}
          <div className="grid grid-cols-2 gap-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            <div><kbd className="font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>Cmd+K</kbd> {t('getstarted.shortcutModelPicker')}</div>
            <div><kbd className="font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>Cmd+I</kbd> {t('getstarted.shortcutSystemPanel')}</div>
            <div><kbd className="font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>Cmd+Shift+Space</kbd> {t('getstarted.shortcutQuickOverlay')}</div>
            <div><kbd className="font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>Alt+Space</kbd> {t('getstarted.shortcutTalk')}</div>
          </div>
          <p className="text-xs mt-3" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('getstarted.dictationBefore')}{' '}
            <kbd className="font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>Control</kbd>{' '}
            {t('getstarted.dictationAfter')}{' '}
            <code>diapason dictate-service</code>.
          </p>
        </Section>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Self-hosted view: running on localhost (manual setup)
// ---------------------------------------------------------------------------
function SelfHostedView() {
  const { t } = useTranslation();
  const detectedId = useMemo(() => detectPlatform(), []);
  const primary = PLATFORMS.find((p) => p.id === detectedId) || PLATFORMS[0];
  const others = PLATFORMS.filter((p) => p.id !== primary.id);

  return (
    <>
      {/* Hero */}
      <div className="text-center mb-14">
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5"
          style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
        >
          <Sparkles size={32} />
        </div>
        <h1 className="text-3xl font-bold mb-2" style={{ color: 'var(--color-text)' }}>
          Diapason
        </h1>
        <p
          className="text-sm mb-4 leading-relaxed max-w-md mx-auto"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {t('getstarted.tagline')}
        </p>
        <span
          className="inline-block text-[11px] font-mono px-2.5 py-1 rounded-full"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
        >
          v{__APP_VERSION__}
        </span>
      </div>

      {/* Desktop Download */}
      <div className="mb-10">
        <div
          className="rounded-xl p-8 text-center"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center justify-center gap-2 mb-1">
            <Monitor size={18} style={{ color: 'var(--color-text-secondary)' }} />
            <h2 className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>
              {t('getstarted.desktopAppTitle')}
            </h2>
          </div>
          <p className="text-xs mb-6" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('getstarted.desktopAppDescription')}
          </p>

          <a
            href={`${GITHUB_BASE}/${primary.file}`}
            className="inline-flex items-center gap-2.5 px-6 py-3 rounded-xl text-sm font-medium transition-opacity cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.9')}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
          >
            <Download size={18} />
            {t('getstarted.downloadFor', { platform: primary.label })}
          </a>

          <div className="mt-4 flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
            <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
              {t('getstarted.or')}
            </span>
            {others.map((p) => (
              <a
                key={p.id}
                href={`${GITHUB_BASE}/${p.file}`}
                className="text-[11px] underline underline-offset-2 transition-colors"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-accent)')}
                onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-secondary)')}
              >
                {p.shortLabel}
              </a>
            ))}
          </div>
        </div>
      </div>

      {/* CLI + Browser sections */}
      <div className="flex flex-col gap-3 mb-10">
        <Section icon={Terminal} title={t('getstarted.cliTitle')} defaultOpen>
          <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {t('getstarted.cliClone')}
          </p>
          <CodeBlock code={"git clone https://github.com/open-diapason/Diapason.git\ncd Diapason\nuv sync"} />
          <p className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
            {t('getstarted.cliThen')}
          </p>
          <CodeBlock code={"diapason init\njarvis doctor\njarvis chat"} />
        </Section>

        <Section icon={Globe} title={t('getstarted.browserTitle')}>
          <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {t('getstarted.browserIntro')}
          </p>
          <CodeBlock code={"git clone https://github.com/open-diapason/Diapason.git\ncd Diapason\nuv sync --extra desktop\njarvis serve --port 8000"} />
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('getstarted.browserNote')}
          </p>
        </Section>

        <Section icon={Globe} title={t('getstarted.dockerTitle')}>
          <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {t('getstarted.dockerIntro')}
          </p>
          <CodeBlock code={"git clone https://github.com/open-diapason/Diapason.git\ncd Diapason\ndocker compose -f deploy/docker/docker-compose.yml up -d"} />
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('getstarted.dockerNote')}
          </p>
        </Section>
      </div>

      {/* System Requirements */}
      <div
        className="rounded-xl px-6 py-5"
        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-2 mb-3">
          <Cpu size={14} style={{ color: 'var(--color-text-tertiary)' }} />
          <h3 className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('getstarted.sysreqTitle')}
          </h3>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          <div>
            <div className="font-medium mb-0.5" style={{ color: 'var(--color-text)' }}>{t('getstarted.desktopAppTitle')}</div>
            {t('getstarted.sysreqDesktop')}
          </div>
          <div>
            <div className="font-medium mb-0.5" style={{ color: 'var(--color-text)' }}>{t('getstarted.sysreqCliTitle')}</div>
            {t('getstarted.sysreqCli')}
          </div>
          <div>
            <div className="font-medium mb-0.5" style={{ color: 'var(--color-text)' }}>{t('getstarted.sysreqMemoryTitle')}</div>
            {t('getstarted.sysreqMemory')}
          </div>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main page — delegates to the context-appropriate view
// ---------------------------------------------------------------------------

export function GetStartedPage() {
  const context = useMemo(detectContext, []);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-16">
        {context === 'hosted' && <HostedView />}
        {context === 'desktop' && <DesktopView />}
        {context === 'selfhosted' && <SelfHostedView />}
      </div>
    </div>
  );
}
