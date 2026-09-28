import { useState, useEffect, useCallback } from 'react';
import {
  Palette,
  Globe,
  Cpu,
  Database,
  Info,
  Check,
  Sun,
  Moon,
  Monitor,
  TerminalSquare,
  Download,
  Upload,
  Trash2,
  Mic,
  Key,
  Search,
  Brain,
  RefreshCw,
  Minus,
  Plus,
} from 'lucide-react';
import {
  useAppStore,
  TERMINAL_SKINS,
  loadConversations,
  saveConversations,
  type ThemeMode,
  type TerminalSkin,
} from '../lib/store';
import { normaliserImport, programmerSuppressionsServeur } from '../lib/convSync';
import { useConfirm } from '../components/ConfirmDialog';
import {
  checkHealth,
  fetchSpeechHealth,
  getMemoryStats,
  getInferenceSource,
  setInferenceSource,
  getCloudKeyStatus,
  saveCloudKey,
  fetchToolCredentialStatus,
  saveToolCredentials,
  deleteToolCredential,
  isTauri,
  fetchModels,
  fetchServerConfig,
  setServerConfigKey,
  type InferenceSource,
  type ServerConfigSnippet,
} from '../lib/api';
import { isAutoUpdateDisabled, setAutoUpdateDisabled } from '../components/Desktop/miseAJour';
import { ZOOM_MAX, ZOOM_MIN, normaliserZoom, zoomEnPourcent, zoomSuivant } from '../lib/zoom';
import { loadDictationStats, type DictationStats } from '../lib/dictationStats';
import { fetchVoiceLiveHealth, type VoiceLiveHealth } from '../lib/voiceLive';
import { annonceDEnregistrement, enregistrerHorsBureau } from '../lib/enregistrerFichier';
import { estMobile } from '../lib/natif';
import {
  choixDeSourceAffiche,
  etatDeLaCle,
  indicationCle,
  sourceEnregistrable,
  type LectureSource,
} from '../lib/reglagesHorsBureau';
import { toast } from 'sonner';
import { useTranslation } from '../i18n/useTranslation';
import { LOCALES, LOCALE_NAMES, type Locale } from '../i18n/locale';
import { SectionCompte } from '../features/compte/SectionCompte';
import { ProfilVocal } from '../features/voix/ProfilVocal';
import { serviParLeTailnet } from '../lib/tailnet';
import { MesuresFluidite } from '../components/MesuresFluidite';

const CLOUD_KEY_STATUS_CHANGED = 'diapason-cloud-key-status-changed';
// Noms de produit, séparés des identifiants persistants. Un ancien serveur
// ne doit pas réintroduire les timbres retirés (27/09/2026).
const NOMS_VOIX_LOCALES = new Map([['qwen3-b', 'Orion']]);

function OllamaModelList() {
  const { t } = useTranslation();
  const [models, setModels] = useState<Array<{ name: string; size?: number }>>([]);
  const [illisibles, setIllisibles] = useState(false);
  useEffect(() => {
    // 26/09/2026 : `localhost:11434` était lu DEPUIS LA PAGE. Dans le
    // téléphone, localhost est le téléphone : « Aucun modèle chargé » pour un
    // Mac qui en a plusieurs. Hors de l'app de bureau, la liste vient du
    // serveur du Mac (/v1/models), et un échec se dit.
    if (!isTauri()) {
      fetchModels()
        .then((liste) => setModels(liste.map((m) => ({ name: m.id }))))
        .catch(() => setIllisibles(true));
      return;
    }
    fetch('http://localhost:11434/api/tags')
      .then(r => r.json())
      .then(data => setModels((data.models || []).map((m: any) => ({ name: m.name, size: m.size }))))
      .catch(() => setModels([]));
  }, []);
  if (illisibles) return <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{t('settings.models.illisibles')}</span>;
  if (models.length === 0) return <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{t('settings.models.none')}</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {models.map(m => (
        <span key={m.name} className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px]"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-success)', display: 'inline-block' }} />
          {m.name}{m.size ? ` (${(m.size / 1e9).toFixed(1)} GB)` : ''}
        </span>
      ))}
    </div>
  );
}

function ApiKeyInput({
  keyName,
  placeholder,
  toolName,
}: {
  keyName: string;
  placeholder: string;
  toolName?: string;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState('');
  const [saved, setSaved] = useState(false);
  const [lecture, setLecture] = useState<Parameters<typeof etatDeLaCle>[0]>(null);
  const [error, setError] = useState('');
  const desktopKeyStorage = isTauri();
  const serverToolStorage = !desktopKeyStorage && !!toolName;
  const canManage = desktopKeyStorage || serverToolStorage;
  const etat = etatDeLaCle(lecture, keyName);
  const hasKey = etat === 'presente';
  const indication = indicationCle({ bureau: desktopKeyStorage, outilServeur: serverToolStorage, etat });

  // 26/09/2026 : hors de l'app de bureau, `canManage` faux donnait
  // « absente » sans rien lire, et un champ désactivé sans explication. L'état
  // se lit partout (le serveur le dit hors de Tauri) ; seule l'écriture
  // reste à l'app de bureau.
  const refresh = useCallback(async () => {
    try {
      const status = serverToolStorage
        ? await fetchToolCredentialStatus(toolName!)
        : await getCloudKeyStatus();
      setLecture({ statut: status });
    } catch {
      setLecture({ echec: true });
    }
  }, [serverToolStorage, toolName]);

  useEffect(() => {
    void refresh();
    window.addEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
    return () => window.removeEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
  }, [refresh]);

  const save = async (v: string) => {
    const next = v.trim();
    if (!next) return;
    setError('');
    try {
      if (desktopKeyStorage) {
        await saveCloudKey(keyName, next);
      } else if (toolName) {
        await saveToolCredentials(toolName, { [keyName]: next });
      } else {
        return;
      }
      setValue('');
      await refresh();
      setSaved(true);
      window.dispatchEvent(new Event(CLOUD_KEY_STATUS_CHANGED));
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e?.message || t('settings.apiKeys.saveError'));
    }
  };

  const remove = async () => {
    setError('');
    try {
      if (desktopKeyStorage) {
        await saveCloudKey(keyName, '');
      } else if (toolName) {
        await deleteToolCredential(toolName, keyName);
      } else {
        return;
      }
      setValue('');
      await refresh();
      setSaved(true);
      window.dispatchEvent(new Event(CLOUD_KEY_STATUS_CHANGED));
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e?.message || t('settings.apiKeys.removeError'));
    }
  };

  return (
    <div className="flex items-center gap-2">
      <input
        type="password"
        value={value}
        onChange={e => setValue(e.target.value)}
        onBlur={() => { if (value.trim()) void save(value); }}
        placeholder={indication ? t(`settings.apiKeys.${indication}`) : placeholder}
        title={indication && !canManage ? t(`settings.apiKeys.${indication}`) : undefined}
        disabled={!canManage}
        className="w-48 px-2 py-1 rounded text-xs"
        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
      {hasKey && canManage && (
        <button
          onClick={() => void remove()}
          className="px-2 py-1 rounded text-[10px] cursor-pointer"
          style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}
        >
          {t('common.remove')}
        </button>
      )}
      {saved && <span className="text-[10px]" style={{ color: 'var(--color-success)' }}>{t('common.saved')}</span>}
      {error && <span className="text-[10px]" style={{ color: 'var(--color-error)' }}>{error}</span>}
    </div>
  );
}

