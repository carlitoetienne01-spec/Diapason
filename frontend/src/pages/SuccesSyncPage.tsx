import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArchiveRestore,
  Check,
  Clipboard,
  HardDrive,
  KeyRound,
  Link2,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  Trash2,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  clearSuccesSyncGuest,
  clearSuccesSyncRelay,
  createSuccesPairing,
  fetchSuccesSyncStatus,
  importLegacySuccesSnapshot,
  joinSuccesSync,
  revokeSuccesPeer,
  runSuccesSync,
  setSuccesSyncRelay,
} from '../features/succes/api';
import type {
  SuccesPairingInvitation,
  SuccesSyncStatus,
} from '../features/succes/types';
import { useConfirm } from '../components/ConfirmDialog';
import { useAppStore } from '../lib/store';

function formatDate(value: number | null | undefined) {
  if (!value) return 'Jamais';
  return new Intl.DateTimeFormat('fr-CA', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

export function SuccesSyncPage() {
  const confirm = useConfirm();
  const [status, setStatus] = useState<SuccesSyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [deviceName, setDeviceName] = useState('Mon autre appareil');
  const [invitation, setInvitation] = useState<SuccesPairingInvitation | null>(null);
  const [copied, setCopied] = useState(false);
  const [relayDraft, setRelayDraft] = useState('');
  const [pairingToken, setPairingToken] = useState('');
  const importRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await fetchSuccesSyncStatus();
      setStatus(next);
      setRelayDraft(next.relayUrl || '');
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'error',
        category: 'succes',
        message: `Diagnostic de synchronisation : ${message}`,
      });
      toast.error('Le diagnostic de synchronisation est indisponible.', {
        description: message,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!status?.guest) return;
    const id = window.setInterval(() => {
      void (async () => {
        try {
          const result = await runSuccesSync();
          setStatus(result.status);
          if (result.pushed > 0 || result.pulled > 0) {
            toast.message('Synchronisation', {
              description: `${result.pushed} envoyée(s) · ${result.pulled} reçue(s)`,
            });
          }
        } catch {
          // Keep quiet on background polls; surface errors on manual sync.
        }
      })();
    }, 60_000);
    return () => window.clearInterval(id);
  }, [status?.guest?.peerId]);

  const preparePairing = async () => {
    if (!deviceName.trim()) return;
    setWorking(true);
    try {
      const next = await createSuccesPairing(deviceName.trim());
      setInvitation(next);
      setCopied(false);
      await load();
      toast.success('Invitation temporaire créée', {
        description: 'Elle expire dans 10 minutes et ne peut être utilisée qu’une fois.',
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error("L'invitation n'a pas pu être créée.", { description: message });
    } finally {
      setWorking(false);
    }
  };

  const copyInvitation = async () => {
    if (!invitation) return;
    try {
      await navigator.clipboard.writeText(invitation.pairingToken);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch (error) {
      toast.error("Le code n'a pas pu être copié.", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const saveRelay = async () => {
    if (!relayDraft.trim()) return;
    setWorking(true);
    try {
      const next = await setSuccesSyncRelay(relayDraft.trim());
      setStatus(next);
      setRelayDraft(next.relayUrl || relayDraft.trim());
      toast.success('Relais enregistré', {
        description: next.relayUrl || undefined,
      });
    } catch (error) {
      toast.error("Le relais n'a pas pu être enregistré.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setWorking(false);
    }
  };

  const removeRelay = async () => {
    const confirmed = await confirm({
      title: 'Retirer le relais HTTPS ?',
      description: 'La synchronisation multi-appareil hors de cette machine ne fonctionnera plus tant qu’un relais n’est pas reconfiguré.',
      confirmLabel: 'Retirer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    setWorking(true);
    try {
      const next = await clearSuccesSyncRelay();
      setStatus(next);
      setRelayDraft('');
      toast.success('Relais retiré');
    } catch (error) {
      toast.error('Impossible de retirer le relais.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setWorking(false);
    }
  };

  const joinRemote = async () => {
    if (!pairingToken.trim()) return;
    setWorking(true);
    try {
      const next = await joinSuccesSync({
        pairingToken: pairingToken.trim(),
        relayUrl: relayDraft.trim() || undefined,
        deviceName: deviceName.trim() || undefined,
      });
      setStatus(next);
      setPairingToken('');
      setRelayDraft(next.relayUrl || relayDraft);
      toast.success('Appareil rejoint', {
        description: next.joined?.relayUrl || next.relayUrl || undefined,
      });
      const result = await runSuccesSync();
      setStatus(result.status);
      toast.success('Première synchronisation terminée', {
        description: `${result.pushed} envoyée(s) · ${result.pulled} reçue(s)`,
      });
    } catch (error) {
      toast.error("L'appairage a échoué.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setWorking(false);
    }
  };

  const syncNow = async () => {
    setWorking(true);
    try {
      const result = await runSuccesSync();
      setStatus(result.status);
      toast.success('Synchronisation terminée', {
        description: `${result.pushed} envoyée(s) · ${result.pulled} reçue(s)`,
      });
      if (result.hasMore) {
        toast.message('Encore des opérations en attente', {
          description: 'Relancez la sync pour continuer le rattrapage.',
        });
      }
    } catch (error) {
      toast.error('La synchronisation a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
      await load();
    } finally {
      setWorking(false);
    }
  };

  const unlinkGuest = async () => {
    const confirmed = await confirm({
      title: 'Se déconnecter de l’appareil hôte ?',
      description: 'La session invité sera effacée sur cet appareil.',
      confirmLabel: 'Retirer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    setWorking(true);
    try {
      const next = await clearSuccesSyncGuest();
      setStatus(next);
      toast.success('Session invité effacée');
    } catch (error) {
      toast.error('Impossible de se déconnecter.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setWorking(false);
    }
  };

  const importLegacy = async (file: File) => {
    setWorking(true);
    try {
      const raw = await file.text();
      const snapshot = JSON.parse(raw) as unknown;
      const result = await importLegacySuccesSnapshot(snapshot);
      await load();
      const summary = result.summary;
      const message = summary.alreadyImported
        ? 'Cette sauvegarde avait déjà été importée.'
        : `${summary.tasksImported} tâche(s) et ${summary.projectsImported} projet(s) importés.`;
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'info',
        category: 'succes',
        message: `Import Life OS : ${message}`,
      });
      toast.success('Import terminé', { description: message });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'error',
        category: 'succes',
        message: `Import Life OS échoué : ${message}`,
      });
      toast.error("La sauvegarde n'a pas pu être importée.", { description: message });
    } finally {
      setWorking(false);
      if (importRef.current) importRef.current.value = '';
    }
  };

  const revoke = async (peerId: string, name: string) => {
    const confirmed = await confirm({
      title: `Retirer l'accès de « ${name} » ?`,
      description: 'Cet appareil ne pourra plus synchroniser tant qu’une nouvelle invitation n’est pas créée.',
      confirmLabel: 'Retirer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    setWorking(true);
    try {
      await revokeSuccesPeer(peerId);
      await load();
      toast.success(`Accès retiré : ${name}`);
    } catch (error) {
      toast.error("L'accès n'a pas pu être retiré.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setWorking(false);
    }
  };

  const relayReady = Boolean(status?.relayUrl || relayDraft.trim());
  const isGuest = Boolean(status?.guest);
  const transportLabel =
    status?.transport === 'https_relay' ? 'Relais HTTPS' : 'Local uniquement';

  return (
    <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
      <main className="max-w-5xl mx-auto w-full">
        <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between mb-7">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>
                Succès
              </span>
              {(loading || working) && (
                <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
              )}
            </div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
              Synchronisation
            </h1>
            <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
              Relais HTTPS de confiance, invitation, puis échange d’opérations — vos données restent chiffrées en transit
              par TLS et ne quittent Diapason que vers l’URL que vous indiquez.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {isGuest && (
              <button
                type="button"
                onClick={() => void syncNow()}
                disabled={working}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium cursor-pointer disabled:opacity-50"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                <RefreshCw size={15} className={working ? 'animate-spin' : ''} /> Synchroniser
              </button>
            )}
            <input
              ref={importRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void importLegacy(file);
              }}
            />
            <button
              type="button"
              onClick={() => importRef.current?.click()}
              disabled={working}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm cursor-pointer disabled:opacity-50"
              style={{
                background: 'var(--color-bg-secondary)',
                color: 'var(--color-text-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <ArchiveRestore size={15} /> Importer Life OS
            </button>
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm cursor-pointer disabled:opacity-50"
              style={{
                background: 'var(--color-bg-secondary)',
                color: 'var(--color-text-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Actualiser
            </button>
          </div>
        </header>

        <section className="grid md:grid-cols-3 gap-4 mb-5">
          <article className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <HardDrive size={19} className="mb-4" style={{ color: 'var(--color-accent)' }} />
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Cet appareil</p>
            <p className="font-medium mt-1 break-all" style={{ color: 'var(--color-text)' }}>
              {status?.deviceId ?? '—'}
            </p>
            <p className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>
              Rôle : {status?.role === 'guest' ? 'invité' : status?.role === 'host' ? 'hôte' : 'prêt'} · curseur{' '}
              {status?.localCursor ?? 0}
            </p>
          </article>
          <article className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <Smartphone size={19} className="mb-4" style={{ color: 'var(--color-accent)' }} />
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Appareils autorisés</p>
            <p className="text-2xl font-semibold mt-1" style={{ color: 'var(--color-text)' }}>
              {status?.peerCount ?? 0}
            </p>
            <p className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>
              {status?.pendingPairings ?? 0} invitation(s) · dernier sync {formatDate(status?.lastSyncAtMs)}
            </p>
          </article>
          <article className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <ShieldCheck size={19} className="mb-4" style={{ color: 'var(--color-success)' }} />
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Transport</p>
            <p className="font-medium mt-1" style={{ color: 'var(--color-text)' }}>
              {transportLabel}
            </p>
            <p className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>
              Jetons hachés · pair/exchange sans clé API locale
            </p>
          </article>
        </section>

        <section
          className="rounded-2xl p-5 mb-5 flex items-start gap-4"
          style={{
            background: status?.relayUrl
              ? 'color-mix(in srgb, var(--color-success) 8%, var(--color-surface))'
              : 'color-mix(in srgb, var(--color-accent) 7%, var(--color-surface))',
            border: status?.relayUrl
              ? '1px solid color-mix(in srgb, var(--color-success) 30%, var(--color-border))'
              : '1px solid color-mix(in srgb, var(--color-accent) 28%, var(--color-border))',
          }}
        >
          {status?.relayUrl ? (
            <Wifi size={20} className="mt-0.5 shrink-0" style={{ color: 'var(--color-success)' }} />
          ) : (
            <WifiOff size={20} className="mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
          )}
          <div className="min-w-0 flex-1">
            <h2 className="font-medium" style={{ color: 'var(--color-text)' }}>
              {status?.relayUrl ? 'Relais HTTPS configuré' : 'Choisissez un relais de confiance'}
            </h2>
            <p className="text-sm mt-1 leading-6" style={{ color: 'var(--color-text-secondary)' }}>
              {status?.message ||
                'Exposez Diapason derrière Tailscale, un tunnel Cloudflare, ou un reverse proxy HTTPS — puis collez l’URL ici.'}
            </p>
            {status?.lastSyncError && (
              <p className="text-xs mt-2" style={{ color: 'var(--color-danger, #ef4444)' }}>
                Dernière erreur : {status.lastSyncError}
              </p>
            )}
          </div>
        </section>

        <section className="rounded-2xl p-5 mb-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <div className="flex items-center gap-2 mb-1">
            <Link2 size={17} style={{ color: 'var(--color-accent)' }} />
            <h2 className="font-medium" style={{ color: 'var(--color-text)' }}>
              URL du relais
            </h2>
          </div>
          <p className="text-xs mb-4" style={{ color: 'var(--color-text-tertiary)' }}>
            Ex. https://diapason.example.com ou http://100.x.y.z:8000 (Tailscale). Diapason n’ouvre aucun port tout seul.
          </p>
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              value={relayDraft}
              onChange={(event) => setRelayDraft(event.target.value)}
              placeholder="https://…"
              className="flex-1 rounded-xl px-3 py-2.5 bg-transparent outline-none text-sm"
              style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
            />
            <button
              type="button"
              disabled={!relayDraft.trim() || working}
              onClick={() => void saveRelay()}
              className="px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-40 cursor-pointer"
              style={{ background: 'var(--color-accent)', color: '#fff' }}
            >
              Enregistrer
            </button>
            {status?.relayUrl && (
              <button
                type="button"
                disabled={working}
                onClick={() => void removeRelay()}
                className="px-4 py-2.5 rounded-xl text-sm cursor-pointer disabled:opacity-40"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border)',
                }}
              >
                Retirer
              </button>
            )}
          </div>
        </section>

        <section className="grid lg:grid-cols-2 gap-5 mb-5">
          <div className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <div className="flex items-center gap-2 mb-1">
              <KeyRound size={17} style={{ color: 'var(--color-accent)' }} />
              <h2 className="font-medium" style={{ color: 'var(--color-text)' }}>
                Préparer un appareil (hôte)
              </h2>
            </div>
            <p className="text-xs mb-4" style={{ color: 'var(--color-text-tertiary)' }}>
              Créez une invitation sur ce Mac, puis collez le code sur l’autre appareil (avec la même URL de relais).
            </p>
            <label className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              Nom de l’appareil invité
              <input
                value={deviceName}
                onChange={(event) => setDeviceName(event.target.value)}
                maxLength={80}
                className="mt-1 w-full rounded-xl px-3 py-2.5 bg-transparent outline-none"
                style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
              />
            </label>
            <button
              type="button"
              disabled={!deviceName.trim() || working}
              onClick={() => void preparePairing()}
              className="mt-3 w-full px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-40 cursor-pointer"
              style={{ background: 'var(--color-accent)', color: '#fff' }}
            >
              Créer une invitation
            </button>
            {invitation && (
              <div className="mt-4 rounded-xl p-3" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                <div className="flex items-center justify-between gap-3 mb-2">
                  <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    Code temporaire · expire à {formatDate(invitation.expiresAtMs)}
                  </p>
                  <button
                    type="button"
                    onClick={() => void copyInvitation()}
                    aria-label="Copier le code"
                    className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                    style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-tertiary)' }}
                  >
                    {copied ? <Check size={14} /> : <Clipboard size={14} />}
                  </button>
                </div>
                <code className="block text-xs break-all select-all" style={{ color: 'var(--color-text-secondary)' }}>
                  {invitation.pairingToken}
                </code>
              </div>
            )}
          </div>

          <div className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <div className="flex items-center gap-2 mb-1">
              <Smartphone size={17} style={{ color: 'var(--color-accent)' }} />
              <h2 className="font-medium" style={{ color: 'var(--color-text)' }}>
                Rejoindre un appareil (invité)
              </h2>
            </div>
            <p className="text-xs mb-4" style={{ color: 'var(--color-text-tertiary)' }}>
              Collez le code reçu, avec l’URL du Mac hôte (ou du tunnel) comme relais.
            </p>
            {isGuest ? (
              <div className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)' }}>
                <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                  Connecté à {status?.guest?.deviceName || 'hôte'}
                </p>
                <p className="text-xs mt-1 break-all" style={{ color: 'var(--color-text-tertiary)' }}>
                  {status?.relayUrl}
                </p>
                <p className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>
                  Pull {status?.guest?.pullCursor ?? 0} · push {status?.guest?.pushCursor ?? 0}
                </p>
                <div className="flex flex-wrap gap-2 mt-3">
                  <button
                    type="button"
                    disabled={working}
                    onClick={() => void syncNow()}
                    className="px-3 py-2 rounded-lg text-sm font-medium cursor-pointer disabled:opacity-40"
                    style={{ background: 'var(--color-accent)', color: '#fff' }}
                  >
                    Synchroniser maintenant
                  </button>
                  <button
                    type="button"
                    disabled={working}
                    onClick={() => void unlinkGuest()}
                    className="px-3 py-2 rounded-lg text-sm cursor-pointer disabled:opacity-40"
                    style={{
                      background: 'var(--color-bg-tertiary)',
                      color: 'var(--color-danger, #ef4444)',
                    }}
                  >
                    Se déconnecter
                  </button>
                </div>
              </div>
            ) : (
              <>
                <label className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  Code d’appairage
                  <textarea
                    value={pairingToken}
                    onChange={(event) => setPairingToken(event.target.value)}
                    rows={3}
                    className="mt-1 w-full rounded-xl px-3 py-2.5 bg-transparent outline-none text-xs font-mono"
                    style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
                    placeholder="diapason_pair_…"
                  />
                </label>
                <button
                  type="button"
                  disabled={!pairingToken.trim() || !relayReady || working}
                  onClick={() => void joinRemote()}
                  className="mt-3 w-full px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-40 cursor-pointer"
                  style={{ background: 'var(--color-accent)', color: '#fff' }}
                >
                  Rejoindre et synchroniser
                </button>
              </>
            )}
          </div>
        </section>

        <section className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <h2 className="font-medium mb-4" style={{ color: 'var(--color-text)' }}>
            Appareils autorisés (côté hôte)
          </h2>
          {!loading && !status?.peers.length && (
            <div className="py-10 text-center">
              <Smartphone className="mx-auto mb-3" style={{ color: 'var(--color-text-tertiary)' }} />
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Aucun autre appareil autorisé
              </p>
              <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                Créez une invitation pour que cet Mac serve d’hôte.
              </p>
            </div>
          )}
          <div className="grid gap-2">
            {status?.peers.map((peer) => (
              <article
                key={peer.id}
                className="flex items-center gap-3 rounded-xl p-3"
                style={{ background: 'var(--color-bg-secondary)' }}
              >
                <div
                  className="size-9 rounded-lg flex items-center justify-center"
                  style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-accent)' }}
                >
                  <Smartphone size={16} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
                    {peer.deviceName}
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                    Dernier échange : {formatDate(peer.lastSeenAtMs)}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={working}
                  onClick={() => void revoke(peer.id, peer.deviceName)}
                  aria-label={`Retirer ${peer.deviceName}`}
                  className="size-9 rounded-lg flex items-center justify-center cursor-pointer disabled:opacity-40"
                  style={{ color: 'var(--color-danger, #ef4444)', background: 'var(--color-bg-tertiary)' }}
                >
                  <Trash2 size={15} />
                </button>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
