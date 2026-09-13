import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  CLE_SIMULATION,
  doitVerifier,
  isAutoUpdateDisabled,
  pourcentage,
  setAutoUpdateDisabled,
  versionSimulee,
} from './miseAJour';

// jsdom sous vitest n'expose pas de `localStorage` utilisable (origine
// opaque) : un stockage en mémoire, réel dans son comportement, suffit.
function stockage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => {
      m.delete(k);
    },
    setItem: (k, v) => {
      m.set(k, String(v));
    },
  };
}

beforeEach(() => {
  vi.stubGlobal('localStorage', stockage());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('pourcentage', () => {
  it('borne et arrondit', () => {
    expect(pourcentage(50, 200)).toBe(25);
    expect(pourcentage(300, 200)).toBe(100);
    expect(pourcentage(-5, 200)).toBe(0);
    expect(pourcentage(199.6, 200)).toBe(100);
  });

  it('ne divise jamais par rien — sans taille annoncée, zéro', () => {
    expect(pourcentage(50, 0)).toBe(0);
    expect(pourcentage(50, null)).toBe(0);
    expect(pourcentage(50, undefined)).toBe(0);
    expect(pourcentage(NaN, 200)).toBe(0);
  });
});

describe('doitVerifier', () => {
  it('seulement dans l’app de bureau, si personne ne l’a éteinte', () => {
    expect(doitVerifier({ estTauri: true, desactivee: false, variableDev: undefined })).toBe(true);
    expect(doitVerifier({ estTauri: false, desactivee: false, variableDev: undefined })).toBe(false);
    expect(doitVerifier({ estTauri: true, desactivee: true, variableDev: undefined })).toBe(false);
  });

  it('respecte la variable du développeur, en 1 ou true, sans casse', () => {
    expect(doitVerifier({ estTauri: true, desactivee: false, variableDev: '1' })).toBe(false);
    expect(doitVerifier({ estTauri: true, desactivee: false, variableDev: 'TRUE' })).toBe(false);
    expect(doitVerifier({ estTauri: true, desactivee: false, variableDev: '0' })).toBe(true);
  });
});

describe('le réglage « désactivé »', () => {
  it('se garde et se retire', () => {
    expect(isAutoUpdateDisabled()).toBe(false);
    setAutoUpdateDisabled(true);
    expect(isAutoUpdateDisabled()).toBe(true);
    setAutoUpdateDisabled(false);
    expect(isAutoUpdateDisabled()).toBe(false);
  });
});

describe('versionSimulee', () => {
  it('ne lit la simulation que hors de l’app de bureau', () => {
    localStorage.setItem(CLE_SIMULATION, ' 9.9.9 ');
    expect(versionSimulee(false)).toBe('9.9.9');
    expect(versionSimulee(true)).toBe('');
  });
});
