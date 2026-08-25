import { useCallback, useEffect, useState } from 'react';
import {
  Check,
  Clipboard,
  Laptop,
  Loader2,
  Monitor,
  Pencil,
  RefreshCw,
  ShieldOff,
  Smartphone,
  Tablet,
  Trash2,
  Globe,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  announceMeshPresence,
  createMeshPairing,
  fetchMeshIdentity,
  forgetMeshDevice,
  listMeshDevices,
  renameMeshDevice,
  revokeMeshDevice,
} from '../features/mesh/api';
import type {
  MeshDeviceType,
  MeshDeviceWithPresence,
  MeshIdentity,
  MeshPairingInvitation,
  MeshPresenceState,
} from '../features/mesh/types';
import { useConfirm } from '../components/ConfirmDialog';
import { PanneauGestes } from '../features/gestes/PanneauGestes';

const DEVICE_ICONS: Record<MeshDeviceType, typeof Monitor> = {
  DESKTOP: Monitor,
  LAPTOP: Laptop,
  PHONE: Smartphone,
  TABLET: Tablet,
  BROWSER: Globe,
};

/**
 * Presence is always shown as words, never as colour alone: the terminal skin
 * collapses success, warning and error onto a single ink, so a coloured dot
 * would say nothing there. The dot is decoration; the label is the message.
 */
const PRESENCE: Record<MeshPresenceState, { label: string; token: string }> = {
  ONLINE: { label: 'En ligne', token: 'var(--color-success)' },
  IDLE: { label: 'Inactif', token: 'var(--color-warning)' },
  BACKGROUND: { label: 'En arrière-plan', token: 'var(--color-warning)' },
  OFFLINE: { label: 'Hors ligne', token: 'var(--color-text-secondary)' },
};

