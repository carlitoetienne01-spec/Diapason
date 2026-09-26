import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { ouvrirLaCloche } from './ouvrirLaCloche';

/**
 * Phase 5 du plan mobile (26/09/2026) : la notification d'approbation
 * touchée ouvre la cloche. Rien ne monte `ApprovalBell` dans ce dépôt ;
 * l'ordre relire → afficher → ouvrir est tenu ici.
 */
describe('La notification touchée ouvre la cloche sur la liste fraîche', () => {
  it('relit avant d’ouvrir, et rend le nombre affiché', async () => {
    const journal: string[] = [];
    const resultat = await ouvrirLaCloche({
      lire: async () => {
        journal.push('lire');
        return ['a', 'b'];
      },
      afficher: (liste) => journal.push(`afficher ${liste.length}`),
      ouvrir: () => journal.push('ouvrir'),
    });
    expect(journal, 'la cloche ne doit s’ouvrir que sur la liste relue').toEqual([
      'lire',
      'afficher 2',
      'ouvrir',
    ]);
    expect(resultat).toEqual({ nombre: 2 });
  });

  it('une relecture qui échoue n’ouvre rien et le dit', async () => {
    // Échec évité : une cloche ouverte sur l'ancienne liste (ou vide) dirait
    // « aucune demande » à la place de « je n'ai pas pu lire ».
    const journal: string[] = [];
    await expect(
      ouvrirLaCloche({
        lire: async () => {
          throw new Error('Failed: 502');
        },
        afficher: () => journal.push('afficher'),
        ouvrir: () => journal.push('ouvrir'),
      }),
    ).rejects.toThrow(/demandes d’approbation|approval requests/);
    expect(journal, 'rien ne doit s’afficher ni s’ouvrir sur un échec').toEqual([]);
  });

  it('une cloche vide s’ouvre quand même : la demande a été tranchée entre-temps', async () => {
    let ouverte = false;
    const resultat = await ouvrirLaCloche({
      lire: async () => [],
      afficher: () => undefined,
      ouvrir: () => (ouverte = true),
    });
    expect(ouverte, 'la personne doit voir que rien n’attend plus').toBe(true);
    expect(resultat).toEqual({ nombre: 0 });
  });
});


describe('La notification n’approuve jamais', () => {
  // Aucun test ne monte ApprovalBell : le gestionnaire du verbe est lu dans
  // la source. Mutant de la contre-épreuve du 26/09/2026 : le gestionnaire
  // `surApprobations` qui appelle approveAction sur toutes les demandes —
  // tsc propre, vitest vert.
  const cloche = readFileSync(join(process.cwd(), 'src', 'components', 'ApprovalBell.tsx'), 'utf-8');
  const debut = cloche.indexOf('pontNatif.surApprobations(');
  const bloc = cloche.slice(debut, cloche.indexOf('}, [', debut));

  it('le gestionnaire du verbe relit et ouvre, sans rien décider', () => {
    expect(debut, 'la cloche n’écoute plus le verbe « approbations »').toBeGreaterThan(0);
    expect(bloc).toContain('ouvrirLaCloche(');
    expect(bloc, 'Approuver et Refuser restent sous le doigt').not.toMatch(
      /approveAction|denyAction|\/approve|\/deny|decide/,
    );
  });

  it('ouvrirLaCloche n’a aucun moyen de décider', () => {
    const source = readFileSync(join(process.cwd(), 'src', 'lib', 'ouvrirLaCloche.ts'), 'utf-8');
    expect(source).not.toMatch(/approveAction|denyAction|from '\.\/api'/);
  });
});
