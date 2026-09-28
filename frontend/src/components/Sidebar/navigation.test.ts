import { describe, expect, it } from 'vitest';
import { ajouterEtape, correspondALaRecherche, panneauVisible, rubriqueDuChemin } from './navigation';

describe('La navigation retrouve les pages et les discussions (§82)', () => {
  it('restaure deux discussions distinctes sur la même route', () => {
    const initial = { etapes: [{ chemin: '/', discussion: 'a' }], position: 0 };
    const suivant = ajouterEtape(initial, { chemin: '/', discussion: 'b' });
    expect(suivant.etapes.map((e) => e.discussion), 'les flèches ne doivent pas perdre le fil').toEqual(['a', 'b']);
    expect(ajouterEtape(suivant, suivant.etapes[1]), 'un rendu ne crée pas de nouvelle étape').toBe(suivant);
  });
  it('abandonne seulement la branche suivante après un retour puis un nouveau choix', () => {
    const historique = { etapes: [{ chemin: '/', discussion: 'a' }, { chemin: '/vie/notes', discussion: null }], position: 0 };
    const suivant = ajouterEtape(historique, { chemin: '/vie/projects', discussion: null });
    expect(suivant.etapes.map((e) => e.chemin)).toEqual(['/', '/vie/projects']);
    expect(suivant.position).toBe(1);
  });
  it('identifie chaque rubrique du rail sans passer par un groupe Plus', () => {
    expect(rubriqueDuChemin('/vie/finances')).toBe('finances');
    expect(rubriqueDuChemin('/vie/habits')).toBe('habitudes');
    expect(rubriqueDuChemin('/vie/year-review')).toBe('bilan');
    expect(rubriqueDuChemin('/vie/dashboard')).toBe('tableau');
    expect(rubriqueDuChemin('/devices')).toBe('reglages');
    expect(rubriqueDuChemin('/vie/sync')).toBe('reglages');
    expect(rubriqueDuChemin('/vie/notes')).toBe('notes');
  });
  it('trouve une note ou un projet sans imposer les accents', () => {
    expect(correspondALaRecherche('Éducation', ' education ')).toBe(true);
    expect(correspondALaRecherche('Anglais', 'repas')).toBe(false);
  });
  it('garde le choix ouvert après une rubrique sans panneau et garde le choix replié partout (§82)', () => {
    const parcours = ['/', '/vie/planner', '/vie/tasks', '/vie/dashboard', '/vie/habits', '/vie/year-review', '/vie/notes', '/vie/projects', '/vie/finances', '/', '/settings', '/devices', '/vie/sync'];
    expect(parcours.map((chemin) => panneauVisible(true, chemin)), 'les pages métier n’ont plus de panneau ; revenir à Discussion ou Réglages conserve le choix ouvert').toEqual([true, false, false, false, false, false, false, false, false, true, true, true, true]);
    expect(parcours.map((chemin) => panneauVisible(false, chemin)), 'changer de rubrique ne doit pas rouvrir le panneau').toEqual(parcours.map(() => false));
    expect(panneauVisible(true, '/inconnue'), 'une route sans panneau ne laisse pas de voile devant la page').toBe(false);
  });
});
