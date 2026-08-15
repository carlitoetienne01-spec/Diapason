import { useCallback, useEffect, useState } from 'react';
import {
  Check,
  Clipboard,
  HardDrive,
  KeyRound,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  Trash2,
  WifiOff,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  createSuccesPairing,
  fetchSuccesSyncStatus,
  revokeSuccesPeer,
} from '../features/succes/api';
import type {
  SuccesPairingInvitation,
  SuccesSyncStatus,
} from '../features/succes/types';
import { useAppStore } from '../lib/store';

function formatDate(value: number | null) {
  if (!value) return 'Jamais connecté';
  return new Intl.DateTimeFormat('fr-CA', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

export function SuccesSyncPage() {
  const [status, setStatus] = useState<SuccesSyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [deviceName, setDeviceName] = useState('Mon autre appareil');
  const [invitation, setInvitation] = useState<SuccesPairingInvitation | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await fetchSuccesSyncStatus());
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

  const preparePairing = async () => {
    if (!deviceName.trim()) return;
    setWorking(true);
    try {
      const next = await createSuccesPairing(deviceName.trim());
      setInvitation(next);
      setCopied(false);
      await load();
      toast.success('Invitation temporaire créée', {
        description: "Elle expire dans 10 minutes et n'ouvre aucun accès réseau.",
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'error',
        category: 'succes',
        message: `Création de l'invitation : ${message}`,
      });
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

  const revoke = async (peerId: string, name: string) => {
    if (!window.confirm(`Retirer l'accès de « ${name} » ?`)) return;
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

  return (
    <div className="flex-1 overflow-y-auto px-5 py-8 md:px-8 md:py-10">
      <main className="max-w-5xl mx-auto w-full">
        <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between mb-7">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium tracking-[0.16em] uppercase" style={{ color: 'var(--color-accent)' }}>Succès</span>
              {(loading || working) && <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />}
            </div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>Synchronisation</h1>
            <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
              Préparez vos appareils sans sacrifier la confidentialité locale de Diapason.
            </p>
          </div>
          <button type="button" onClick={() => void load()} disabled={loading} className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm cursor-pointer disabled:opacity-50" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Actualiser
          </button>
        </header>

        <section className="grid md:grid-cols-3 gap-4 mb-5">
          <article className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <HardDrive size={19} className="mb-4" style={{ color: 'var(--color-accent)' }} />
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Cet appareil</p>
            <p className="font-medium mt-1 break-all" style={{ color: 'var(--color-text)' }}>{status?.deviceId ?? '—'}</p>
            <p className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>Curseur local : {status?.localCursor ?? 0}</p>
          </article>
          <article className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <Smartphone size={19} className="mb-4" style={{ color: 'var(--color-accent)' }} />
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Appareils autorisés</p>
            <p className="text-2xl font-semibold mt-1" style={{ color: 'var(--color-text)' }}>{status?.peerCount ?? 0}</p>
            <p className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>{status?.pendingPairings ?? 0} invitation(s) en attente</p>
          </article>
          <article className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <ShieldCheck size={19} className="mb-4" style={{ color: 'var(--color-success)' }} />
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Protection actuelle</p>
            <p className="font-medium mt-1" style={{ color: 'var(--color-text)' }}>Local uniquement</p>
            <p className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>Jetons conservés sous forme hachée · accès révocables</p>
          </article>
        </section>

        <section className="rounded-2xl p-5 mb-5 flex items-start gap-4" style={{ background: 'color-mix(in srgb, var(--color-accent) 7%, var(--color-surface))', border: '1px solid color-mix(in srgb, var(--color-accent) 28%, var(--color-border))' }}>
          <WifiOff size={20} className="mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
          <div>
            <h2 className="font-medium" style={{ color: 'var(--color-text)' }}>Aucune ouverture réseau automatique</h2>
            <p className="text-sm mt-1 leading-6" style={{ color: 'var(--color-text-secondary)' }}>
              Le moteur hors ligne, les conflits et les files d'opérations sont prêts. Pour synchroniser réellement par Internet ou Wi-Fi, il reste à choisir et configurer un relais HTTPS de confiance. Diapason ne publie pas vos données ni son port local de lui-même.
            </p>
          </div>
        </section>

        <section className="grid lg:grid-cols-[0.9fr_1.1fr] gap-5">
          <div className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <div className="flex items-center gap-2 mb-1"><KeyRound size={17} style={{ color: 'var(--color-accent)' }} /><h2 className="font-medium" style={{ color: 'var(--color-text)' }}>Préparer un appareil</h2></div>
            <p className="text-xs mb-4" style={{ color: 'var(--color-text-tertiary)' }}>L'invitation expire après 10 minutes et ne peut être utilisée qu'une fois.</p>
            <label className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              Nom de l'appareil
              <input value={deviceName} onChange={(event) => setDeviceName(event.target.value)} maxLength={80} className="mt-1 w-full rounded-xl px-3 py-2.5 bg-transparent outline-none" style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
            </label>
            <button type="button" disabled={!deviceName.trim() || working} onClick={() => void preparePairing()} className="mt-3 w-full px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-40 cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>Créer une invitation</button>
            {invitation && (
              <div className="mt-4 rounded-xl p-3" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                <div className="flex items-center justify-between gap-3 mb-2">
                  <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Code temporaire · expire à {formatDate(invitation.expiresAtMs)}</p>
                  <button type="button" onClick={() => void copyInvitation()} aria-label="Copier le code" className="size-8 rounded-lg flex items-center justify-center cursor-pointer" style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-tertiary)' }}>{copied ? <Check size={14} /> : <Clipboard size={14} />}</button>
                </div>
                <code className="block text-xs break-all select-all" style={{ color: 'var(--color-text-secondary)' }}>{invitation.pairingToken}</code>
              </div>
            )}
          </div>

          <div className="rounded-2xl p-5" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <h2 className="font-medium mb-4" style={{ color: 'var(--color-text)' }}>Appareils autorisés</h2>
            {!loading && !status?.peers.length && (
              <div className="py-10 text-center">
                <Smartphone className="mx-auto mb-3" style={{ color: 'var(--color-text-tertiary)' }} />
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Aucun autre appareil autorisé</p>
                <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Vos données restent uniquement sur ce Mac.</p>
              </div>
            )}
            <div className="grid gap-2">
              {status?.peers.map((peer) => (
                <article key={peer.id} className="flex items-center gap-3 rounded-xl p-3" style={{ background: 'var(--color-bg-secondary)' }}>
                  <div className="size-9 rounded-lg flex items-center justify-center" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-accent)' }}><Smartphone size={16} /></div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>{peer.deviceName}</p>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>Dernier échange : {formatDate(peer.lastSeenAtMs)}</p>
                  </div>
                  <button type="button" disabled={working} onClick={() => void revoke(peer.id, peer.deviceName)} aria-label={`Retirer ${peer.deviceName}`} className="size-9 rounded-lg flex items-center justify-center cursor-pointer disabled:opacity-40" style={{ color: 'var(--color-danger, #ef4444)', background: 'var(--color-bg-tertiary)' }}><Trash2 size={15} /></button>
                </article>
              ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
