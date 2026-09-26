// Le préchargement des pages au téléphone (chantier de la fluidité, lot 2,
// 26/09/2026) : la première visite des Tâches attendait 400 ms ses morceaux
// JS avant de demander ses données, en 4G simulée.

import { describe, expect, it, vi } from 'vitest';

import { memoiserChargeur, planifierPrechargement, type OptionsPrechargement } from './prechargerPages';

function doublures(surcharges: Partial<OptionsPrechargement> = {}) {
  const creux: (() => void)[] = [];
  const plusTard: (() => void)[] = [];
  const options: OptionsPrechargement = {
    enCreux: (travail) => void creux.push(travail),
    visible: () => true,
    plusTard: (travail) => void plusTard.push(travail),
    economieDeDonnees: () => false,
    ...surcharges,
  };
  /** Joue les creux en attente, et laisse les promesses se résoudre. */
  const jouer = async () => {
    for (let tour = 0; tour < 20 && (creux.length || plusTard.length); tour += 1) {
      const lot = creux.splice(0);
      for (const travail of lot) travail();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    }
  };
  return { options, creux, plusTard, jouer };
}

describe('memoiserChargeur', () => {
  it("n'importe qu'une fois une page que le préchargement et React.lazy demandent tous les deux", async () => {
    const importer = vi.fn(async () => ({ Page: 'module' }));
    const memo = memoiserChargeur(importer);
    const [a, b] = await Promise.all([memo.charger(), memo.charger()]);
    expect(importer, 'un seul import pour deux demandeurs').toHaveBeenCalledTimes(1);
    expect(a, 'les deux demandeurs reçoivent le même module').toBe(b);
  });

  it("rend le module sans attendre une fois arrivé, et rien avant — pour ne pas suspendre une page déjà là", async () => {
    const memo = memoiserChargeur(async () => 'module');
    expect(memo.module(), 'rien tant que le morceau n’est pas arrivé').toBeNull();
    const enVol = memo.charger();
    expect(memo.module(), 'toujours rien pendant le transfert').toBeNull();
    await enVol;
    expect(memo.module(), 'le module est lisible dès son arrivée').toBe('module');
  });

  it("oublie un échec : une coupure 4G passagère ne condamne pas la page pour toute la session", async () => {
    let essai = 0;
    const memo = memoiserChargeur(async () => {
      essai += 1;
      if (essai === 1) throw new Error('Load failed');
      return 'module';
    });
    await expect(memo.charger(), 'le premier essai échoue').rejects.toThrow('Load failed');
    await expect(memo.charger(), 'le second relance l’import au lieu de rendre le vieux rejet').resolves.toBe('module');
  });
});

describe('planifierPrechargement', () => {
  it('précharge les pages une à une, chacune dans son propre creux, dans l’ordre donné', async () => {
    const ordre: string[] = [];
    const { options, creux, jouer } = doublures();
    const chargeurs = ['taches', 'planificateur', 'notes'].map((nom) => async () => void ordre.push(nom));
    const { fini } = planifierPrechargement(chargeurs, options);
    expect(ordre, 'rien avant le premier creux : la page affichée passe d’abord').toEqual([]);
    expect(creux.length, 'un seul creux demandé à la fois').toBe(1);
    await jouer();
    expect(ordre, 'les onglets dans l’ordre donné').toEqual(['taches', 'planificateur', 'notes']);
    await expect(fini).resolves.toEqual({ charges: 3, interrompu: false });
  });

  it('n’en lance jamais deux en même temps : ils se disputeraient le lien avec les lectures de la page', async () => {
    let enVol = 0;
    let maximum = 0;
    const { options, jouer } = doublures();
    const chargeur = async () => {
      enVol += 1;
      maximum = Math.max(maximum, enVol);
      await Promise.resolve();
      enVol -= 1;
    };
    const { fini } = planifierPrechargement([chargeur, chargeur, chargeur, chargeur], options);
    await jouer();
    await fini;
    expect(maximum, 'un seul morceau en vol à la fois').toBe(1);
  });

  it('s’arrête au premier échec au lieu d’user la radio sur un réseau tombé', async () => {
    const appels: number[] = [];
    const { options, jouer } = doublures();
    const chargeurs = [0, 1, 2].map((i) => async () => {
      appels.push(i);
      if (i === 1) throw new Error('Load failed');
    });
    const { fini } = planifierPrechargement(chargeurs, options);
    await jouer();
    expect(appels, 'rien après le morceau qui a échoué').toEqual([0, 1]);
    await expect(fini).resolves.toEqual({ charges: 1, interrompu: true });
  });

  it('ne charge rien quand Android demande d’économiser les données', async () => {
    const chargeur = vi.fn(async () => {});
    const { options, jouer } = doublures({ economieDeDonnees: () => true });
    const { fini } = planifierPrechargement([chargeur, chargeur], options);
    await jouer();
    expect(chargeur, 'aucun octet en mode économie de données').not.toHaveBeenCalled();
    await expect(fini).resolves.toEqual({ charges: 0, interrompu: true });
  });

  it('attend que l’écran revienne au lieu de charger en arrière-plan', async () => {
    let visible = false;
    const chargeur = vi.fn(async () => {});
    const { options, plusTard, jouer } = doublures({ visible: () => visible });
    planifierPrechargement([chargeur], options);
    await jouer();
    expect(chargeur, 'rien tant que l’écran est caché').not.toHaveBeenCalled();
    expect(plusTard.length, 'un nouvel essai est prévu').toBe(1);
    visible = true;
    plusTard.splice(0)[0]();
    await jouer();
    expect(chargeur, 'chargé une fois l’écran revenu').toHaveBeenCalledTimes(1);
  });

  it('s’arrête net quand on l’annule (démontage de l’app)', async () => {
    const chargeur = vi.fn(async () => {});
    const { options, jouer } = doublures();
    const { annuler, fini } = planifierPrechargement([chargeur, chargeur], options);
    annuler();
    await jouer();
    expect(chargeur, 'rien après l’annulation').not.toHaveBeenCalled();
    await expect(fini).resolves.toEqual({ charges: 0, interrompu: true });
  });
});