function formatDate(value: number | null | undefined) {
  if (!value) return 'Jamais';
  return new Intl.DateTimeFormat('fr-CA', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

export function DevicesPage() {
  const confirm = useConfirm();
  const [identity, setIdentity] = useState<MeshIdentity | null>(null);
  const [devices, setDevices] = useState<MeshDeviceWithPresence[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [showRevoked, setShowRevoked] = useState(false);
  const [deviceName, setDeviceName] = useState('Mon autre appareil');
  const [invitation, setInvitation] = useState<MeshPairingInvitation | null>(null);
  const [copied, setCopied] = useState(false);
  const [renaming, setRenaming] = useState<{ id: string; value: string } | null>(null);

  /**
   * @param quiet background refreshes stay silent. A toast on every failed
   * refresh would fire every twenty seconds while the backend is busy, which
   * tells the user nothing they can act on and buries the toasts that matter.
   */
  const load = useCallback(
    async (quiet = false) => {
      try {
        const fleet = await listMeshDevices({ includeRevoked: showRevoked });
        setDevices(fleet);
      } catch (error) {
        if (!quiet) {
          toast.error('La liste des appareils est indisponible.', {
            description: error instanceof Error ? error.message : String(error),
          });
        }
      } finally {
        setLoading(false);
      }
    },
    [showRevoked],
  );

  // Fetched once: this machine's identity is fixed for the life of the
  // process, so re-reading it on every refresh would double the request cost
  // of the screen for an answer that cannot change.
  useEffect(() => {
    fetchMeshIdentity().then(setIdentity).catch(() => setIdentity(null));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Presence is derived from the last beacon, so it goes stale on its own.
  // Refreshing on a beat is what makes "en ligne" mean now rather than "the
  // last time this screen was opened". Twenty seconds sits just inside the
  // 45-second online window without spending the shared request budget.
  useEffect(() => {
    const timer = window.setInterval(() => void load(true), 20000);
    return () => window.clearInterval(timer);
  }, [load]);

  const invite = async () => {
    const name = deviceName.trim();
    if (!name) return;
    setWorking(true);
    try {
      const created = await createMeshPairing(name);
      setInvitation(created);
      setCopied(false);
    } catch (error) {
      toast.error("L'invitation n'a pas pu être créée.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setWorking(false);
    }
  };

  const copyToken = async () => {
    if (!invitation) return;
    try {
      await navigator.clipboard.writeText(invitation.pairingToken);
      setCopied(true);
      // Never toast the token itself: it is the credential that lets a device
      // into the fleet, and a toast is readable over someone's shoulder.
      toast.success('Code copié');
    } catch {
      toast.error('Le code n’a pas pu être copié.');
    }
  };

  const announce = async () => {
    setWorking(true);
    try {
      const result = await announceMeshPresence('foreground');
      toast.success(
        result.reached === 0
          ? 'Aucun appareil joint pour l’instant.'
          : `${result.reached} appareil(s) prévenu(s).`,
        {
          description:
            result.skipped > 0 ? `${result.skipped} injoignable(s).` : undefined,
        },
      );
      await load();
    } catch (error) {
      toast.error("L'annonce n'a pas pu être envoyée.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setWorking(false);
    }
  };

  const commitRename = async () => {
    if (!renaming) return;
    const name = renaming.value.trim();
    if (!name) return setRenaming(null);
    setWorking(true);
    try {
      await renameMeshDevice(renaming.id, name);
      setRenaming(null);
      await load();
    } catch (error) {
      toast.error('Le nom n’a pas pu être changé.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setWorking(false);
    }
  };

  const revoke = async (device: MeshDeviceWithPresence) => {
    const confirmed = await confirm({
      title: `Retirer « ${device.name} » du réseau ?`,
      description:
        'Cet appareil ne pourra plus rien envoyer ni recevoir, et ne pourra plus signaler sa présence. C’est définitif : pour le réadmettre il faudra l’oublier puis l’appairer à nouveau.',
      confirmLabel: 'Retirer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    setWorking(true);
    try {
      await revokeMeshDevice(device.deviceId);
      setShowRevoked(true);
      await load();
      toast.success(`${device.name} n’a plus accès.`);
    } catch (error) {
      toast.error("L'appareil n'a pas pu être retiré.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setWorking(false);
    }
  };

  const forget = async (device: MeshDeviceWithPresence) => {
    const confirmed = await confirm({
      title: `Oublier « ${device.name} » ?`,
      description:
        'Sa clé sera effacée de cet appareil. Il pourra être appairé de nouveau avec une nouvelle invitation.',
      confirmLabel: 'Oublier',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    setWorking(true);
    try {
      await forgetMeshDevice(device.deviceId);
      await load();
      toast.success(`${device.name} a été oublié.`);
    } catch (error) {
      toast.error("L'appareil n'a pas pu être oublié.", {
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
              <span
                className="text-xs font-medium tracking-[0.16em] uppercase"
                style={{ color: 'var(--color-accent)' }}
              >
                Diapason
              </span>
              {(loading || working) && (
                <Loader2
                  size={13}
                  className="animate-spin"
                  style={{ color: 'var(--color-accent)' }}
                />
              )}
            </div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
              Appareils
            </h1>
            <p
              className="text-sm mt-2 max-w-2xl"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              Vos appareils appairés, ce qu’ils savent faire et s’ils sont allumés. Chacun
              signe ce qu’il envoie ; rien ne circule sans être vérifié.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void announce()}
              disabled={working}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium cursor-pointer disabled:opacity-50"
              style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
            >
              <RefreshCw size={15} className={working ? 'animate-spin' : ''} /> Signaler ma
              présence
            </button>
          </div>
        </header>

        {/* Les gestes de la main (25/08/2026). Ici, parce que c'est la page
            des appareils : un geste est une manière de désigner un appareil
            autant qu'une manière d'agir. */}
        <div className="mb-7">
          <PanneauGestes />
        </div>

        {identity && (
          <section
            className="rounded-2xl border p-5 mb-5"
            style={{
              borderColor: 'var(--color-border)',
              background: 'var(--color-surface)',
            }}
          >
            <h2 className="text-sm font-semibold mb-1" style={{ color: 'var(--color-text)' }}>
              Cet appareil
            </h2>
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              {identity.name} · {identity.platform}
            </p>
            <p className="text-xs mt-2 font-mono" style={{ color: 'var(--color-text-secondary)' }}>
              {identity.deviceId}
            </p>
          </section>
        )}

        <section
          className="rounded-2xl border p-5 mb-5"
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}
        >
          <h2 className="text-sm font-semibold mb-1" style={{ color: 'var(--color-text)' }}>
            Ajouter un appareil
          </h2>
          <p className="text-sm mb-4" style={{ color: 'var(--color-text-secondary)' }}>
            Créez une invitation, puis saisissez le code sur l’autre appareil. Elle ne sert
            qu’une fois et expire au bout de dix minutes.
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              value={deviceName}
              onChange={(event) => setDeviceName(event.target.value)}
              placeholder="Nom de l’appareil"
              className="flex-1 min-w-[12rem] px-3 py-2 rounded-xl text-sm"
              style={{
                background: 'var(--color-bg)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
            />
            <button
              type="button"
              onClick={() => void invite()}
              disabled={working || !deviceName.trim()}
              className="px-4 py-2 rounded-xl text-sm font-medium cursor-pointer disabled:opacity-50"
              style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
            >
              Créer une invitation
            </button>
          </div>

          {invitation && (
            <div
              className="mt-4 rounded-xl p-4"
              style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}
            >
              <p className="text-xs mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                Code pour « {invitation.deviceName} » — valable{' '}
                {Math.round(invitation.expiresInSeconds / 60)} minutes. Ne le partagez pas.
              </p>
              <div className="flex items-center gap-2">
                <code
                  className="flex-1 text-xs font-mono break-all"
                  style={{ color: 'var(--color-text)' }}
                >
                  {invitation.pairingToken}
                </code>
                <button
                  type="button"
                  onClick={() => void copyToken()}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer"
                  style={{
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                >
                  {copied ? <Check size={13} /> : <Clipboard size={13} />}
                  {copied ? 'Copié' : 'Copier'}
                </button>
              </div>
            </div>
          )}
        </section>

        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
            Appareils appairés
          </h2>
          <label
            className="flex items-center gap-2 text-xs cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <input
              type="checkbox"
              checked={showRevoked}
              onChange={(event) => setShowRevoked(event.target.checked)}
            />
            Afficher les appareils retirés
          </label>
        </div>

        {!loading && devices.length === 0 && (
          <p
            className="rounded-2xl border p-6 text-sm text-center"
            style={{
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-secondary)',
            }}
          >
            Aucun autre appareil pour l’instant. Créez une invitation ci-dessus pour en
            ajouter un.
          </p>
        )}

        <ul className="flex flex-col gap-3">
          {devices.map((device) => {
            const Icon = DEVICE_ICONS[device.deviceType] ?? Monitor;
            const revoked = device.trustLevel === 'REVOKED';
            const presence = PRESENCE[device.presence.state] ?? PRESENCE.OFFLINE;
            return (
              <li
                key={device.deviceId}
                className="rounded-2xl border p-4"
                style={{
                  borderColor: 'var(--color-border)',
                  background: 'var(--color-surface)',
                  opacity: revoked ? 0.6 : 1,
                }}
              >
                <div className="flex items-start gap-3">
                  <Icon size={18} style={{ color: 'var(--color-text-secondary)' }} />
                  <div className="flex-1 min-w-0">
                    {renaming?.id === device.deviceId ? (
                      <div className="flex gap-2">
                        <input
                          autoFocus
                          value={renaming.value}
                          onChange={(event) =>
                            setRenaming({ id: device.deviceId, value: event.target.value })
                          }
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') void commitRename();
                            if (event.key === 'Escape') setRenaming(null);
                          }}
                          className="flex-1 px-2 py-1 rounded-lg text-sm"
                          style={{
                            background: 'var(--color-bg)',
                            color: 'var(--color-text)',
                            border: '1px solid var(--color-border)',
                          }}
                        />
                        <button
                          type="button"
                          onClick={() => void commitRename()}
                          className="px-3 py-1 rounded-lg text-xs cursor-pointer"
                          style={{
                            background: 'var(--color-accent)',
                            color: 'var(--color-on-accent)',
                          }}
                        >
                          Renommer
                        </button>
                      </div>
                    ) : (
                      <p
                        className="text-sm font-medium truncate"
                        style={{ color: 'var(--color-text)' }}
                      >
                        {device.name}
                      </p>
                    )}
                    <div
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-xs"
                      style={{ color: 'var(--color-text-secondary)' }}
                    >
                      <span className="flex items-center gap-1.5">
                        <span
                          aria-hidden
                          className="inline-block w-1.5 h-1.5 rounded-full"
                          style={{ background: presence.token }}
                        />
                        {revoked ? 'Retiré' : presence.label}
                      </span>
                      <span>{device.platform}</span>
                      <span>Vu {formatDate(device.lastSeenAtMs)}</span>
                      {device.address && <span className="font-mono">{device.address}</span>}
                    </div>
                    {device.capabilities.length > 0 && (
                      <p
                        className="text-xs mt-1.5"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        Peut : {device.capabilities.join(', ')}
                      </p>
                    )}
                    {device.declaredCapabilities.length > device.capabilities.length && (
                      // The gap between what a device claims and what it is
                      // granted is the whole explanation for "il ne peut pas
                      // faire ça" — hiding it would make the refusal arbitrary.
                      <p className="text-xs mt-1" style={{ color: 'var(--color-warning)' }}>
                        Certaines fonctions demandées ne sont pas permises sur ce type
                        d’appareil.
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    {!revoked && (
                      <>
                        <button
                          type="button"
                          title="Renommer"
                          onClick={() =>
                            setRenaming({ id: device.deviceId, value: device.name })
                          }
                          className="p-2 rounded-lg cursor-pointer"
                          style={{ color: 'var(--color-text-secondary)' }}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          title="Retirer du réseau"
                          onClick={() => void revoke(device)}
                          className="p-2 rounded-lg cursor-pointer"
                          style={{ color: 'var(--color-text-secondary)' }}
                        >
                          <ShieldOff size={14} />
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      title="Oublier"
                      onClick={() => void forget(device)}
                      className="p-2 rounded-lg cursor-pointer"
                      style={{ color: 'var(--color-text-secondary)' }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </main>
    </div>
  );
}

export default DevicesPage;
