/**
 * Language selection: what it is, where it comes from, where it is kept.
 *
 * Deliberately free of React and of the message catalogue, so both the app and
 * the tests can reason about a locale without pulling in either.
 */

export const LOCALES = ['fr', 'en'] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = 'en';

export const LOCALE_NAMES: Record<Locale, string> = {
  fr: 'Français',
  en: 'English',
};

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value);
}

/**
 * Best guess from what the browser advertises.
 *
 * `navigator.languages` is ordered by preference, so the first entry whose
 * base tag we support wins — `fr-CA` and `fr` must both give French, which a
 * plain equality check on the full tag would miss.
 */
export function detectLocale(
  languages: readonly string[] = typeof navigator === 'undefined'
    ? []
    : (navigator.languages ?? [navigator.language]),
): Locale {
  for (const tag of languages) {
    const base = String(tag).toLowerCase().split('-')[0];
    if (isLocale(base)) return base;
  }
  return DEFAULT_LOCALE;
}

/**
 * La langue de l'interface, lue HORS de React.
 *
 * 26/09/2026 : le pont natif et les fonctions d'`api.ts` lèvent des erreurs
 * que l'interface affiche telles quelles, sans passer par `useTranslation`.
 * Elles étaient écrites en anglais en dur (« … in the desktop app only. »),
 * donc affichées en anglais à qui avait choisi le français. `<html lang>` est
 * posé par `TranslationProvider` au premier rendu : c'est la même source que
 * l'interface, sans dépendre de React ni du catalogue.
 */
export function localeDuDocument(lang?: string | null, languages?: readonly string[]): Locale {
  const valeur = lang === undefined ? langDuDocument() : lang;
  return isLocale(valeur) ? valeur : detectLocale(languages);
}

// Lu dans un CORPS de fonction, jamais dans une valeur par défaut de
// paramètre. 26/09/2026 : `document.documentElement?.getAttribute?.('lang')`
// en valeur par défaut, abaissé par esbuild pour la cible de Vite (es2020,
// safari14…), devenait `_b.call(_a, "lang")` avec `_a` hors de portée :
// « n is not defined » dans le bundle construit, à chaque erreur traduite
// hors de React — alors que vitest, qui n'abaisse rien, restait vert.
function langDuDocument(): string | null {
  if (typeof document === 'undefined') return null;
  const racine = document.documentElement;
  if (!racine || typeof racine.getAttribute !== 'function') return null;
  return racine.getAttribute('lang');
}