function CloudProviderStatus({ label, keyName }: { label: string; keyName: string }) {
  const { t } = useTranslation();
  const [lecture, setLecture] = useState<Parameters<typeof etatDeLaCle>[0]>(null);
  const etat = etatDeLaCle(lecture, keyName);

  // 26/09/2026 : hors de l'app de bureau, la pastille restait grise sans
  // rien lire, pendant que la palette disait la clé présente.
  const refresh = useCallback(async () => {
    try {
      setLecture({ statut: await getCloudKeyStatus() });
    } catch {
      setLecture({ echec: true });
    }
  }, []);

  useEffect(() => {
    void refresh();
    window.addEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
    return () => window.removeEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
  }, [refresh]);

  return (
    <span
      className="flex items-center gap-1 text-xs"
      style={{ color: 'var(--color-text-secondary)' }}
      title={etat === 'illisible' ? t('settings.apiKeys.illisible') : undefined}
    >
      <span style={{
        width: 6, height: 6, borderRadius: '50%', display: 'inline-block', boxSizing: 'border-box',
        background: etat === 'presente' ? 'var(--color-success)' : etat === 'illisible' ? 'transparent' : 'var(--color-text-tertiary)',
        border: etat === 'illisible' ? '1px solid var(--color-text-tertiary)' : 'none',
      }} />
      {label}
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-5"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <h3 className="text-sm font-semibold mb-4" style={{ color: 'var(--color-text)' }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

// 26/09/2026 : à 375 px, l'étiquette et son contrôle se disputaient une
// seule ligne — « URL de l'API » tombait à 45 px de large, un mot par ligne,
// et le sélecteur de thème (359 px) poussait la page de 99 px vers la droite.
// Sous sm, la rangée passe à la ligne quand les deux ne tiennent pas côte à
// côte (12rem pour l'étiquette) ; au-delà, elle reste celle du bureau, où la
// liste des modèles tient à droite de son étiquette.
function SettingRow({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-3 max-sm:flex-wrap max-sm:gap-x-4 max-sm:gap-y-2" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
      <div className="max-sm:min-w-0 max-sm:flex-[1_1_12rem]">
        <div className="text-sm" style={{ color: 'var(--color-text)' }}>{label}</div>
        {description && (
          <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{description}</div>
        )}
      </div>
      <div className="max-sm:min-w-0 max-sm:max-w-full">{children}</div>
    </div>
  );
}

// Only the parts a hook cannot produce. The labels are translated at render,
// inside the component, because `t` cannot be called at module scope.
const themeOptions: { value: ThemeMode; icon: typeof Sun }[] = [
  { value: 'light', icon: Sun },
  { value: 'dark', icon: Moon },
  { value: 'system', icon: Monitor },
  { value: 'terminal', icon: TerminalSquare },
];

/**
 * Screen names are proper nouns, so they are not translated. Each carries the
 * two colours that identify it at a glance — a swatch says more about a screen
 * than its name does.
 */
const TERMINAL_SKIN_SWATCHES: Record<TerminalSkin, { name: string; bg: string; fg: string }> = {
  phosphor: { name: 'Phosphore', bg: '#030703', fg: '#7af046' },
  ardechine: { name: 'Ardéchine', bg: '#beb3a1', fg: '#14120e' },
  oxblood: { name: 'Oxblood', bg: '#150a09', fg: '#cf5346' },
  sage: { name: 'Sauge', bg: '#000000', fg: '#90a481' },
};

export function SettingsPage() {
  const { t, locale, setLocale } = useTranslation();
  const confirm = useConfirm();
  const themeLabels: Record<ThemeMode, string> = {
    light: t('settings.theme.light'),
    dark: t('settings.theme.dark'),
    system: t('settings.theme.system'),
    terminal: t('settings.theme.terminal'),
  };
  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);
  const conversations = useAppStore((s) => s.conversations);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [speechBackendAvailable, setSpeechBackendAvailable] = useState<boolean | null>(null);
  const [voiceLiveAvailable, setVoiceLiveAvailable] = useState<boolean | null>(null);
  const [voiceProvider, setVoiceProvider] = useState('local');
  const [santeVoix, setSanteVoix] = useState<VoiceLiveHealth | null>(null);
  const [enregistrementVoix, setEnregistrementVoix] = useState(false);
  const voixInstallees = (santeVoix?.voices ?? []).filter((id) => NOMS_VOIX_LOCALES.has(id));
  // Held as a shape rather than a finished sentence: the sentence is built at
  // render, so it follows a language change instead of freezing the wording
  // that was current when the health check answered.
  const [voiceLiveDetail, setVoiceLiveDetail] = useState<
    | { kind: 'ready'; providers: string }
    | { kind: 'needsKey' }
    | { kind: 'unavailable' }
    | null
  >(null);
  const [dictationStats, setDictationStats] = useState<DictationStats>(() => loadDictationStats());
  const [saved, setSaved] = useState(false);
  const [serverCfg, setServerCfg] = useState<ServerConfigSnippet | null>(null);
  const [serverCfgError, setServerCfgError] = useState('');

  const refreshServerCfg = useCallback(async () => {
    try {
      const cfg = await fetchServerConfig();
      setServerCfg(cfg);
      setServerCfgError('');
    } catch (e: any) {
      setServerCfgError(e?.message || t('settings.desktop.configUnavailable'));
    }
  }, [t]);

  useEffect(() => {
    void refreshServerCfg();
  }, [refreshServerCfg]);

  const [autoUpdateEnabled, setAutoUpdateEnabled] = useState(() => !isAutoUpdateDisabled());
  const [updateCheckState, setUpdateCheckState] = useState<'idle' | 'checking' | 'available' | 'latest'>('idle');

  const handleAutoUpdateToggle = useCallback((enabled: boolean) => {
    setAutoUpdateEnabled(enabled);
    setAutoUpdateDisabled(!enabled);
  }, []);

  const handleCheckNow = useCallback(async () => {
    if (!(window as any).__TAURI_INTERNALS__) return;
    setUpdateCheckState('checking');
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const update = await check();
      setUpdateCheckState(update ? 'available' : 'latest');
      setTimeout(() => setUpdateCheckState('idle'), 4000);
    } catch {
      setUpdateCheckState('idle');
    }
  }, []);

  const [memoryStats, setMemoryStats] = useState<{ entries: number; backend: string } | null>(null);
  const [memoryEnabled, setMemoryEnabled] = useState(() => {
    try { return localStorage.getItem('diapason-memory-enabled') !== 'false'; } catch { return true; }
  });
  const [memoryBackend, setMemoryBackend] = useState(() => {
    try { return localStorage.getItem('diapason-memory-backend') || 'sqlite'; } catch { return 'sqlite'; }
  });
  const [memoryTopK, setMemoryTopK] = useState(() => {
    try { return parseInt(localStorage.getItem('diapason-memory-top-k') || '5'); } catch { return 5; }
  });
  const [memoryMinScore, setMemoryMinScore] = useState(() => {
    try { return parseFloat(localStorage.getItem('diapason-memory-min-score') || '0.1'); } catch { return 0.1; }
  });
  const [memoryMaxTokens, setMemoryMaxTokens] = useState(() => {
    try { return parseInt(localStorage.getItem('diapason-memory-max-tokens') || '2048'); } catch { return 2048; }
  });

  const [srcKind, setSrcKind] = useState<InferenceSource['kind']>('ollama');
  const [customHost, setCustomHost] = useState('http://localhost:1234/v1');
  const [customModel, setCustomModel] = useState('');
  const [customEngine, setCustomEngine] = useState('lmstudio');
  const [customKey, setCustomKey] = useState('');
  const [srcMsg, setSrcMsg] = useState('');
  const [lectureSource, setLectureSource] = useState<LectureSource>({ etat: 'attente' });
  const choixSource = choixDeSourceAffiche(lectureSource, srcKind);
  const sourceModifiable = sourceEnregistrable(lectureSource);

  useEffect(() => {
    getInferenceSource().then((s) => {
      setSrcKind(s.kind);
      if (s.host) setCustomHost(s.host);
      if (s.model) setCustomModel(s.model);
      if (s.engine) setCustomEngine(s.engine);
      setLectureSource({ etat: 'lue', source: s });
      if (s.hostIllisible) setSrcMsg(t('settings.inference.hostIllisible'));
      // 26/09/2026 : un échec de lecture était avalé, et le sélecteur restait
      // sur « Ollama » — sa valeur initiale, pas celle du Mac. Le message
      // seul (f8ea8bf) laissait encore « Ollama intégré » affiché au-dessus,
      // et « Enregistrer » actif : le sélecteur dit désormais « inconnue ».
    }).catch((e: any) => {
      const message = e?.message ?? t('common.error');
      setLectureSource({ etat: 'echec', message });
      setSrcMsg(message);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const saveSource = useCallback(async () => {
    try {
      if (srcKind === 'custom') {
        await setInferenceSource({ kind: 'custom', host: customHost, model: customModel, engine: customEngine, apiKey: customKey || undefined });
      } else {
        await setInferenceSource({ kind: 'ollama' });
      }
      setSrcMsg(t('settings.inference.saved'));
    } catch (e: any) {
      setSrcMsg(e?.message ?? t('common.saveFailed'));
    }
  }, [srcKind, customHost, customModel, customEngine, customKey, t]);

  useEffect(() => {
    checkHealth().then(setHealthy);
    fetchSpeechHealth()
      .then((h) => setSpeechBackendAvailable(h.available))
      .catch(() => setSpeechBackendAvailable(false));
    fetchVoiceLiveHealth()
      .then((h) => {
        const p = (h as { default_provider?: string }).default_provider;
        if (p === 'local' || p === 'gemini' || p === 'openai') setVoiceProvider(p);
        return h;
      })
      .then((h) => {
        setSanteVoix(h);
        setVoiceLiveAvailable(h.available);
        const parts = Object.entries(h.providers || {})
          .filter(([, v]) => v.configured)
          .map(([k]) => k);
        setVoiceLiveDetail(
          h.available
            ? { kind: 'ready', providers: parts.join(', ') || h.default_provider }
            : { kind: 'needsKey' },
        );
      })
      .catch(() => {
        setVoiceLiveAvailable(false);
        setVoiceLiveDetail({ kind: 'unavailable' });
      });
    setDictationStats(loadDictationStats());
    getMemoryStats()
      .then(setMemoryStats)
      .catch(() => setMemoryStats(null));
  }, []);

  const showSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const choisirVoix = async (id: string) => {
    if (enregistrementVoix || !voixInstallees.includes(id)) return;
    setEnregistrementVoix(true);
    try {
      await setServerConfigKey('speech.realtime.voice', id);
      const sante = await fetchVoiceLiveHealth();
      setSanteVoix(sante);
      if (sante.defaultVoice !== id) throw new Error('voice-not-saved');
      showSaved();
    } catch {
      toast.error(t('settings.speech.voiceSaveError'));
    } finally {
      setEnregistrementVoix(false);
    }
  };

  const patchServer = useCallback(
    async (key: string, value: unknown) => {
      try {
        await setServerConfigKey(key, value);
        await refreshServerCfg();
        setSaved(true);
        setTimeout(() => setSaved(false), 1500);
      } catch (e: any) {
        setServerCfgError(e?.message || t('common.saveFailed'));
      }
    },
    [refreshServerCfg, t],
  );

  // 26/09/2026 : l'URL blob: était relâchée juste après le clic (Safari
  // annule alors le téléchargement) et le clic ne fait rien dans la WebView
  // d'Android. Le téléphone passe par sa coquille ; un échec se dit.
  const handleExport = async () => {
    const data = JSON.stringify(loadConversations());
    const blob = new Blob([data], { type: 'application/json' });
    try {
      const nom = await enregistrerHorsBureau(
        blob,
        `diapason-export-${new Date().toISOString().slice(0, 10)}.json`,
      );
      if (annonceDEnregistrement(nom)) showSaved();
    } catch (e: any) {
      toast.error(e?.message || t('common.saveFailed'));
    }
  };

  const handleImport = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        try {
          // Normaliser d'abord : une sauvegarde sans `conversations` ou aux
          // champs mal typés plantait le store à chaque tick et se faisait
          // refuser par le serveur pour de bon (16 sept. 2026). Puis passer
          // par saveConversations, pas par un setItem direct : c'est elle
          // qui émet l'événement de modification, donc c'est elle qui fait
          // pousser l'import vers le serveur — un setItem nu laissait
          // l'import invisible aux autres fenêtres.
          const propre = normaliserImport(JSON.parse(ev.target?.result as string));
          if (propre) {
            saveConversations(propre);
            useAppStore.getState().loadConversations();
            useAppStore.getState().loadMessages(propre.activeId);
            showSaved();
          }
        } catch {}
      };
      reader.readAsText(file);
    };
    input.click();
  };

  const handleClear = async () => {
    const confirmed = await confirm({
      title: t('settings.data.clearDescription'),
      description: t('common.confirmAgain'),
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    // Poser d'abord les pierres tombales côté serveur : effacer seulement le
    // localStorage laisserait la copie serveur intacte, et tout l'historique
    // « supprimé » ressusciterait au tirage suivant — un mensonge (§100).
    programmerSuppressionsServeur(Object.keys(loadConversations().conversations));
    saveConversations({ version: 1, conversations: {}, activeId: null });
    useAppStore.getState().loadMessages(null);
    useAppStore.getState().loadConversations();
    showSaved();
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <header className="mb-6">
          <div className="flex items-center justify-between gap-3">
            <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              {t('nav.settings')}
            </h1>
            {saved && (
              <span className="flex items-center gap-1 text-xs px-2 py-1 rounded-full" style={{
                background: 'var(--color-accent-subtle)',
                color: 'var(--color-success)',
              }}>
                <Check size={12} /> {t('common.saved')}
              </span>
            )}
          </div>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            {t('settings.subtitle')}
          </p>
        </header>

        <div className="flex flex-col gap-4">
          {/* Appearance */}
          <Section title={t('settings.appearance.title')}>
            <SettingRow
              label={t('settings.language.label')}
              description={t('settings.language.help')}
            >
              <select
                value={locale}
                onChange={(e) => {
                  setLocale(e.target.value as Locale);
                  showSaved();
                }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                {LOCALES.map((code) => (
                  // Each language is named in itself — someone stuck in a
                  // language they cannot read still recognises "Français".
                  <option key={code} value={code}>
                    {LOCALE_NAMES[code]}
                  </option>
                ))}
              </select>
            </SettingRow>
            <SettingRow label={t('settings.theme.label')} description={t('settings.theme.description')}>
              <div className="flex flex-wrap gap-1 p-0.5 rounded-lg" style={{ background: 'var(--color-bg-secondary)' }}>
                {themeOptions.map((opt) => {
                  const isActive = settings.theme === opt.value;
                  return (
                    <button
                      key={opt.value}
                      onClick={() => { updateSettings({ theme: opt.value }); showSaved(); }}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                      style={{
                        background: isActive ? 'var(--color-surface)' : 'transparent',
                        color: isActive ? 'var(--color-text)' : 'var(--color-text-tertiary)',
                        boxShadow: isActive ? 'var(--shadow-sm)' : 'none',
                      }}
                    >
                      <opt.icon size={14} />
                      {themeLabels[opt.value]}
                    </button>
                  );
                })}
              </div>
            </SettingRow>
            {settings.theme === 'terminal' && (
              <SettingRow
                label={t('settings.terminalSkin.label')}
                description={t('settings.terminalSkin.description')}
              >
                <div className="flex flex-wrap gap-1 p-0.5 rounded-lg" style={{ background: 'var(--color-bg-secondary)' }}>
                  {TERMINAL_SKINS.map((skin) => {
                    const isActive = (settings.terminalSkin ?? 'phosphor') === skin;
                    const swatch = TERMINAL_SKIN_SWATCHES[skin];
                    return (
                      <button
                        key={skin}
                        onClick={() => { updateSettings({ terminalSkin: skin }); showSaved(); }}
                        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                        style={{
                          background: isActive ? 'var(--color-surface)' : 'transparent',
                          color: isActive ? 'var(--color-text)' : 'var(--color-text-tertiary)',
                          boxShadow: isActive ? 'var(--shadow-sm)' : 'none',
                        }}
                      >
                        <span
                          aria-hidden="true"
                          className="flex items-center justify-center"
                          style={{
                            width: 16,
                            height: 16,
                            background: swatch.bg,
                            color: swatch.fg,
                            border: '1px solid var(--color-border)',
                            fontSize: 9,
                            lineHeight: 1,
                            fontFamily: 'var(--font-hud)',
                          }}
                        >
                          A
                        </span>
                        {swatch.name}
                      </button>
                    );
                  })}
                </div>
              </SettingRow>
            )}
            <SettingRow label={t('settings.fontSize.label')}>
              <select
                value={settings.fontSize}
                onChange={(e) => { updateSettings({ fontSize: e.target.value as any }); showSaved(); }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="small">{t('settings.fontSize.small')}</option>
                <option value="default">{t('settings.fontSize.default')}</option>
                <option value="large">{t('settings.fontSize.large')}</option>
              </select>
            </SettingRow>
            {/* Au téléphone seulement : la main qui tient la roue (26/09/2026,
                lot 3). Le bureau et le mini-panneau n'ont pas de roue. */}
            {estMobile && (
              <SettingRow label={t('settings.roue.gauche')} description={t('settings.roue.gaucheAide')}>
                <label className="inline-flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings.roueAGauche}
                    onChange={(e) => { updateSettings({ roueAGauche: e.target.checked }); showSaved(); }}
                    className="w-4 h-4 cursor-pointer"
                    style={{ accentColor: 'var(--color-accent)' }}
                  />
                  <span className="sr-only">{t('settings.roue.gauche')}</span>
                </label>
              </SettingRow>
            )}
            {/* Le zoom agrandit TOUT, pixels compris — la taille du texte
                ci-dessus ne touche que les unités relatives. Réservé à l'app
                de bureau : un navigateur a déjà le sien (⌘ +). */}
            {isTauri() && (
              <SettingRow label={t('settings.zoom.label')} description={t('settings.zoom.hint')}>
                <div className="flex items-center gap-1">
                  {(['moins', 'plus'] as const).map((sens, i) => {
                    const zoom = normaliserZoom(settings.zoom);
                    const bloque = sens === 'moins' ? zoom <= ZOOM_MIN : zoom >= ZOOM_MAX;
                    const bouton = (
                      <button
                        key={sens}
                        type="button"
                        onClick={() => { updateSettings({ zoom: zoomSuivant(zoom, sens) }); showSaved(); }}
                        disabled={bloque}
                        aria-label={sens === 'moins' ? t('settings.zoom.out') : t('settings.zoom.in')}
                        className="w-8 h-8 flex items-center justify-center rounded-lg cursor-pointer disabled:opacity-40 disabled:cursor-default"
                        style={{
                          background: 'var(--color-bg-secondary)',
                          color: 'var(--color-text)',
                          border: '1px solid var(--color-border)',
                        }}
                      >
                        {sens === 'moins' ? <Minus size={14} /> : <Plus size={14} />}
                      </button>
                    );
                    return i === 0 ? (
                      [bouton, (
                        <span
                          key="valeur"
                          className="w-14 text-center text-sm tabular-nums"
                          style={{ color: 'var(--color-text)' }}
                        >
                          {zoomEnPourcent(zoom)}
                        </span>
                      )]
                    ) : bouton;
                  })}
                </div>
              </SettingRow>
            )}
          </Section>

          {/* Connection */}
          <Section title={t('settings.connection.title')}>
            <SettingRow
              label={t('settings.connection.serverStatus')}
              description={serverInfo ? `${serverInfo.engine} / ${serverInfo.model}` : t('settings.connection.notConnected')}
            >
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: healthy === true ? 'var(--color-success)' : healthy === false ? 'var(--color-error)' : 'var(--color-text-tertiary)' }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {healthy === true
                    ? t('settings.connection.connected')
                    : healthy === false
                      ? t('settings.connection.disconnected')
                      : t('common.checking')}
                </span>
              </div>
            </SettingRow>
            {/* 26/09/2026 : au téléphone, une URL saisie ici détournait tous
                les appels (getBase lit diapason-settings.apiUrl), et la
                session est un cookie que ce champ ne remplace pas. */}
            {!estMobile && (<>
            <SettingRow label={t('settings.connection.apiUrl')} description={t('settings.connection.apiUrlDescription')}>
              <input
                type="text"
                value={settings.apiUrl}
                onChange={(e) => { updateSettings({ apiUrl: e.target.value }); showSaved(); }}
                placeholder="http://localhost:8000"
                className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </SettingRow>
            <SettingRow label={t('settings.connection.apiKey')} description={t('settings.connection.apiKeyDescription')}>
              <input
                type="password"
                value={settings.apiKey}
                onChange={(e) => { updateSettings({ apiKey: e.target.value }); showSaved(); }}
                placeholder="DIAPASON_API_KEY"
                autoComplete="off"
                className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </SettingRow>
            </>)}
          </Section>

          {/* Au téléphone seulement : le relevé de fluidité de CETTE WebView,
              pour lire les vrais chiffres du téléphone (26/09/2026). */}
          {estMobile && (
            <Section title={t('settings.fluidite.title')}>
              <MesuresFluidite />
            </Section>
          )}

          {/* Compte et chiffrement — après Connexion (compte-chiffre.md §3.11). */}
          <SectionCompte />

          {/* Inference source */}
          <Section title={t('settings.inference.title')}>
            <SettingRow label={t('settings.inference.sourceLabel')} description={t('settings.inference.sourceDescription')}>
              <select
                value={choixSource}
                disabled={!sourceModifiable}
                onChange={(e) => { setSrcKind(e.target.value as InferenceSource['kind']); setSrcMsg(''); }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
              >
                {choixSource === 'inconnue' && (
                  <option value="inconnue" disabled>{t('settings.inference.inconnue')}</option>
                )}
                <option value="ollama">{t('settings.inference.ollama')}</option>
                <option value="custom">{t('settings.inference.custom')}</option>
              </select>
            </SettingRow>
            {choixSource === 'custom' && (
              <>
                <SettingRow label={t('settings.inference.serverUrl')} description={t('settings.inference.serverUrlDescription')}>
                  <input type="text" value={customHost} onChange={(e) => { setCustomHost(e.target.value); setSrcMsg(''); }} placeholder="http://localhost:1234/v1"
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
                <SettingRow label={t('settings.inference.model')} description={t('settings.inference.modelDescription')}>
                  <input type="text" value={customModel} onChange={(e) => { setCustomModel(e.target.value); setSrcMsg(''); }} placeholder="qwen2.5-7b-instruct"
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
                <SettingRow label={t('settings.inference.serverType')} description={t('settings.inference.serverTypeDescription')}>
                  <select value={customEngine} onChange={(e) => { setCustomEngine(e.target.value); setSrcMsg(''); }}
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
                    <option value="lmstudio">LM Studio</option>
                    <option value="vllm">vLLM</option>
                    <option value="sglang">SGLang</option>
                    <option value="llamacpp">llama.cpp</option>
                    <option value="mlx">MLX</option>
                  </select>
                </SettingRow>
                <SettingRow label={t('settings.inference.apiKeyOptional')} description={t('settings.inference.apiKeyDescription')}>
                  <input type="password" value={customKey} onChange={(e) => { setCustomKey(e.target.value); setSrcMsg(''); }} placeholder={t('settings.inference.apiKeyPlaceholder')}
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
              </>
            )}
            <SettingRow label="" description={srcMsg}>
              {/* 26/09/2026 : `--color-text` sur `--color-accent` — en Ardéchine,
                  les deux valent rgb(20,18,14) : un pavé noir, contraste 1,00.
                  Le couple des boutons pleins (« Nouvel agent ») est lisible
                  dans chaque thème. */}
              <button onClick={saveSource}
                disabled={!sourceModifiable}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', border: '1px solid transparent' }}>
                {t('settings.inference.save')}
              </button>
            </SettingRow>
          </Section>

          {/* Models */}
          <Section title={t('settings.models.title')}>
            <SettingRow label={t('settings.models.localLabel')} description={t('settings.models.localDescription')}>
              <OllamaModelList />
            </SettingRow>
            <div className="text-xs mt-2 px-1" style={{ color: 'var(--color-text-tertiary)' }}>
              {t('settings.models.pullHintBefore')} <code className="px-1 py-0.5 rounded text-[11px]" style={{ background: 'var(--color-bg-tertiary)' }}>ollama pull &lt;model-name&gt;</code> {t('settings.models.pullHintAfter')}
            </div>
            <SettingRow label={t('settings.models.cloudLabel')} description={t('settings.models.cloudDescription')}>
              <div className="flex flex-wrap gap-3">
                <CloudProviderStatus label="OpenAI" keyName="OPENAI_API_KEY" />
                <CloudProviderStatus label="Anthropic" keyName="ANTHROPIC_API_KEY" />
                <CloudProviderStatus label="Google" keyName="GEMINI_API_KEY" />
                <CloudProviderStatus label="OpenRouter" keyName="OPENROUTER_API_KEY" />
              </div>
            </SettingRow>
          </Section>

          {/* API Keys */}
          <Section title={t('settings.apiKeys.title')}>
            <SettingRow label="OpenAI" description="GPT-4, GPT-3.5, etc.">
              <ApiKeyInput keyName="OPENAI_API_KEY" placeholder="sk-..." />
            </SettingRow>
            <SettingRow label="Anthropic" description={t('settings.apiKeys.anthropicDescription')}>
              <ApiKeyInput keyName="ANTHROPIC_API_KEY" placeholder="sk-ant-..." />
            </SettingRow>
            <SettingRow label="Google" description={t('settings.apiKeys.googleDescription')}>
              <ApiKeyInput keyName="GEMINI_API_KEY" placeholder="AI..." />
            </SettingRow>
            <SettingRow label="OpenRouter" description={t('settings.apiKeys.openrouterDescription')}>
              <ApiKeyInput keyName="OPENROUTER_API_KEY" placeholder="sk-or-..." />
            </SettingRow>
          </Section>

          {/* Tools */}
          <Section title={t('settings.tools.title')}>
            <SettingRow label={t('settings.tools.webSearch')} description={t('settings.tools.webSearchDescription')}>
              <ApiKeyInput keyName="TAVILY_API_KEY" placeholder="tvly-..." toolName="web_search" />
            </SettingRow>
          </Section>

          {/* Memory */}
          <Section title={t('settings.memory.title')}>
            <SettingRow
              label={t('settings.memory.statusLabel')}
              description={
                memoryStats
                  ? t('settings.memory.statusDetail', { backend: memoryStats.backend, count: memoryStats.entries })
                  : t('settings.memory.unreachable')
              }
            >
              <div className="flex items-center gap-2">
                <Brain size={14} style={{ color: memoryStats ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {memoryStats
                    ? t('settings.memory.entries', { count: memoryStats.entries })
                    : t('common.unavailable')}
                </span>
              </div>
            </SettingRow>
            <SettingRow label={t('settings.memory.useContext')} description={t('settings.memory.useContextDescription')}>
              <button
                onClick={() => {
                  const next = !memoryEnabled;
                  setMemoryEnabled(next);
                  try { localStorage.setItem('diapason-memory-enabled', String(next)); } catch {}
                  showSaved();
                }}
                data-cible-libre=""
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer cible-etendue [--cible-marge:-8px_0]"
                style={{
                  background: memoryEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: memoryEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label={t('settings.memory.backendLabel')} description={t('settings.memory.backendDescription')}>
              <select
                value={memoryBackend}
                onChange={(e) => {
                  setMemoryBackend(e.target.value);
                  try { localStorage.setItem('diapason-memory-backend', e.target.value); } catch {}
                  showSaved();
                }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="sqlite">sqlite</option>
                <option value="faiss">faiss</option>
                <option value="bm25">bm25</option>
                <option value="colbert">colbert</option>
                <option value="hybrid">hybrid</option>
              </select>
            </SettingRow>
            <SettingRow label={t('settings.memory.topK')} description={`${memoryTopK}`}>
              <input
                type="range"
                min="1"
                max="20"
                step="1"
                value={memoryTopK}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  setMemoryTopK(v);
                  try { localStorage.setItem('diapason-memory-top-k', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label={t('settings.memory.minScore')} description={`${memoryMinScore}`}>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={memoryMinScore}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  setMemoryMinScore(v);
                  try { localStorage.setItem('diapason-memory-min-score', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label={t('settings.memory.maxTokens')} description={`${memoryMaxTokens}`}>
              <input
                type="range"
                min="256"
                max="8192"
                step="256"
                value={memoryMaxTokens}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  setMemoryMaxTokens(v);
                  try { localStorage.setItem('diapason-memory-max-tokens', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
          </Section>

          {/* Model defaults */}
          <Section title={t('settings.modelDefaults.title')}>
            <SettingRow label={t('settings.modelDefaults.temperature')} description={`${settings.temperature}`}>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={settings.temperature}
                onChange={(e) => { updateSettings({ temperature: parseFloat(e.target.value) }); showSaved(); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label={t('settings.modelDefaults.maxTokens')} description={`${settings.maxTokens}`}>
              <input
                type="range"
                min="256"
                max="32768"
                step="256"
                value={settings.maxTokens}
                onChange={(e) => { updateSettings({ maxTokens: parseInt(e.target.value) }); showSaved(); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
          </Section>

          {/* Speech */}
          <Section title={t('settings.speech.title')}>
            <SettingRow label={t('settings.speech.voiceLabel')} description={t('settings.speech.voiceDescription')}>
              <div className="flex min-w-0 max-w-full flex-col items-start gap-1.5 sm:items-end">
                <select
                  aria-label={t('settings.speech.voiceLabel')}
                  value={voixInstallees.includes(santeVoix?.defaultVoice ?? '') ? santeVoix!.defaultVoice : ''}
                  disabled={enregistrementVoix || voixInstallees.length < 2}
                  onChange={(event) => void choisirVoix(event.target.value)}
                  className="max-w-full rounded-lg px-3 py-2 text-sm"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
                >
                  {!voixInstallees.includes(santeVoix?.defaultVoice ?? '') && <option value="" disabled>
                    {voiceLiveAvailable === null ? t('common.checking') : t('common.unavailable')}
                  </option>}
                  {voixInstallees.map((id) => <option key={id} value={id}>{NOMS_VOIX_LOCALES.get(id)}</option>)}
                </select>
                {santeVoix?.defaultVoice === 'qwen3-b' && voixInstallees.includes('qwen3-b') && <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {t('settings.speech.orionDescription')}
                </span>}
                {enregistrementVoix && <span className="text-xs" role="status">{t('settings.speech.voiceSaving')}</span>}
              </div>
            </SettingRow>
            {!estMobile && !serviParLeTailnet() && <ProfilVocal />}
            <SettingRow label={t('settings.speech.sttLabel')} description={t('settings.speech.sttDescription')}>
              <button
                onClick={() => { updateSettings({ speechEnabled: !settings.speechEnabled }); showSaved(); }}
                data-cible-libre=""
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer cible-etendue [--cible-marge:-8px_0]"
                style={{
                  background: settings.speechEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: settings.speechEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label={t('settings.speech.backendStatus')} description={t('settings.speech.backendDescription')}>
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: speechBackendAvailable === true ? 'var(--color-success)'
                      : speechBackendAvailable === false ? 'var(--color-text-tertiary)'
                      : 'var(--color-text-tertiary)',
                  }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {speechBackendAvailable === null ? t('common.checking')
                    : speechBackendAvailable ? t('settings.speech.available')
                    : t('settings.speech.notConfigured')}
                </span>
              </div>
            </SettingRow>
            {/* These counters come from InputArea (the in-window mic button),
                so they say nothing about the background service. Labelled for
                what they actually measure rather than left to imply they
                cover all dictation. */}
            <SettingRow
              label={t('settings.speech.inWindowLabel')}
              description={t('settings.speech.inWindowDescription')}
            >
              <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                {t('settings.speech.sessions', { count: dictationStats.sessions })} ·{' '}
                {t('settings.speech.characters', { count: dictationStats.characters })}
              </span>
            </SettingRow>
            {/* Was "PTT hotkey: ⌘⌥Space". That shortcut is no longer
                registered: it drove an in-window chain that went silent the
                moment the window closed, while still firing. Dictation is the
                background service now, and it holds a bare Control. */}
            <SettingRow
              label={t('settings.speech.hotkeyLabel')}
              description={t('settings.speech.hotkeyDescription')}
            >
              <span className="text-xs font-mono" style={{ color: 'var(--color-text-secondary)' }}>
                {t('settings.speech.hotkeyValue')}
              </span>
            </SettingRow>
            <SettingRow
              label={t('settings.speech.serviceLabel')}
              description={t('settings.speech.serviceDescription')}
            >
              <span className="text-xs font-mono" style={{ color: 'var(--color-text-secondary)' }}>
                diapason dictate --setup
              </span>
            </SettingRow>
            <SettingRow
              label={t('settings.speech.realtimeLabel')}
              description={t('settings.speech.realtimeDescription')}
            >
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: voiceLiveAvailable === true ? 'var(--color-success)'
                      : voiceLiveAvailable === false ? 'var(--color-text-tertiary)'
                      : 'var(--color-text-tertiary)',
                  }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {voiceLiveAvailable === null || voiceLiveDetail === null
                    ? t('common.checking')
                    : voiceLiveDetail.kind === 'ready'
                      ? t('settings.speech.voiceLiveReady', { providers: voiceLiveDetail.providers })
                      : voiceLiveDetail.kind === 'needsKey'
                        ? t('settings.speech.voiceLiveNeedsKey')
                        : t('common.unavailable')}
                </span>
              </div>
            </SettingRow>
            <SettingRow
              label={t('settings.speech.providerLabel')}
              description={t('settings.speech.providerDescription')}
            >
              <select
                value={voiceProvider}
                onChange={(e) => {
                  const v = e.target.value;
                  setVoiceProvider(v);
                  void setServerConfigKey('speech.realtime.provider', v).catch(
                    () => undefined,
                  );
                }}
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
            </SettingRow>
            {!speechBackendAvailable && speechBackendAvailable !== null && (
              <div className="text-xs mt-2 px-1" style={{ color: 'var(--color-text-tertiary)' }}>
                {t('settings.speech.setupHint')}{' '}
                {t('settings.speech.docsHintBefore')}{' '}
                <a href="https://carlitoetienne01-spec.github.io/Diapason/user-guide/tools/" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)' }}>{t('settings.speech.docsLink')}</a>{' '}
                {t('settings.speech.docsHintAfter')}
              </div>
            )}
          </Section>

          {/* Desktop server config (writes ~/.diapason/config.toml) */}
          <Section title={t('settings.desktop.title')}>
            {serverCfgError && !serverCfg && (
              <p className="text-xs px-1 mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                {serverCfgError} — {t('settings.desktop.startServerHint')}
              </p>
            )}
            <SettingRow
              label={t('settings.desktop.visionLabel')}
              description={t('settings.desktop.visionDescription')}
            >
              <button
                type="button"
                disabled={!serverCfg}
                onClick={() => void patchServer('desktop.vision.enabled', !serverCfg?.desktop.vision.enabled)}
                data-cible-libre=""
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer cible-etendue [--cible-marge:-8px_0] disabled:opacity-40"
                style={{
                  background: serverCfg?.desktop.vision.enabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: serverCfg?.desktop.vision.enabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow
              label={t('settings.desktop.polishLabel')}
              description={t('settings.desktop.polishDescription')}
            >
              <button
                type="button"
                disabled={!serverCfg}
                onClick={() => void patchServer('dictation.polish', !serverCfg?.dictation.polish)}
                data-cible-libre=""
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer cible-etendue [--cible-marge:-8px_0] disabled:opacity-40"
                style={{
                  background: serverCfg?.dictation.polish ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: serverCfg?.dictation.polish ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow
              label={t('settings.desktop.emailModeLabel')}
              description={t('settings.desktop.emailModeDescription')}
            >
              <select
                disabled={!serverCfg}
                value={serverCfg?.dictation.email_mode || 'off'}
                onChange={(e) => void patchServer('dictation.email_mode', e.target.value)}
                className="text-xs px-2 py-1 rounded cursor-pointer"
                style={{
                  background: 'var(--color-bg-tertiary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="off">off</option>
                <option value="auto">auto</option>
                <option value="on">on</option>
              </select>
            </SettingRow>
            <SettingRow
              label={t('settings.desktop.autoLearnLabel')}
              description={t('settings.desktop.autoLearnDescription')}
            >
              <button
                type="button"
                disabled={!serverCfg}
                onClick={() =>
                  void patchServer('dictation.auto_learn', !(serverCfg?.dictation.auto_learn ?? true))
                }
                data-cible-libre=""
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer cible-etendue [--cible-marge:-8px_0] disabled:opacity-40"
                style={{
                  background: (serverCfg?.dictation.auto_learn ?? true)
                    ? 'var(--color-accent)'
                    : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: (serverCfg?.dictation.auto_learn ?? true)
                      ? 'translateX(20px)'
                      : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow
              label={t('settings.desktop.wakeBackendLabel')}
              description={t('settings.desktop.wakeBackendDescription')}
            >
              <select
                disabled={!serverCfg}
                value={serverCfg?.speech.wakeword.backend || 'phrase_gate'}
                onChange={(e) => void patchServer('speech.wakeword.backend', e.target.value)}
                className="text-xs px-2 py-1 rounded cursor-pointer"
                style={{
                  background: 'var(--color-bg-tertiary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="phrase_gate">phrase_gate</option>
                <option value="openwakeword">openwakeword</option>
                <option value="auto">auto</option>
              </select>
            </SettingRow>
            <SettingRow
              label={t('settings.desktop.textGateLabel')}
              description={t('settings.desktop.textGateDescription')}
            >
              <button
                type="button"
                disabled={!serverCfg}
                onClick={() =>
                  void patchServer('speech.wakeword.text_gate', !serverCfg?.speech.wakeword.text_gate)
                }
                data-cible-libre=""
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer cible-etendue [--cible-marge:-8px_0] disabled:opacity-40"
                style={{
                  background: serverCfg?.speech.wakeword.text_gate ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: serverCfg?.speech.wakeword.text_gate ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow
              label={t('settings.desktop.heartbeatLabel')}
              description={t('settings.desktop.heartbeatDescription')}
            >
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={!serverCfg}
                  onClick={() => void patchServer('heartbeat.enabled', !serverCfg?.heartbeat.enabled)}
                  className="text-[10px] px-2 py-1 rounded cursor-pointer disabled:opacity-40"
                  style={{
                    background: serverCfg?.heartbeat.enabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                    color: serverCfg?.heartbeat.enabled ? '#fff' : 'var(--color-text-secondary)',
                  }}
                >
                  {t('settings.desktop.heartbeat')}
                </button>
                <button
                  type="button"
                  disabled={!serverCfg}
                  onClick={() => void patchServer('routines.enabled', !serverCfg?.routines.enabled)}
                  className="text-[10px] px-2 py-1 rounded cursor-pointer disabled:opacity-40"
                  style={{
                    background: serverCfg?.routines.enabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                    color: serverCfg?.routines.enabled ? '#fff' : 'var(--color-text-secondary)',
                  }}
                >
                  {t('settings.desktop.routines')}
                </button>
              </div>
            </SettingRow>
            <SettingRow
              label={t('settings.desktop.rebuildLabel')}
              description={t('settings.desktop.rebuildDescription')}
            >
              <span className="text-[10px] font-mono" style={{ color: 'var(--color-text-secondary)' }}>
                ./scripts/rebuild-desktop.sh
              </span>
            </SettingRow>
          </Section>

          {/* Data */}
          <Section title={t('settings.data.title')}>
            <SettingRow
              label={t('settings.data.conversations')}
              description={t('settings.data.storedLocally', { count: conversations.length })}
            >
              <div className="flex gap-2">
                <button
                  onClick={handleExport}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
                >
                  <Download size={12} /> {t('common.export')}
                </button>
                <button
                  onClick={handleImport}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
                >
                  <Upload size={12} /> {t('common.import')}
                </button>
              </div>
            </SettingRow>
            <SettingRow label={t('settings.data.clearLabel')} description={t('settings.data.clearDescription')}>
              <button
                onClick={() => void handleClear()}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                style={{
                  color: 'var(--color-error)',
                  background: 'transparent',
                  border: '1px solid var(--color-error)',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(220,38,38,0.1)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
              >
                <Trash2 size={12} /> {t('common.clear')}
              </button>
            </SettingRow>
          </Section>

          {/* Updates — 26/09/2026 : hors de l'app de bureau, l'interrupteur
              écrivait un réglage que rien ne lit et « Vérifier maintenant »
              ne faisait rien, sans un mot. La mise à jour est celle de l'app. */}
          {isTauri() && (
          <Section title={t('settings.updates.title')}>
            <SettingRow label={t('settings.updates.autoLabel')} description={t('settings.updates.autoDescription')}>
              <button
                onClick={() => handleAutoUpdateToggle(!autoUpdateEnabled)}
                data-cible-libre=""
                className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors cible-etendue [--cible-marge:-10px_-2px]"
                style={{ background: autoUpdateEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
              >
                <span
                  className="inline-block h-3.5 w-3.5 rounded-full transition-transform"
                  style={{
                    background: 'white',
                    transform: autoUpdateEnabled ? 'translateX(18px)' : 'translateX(2px)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label={t('settings.updates.checkLabel')} description={t('settings.updates.checkDescription')}>
              <button
                onClick={handleCheckNow}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)', color: 'var(--color-text)', cursor: 'pointer' }}
                disabled={updateCheckState === 'checking'}
              >
                <RefreshCw size={12} className={updateCheckState === 'checking' ? 'animate-spin' : ''} />
                {updateCheckState === 'checking' && t('common.checking')}
                {updateCheckState === 'available' && t('settings.updates.available')}
                {updateCheckState === 'latest' && t('settings.updates.upToDate')}
                {updateCheckState === 'idle' && t('settings.updates.checkNow')}
              </button>
            </SettingRow>
          </Section>
          )}

          {/* About */}
          <Section title={t('settings.about.title')}>
            <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              <p className="mb-2">
                <span className="font-semibold" style={{ color: 'var(--color-text)' }}>Diapason</span> — {t('settings.about.tagline')}
              </p>
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                {t('settings.about.research')}
              </p>
              <div className="flex gap-3 mt-3 text-xs">
                <a
                  href="https://diapason.stanford.edu/"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--color-accent)' }}
                >
                  {t('settings.about.projectSite')}
                </a>
                <a
                  href="https://carlitoetienne01-spec.github.io/Diapason/"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--color-accent)' }}
                >
                  {t('common.documentation')}
                </a>
              </div>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
