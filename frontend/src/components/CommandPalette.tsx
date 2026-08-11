import { useState, useRef, useEffect, useCallback } from 'react';
import { Search, Cpu, X, Download, Loader2, Trash2, Check, Cloud, Key, Eye, EyeOff } from 'lucide-react';
import { useAppStore } from '../lib/store';
import { useTranslation } from '../i18n/useTranslation';
import type { MessageKey } from '../i18n/translate';
import {
  pullModel,
  deleteModel,
  fetchModels,
  preloadModel,
  isTauri,
  getCloudKeyStatus,
  saveCloudKey,
} from '../lib/api';

/**
 * A model entry as the palette shows it.
 *
 * `name` is the vendor's own product name and stays as written in every
 * language; only the qualifier after it (`note`) is a translated phrase, held
 * here as a catalogue key because module scope cannot call the hook.
 */
interface CatalogueModel {
  id: string;
  size: string;
  name: string;
  note?: MessageKey;
}

/** Popular models that users can download from the catalogue. */
const CATALOGUE_MODELS: CatalogueModel[] = [
  { id: 'qwen3.5:0.8b', size: '~1 GB', name: 'Qwen 3.5 0.8B', note: 'models.note.fastLightweight' },
  { id: 'qwen3.5:2b', size: '~2.7 GB', name: 'Qwen 3.5 2B' },
  { id: 'qwen3.5:4b', size: '~3.4 GB', name: 'Qwen 3.5 4B', note: 'models.note.recommendedDefault' },
  { id: 'qwen3.5:9b', size: '~6.6 GB', name: 'Qwen 3.5 9B' },
  { id: 'qwen3.5:27b', size: '~17 GB', name: 'Qwen 3.5 27B' },
  { id: 'qwen3.5:35b', size: '~24 GB', name: 'Qwen 3.5 35B' },
  { id: 'qwen3.5:122b', size: '~81 GB', name: 'Qwen 3.5 122B', note: 'models.note.largest' },
  { id: 'llama3.3:latest', size: '~4.9 GB', name: 'Llama 3.3 8B' },
  { id: 'mistral:latest', size: '~4.1 GB', name: 'Mistral 7B' },
  { id: 'gemma3:latest', size: '~3.3 GB', name: 'Gemma 3 4B' },
  { id: 'deepseek-r1:7b', size: '~4.7 GB', name: 'DeepSeek R1 7B' },
  { id: 'phi4:latest', size: '~9.1 GB', name: 'Phi-4 14B' },
];

/** Cloud provider definitions */
interface CloudProvider {
  name: string;
  envKey: string;
  models: Array<{ id: string; name: string; note?: MessageKey }>;
}

