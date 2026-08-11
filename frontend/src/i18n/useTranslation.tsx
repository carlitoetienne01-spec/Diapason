import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { DEFAULT_LOCALE, detectLocale, isLocale, type Locale } from './locale';
import { translate, type MessageKey, type Vars } from './translate';

const STORAGE_KEY = 'diapason-locale';

interface TranslationContext {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, vars?: Vars) => string;
}

const Context = createContext<TranslationContext | null>(null);

function readStored(): Locale | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return isLocale(raw) ? raw : null;
  } catch {
    // Private browsing, or storage disabled: fall through to detection.
    return null;
  }
}

export function TranslationProvider({ children }: { children: React.ReactNode }) {
  // A stored choice always wins over detection — someone who picked English on
  // a French machine meant it, and re-detecting on every launch would silently
  // overrule them.
  const [locale, setLocaleState] = useState<Locale>(
    () => readStored() ?? detectLocale(),
  );

  useEffect(() => {
    // Screen readers and CSS hyphenation both key off this, so it is not
    // decoration: leaving it at the wrong language mispronounces the whole UI.
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // The choice still applies for this session; it just will not persist.
    }
  }, []);

  const value = useMemo<TranslationContext>(
    () => ({
      locale,
      setLocale,
      t: (key, vars) => translate(locale, key, vars),
    }),
    [locale, setLocale],
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useTranslation(): TranslationContext {
  const context = useContext(Context);
  // Rendering English rather than throwing: a component mounted outside the
  // provider — a test, a portal, an error boundary's fallback — should still
  // show words.
  if (context === null) {
    return {
      locale: DEFAULT_LOCALE,
      setLocale: () => {},
      t: (key, vars) => translate(DEFAULT_LOCALE, key, vars),
    };
  }
  return context;
}
