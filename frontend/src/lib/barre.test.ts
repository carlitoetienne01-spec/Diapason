import { describe, expect, it } from 'vitest';

import {
  REQUETE_BARRE_EN_COLONNE,
  appliquerNavigation,
  barreApresNavigation,
  barreOuverteAuDemarrage,
  barreSuperposee,
  estCheminDesReglages,
  inscrireRetourBarre,
  retourFermeLaBarre,
} from './barre';
import { PontNatif } from './natif';

/** Une fenêtre dont la largeur est dite par la seule requête média. */
function largeur(px: number) {
  const requetes: string[] = [];
  const matchMedia = (requete: string) => {
    requetes.push(requete);
    const min = /min-width:\s*(\d+(?:\.\d+)?)rem/.exec(requete);
    return { matches: min ? px >= Number(min[1]) * 16 : false };
  };
  return { matchMedia, requetes };
}

describe('La barre démarre fermée là où elle couvrirait la page', () => {
  it('fermée à 390 px, la largeur d’un téléphone', () => {
    // Échec évité (26/09/2026, diapason-mobile.md étape 5) : ouverte au
    // lancement, le tiroir de 260 px cachait deux tiers de la Discussion.
    expect(barreOuverteAuDemarrage(largeur(390).matchMedia)).toBe(false);
  });

  it('fermée à 340 px, le mini-panneau le plus étroit', () => {
    expect(barreOuverteAuDemarrage(largeur(340).matchMedia)).toBe(false);
  });

  it('ouverte en colonne, dès 768 px (le point `md` de Tailwind)', () => {
    expect(barreOuverteAuDemarrage(largeur(768).matchMedia)).toBe(true);
    expect(barreOuverteAuDemarrage(largeur(1440).matchMedia)).toBe(true);
  });

  it('ouverte quand la fenêtre ne sait pas répondre, comme avant', () => {
    // jsdom et un rendu sans fenêtre n'ont pas de matchMedia : garder
    // l'ancien défaut plutôt que de cacher la navigation sur le bureau.
    expect(barreOuverteAuDemarrage(undefined)).toBe(true);
    const casse = () => {
      throw new Error('pas de média');
    };
    expect(barreSuperposee(casse)).toBe(false);
  });

  it('interroge une requête que les vieux WebKit comprennent', () => {
    // La syntaxe d'intervalle (`width < 48rem`) n'existe qu'à partir de
    // Safari 16.4 : ailleurs elle ne correspond jamais, et la barre serait
    // prise pour un tiroir sur tous les bureaux.
    const { matchMedia, requetes } = largeur(1024);
    barreSuperposee(matchMedia);
    expect(requetes).toEqual([REQUETE_BARRE_EN_COLONNE]);
    expect(REQUETE_BARRE_EN_COLONNE).toMatch(/^\(min-width: /);
  });
});

describe('Après une navigation, le tiroir se retire', () => {
  const tiroir = { ouverte: true, superposee: true };

  it('se referme après le choix d’une page de vie', () => {
    // Échec évité (26/09/2026) : toucher « Tâches » laissait le tiroir
    // par-dessus la page des tâches, à deviner derrière le voile.
    expect(barreApresNavigation({ ...tiroir, avant: '/', apres: '/vie/tasks' })).toBe(false);
  });

  it('se referme quand une discussion s’ouvre depuis la Discussion', () => {
    // Même chemin (« / »), autre fil : la navigation a bien eu lieu.
    expect(barreApresNavigation({ ...tiroir, avant: '/', apres: '/' })).toBe(false);
  });

  it('se referme après le choix d’un onglet des Réglages', () => {
    expect(barreApresNavigation({ ...tiroir, avant: '/settings', apres: '/agents' })).toBe(false);
  });

  it('reste ouvert quand « Réglages » remplace la liste par ses onglets', () => {
    // Refermer ici obligeait à rouvrir le tiroir pour voir les onglets
    // qu'on venait justement de demander.
    expect(barreApresNavigation({ ...tiroir, avant: '/vie/notes', apres: '/settings' })).toBe(true);
  });

  it('reste ouvert quand « Retour » quitte les Réglages', () => {
    expect(barreApresNavigation({ ...tiroir, avant: '/logs', apres: '/vie/notes' })).toBe(true);
  });

  it('ne touche jamais une colonne : le bureau garde sa barre', () => {
    expect(
      barreApresNavigation({ ouverte: true, superposee: false, avant: '/', apres: '/vie/tasks' }),
    ).toBe(true);
  });

  it('ne rouvre jamais une barre fermée', () => {
    expect(
      barreApresNavigation({ ouverte: false, superposee: true, avant: '/', apres: '/settings' }),
    ).toBe(false);
  });

  it('connaît toutes les pages du tiroir des Réglages', () => {
    for (const chemin of ['/settings', '/get-started', '/data-sources', '/agents', '/logs', '/vie/sync', '/devices', '/dashboard']) {
      expect(estCheminDesReglages(chemin), chemin).toBe(true);
    }
    expect(estCheminDesReglages('/vie/dashboard')).toBe(false);
  });
});

describe('Le retour d’Android ferme d’abord le tiroir', () => {
  it('consomme le retour quand le tiroir est ouvert', () => {
    expect(retourFermeLaBarre(true, true)).toBe(true);
  });

  it('laisse le retour à la coquille quand rien n’est à fermer', () => {
    // `false` fait faire `goBack()` à la coquille : un retour avalé sans
    // rien fermer bloquerait la personne sur la page.
    expect(retourFermeLaBarre(false, true)).toBe(false);
  });

  it('ne ferme pas une colonne (téléphone à l’horizontale)', () => {
    expect(retourFermeLaBarre(true, false)).toBe(false);
  });
});

describe('Le câblage de la barre au store et au retour d’Android', () => {
  // Échec évité (26/09/2026) : l'effet de Sidebar.tsx qui applique
  // `barreApresNavigation`, et l'inscription au retour, pouvaient
  // disparaître sans un rouge — les fonctions pures, elles, restaient vertes.
  function etat(ouverte: boolean) {
    const e = {
      sidebarOpen: ouverte,
      setSidebarOpen: (o: boolean) => {
        e.sidebarOpen = o;
      },
    };
    return e;
  }

  it('une navigation dans le tiroir le referme', () => {
    const e = etat(true);
    appliquerNavigation(e, { superposee: true, avant: '/', apres: '/vie/tasks' });
    expect(e.sidebarOpen).toBe(false);
  });

  it('le retour d’Android ferme le tiroir, par le vrai pont', () => {
    const envoyes: Array<Record<string, unknown>> = [];
    const pont = new PontNatif({ postMessage: (t: string) => envoyes.push(JSON.parse(t)) });
    const e = etat(true);
    const desinscrire = inscrireRetourBarre(pont, () => e, () => true);
    pont.recevoir({ type: 'demande', id: 'c1', verbe: 'retour' });
    expect(e.sidebarOpen).toBe(false);
    expect(envoyes[0]).toMatchObject({ ok: true, donnees: { traite: true } });
    pont.recevoir({ type: 'demande', id: 'c2', verbe: 'retour' });
    expect(envoyes[1], 'tiroir fermé : la coquille fait son propre retour').toMatchObject({
      donnees: { traite: false },
    });
    desinscrire();
  });

  it('une colonne ne consomme pas le retour', () => {
    const pont = new PontNatif({ postMessage: () => {} });
    const e = etat(true);
    inscrireRetourBarre(pont, () => e, () => false);
    pont.recevoir({ type: 'demande', id: 'c1', verbe: 'retour' });
    expect(e.sidebarOpen).toBe(true);
  });

  it('hors du téléphone, rien ne s’inscrit', () => {
    expect(() => inscrireRetourBarre(null, () => etat(true), () => true)()).not.toThrow();
  });
});
