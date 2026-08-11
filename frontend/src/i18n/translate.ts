import { MESSAGES } from './messages';
import { DEFAULT_LOCALE, type Locale } from './locale';

/**
 * The translation function, and nothing else.
 *
 * English is the reference catalogue: its keys are the type, so a key that
 * exists in no language fails to compile, and a French entry that drifts from
 * it fails a test rather than silently rendering the wrong sentence.
 */
export type MessageKey = keyof typeof MESSAGES.en;

export type Vars = Record<string, string | number>;

const PLACEHOLDER = /\{(\w+)\}/g;

/**
 * Plural forms, written as `one | other` inside a single message.
 *
 * `Intl.PluralRules` is in every browser this app runs in, so the rules come
 * from the platform instead of a table this project would have to maintain —
 * and French's "0 and 1 are both singular" is handled without anyone here
 * having to know that.
 */
function selectPlural(text: string, locale: Locale, count: number): string {
  const forms = text.split('|').map((part) => part.trim());
  // Exactly two forms, or none. A message that happens to contain a pipe —
  // "install | status | logs" — is a list, not a plural, and splitting it
  // would silently show the user a fragment of their own command.
  if (forms.length !== 2) return text;
  const category = new Intl.PluralRules(locale).select(count);
  // Anything the platform reports that is not "one" takes the second form,
  // which is what both French and English need.
  return category === 'one' ? forms[0] : forms[1];
}

export function interpolate(text: string, vars?: Vars): string {
  if (!vars) return text;
  // An unknown placeholder is left verbatim: showing `{name}` points at the
  // bug, while an empty string quietly produces a sentence with a hole in it.
  return text.replace(PLACEHOLDER, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}

export function translate(locale: Locale, key: MessageKey, vars?: Vars): string {
  const catalogue = MESSAGES[locale] ?? MESSAGES[DEFAULT_LOCALE];
  // Fall back through English rather than rendering a raw key: a missing
  // French entry should read as untranslated, never as `settings.theme.label`.
  const raw =
    (catalogue as Record<string, string>)[key] ??
    (MESSAGES[DEFAULT_LOCALE] as Record<string, string>)[key] ??
    key;

  const text =
    typeof vars?.count === 'number'
      ? selectPlural(raw, locale, vars.count)
      : raw;
  return interpolate(text, vars);
}
