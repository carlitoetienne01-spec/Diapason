import { useState } from 'react';

import { useTranslation } from '../i18n/useTranslation';
import type { MessageKey } from '../i18n/translate';
import { releveNavigation, resumer, type GenreVisite } from '../lib/mesuresNavigation';

/** Le nom de chaque page, celui de la navigation ; une route inconnue garde son chemin. */
const NOMS_DES_ROUTES: Record<string, MessageKey> = {
  '/': 'nav.chat',
  '/vie/tasks': 'nav.vieTasks',
  '/vie/planner': 'nav.viePlanner',
  '/vie/notes': 'nav.vieNotes',
  '/vie/projects': 'nav.vieProjects',
  '/vie/finances': 'nav.vieFinances',
  '/vie/habits': 'nav.vieHabits',
  '/vie/year-review': 'nav.vieYearReview',
  '/vie/dashboard': 'nav.vieDashboard',
  '/vie/sync': 'nav.vieSync',
  '/settings': 'nav.settings',
  '/devices': 'nav.devices',
  '/dashboard': 'nav.dashboard',
  '/agents': 'nav.agents',
  '/logs': 'nav.logs',
  '/data-sources': 'nav.dataSources',
  '/get-started': 'nav.getStarted',
};

const NOMS_DES_GENRES: Record<GenreVisite, MessageKey> = {
  ouverture: 'settings.fluidite.kindOpening',
  premiere: 'settings.fluidite.kindFirst',
  revisite: 'settings.fluidite.kindReturn',
};

/**
 * Réglages → « Mesures de fluidité », au téléphone seulement (26/09/2026,
 * chantier de la fluidité, lot 2) : médiane et 90e centile du temps jusqu'au
 * contenu, par page, relevés dans CETTE WebView (lib/mesuresNavigation.ts).
 * Carlito y lit les chiffres de son téléphone, pas ceux du banc du Mac.
 */
export function MesuresFluidite() {
  const { t, locale } = useTranslation();
  const [lignes, setLignes] = useState(() => resumer(releveNavigation.echantillons()));
  const actualiser = () => setLignes(resumer(releveNavigation.echantillons()));
  const effacer = () => {
    releveNavigation.effacer();
    actualiser();
  };
  const nombre = new Intl.NumberFormat(locale === 'fr' ? 'fr-CA' : 'en-CA');
  const ms = (valeur: number) => `${nombre.format(valeur)} ms`;
  const auPlafond = lignes.reduce((total, ligne) => total + ligne.auPlafond, 0);
  const bouton = 'min-h-10 px-3 rounded-lg text-xs font-medium';
  const styleBouton = { color: 'var(--color-text)', border: '1px solid var(--color-border)' };

  return (
    <div className="grid gap-3">
      <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        {t('settings.fluidite.description')}
      </p>
      {lignes.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          {t('settings.fluidite.empty')}
        </p>
      ) : (
        <table className="w-full text-xs tabular-nums" style={{ color: 'var(--color-text)' }}>
          <thead>
            <tr style={{ color: 'var(--color-text-tertiary)' }}>
              <th className="text-left font-medium py-1 pr-2">{t('settings.fluidite.page')}</th>
              <th className="text-left font-medium py-1 pr-2">{t('settings.fluidite.kind')}</th>
              <th className="text-right font-medium py-1 pr-2">{t('settings.fluidite.count')}</th>
              <th className="text-right font-medium py-1 pr-2">{t('settings.fluidite.median')}</th>
              <th className="text-right font-medium py-1">{t('settings.fluidite.p90')}</th>
            </tr>
          </thead>
          <tbody>
            {lignes.map((ligne) => (
              <tr key={`${ligne.route} ${ligne.genre}`} style={{ borderTop: '1px solid var(--color-border-subtle)' }}>
                <td className="py-1.5 pr-2">{NOMS_DES_ROUTES[ligne.route] ? t(NOMS_DES_ROUTES[ligne.route]) : ligne.route}</td>
                <td className="py-1.5 pr-2" style={{ color: 'var(--color-text-secondary)' }}>
                  {t(NOMS_DES_GENRES[ligne.genre])}
                </td>
                <td className="py-1.5 pr-2 text-right">{ligne.n}</td>
                <td className="py-1.5 pr-2 text-right">{ms(ligne.medianeMs)}</td>
                <td className="py-1.5 text-right">{ms(ligne.p90Ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {auPlafond > 0 && (
        <p className="text-xs" style={{ color: 'var(--color-warning)' }}>
          {t('settings.fluidite.capped', { count: auPlafond })}
        </p>
      )}
      <div className="flex gap-2">
        <button type="button" className={bouton} style={styleBouton} onClick={actualiser}>
          {t('settings.fluidite.refresh')}
        </button>
        <button type="button" className={bouton} style={styleBouton} onClick={effacer} disabled={lignes.length === 0}>
          {t('settings.fluidite.clear')}
        </button>
      </div>
    </div>
  );
}
