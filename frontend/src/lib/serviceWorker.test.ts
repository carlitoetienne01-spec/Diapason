// Le service worker : inscrit sur le Mac, désinscrit au téléphone (plan
// mobile, phase 3, étape 7 — 26/09/2026).

import { describe, expect, it, vi } from 'vitest';

import { gererLeServiceWorker, type CachesSW, type ConteneurSW } from './serviceWorker';

function faux(inscriptions = 0) {
  const desinscrire = vi.fn(async () => true);
  const conteneur: ConteneurSW = {
    register: vi.fn(async () => ({})),
    getRegistrations: vi.fn(async () => Array.from({ length: inscriptions }, () => ({ unregister: desinscrire }))),
  };
  return { conteneur, desinscrire };
}

function fauxCaches(noms: string[]) {
  const effaces: string[] = [];
  const caches: CachesSW = {
    keys: async () => noms,
    delete: async (nom) => {
      effaces.push(nom);
      return true;
    },
  };
  return { caches, effaces };
}

describe('gererLeServiceWorker', () => {
  it('inscrit /sw.js sur le Mac, comme registerSW.js le faisait', async () => {
    const { conteneur } = faux();
    await expect(gererLeServiceWorker({ conteneur, servi: false, actif: true })).resolves.toBe('inscrit');
    expect(conteneur.register).toHaveBeenCalledWith('/sw.js', { scope: '/' });
  });

  it('n’inscrit rien au téléphone, et désinscrit ce qu’un chargement précédent avait inscrit', async () => {
    const { conteneur, desinscrire } = faux(2);
    const { caches, effaces } = fauxCaches(['workbox-precache-v2-https://atelier/', 'autre-cache']);
    await expect(gererLeServiceWorker({ conteneur, caches, servi: true, actif: true })).resolves.toBe('desinscrit');
    expect(conteneur.register, 'une inscription au téléphone servirait un bundle en cache').not.toHaveBeenCalled();
    expect(desinscrire).toHaveBeenCalledTimes(2);
    expect(effaces, 'seul le précache de Workbox est vidé').toEqual(['workbox-precache-v2-https://atelier/']);
  });

  it('une désinscription qui échoue n’arrête pas les autres', async () => {
    const echec = vi.fn(async () => {
      throw new Error('refus');
    });
    const reussite = vi.fn(async () => true);
    const conteneur: ConteneurSW = {
      register: vi.fn(async () => ({})),
      getRegistrations: async () => [{ unregister: echec }, { unregister: reussite }],
    };
    await expect(gererLeServiceWorker({ conteneur, servi: true, actif: true })).resolves.toBe('desinscrit');
    expect(reussite).toHaveBeenCalled();
  });

  it('retire le worker ancien même si le nouveau build ne publie plus sw.js', async () => {
    const { conteneur, desinscrire } = faux(1);
    await expect(gererLeServiceWorker({ conteneur, servi: false, actif: false })).resolves.toBe('desinscrit');
    expect(conteneur.register).not.toHaveBeenCalled();
    expect(desinscrire).toHaveBeenCalledOnce();
  });

  it('le mini-panneau abandonne le cache ancien même avec un build PWA', async () => {
    const { conteneur, desinscrire } = faux(1);
    const { caches, effaces } = fauxCaches(['workbox-precache-v2-http://127.0.0.1:8000/', 'documents']);
    await expect(gererLeServiceWorker({ conteneur, caches, servi: false, compact: true, actif: true })).resolves.toBe('desinscrit');
    expect(conteneur.register, 'le panneau doit recevoir le même compositeur que l’app').not.toHaveBeenCalled();
    expect(desinscrire).toHaveBeenCalledOnce();
    expect(effaces, 'les données utilisateur restent intactes').toEqual(['workbox-precache-v2-http://127.0.0.1:8000/']);
  });

  it('se tait sans API de service worker', async () => {
    await expect(gererLeServiceWorker({ conteneur: null, servi: true, actif: true })).resolves.toBe('absent');
  });
});
