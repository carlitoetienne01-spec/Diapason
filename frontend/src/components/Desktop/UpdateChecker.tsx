import React, { useState, useEffect, useCallback, useRef } from 'react';

import { useTranslation } from '../../i18n/useTranslation';

type UpdateState = 'idle' | 'available' | 'downloading' | 'ready' | 'error';

const CHECK_INTERVAL_MS = 30 * 60 * 1000; // 30 minutes
const DISABLED_KEY = 'oj-auto-update-disabled';

export function isAutoUpdateDisabled(): boolean {
  try {
    return localStorage.getItem(DISABLED_KEY) === '1';
  } catch {
    return false;
  }
}

export function setAutoUpdateDisabled(disabled: boolean): void {
  try {
    if (disabled) {
      localStorage.setItem(DISABLED_KEY, '1');
    } else {
      localStorage.removeItem(DISABLED_KEY);
    }
  } catch {}
}

export function UpdateChecker() {
  const { t } = useTranslation();
  const [state, setState] = useState<UpdateState>('idle');
  const [version, setVersion] = useState('');
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState('');
  const [dismissed, setDismissed] = useState(false);
  const updateRef = useRef<any>(null);

  const checkForUpdate = useCallback(async () => {
    if (isAutoUpdateDisabled()) return;
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const update = await check();
      if (update) {
        updateRef.current = update;
        setVersion(update.version);
        setState('available');
        setDismissed(false);
      }
    } catch {
      // Silently ignore — likely running in browser or no update available
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined' || !(window as any).__TAURI_INTERNALS__) {
      return;
    }
    if (isAutoUpdateDisabled()) return;

    // Local dev escape hatch: skip the auto-update poll if explicitly
    // disabled. Vite exposes any ``VITE_``-prefixed env var on
    // ``import.meta.env``, so a frontend dev can ``export
    // VITE_DIAPASON_NO_UPDATER=1`` before ``npm run tauri dev`` to
    // silence the 30-min poll. See docs/desktop-auto-update.md.
    const noUpdater = (import.meta as any).env?.VITE_DIAPASON_NO_UPDATER;
    if (noUpdater === '1' || noUpdater === 'true') {
      return;
    }

    checkForUpdate();
    const interval = setInterval(checkForUpdate, CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [checkForUpdate]);

  const handleDownload = useCallback(async () => {
    const update = updateRef.current;
    if (!update) return;

    setState('downloading');
    setProgress(0);

    try {
      let downloaded = 0;
      const contentLength = update.contentLength ?? 0;

      await update.downloadAndInstall((event: any) => {
        if (event.event === 'Progress') {
          downloaded += event.data?.chunkLength ?? 0;
          if (contentLength > 0) {
            setProgress(Math.min(100, Math.round((downloaded / contentLength) * 100)));
          }
        } else if (event.event === 'Finished') {
          setProgress(100);
        }
      });

      setState('ready');
    } catch (e: any) {
      setErrorMsg(e?.message || t('common.downloadFailed'));
      setState('error');
      setTimeout(() => setState('idle'), 5000);
    }
  }, [t]);

  const handleRelaunch = useCallback(async () => {
    try {
      const { relaunch } = await import('@tauri-apps/plugin-process');
      await relaunch();
    } catch {
      setErrorMsg(t('update.restartManually'));
      setState('error');
      setTimeout(() => setState('idle'), 5000);
    }
  }, [t]);

  const handleDisable = useCallback(() => {
    setAutoUpdateDisabled(true);
    setState('idle');
    setDismissed(false);
  }, []);

  if (state === 'idle' || dismissed) return null;

  return (
    <div style={styles.banner}>
      {state === 'available' && (
        <div style={styles.row}>
          <span>{t('update.available')} <strong>v{version}</strong></span>
          <div style={styles.actions}>
            <button style={styles.primaryBtn} onClick={handleDownload}>{t('common.download')}</button>
            <button style={styles.secondaryBtn} onClick={() => setDismissed(true)}>{t('common.later')}</button>
            <button style={styles.muteBtn} onClick={handleDisable}>{t('update.disableAuto')}</button>
          </div>
        </div>
      )}

      {state === 'downloading' && (
        <div style={styles.row}>
          <span>{t('update.downloadingProgress', { progress })}</span>
          <div style={styles.progressBar}>
            <div style={{ ...styles.progressFill, width: `${progress}%` }} />
          </div>
        </div>
      )}

      {state === 'ready' && (
        <div style={styles.row}>
          <span style={{ color: '#a6e3a1' }}>{t('update.installed')}</span>
          <div style={styles.actions}>
            <button style={styles.successBtn} onClick={handleRelaunch}>{t('update.relaunch')}</button>
            <button style={styles.secondaryBtn} onClick={() => setDismissed(true)}>{t('common.later')}</button>
          </div>
        </div>
      )}

      {state === 'error' && (
        <div style={styles.row}>
          <span style={{ color: '#f38ba8' }}>{t('update.error', { message: errorMsg })}</span>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  banner: {
    padding: '10px 24px',
    backgroundColor: '#181825',
    borderBottom: '1px solid #313244',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '16px',
    fontSize: '13px',
  },
  actions: {
    display: 'flex',
    gap: '8px',
    alignItems: 'center',
  },
  primaryBtn: {
    padding: '4px 14px',
    border: 'none',
    borderRadius: '4px',
    backgroundColor: '#89b4fa',
    color: '#1e1e2e',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
  },
  successBtn: {
    padding: '4px 14px',
    border: 'none',
    borderRadius: '4px',
    backgroundColor: '#a6e3a1',
    color: '#1e1e2e',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
  },
  secondaryBtn: {
    padding: '4px 14px',
    border: '1px solid #45475a',
    borderRadius: '4px',
    backgroundColor: 'transparent',
    color: '#a6adc8',
    fontSize: '12px',
    cursor: 'pointer',
  },
  muteBtn: {
    padding: '0',
    border: 'none',
    backgroundColor: 'transparent',
    color: '#585b70',
    fontSize: '11px',
    cursor: 'pointer',
    textDecoration: 'underline',
  },
  progressBar: {
    flex: 1,
    maxWidth: '300px',
    height: '6px',
    backgroundColor: '#313244',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: '#89b4fa',
    borderRadius: '3px',
    transition: 'width 0.3s ease',
  },
};