const CLOUD_PROVIDERS: CloudProvider[] = [
  {
    name: 'OpenAI',
    envKey: 'OPENAI_API_KEY',
    models: [
      { id: 'gpt-4o', name: 'GPT-4o', note: 'models.note.fastMultimodal' },
      { id: 'gpt-4o-mini', name: 'GPT-4o Mini', note: 'models.note.cheapFast' },
      { id: 'o3-mini', name: 'o3-mini', note: 'models.note.reasoning' },
    ],
  },
  {
    name: 'Anthropic',
    envKey: 'ANTHROPIC_API_KEY',
    models: [
      { id: 'claude-sonnet-4-6', name: 'Claude Sonnet 4.6', note: 'models.note.balanced' },
      { id: 'claude-opus-4-6', name: 'Claude Opus 4.6', note: 'models.note.mostCapable' },
      { id: 'claude-haiku-4-5', name: 'Claude Haiku 4.5', note: 'models.note.fastest' },
    ],
  },
  {
    name: 'Google',
    envKey: 'GEMINI_API_KEY',
    models: [
      { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro', note: 'models.note.flagship' },
      { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash', note: 'models.note.fast' },
      { id: 'gemini-3-pro', name: 'Gemini 3 Pro', note: 'models.note.latest' },
    ],
  },
  {
    name: 'OpenRouter',
    envKey: 'OPENROUTER_API_KEY',
    models: [
      { id: 'openrouter/auto', name: 'Auto', note: 'models.note.bestForTask' },
      { id: 'openrouter/anthropic/claude-sonnet-4', name: 'Claude Sonnet 4', note: 'models.note.viaOpenRouter' },
      { id: 'openrouter/deepseek/deepseek-r1', name: 'DeepSeek R1', note: 'models.note.viaOpenRouter' },
    ],
  },
];

type Tab = 'installed' | 'catalogue' | 'cloud';

export function CommandPalette() {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [tab, setTab] = useState<Tab>('installed');
  const [pulling, setPulling] = useState<string | null>(null);
  const [pullError, setPullError] = useState<string | null>(null);
  const [pullSuccess, setPullSuccess] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [customModel, setCustomModel] = useState('');
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [cloudKeyStatus, setCloudKeyStatus] = useState<Record<string, boolean>>({});
  const [cloudKeyError, setCloudKeyError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const models = useAppStore((s) => s.models);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const setModels = useAppStore((s) => s.setModels);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);

  const installedIds = new Set(models.map((m) => m.id));
  const desktopKeyStorage = isTauri();

  /** Product name plus its translated qualifier, e.g. "Gemma 3 4B — rapide". */
  const modelLabel = useCallback(
    (m: { name: string; note?: MessageKey }) => (m.note ? `${m.name} — ${t(m.note)}` : m.name),
    [t],
  );

  const refreshCloudKeyStatus = useCallback(async () => {
    if (!desktopKeyStorage) {
      setCloudKeyStatus({});
      return;
    }
    try {
      setCloudKeyStatus(await getCloudKeyStatus());
      setCloudKeyError(null);
    } catch (e: any) {
      setCloudKeyError(e?.message || t('models.cloudKeyStatusFailed'));
    }
  }, [desktopKeyStorage, t]);

  const filtered = tab === 'installed'
    ? (query
        ? models.filter((m) => m.id.toLowerCase().includes(query.toLowerCase()))
        : models)
    : tab === 'catalogue'
    ? CATALOGUE_MODELS.filter((m) =>
        !installedIds.has(m.id) &&
        (!query || m.id.toLowerCase().includes(query.toLowerCase()) || modelLabel(m).toLowerCase().includes(query.toLowerCase()))
      )
    : []; // cloud tab doesn't use filtered

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    void refreshCloudKeyStatus();
  }, [refreshCloudKeyStatus]);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query, tab]);

  useEffect(() => {
    if (pullSuccess) {
      const t = setTimeout(() => setPullSuccess(null), 3000);
      return () => clearTimeout(t);
    }
  }, [pullSuccess]);

  const handleSelect = async (modelId: string) => {
    const previousModel = selectedModel;
    setSelectedModel(modelId);
    setCommandPaletteOpen(false);

    if (modelId !== previousModel) {
      const { setModelLoading, addLogEntry } = useAppStore.getState();
      setModelLoading(true);
      addLogEntry({ timestamp: Date.now(), level: 'info', category: 'model', message: t('logs.model.switching', { model: modelId }) });
      try {
        await preloadModel(modelId);
        addLogEntry({ timestamp: Date.now(), level: 'info', category: 'model', message: t('logs.model.loaded', { model: modelId }) });
      } catch (e: any) {
        addLogEntry({ timestamp: Date.now(), level: 'error', category: 'model', message: t('logs.model.loadFailed', { model: modelId, error: e.message }) });
      } finally {
        setModelLoading(false);
      }
    }
  };

  const refreshModels = async () => {
    try {
      const m = await fetchModels();
      setModels(m);
    } catch {}
  };

  const handlePull = async (modelId: string) => {
    setPulling(modelId);
    setPullError(null);
    try {
      await pullModel(modelId);
      setPullSuccess(modelId);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'model',
        message: t('logs.model.downloaded', { model: modelId }),
      });
      await refreshModels();
      setSelectedModel(modelId);
    } catch (e: any) {
      setPullError(e.message || t('common.downloadFailed'));
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'error', category: 'model',
        message: t('logs.model.downloadFailed', { model: modelId, error: e.message }),
      });
    } finally {
      setPulling(null);
    }
  };

  const handleDelete = async (modelId: string) => {
    setDeleting(modelId);
    try {
      await deleteModel(modelId);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'model',
        message: t('logs.model.deleted', { model: modelId }),
      });
      await refreshModels();
      if (selectedModel === modelId) {
        const remaining = models.filter((m) => m.id !== modelId);
        if (remaining.length > 0) setSelectedModel(remaining[0].id);
      }
    } catch {} finally {
      setDeleting(null);
    }
  };

  const handleCustomPull = async () => {
    const name = customModel.trim();
    if (!name) return;
    await handlePull(name);
    setCustomModel('');
  };

  const handleSaveKey = async (provider: CloudProvider, value: string) => {
    const keyValue = value.trim();
    setSavingKey(provider.envKey);
    setCloudKeyError(null);

    try {
      await saveCloudKey(provider.envKey, keyValue);
      setApiKeys((prev) => ({ ...prev, [provider.envKey]: '' }));
      await refreshCloudKeyStatus();
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'model',
        // Two whole sentences rather than an interpolated verb: "saved" and
        // "removed" do not agree the same way once the sentence is French.
        message: keyValue
          ? t('logs.model.apiKeySaved', { provider: provider.name })
          : t('logs.model.apiKeyRemoved', { provider: provider.name }),
      });
      await refreshModels();
    } catch (e: any) {
      setCloudKeyError(e?.message || t('models.saveKeyFailed', { provider: provider.name }));
    } finally {
      setSavingKey(null);
    }
  };

  const handleKeyBlur = (provider: CloudProvider) => {
    const draft = apiKeys[provider.envKey] || '';
    if (draft.trim()) void handleSaveKey(provider, draft);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setCommandPaletteOpen(false);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && tab === 'installed' && filtered.length > 0) {
      e.preventDefault();
      handleSelect((filtered[selectedIdx] as any).id);
    }
  };

  const TAB_LABELS: Record<Tab, string> = {
    installed: t('models.tab.installed', { count: models.length }),
    catalogue: t('common.download'),
    cloud: t('models.tab.cloud'),
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]"
      onClick={() => setCommandPaletteOpen(false)}
    >
      <div className="fixed inset-0" style={{ background: 'rgba(0,0,0,0.5)' }} />

      <div
        className="relative w-full max-w-lg rounded-xl overflow-hidden"
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-lg)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Tabs */}
        <div className="flex" style={{ borderBottom: '1px solid var(--color-border)' }}>
          {(['installed', 'catalogue', 'cloud'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="flex-1 px-3 py-2.5 text-xs font-medium transition-colors cursor-pointer"
              style={{
                color: tab === t ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
                borderBottom: tab === t ? '2px solid var(--color-accent)' : '2px solid transparent',
                background: 'transparent',
              }}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </div>

        {/* Search (not for cloud tab) */}
        {tab !== 'cloud' && (
          <div
            className="flex items-center gap-3 px-4 py-3"
            style={{ borderBottom: '1px solid var(--color-border)' }}
          >
            <Search size={18} style={{ color: 'var(--color-text-tertiary)' }} />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={tab === 'installed' ? t('models.searchInstalled') : t('models.searchCatalogue')}
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: 'var(--color-text)' }}
            />
            <button
              onClick={() => setCommandPaletteOpen(false)}
              className="p-1 rounded cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              <X size={16} />
            </button>
          </div>
        )}

        {/* Status messages */}
        {pullError && (
          <div className="px-4 py-2 text-xs" style={{ color: 'var(--color-error)', background: 'rgba(220,38,38,0.05)' }}>
            {pullError}
          </div>
        )}
        {pullSuccess && (
          <div className="px-4 py-2 text-xs flex items-center gap-1.5" style={{ color: 'var(--color-success)', background: 'color-mix(in srgb, var(--color-success) 5%, transparent)' }}>
            <Check size={12} /> {t('models.downloadSuccess', { model: pullSuccess })}
          </div>
        )}
        {tab === 'cloud' && cloudKeyError && (
          <div className="px-4 py-2 text-xs" style={{ color: 'var(--color-error)', background: 'rgba(220,38,38,0.05)' }}>
            {cloudKeyError}
          </div>
        )}

        {/* Results */}
        <div className="max-h-[400px] overflow-y-auto py-2">
          {tab === 'installed' ? (
            filtered.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                {models.length === 0
                  ? t('models.emptyInstalled')
                  : t('models.noMatches')}
              </div>
            ) : (
              (filtered as typeof models).map((model, idx) => {
                const isActive = model.id === selectedModel;
                const isSelected = idx === selectedIdx;
                const isDeleting = deleting === model.id;
                return (
                  <div
                    key={model.id}
                    className="flex items-center gap-3 w-full px-4 py-2.5 transition-colors"
                    style={{ background: isSelected ? 'var(--color-bg-secondary)' : 'transparent' }}
                    onMouseEnter={() => setSelectedIdx(idx)}
                  >
                    <button
                      onClick={() => handleSelect(model.id)}
                      className="flex items-center gap-3 flex-1 min-w-0 text-left cursor-pointer"
                      style={{ background: 'none', border: 'none', padding: 0 }}
                    >
                      <Cpu size={16} style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm truncate" style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-text)', fontWeight: isActive ? 500 : 400 }}>
                          {model.id}
                        </div>
                      </div>
                      {isActive && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}>
                          {t('common.active')}
                        </span>
                      )}
                    </button>
                    <button
                      onClick={() => handleDelete(model.id)}
                      disabled={isDeleting}
                      className="p-1 rounded transition-colors cursor-pointer"
                      style={{ color: 'var(--color-text-tertiary)', opacity: 0 }}
                      title={t('models.deleteModel')}
                      onMouseEnter={(e) => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.color = 'var(--color-error)'; }}
                      onMouseLeave={(e) => { e.currentTarget.style.opacity = '0'; e.currentTarget.style.color = 'var(--color-text-tertiary)'; }}
                    >
                      {isDeleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    </button>
                  </div>
                );
              })
            )
          ) : tab === 'catalogue' ? (
            <>
              {(filtered as typeof CATALOGUE_MODELS).map((model) => {
                const isPulling = pulling === model.id;
                const justInstalled = pullSuccess === model.id;
                return (
                  <div key={model.id} className="flex items-center gap-3 w-full px-4 py-2.5">
                    <Download size={16} style={{ color: 'var(--color-text-tertiary)' }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm truncate" style={{ color: 'var(--color-text)' }}>{model.id}</div>
                      <div className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>{modelLabel(model)} &middot; {model.size}</div>
                    </div>
                    <button
                      onClick={() => handlePull(model.id)}
                      disabled={isPulling || !!pulling}
                      className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium cursor-pointer"
                      style={{
                        background: justInstalled ? 'var(--color-accent-subtle)' : 'var(--color-accent)',
                        color: justInstalled ? 'var(--color-accent)' : 'var(--color-on-accent)',
                        opacity: (isPulling || (pulling && !isPulling)) ? 0.5 : 1,
                      }}
                    >
                      {isPulling ? <><Loader2 size={12} className="animate-spin" /> {t('common.downloading')}</> :
                       justInstalled ? <><Check size={12} /> {t('models.installed')}</> :
                       <><Download size={12} /> {t('common.download')}</>}
                    </button>
                  </div>
                );
              })}
              <div className="px-4 py-3 mt-1" style={{ borderTop: '1px solid var(--color-border)' }}>
                <div className="text-[11px] mb-2" style={{ color: 'var(--color-text-tertiary)' }}>{t('models.customPrompt')}</div>
                <div className="flex gap-2">
                  <input
                    type="text" value={customModel}
                    onChange={(e) => setCustomModel(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleCustomPull(); } }}
                    placeholder={t('models.customPlaceholder')}
                    className="flex-1 text-sm px-3 py-1.5 rounded-lg outline-none"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
                  />
                  <button
                    onClick={handleCustomPull} disabled={!customModel.trim() || !!pulling}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer"
                    style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', opacity: (!customModel.trim() || pulling) ? 0.5 : 1 }}
                  >
                    <Download size={12} /> {t('models.pull')}
                  </button>
                </div>
              </div>
            </>
          ) : (
            /* ── Cloud Models tab ── */
            <div className="px-4 py-2">
              <div className="text-[11px] mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
                {desktopKeyStorage
                  ? t('models.cloudKeysDesktop')
                  : t('models.cloudKeysServer')}
              </div>

              {CLOUD_PROVIDERS.map((provider) => {
                const key = apiKeys[provider.envKey] || '';
                const hasSavedKey = !!cloudKeyStatus[provider.envKey];
                const hasKey = hasSavedKey || !!key.trim();
                const isVisible = showKeys[provider.envKey];
                const isSaving = savingKey === provider.envKey;

                return (
                  <div key={provider.name} className="mb-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Cloud size={14} style={{ color: hasKey ? 'var(--color-success)' : 'var(--color-text-tertiary)' }} />
                      <span className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>{provider.name}</span>
                      {hasKey && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: 'color-mix(in srgb, var(--color-success) 10%, transparent)', color: 'var(--color-success)' }}>
                          {t('common.connected')}
                        </span>
                      )}
                    </div>

                    {/* API key input */}
                    <div className="flex gap-1.5 mb-2">
                      <div className="flex-1 flex items-center rounded-lg" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                        <Key size={12} className="ml-2.5 shrink-0" style={{ color: 'var(--color-text-tertiary)' }} />
                        <input
                          type={isVisible ? 'text' : 'password'}
                          value={key}
                          onChange={(e) => setApiKeys((prev) => ({ ...prev, [provider.envKey]: e.target.value }))}
                          onBlur={() => handleKeyBlur(provider)}
                          placeholder={hasSavedKey ? t('models.keyInSecureStorage') : provider.envKey}
                          disabled={!desktopKeyStorage || isSaving}
                          className="flex-1 text-xs px-2 py-1.5 bg-transparent outline-none font-mono"
                          style={{ color: 'var(--color-text)' }}
                        />
                        <button
                          onClick={() => setShowKeys((prev) => ({ ...prev, [provider.envKey]: !prev[provider.envKey] }))}
                          className="px-2 cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}
                        >
                          {isVisible ? <EyeOff size={12} /> : <Eye size={12} />}
                        </button>
                      </div>
                      {hasSavedKey && (
                        <button
                          onClick={() => handleSaveKey(provider, '')}
                          disabled={isSaving}
                          className="px-2 py-1 rounded-lg text-[10px] cursor-pointer"
                          style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)', opacity: isSaving ? 0.5 : 1 }}
                        >
                          {isSaving ? t('common.saving') : t('common.remove')}
                        </button>
                      )}
                    </div>

                    {/* Models for this provider (only show if key is set) */}
                    {hasKey && (
                      <div className="ml-5 flex flex-col gap-1">
                        {provider.models.map((model) => {
                          const isActive = model.id === selectedModel;
                          return (
                            <button
                              key={model.id}
                              onClick={() => handleSelect(model.id)}
                              className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left cursor-pointer transition-colors"
                              style={{ background: isActive ? 'var(--color-accent-subtle)' : 'transparent' }}
                              onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--color-bg-secondary)'; }}
                              onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                            >
                              <Cloud size={12} style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                              <div className="flex-1 min-w-0">
                                <div className="text-xs truncate" style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-text)', fontWeight: isActive ? 500 : 400 }}>
                                  {model.id}
                                </div>
                                <div className="text-[10px] truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                                  {modelLabel(model)}
                                </div>
                              </div>
                              {isActive && (
                                <span className="text-[9px] px-1.5 py-0.5 rounded-full shrink-0" style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}>
                                  {t('common.active')}
                                </span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          className="flex items-center gap-4 px-4 py-2 text-[11px]"
          style={{ borderTop: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}
        >
          {tab === 'installed' ? (
            <>
              <span><kbd className="font-mono">↑↓</kbd> {t('common.navigate')}</span>
              <span><kbd className="font-mono">{t('common.key.enter')}</kbd> {t('common.select')}</span>
              <span><kbd className="font-mono">{t('common.key.esc')}</kbd> {t('common.close')}</span>
            </>
          ) : tab === 'catalogue' ? (
            <span>{t('models.catalogueSource')}</span>
          ) : (
            <span>{t('models.keysStayLocal')}</span>
          )}
        </div>
      </div>
    </div>
  );
}
