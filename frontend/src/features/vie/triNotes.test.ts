import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { estTriNotes, triInitialDesNotes, unArrangementExiste } from './triNotes';

describe('le tri des cartables à l’ouverture de Notes', () => {
  it('montre « Mon ordre » dès qu’un cartable a été rangé, sans rien avoir à choisir', () => {
    // 17 sept. 2026 : l’arrangement existait côté serveur mais la page
    // rouvrait toujours en « Récent » — le dernier édité passait devant.
    const notes = [{ order: 0 }, { order: 2 }, { order: 1 }];
    expect(unArrangementExiste(notes)).toBe(true);
    expect(triInitialDesNotes(undefined, notes)).toBe('manuel');
  });

  it('reste en « Récent » pour qui n’a jamais rien rangé', () => {
    const jamaisRangees = [{ order: 0 }, {}, { order: 0 }];
    expect(unArrangementExiste(jamaisRangees)).toBe(false);
    expect(triInitialDesNotes(undefined, jamaisRangees)).toBe('recent');
    expect(triInitialDesNotes(undefined, [])).toBe('recent');
  });

  it('respecte un choix mémorisé, même quand un arrangement existe', () => {
    const rangees = [{ order: 3 }];
    expect(triInitialDesNotes('name-asc', rangees)).toBe('name-asc');
    expect(triInitialDesNotes('recent', rangees)).toBe('recent');
  });

  it('ignore une valeur mémorisée qui n’est pas un tri', () => {
    expect(estTriNotes('manuel')).toBe(true);
    expect(estTriNotes('aleatoire')).toBe(false);
    expect(estTriNotes(42)).toBe(false);
    expect(triInitialDesNotes('aleatoire', [{ order: 1 }]), 'une valeur inconnue ne casse rien').toBe(
      'manuel',
    );
  });
});

/**
 * 27/09/2026, contre-épreuve du chantier « soyeux » (constat 1) : le tri
 * n'était inféré qu'au CHARGEMENT. Au montage, la liste du cache sortait en
 * « Récent » (60, 59, 58…), puis une à deux images plus tard en « Mon ordre »
 * (10, 12, 15…). Au retour sur les Notes, la position rendue tenait une image,
 * puis l'ancrage du défilement suivait la liste réordonnée : 2 685 px de recul
 * sur l'émulateur, 14 retours au doigt sur 15. Le calcul est pur (plus haut) ;
 * c'est son APPEL au montage qu'on tient ici, en lisant la page comme du
 * texte, faute de tests de composants.
 */
describe('le tri des Notes au montage de la page', () => {
  const page = readFileSync(join(__dirname, '../../pages/VieNotesPage.tsx'), 'utf8');

  it('infère le tri sur la liste du cache dès le montage, comme au chargement', () => {
    expect(page, 'la liste du montage est lue une fois, et sert aux deux états').toContain(
      'const [notes, setNotes] = useState<CartableNote[]>(notesAuMontage);',
    );
    expect(page, 'le tri initial vient du même calcul que celui du chargement, sur la liste du cache').toContain(
      'useState<SortMode>(() => triInitialDesNotes(loadNotesSort(), notesAuMontage))',
    );
    expect(page, 'aucun tri initial en dur').not.toMatch(/loadNotesSort\(\) \?\? '/);
  });

  it('rend le même ordre au montage et à la relecture quand le serveur rend la liste du cache', () => {
    const cache = [{ order: 0 }, { order: 2 }, { order: 1 }];
    const relue = cache.map((note) => ({ ...note }));
    expect(triInitialDesNotes(undefined, cache), 'au montage, sur le cache').toBe(triInitialDesNotes(undefined, relue));
  });
});
