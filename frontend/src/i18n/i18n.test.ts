import { describe, expect, it } from 'vitest';

import { DEFAULT_LOCALE, LOCALES, detectLocale, isLocale } from './locale';
import { MESSAGES } from './messages';
import { interpolate, translate } from './translate';

describe('locale detection', () => {
  it('takes the first supported language the browser offers', () => {
    expect(detectLocale(['de', 'fr', 'en'])).toBe('fr');
  });

  it('matches on the base tag, not the full one', () => {
    // fr-CA and fr-FR are both French; comparing whole tags would miss them
    // and quietly hand a French speaker an English interface.
    expect(detectLocale(['fr-CA'])).toBe('fr');
    expect(detectLocale(['en-GB'])).toBe('en');
  });

  it('is case-insensitive', () => {
    expect(detectLocale(['FR-fr'])).toBe('fr');
  });

  it('falls back when nothing matches', () => {
    expect(detectLocale(['de', 'ja'])).toBe(DEFAULT_LOCALE);
    expect(detectLocale([])).toBe(DEFAULT_LOCALE);
  });

  it('rejects anything that is not a supported locale', () => {
    expect(isLocale('fr')).toBe(true);
    expect(isLocale('de')).toBe(false);
    expect(isLocale(null)).toBe(false);
    expect(isLocale(42)).toBe(false);
  });
});

describe('catalogue', () => {
  const enKeys = Object.keys(MESSAGES.en).sort();

  it('covers every locale', () => {
    for (const locale of LOCALES) {
      expect(MESSAGES[locale], `catalogue manquant pour ${locale}`).toBeDefined();
    }
  });

  it.each(LOCALES)('%s has exactly the English keys — no more, no less', (locale) => {
    // A missing key renders English inside a French sentence; an extra one is
    // dead weight nobody will ever notice is unused.
    expect(Object.keys(MESSAGES[locale]).sort()).toEqual(enKeys);
  });

  it('has no empty string anywhere', () => {
    for (const locale of LOCALES) {
      const blank = Object.entries(MESSAGES[locale])
        .filter(([, value]) => !String(value).trim())
        .map(([key]) => key);
      expect(blank, `entrées vides en ${locale}`).toEqual([]);
    }
  });

  // Times are the one place where the two languages legitimately want
  // different variables: English says "2 PM", French says "14 h". Both are
  // supplied by the caller, so the divergence is intended, not a drift.
  const DIFFERENT_VARS_ON_PURPOSE = new Set([
    'agents.schedule.hourAm',
    'agents.schedule.hourPm',
    'agents.schedule.timeAm',
    'agents.schedule.timePm',
  ]);

  it('keeps the same placeholders in both languages', () => {
    // A translation that drops {name} renders a sentence with a hole in it,
    // and one that invents {nom} renders the placeholder verbatim.
    const names = (text: string) =>
      (String(text).match(/\{(\w+)\}/g) ?? []).sort().join(',');
    const mismatched: string[] = [];
    for (const key of enKeys) {
      if (DIFFERENT_VARS_ON_PURPOSE.has(key)) continue;
      const en = names(MESSAGES.en[key as keyof typeof MESSAGES.en]);
      const fr = names(MESSAGES.fr[key as keyof typeof MESSAGES.fr]);
      if (en !== fr) mismatched.push(`${key}: en=[${en}] fr=[${fr}]`);
    }
    expect(mismatched).toEqual([]);
  });

  it('keeps plural forms paired', () => {
    // If one language offers two forms and the other one, the singular or the
    // plural is wrong in half the cases.
    const forms = (text: string) => String(text).split('|').length;
    const mismatched: string[] = [];
    for (const key of enKeys) {
      const en = forms(MESSAGES.en[key as keyof typeof MESSAGES.en]);
      const fr = forms(MESSAGES.fr[key as keyof typeof MESSAGES.fr]);
      if (en !== fr) mismatched.push(`${key}: en=${en} formes, fr=${fr}`);
    }
    expect(mismatched).toEqual([]);
  });

  it('never translates the product name', () => {
    // "diapason" is an ordinary French word (a tuning fork), so a translator
    // rendering the brand as a common noun is a real risk. Command lines and
    // paths — `diapason serve`, ~/.diapason/ — are legitimately lowercase and
    // are not the brand, so they are excluded rather than force-capitalised.
    // "diapason " followed by a lowercase word is an invocation, not the
    // brand — as are backticks, paths and flags.
    const looksLikeCommandOrPath = (value: string) =>
      /`|~\/\.|--|\/|\.json|\.toml|diapason [a-z-]+ ?/.test(value);
    const wrong = Object.entries(MESSAGES.fr)
      .filter(
        ([, value]) =>
          /diapason/i.test(value) &&
          !value.includes('Diapason') &&
          !looksLikeCommandOrPath(value),
      )
      .map(([key]) => key);
    expect(wrong).toEqual([]);
  });

  it('has French that is actually French', () => {
    // Cheap smoke test against a catalogue that was copied but never
    // translated: some accented character must appear somewhere.
    const accented = Object.values(MESSAGES.fr).filter((v) =>
      /[éèêàçùôûîï]/i.test(String(v)),
    );
    expect(accented.length).toBeGreaterThan(0);
  });
});

describe('translate', () => {
  it('returns the message for the locale', () => {
    expect(translate('fr', 'nav.settings')).toBe('Réglages');
    expect(translate('en', 'nav.settings')).toBe('Settings');
  });

  it('falls back to English rather than showing a key', () => {
    // Seeing "settings.theme.label" on screen is worse than seeing English.
    const missing = 'definitely.not.a.key' as never;
    expect(translate('fr', missing)).toBe('definitely.not.a.key');
  });

  it('substitutes variables', () => {
    expect(interpolate('Bonjour {name}', { name: 'Carlito' })).toBe(
      'Bonjour Carlito',
    );
  });

  it('leaves an unknown placeholder visible', () => {
    // Rendering nothing would hide the bug behind a plausible sentence.
    expect(interpolate('Bonjour {name}', { other: 'x' })).toBe('Bonjour {name}');
  });

  it('handles a message with no variables at all', () => {
    expect(interpolate('Réglages')).toBe('Réglages');
  });
});

describe('plurals', () => {
  const catalogue = MESSAGES as unknown as {
    en: Record<string, string>;
    fr: Record<string, string>;
  };

  it('picks the singular for one', () => {
    catalogue.en['test.plural'] = '{count} file | {count} files';
    catalogue.fr['test.plural'] = '{count} fichier | {count} fichiers';
    expect(translate('en', 'test.plural' as never, { count: 1 })).toBe('1 file');
    expect(translate('fr', 'test.plural' as never, { count: 1 })).toBe('1 fichier');
  });

  it('picks the plural for many', () => {
    expect(translate('fr', 'test.plural' as never, { count: 7 })).toBe('7 fichiers');
  });

  it('treats zero as singular in French and plural in English', () => {
    // The rule French speakers expect and English speakers do not — taken from
    // Intl.PluralRules rather than hand-written, which is the whole point.
    expect(translate('fr', 'test.plural' as never, { count: 0 })).toBe('0 fichier');
    expect(translate('en', 'test.plural' as never, { count: 0 })).toBe('0 files');
    delete catalogue.en['test.plural'];
    delete catalogue.fr['test.plural'];
  });
});
