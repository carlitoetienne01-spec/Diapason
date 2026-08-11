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
