import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';

import { fetchMeshInbox } from '../features/mesh/api';
import { playFileArrivalChime } from '../features/mesh/fileArrival';
import { resolveSuccessRoute } from '../features/mesh/routes';
import type { MeshFileReceived, MeshInboxEntry } from '../features/mesh/types';
import { useTranslation } from '../i18n/useTranslation';
import { isTauri } from '../lib/api';
import { useAppStore } from '../lib/store';
import { FileArrivalNotice } from './FileArrivalNotice';

type VisibleReceipt = MeshFileReceived & { eventId: string };

/**
 * The hand at the end of the mesh: what another device asked for actually
 * happens here.
 *
 * It polls the backend's inbox — filled only by commands and transfers that
 * already survived their cryptographic checks — and turns each entry into a
 * screen, a selection, a notification, or a brief verified-arrival card.
 *
 * Exactly one of these may be mounted. `GET /v1/mesh/inbox` drains on read,
 * so a second poller would not duplicate work: it would make navigations
 * vanish at random into whichever poller won the race.
 */
export function MeshHost() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addLogEntry = useAppStore((s) => s.addLogEntry);
  const setPendingMeshSelection = useAppStore((s) => s.setPendingMeshSelection);
  const [receivedFiles, setReceivedFiles] = useState<VisibleReceipt[]>([]);
  const dismissReceivedFile = useCallback((eventId: string) => {
    setReceivedFiles((current) =>
      current.filter((item) => item.eventId !== eventId),
    );
  }, []);

  const announceReceivedFile = useCallback(
    async (entry: MeshInboxEntry) => {
      const receipt = entry.fileReceived;
      if (!receipt) return;
      const eventId = entry.commandId || `${receipt.sourceDeviceId}:${entry.receivedAtMs}`;
      setReceivedFiles((current) => {
        if (current.some((item) => item.eventId === eventId)) return current;
        return [...current, { ...receipt, eventId }].slice(-3);
      });
      void playFileArrivalChime();
      addLogEntry({
        timestamp: Date.now(),
        level: 'info',
        category: 'mesh',
        message: `${receipt.fileName} reçu depuis ${receipt.sourceDeviceName}.`,
      });

      const windowIsVisible =
        document.visibilityState === 'visible' &&
        (typeof document.hasFocus !== 'function' || document.hasFocus());
      if (!windowIsVisible) {
        await showNotification(
          t('mesh.fileArrival.title'),
          t('mesh.fileArrival.notificationBody', {
            file: receipt.fileName,
            device: receipt.sourceDeviceName,
          }),
        );
      }
    },
    [addLogEntry, t],
  );

  const handleEntry = useCallback(
    async (entry: MeshInboxEntry) => {
      if (entry.fileReceived) {
        await announceReceivedFile(entry);
        return;
      }
      if (entry.notification) {
        await showNotification(entry.notification.title, entry.notification.body);
        return;
      }

      const target = resolveSuccessRoute(entry.route ?? '');
      if (!target) {
        // Doing nothing is the honest response to a route this version does
        // not know: navigating somewhere approximate would look like the
        // command was honoured.
        addLogEntry({
          timestamp: Date.now(),
          level: 'warn',
          category: 'mesh',
          message: `Écran inconnu demandé par un autre appareil : ${entry.route ?? '(vide)'}`,
        });
        return;
      }

      // Set before navigating: the target page reads the selection on mount,
      // and the mount happens inside navigate().
      if (target.selection) setPendingMeshSelection(target.selection);
      navigate(target.path);

      // Focus on every routed entry, not only on the ones that ask for it.
      // A screen opened behind another application is a command the user
      // never sees — which is indistinguishable from one that failed.
      await focusMainWindow();
    },
    [addLogEntry, announceReceivedFile, navigate, setPendingMeshSelection],
  );

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const entries = await fetchMeshInbox();
        // Processed BEFORE the cancelled check on purpose. StrictMode mounts,
        // cleans up and remounts in development; by the time the flag flips,
        // this request has already drained the server queue. Discarding the
        // response here would lose the navigation for good.
        for (const entry of entries) {
          // Each entry stands alone. The inbox has already been drained by
          // the time we get here, so one entry that throws must not take the
          // rest of the batch with it — a single malformed route from one
          // device would silently swallow a command sent by another.
          try {
            await handleEntry(entry);
          } catch (error) {
            addLogEntry({
              timestamp: Date.now(),
              level: 'error',
              category: 'mesh',
              message: `Demande d'un autre appareil ignorée : ${
                error instanceof Error ? error.message : String(error)
              }`,
            });
          }
        }
      } catch {
        // The backend may still be starting, or briefly unreachable. A
        // background poll must stay silent — there is nothing for the user
        // to do about it, and a toast every two seconds would be noise.
      }
      if (!cancelled) timer = window.setTimeout(tick, 2000);
    };

    // Not immediate: under Tauri the local API key is minted by the Python
    // server after the webview renders, so the very first call would spend
    // itself on a 401.
    timer = window.setTimeout(tick, 1200);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [handleEntry, addLogEntry]);

  return (
    <div
      className="pointer-events-none fixed right-5 top-5 z-[120] flex flex-col items-end gap-2.5"
      aria-live="polite"
      aria-atomic="false"
    >
      {receivedFiles.map((receipt) => (
        <FileArrivalNotice
          key={receipt.eventId}
          eventId={receipt.eventId}
          receipt={receipt}
          onDismiss={dismissReceivedFile}
        />
      ))}
    </div>
  );
}

/** Bring this window forward. Silently a no-op outside the desktop app. */
async function focusMainWindow(): Promise<void> {
  if (!isTauri()) return;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke('focus_main_window');
  } catch {
    // An older binary may not carry the command; the navigation still stands.
  }
}

async function showNotification(title: string, body: string): Promise<void> {
  if (!isTauri()) {
    toast(title, { description: body });
    return;
  }
  try {
    const { isPermissionGranted, requestPermission, sendNotification } = await import(
      '@tauri-apps/plugin-notification'
    );
    let granted = await isPermissionGranted();
    if (!granted) granted = (await requestPermission()) === 'granted';
    // Falling back to the in-app toast rather than dropping it: the user
    // asked for this from another device and deserves to see it land.
    if (!granted) {
      toast(title, { description: body });
      return;
    }
    sendNotification({ title, body });
  } catch {
    toast(title, { description: body });
  }
}

export default MeshHost;
