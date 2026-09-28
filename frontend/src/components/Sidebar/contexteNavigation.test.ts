import { afterEach, describe, expect, it } from 'vitest';
import { retirerContexte, useContexteNavigation } from './contexteNavigation';

afterEach(() => useContexteNavigation.setState({ proprietaire: null, contexte: null }));

describe('Le panneau suit uniquement la page courante (§5, §82)', () => {
  it('ne vide pas les nouveaux contrôles quand la page précédente se démonte', () => {
    const ancienne = Symbol('planificateur');
    const actuelle = Symbol('taches');
    const contexte = { chemin: '/vie/tasks', groupes: [] };
    useContexteNavigation.setState({ proprietaire: actuelle, contexte });
    retirerContexte(ancienne);
    expect(useContexteNavigation.getState().contexte, 'un ancien nettoyage ne retire pas la navigation courante').toBe(contexte);
    retirerContexte(actuelle);
    expect(useContexteNavigation.getState().contexte, 'aucune commande ne survit à sa page').toBeNull();
  });
});
