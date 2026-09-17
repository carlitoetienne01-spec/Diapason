import { describe, expect, it } from 'vitest';

import { dateAvecJour, ecartJours, joursDeRetard, libelleEcheance } from './echeances';

// Le 17 septembre 2026 est un jeudi.
const AUJOURDHUI = '2026-09-17';

describe('le libellé d’échéance de la carte de tâche', () => {
  it('dit « Aujourd’hui » et « Demain » plutôt qu’une date ISO à soustraire', () => {
    expect(libelleEcheance('2026-09-17', AUJOURDHUI)).toBe('Aujourd’hui');
    expect(libelleEcheance('2026-09-18', AUJOURDHUI)).toBe('Demain');
  });

  it('donne le jour de la semaine tant qu’on est dans la semaine qui vient', () => {
    expect(libelleEcheance('2026-09-19', AUJOURDHUI)).toBe('sam. 19 sept.');
    expect(libelleEcheance('2026-09-23', AUJOURDHUI)).toBe('mer. 23 sept.');
  });

  it('abandonne le jour de la semaine au-delà de six jours — il ne dirait plus rien', () => {
    expect(libelleEcheance('2026-09-24', AUJOURDHUI)).toBe('24 sept.');
    expect(libelleEcheance('2026-10-03', AUJOURDHUI)).toBe('3 oct.');
  });

  it('tait l’année courante et la dit dès qu’elle change', () => {
    expect(libelleEcheance('2026-12-24', AUJOURDHUI)).not.toContain('2026');
    expect(libelleEcheance('2027-01-03', AUJOURDHUI)).toBe('3 janv. 2027');
  });

  it('signale le retard en jours — ce que la Liste ne disait jamais', () => {
    expect(libelleEcheance('2026-09-16', AUJOURDHUI)).toBe('En retard de 1 j');
    expect(libelleEcheance('2026-09-14', AUJOURDHUI)).toBe('En retard de 3 j');
  });

  it('ne met jamais une tâche terminée en retard : sa date passée redevient une date', () => {
    expect(libelleEcheance('2026-09-14', AUJOURDHUI, { terminee: true })).toBe('14 sept.');
    expect(libelleEcheance('2025-12-30', AUJOURDHUI, { terminee: true })).toBe('30 déc. 2025');
  });

  it('rend une chaîne vide pour une tâche sans date', () => {
    expect(libelleEcheance('', AUJOURDHUI)).toBe('');
  });
});

describe('la date avec son jour de semaine — le libellé d’un choix', () => {
  it('garde le jour de semaine au-delà de six jours, là où l’échéance l’abandonne', () => {
    // Deux lundis à choisir : sans le jour, la seconde chip perdait ce qui
    // les rend sœurs (revue du 17 sept. 2026, défaut 22).
    expect(dateAvecJour('2026-09-21', AUJOURDHUI)).toBe('lun. 21 sept.');
    expect(dateAvecJour('2026-09-28', AUJOURDHUI)).toBe('lun. 28 sept.');
  });

  it('ne dit jamais « Demain » ni « En retard » : un choix se lit par sa date', () => {
    expect(dateAvecJour('2026-09-18', AUJOURDHUI)).toBe('ven. 18 sept.');
    expect(dateAvecJour('2026-09-14', AUJOURDHUI)).toBe('lun. 14 sept.');
  });

  it('dit l’année dès qu’elle change, et rien pour une date vide', () => {
    expect(dateAvecJour('2027-01-01', AUJOURDHUI)).toBe('ven. 1 janv. 2027');
    expect(dateAvecJour('', AUJOURDHUI)).toBe('');
  });
});

describe('les jours de retard', () => {
  it('comptent en jours civils, midi à midi, sans se laisser décaler par l’heure d’été', () => {
    // Le passage à l'heure d'été (8 mars 2026 à Toronto) fait des journées de 23 h.
    expect(ecartJours('2026-03-07', '2026-03-09')).toBe(2);
    expect(joursDeRetard('2026-03-07', '2026-03-09')).toBe(2);
  });

  it('valent 0 pour une échéance à venir ou sans date', () => {
    expect(joursDeRetard('2026-09-20', AUJOURDHUI)).toBe(0);
    expect(joursDeRetard('', AUJOURDHUI)).toBe(0);
  });
});
