import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadReseauVue, saveReseauVue } from './uiPrefs';

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

describe('la vue du réseau retenue', () => {
  it('ne rend rien tant que rien n’a été choisi — c’est le CSS qui décide', () => {
    // Un défaut posé ici serait lu en JS ; sous `sm` la Liste s'affiche par
    // le CSS, sans que la largeur soit jamais lue par la vue.
    expect(loadReseauVue()).toBeUndefined();
  });

  it('rend le choix tel quel, Graphe comme Liste', () => {
    saveReseauVue('liste');
    expect(loadReseauVue()).toBe('liste');
    saveReseauVue('graphe');
    expect(loadReseauVue()).toBe('graphe');
  });

  it('ignore une valeur inconnue écrite à la main dans le stockage', () => {
    localStorage.setItem('diapason-succes-ui-prefs', JSON.stringify({ reseauVue: 'carte' }));
    expect(loadReseauVue()).toBeUndefined();
  });
});
