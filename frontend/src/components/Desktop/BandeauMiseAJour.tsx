// Le bandeau de mise à jour, dans la barre latérale — au-dessus de Réglages
// et Parler, un seul bouton : « Installer ».
//
// Avant, un bandeau en surimpression tout en haut de la fenêtre, aux
// couleurs d'un thème étranger, avec trois boutons. Demandé le 13 septembre
// 2026 : qu'il vive en bas, dans les couleurs de l'app, et qu'un clic
// suffise. La logique (quand vérifier, comment compter) est dans
// `miseAJour.ts` ; ici, le crochet qui parle au plugin et le dessin.

import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, Loader2, RefreshCw, Sparkles, X } from 'lucide-react';

import { useTranslation } from '../../i18n/useTranslation';
import { isTauri } from '../../lib/api';
import {
  INTERVALLE_VERIFICATION_MS,
  doitVerifier,
  isAutoUpdateDisabled,
  pourcentage,
  versionSimulee,
  type EtatMiseAJour,
} from './miseAJour';

interface Update {
  version: string;
  contentLength?: number;
  downloadAndInstall: (
    onEvent: (e: { event: string; data?: { chunkLength?: number } }) => void,
  ) => Promise<void>;
}

/** Ce que sait le bandeau : l'état, la version, l'avancement, les gestes. */
export function useMiseAJour() {
  const [etat, setEtat] = useState<EtatMiseAJour>('aucune');
  const [version, setVersion] = useState('');
  const [progres, setProgres] = useState(0);
  const [ecartee, setEcartee] = useState(false);
  const miseAJour = useRef<Update | null>(null);

  const verifier = useCallback(async () => {
    if (isAutoUpdateDisabled()) return;
    // En développement (navigateur), une version posée dans localStorage
    // fait apparaître le bandeau ; on ne peut pas publier pour le voir.
    const simulee = versionSimulee(isTauri());
    if (simulee) {
      miseAJour.current = {
        version: simulee,
        contentLength: 100,
        downloadAndInstall: async (onEvent) => {
          for (let i = 0; i < 10; i += 1) {
            await new Promise((r) => window.setTimeout(r, 120));
            onEvent({ event: 'Progress', data: { chunkLength: 10 } });
          }
          onEvent({ event: 'Finished' });
        },
      };
      setVersion(simulee);
      setEtat('disponible');
      return;
    }
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const update = await check();
      if (update) {
        miseAJour.current = update as unknown as Update;
        setVersion(update.version);
        setEtat('disponible');
        setEcartee(false);
      }
    } catch {
      // Pas de version publiée (404), pas de réseau : il n'y a rien à dire.
    }
  }, []);

  useEffect(() => {
    const estTauri = isTauri();
    const variableDev = (import.meta as unknown as { env?: Record<string, string> }).env
      ?.VITE_DIAPASON_NO_UPDATER;
    const simulee = versionSimulee(estTauri);
    if (!simulee && !doitVerifier({ estTauri, desactivee: isAutoUpdateDisabled(), variableDev })) {
      return;
    }
    void verifier();
    const id = window.setInterval(() => void verifier(), INTERVALLE_VERIFICATION_MS);
    return () => window.clearInterval(id);
  }, [verifier]);

  const installer = useCallback(async () => {
    const update = miseAJour.current;
    if (!update) return;
    setEtat('installation');
    setProgres(0);
    let telecharge = 0;
    try {
      await update.downloadAndInstall((e) => {
        if (e.event === 'Progress') {
          telecharge += e.data?.chunkLength ?? 0;
          setProgres(pourcentage(telecharge, update.contentLength));
        } else if (e.event === 'Finished') {
          setProgres(100);
        }
      });
      setEtat('prete');
    } catch {
      setEtat('echec');
      // Le bandeau se retire de lui-même : une erreur qui reste affichée
      // dans une barre latérale devient du bruit. La prochaine vérification
      // le fera revenir si la mise à jour est toujours là.
      window.setTimeout(() => setEtat('aucune'), 6000);
    }
  }, []);

  const relancer = useCallback(async () => {
    try {
      const { relaunch } = await import('@tauri-apps/plugin-process');
      await relaunch();
    } catch {
      // Hors de l'app de bureau (simulation), il n'y a rien à relancer.
      setEtat('aucune');
    }
  }, []);

  return { etat, version, progres, ecartee, installer, relancer, ecarter: () => setEcartee(true) };
}

export function BandeauMiseAJour() {
  const { t } = useTranslation();
  const { etat, version, progres, ecartee, installer, relancer, ecarter } = useMiseAJour();

  if (etat === 'aucune' || ecartee) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="mx-3 mb-2 rounded-xl px-3 py-2.5 text-xs"
      style={{
        background: 'var(--color-accent-subtle)',
        border: '1px solid var(--color-accent)',
        color: 'var(--color-text)',
      }}
    >
      {etat === 'disponible' && (
        <div className="grid gap-2">
          {/* Deux rangées : la barre fait ~300 px, et « Nouvelle version
              1.2.3 » + « Installer » sur une seule ligne tronquait le titre
              à « Nouvelle v… » (vu le 13 septembre 2026). */}
          <div className="flex items-center gap-2">
            <Sparkles size={14} className="shrink-0" style={{ color: 'var(--color-accent)' }} />
            <span className="flex-1 min-w-0 truncate font-medium">
              {t('update.sidebar.title', { version })}
            </span>
            <button
              type="button"
              onClick={ecarter}
              aria-label={t('update.sidebar.dismiss')}
              title={t('update.sidebar.dismiss')}
              className="rounded-md p-1 cursor-pointer shrink-0"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              <X size={12} />
            </button>
          </div>
          <button
            type="button"
            onClick={() => void installer()}
            className="flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium cursor-pointer w-full"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            <ArrowDownToLine size={12} />
            {t('update.sidebar.install')}
          </button>
        </div>
      )}

      {etat === 'installation' && (
        <div className="grid gap-1.5">
          <div className="flex items-center gap-2">
            <Loader2 size={14} className="animate-spin shrink-0" style={{ color: 'var(--color-accent)' }} />
            <span className="flex-1 min-w-0 truncate">
              {t('update.sidebar.installing', { progress: progres })}
            </span>
          </div>
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-secondary)' }}>
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${progres}%`, background: 'var(--color-accent)' }}
            />
          </div>
        </div>
      )}

      {etat === 'prete' && (
        <div className="grid gap-2">
          <div className="flex items-center gap-2">
            <Sparkles size={14} className="shrink-0" style={{ color: 'var(--color-accent)' }} />
            <span className="flex-1 min-w-0 truncate font-medium">
              {t('update.sidebar.ready', { version })}
            </span>
          </div>
          <button
            type="button"
            onClick={() => void relancer()}
            className="flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium cursor-pointer w-full"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            <RefreshCw size={12} />
            {t('update.sidebar.relaunch')}
          </button>
        </div>
      )}

      {etat === 'echec' && (
        <div className="flex items-center gap-2" style={{ color: 'var(--color-text-secondary)' }}>
          <X size={14} className="shrink-0" />
          <span className="flex-1 min-w-0 truncate">{t('update.sidebar.failed')}</span>
        </div>
      )}
    </div>
  );
}
