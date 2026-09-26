import { describe, expect, it } from 'vitest';

import { hotesDuMac } from './hotesDuMac';

describe('Ce que seule la fenêtre du Mac monte', () => {
  it('le téléphone ne vide pas la boîte du Mac et ne publie pas sa vue', () => {
    // Échec évité (26/09/2026) : la WebView du téléphone relevait
    // /v1/mesh/inbox?drain=true et avalait les navigations du Mac.
    expect(hotesDuMac(true, false)).toEqual({ boiteDuMaillage: false, contexteDeLaVue: false });
    expect(hotesDuMac(true, true)).toEqual({ boiteDuMaillage: false, contexteDeLaVue: false });
  });

  it('le mini-panneau n’est pas un second lecteur de la boîte', () => {
    expect(hotesDuMac(false, true)).toEqual({ boiteDuMaillage: false, contexteDeLaVue: true });
  });

  it('la fenêtre du Mac monte les deux', () => {
    expect(hotesDuMac(false, false)).toEqual({ boiteDuMaillage: true, contexteDeLaVue: true });
  });
});
