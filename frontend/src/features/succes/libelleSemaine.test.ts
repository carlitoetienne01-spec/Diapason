import { describe, expect, it } from 'vitest';

import { libelleIntervalle } from './libelleSemaine';

describe('le titre de la vue Semaine', () => {
  it('ne répète pas le mois quand la semaine n’en change pas', () => {
    expect(libelleIntervalle('2026-09-14', '2026-09-20', 2026)).toBe('14 – 20 sept.');
  });

  it('nomme les deux mois quand la semaine les chevauche', () => {
    expect(libelleIntervalle('2026-09-28', '2026-10-04', 2026)).toBe('28 sept. – 4 oct.');
  });

  it('tait l’année courante — elle ne dit rien et prend la place du reste', () => {
    expect(libelleIntervalle('2026-03-02', '2026-03-08', 2026)).not.toContain('2026');
  });

  it('dit l’année quand on a quitté l’année courante', () => {
    expect(libelleIntervalle('2027-03-01', '2027-03-07', 2026)).toBe('1 – 7 mars 2027');
  });

  it('dit les deux années quand la semaine passe le Nouvel An', () => {
    const libelle = libelleIntervalle('2025-12-29', '2026-01-04', 2026);
    expect(libelle).toContain('2025');
    expect(libelle).toContain('2026');
    expect(libelle).toBe('29 déc. 2025 – 4 janv. 2026');
  });

  it('reste court : jamais une date ISO brute', () => {
    const libelle = libelleIntervalle('2026-09-14', '2026-09-20', 2026);
    expect(libelle).not.toMatch(/\d{4}-\d{2}-\d{2}/);
    expect(libelle.length).toBeLessThan(20);
  });
});
