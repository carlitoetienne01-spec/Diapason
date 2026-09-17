import { describe, expect, it } from 'vitest';

import { DateAmbigueError, DateInconnueError } from './api';
import {
  EXEMPLES_EXPRESSION,
  EXPRESSION_MAX,
  chipsAmbiguite,
  expressionDeReport,
  lireRefusDeReport,
  phraseReportee,
  proposeDecoupage,
} from './report';

describe('L’expression envoyée au résolveur de dates', () => {
  it('part telle quelle, ébarbée — c’est le serveur qui la comprend', () => {
    expect(expressionDeReport('  dans 3 jours ')).toBe('dans 3 jours');
    expect(expressionDeReport('lundi')).toBe('lundi');
  });

  it('ne part jamais vide : Entrée sur un champ vide ne fait rien', () => {
    expect(expressionDeReport('')).toBeNull();
    expect(expressionDeReport('   \n')).toBeNull();
  });

  it('se borne aux 80 caractères que la route accepte', () => {
    // Au-delà, un 422 de validation en anglais aurait été pris pour une
    // date inconnue.
    const longue = 'x'.repeat(EXPRESSION_MAX + 20);
    expect(expressionDeReport(longue)).toHaveLength(EXPRESSION_MAX);
  });

  it('ne promet en exemple que ce que le résolveur du serveur comprend', () => {
    // « 21 sept » figurait dans le placeholder et rendait 422 à coup sûr :
    // `resolve_date_expression` ne connaît aucun nom de mois (défaut 7).
    expect(EXEMPLES_EXPRESSION).not.toMatch(/sept\b/);
    expect(EXEMPLES_EXPRESSION).toContain('21/09/2026');
    expect(EXEMPLES_EXPRESSION).toContain('dans 3 jours');
  });
});

describe('Le refus du serveur, répondu depuis la carte', () => {
  it('rend les deux jours d’une date ambiguë (409 ambiguous_date)', () => {
    const refus = lireRefusDeReport(
      new DateAmbigueError('Cette date peut désigner deux jours.', ['2026-09-21', '2026-09-28']),
    );
    expect(refus).toEqual({
      type: 'ambigue',
      message: 'Cette date peut désigner deux jours.',
      options: ['2026-09-21', '2026-09-28'],
    });
  });

  it('rend le message d’une date inconnue (422) sous le champ, pas en toast', () => {
    const refus = lireRefusDeReport(new DateInconnueError("Je n'ai pas reconnu cette date."));
    expect(refus).toEqual({ type: 'inconnue', message: "Je n'ai pas reconnu cette date." });
  });

  it('laisse le reste à la page : réseau coupé, tâche disparue', () => {
    expect(lireRefusDeReport(new Error('Connexion locale interrompue.'))).toBeNull();
    expect(lireRefusDeReport('pas une erreur')).toBeNull();
  });

  it('date les chips d’ambiguïté pour qu’on sache lequel choisir', () => {
    const chips = chipsAmbiguite(['2026-09-21', '2026-09-28'], '2026-09-17');
    expect(chips.map((chip) => chip.date)).toEqual(['2026-09-21', '2026-09-28']);
    expect(chips[0].label).toMatch(/21/);
    expect(chips[1].label).toMatch(/28/);
    expect(chips[0].label).not.toBe(chips[1].label);
  });

  it('donne le jour de semaine aux DEUX chips, même celle au-delà de six jours', () => {
    // « lundi prochain » : la seconde option est toujours à 8-14 jours, et
    // se lisait « 28 sept. » à côté de « lun. 21 sept. » (défaut 22).
    const chips = chipsAmbiguite(['2026-09-21', '2026-09-28'], '2026-09-17');
    expect(chips.map((chip) => chip.label)).toEqual(['lun. 21 sept.', 'lun. 28 sept.']);
    // « vendredi prochain » depuis un jeudi : jamais « Demain » sur une chip.
    const proches = chipsAmbiguite(['2026-09-18', '2026-09-25'], '2026-09-17');
    expect(proches.map((chip) => chip.label)).toEqual(['ven. 18 sept.', 'ven. 25 sept.']);
  });
});

describe('Le toast d’un report parle la langue de la carte, sur la date du serveur', () => {
  it('dit le jour de semaine plutôt que l’ISO que la carte vient de bannir (défaut 12)', () => {
    expect(phraseReportee('2026-09-21', '2026-09-17')).toBe('Reportée au lun. 21 sept.');
    expect(phraseReportee('2026-10-03', '2026-09-17')).toBe('Reportée au 3 oct.');
  });

  it('tourne « Aujourd’hui » et « Demain » en phrase, pas en « Reportée au Demain »', () => {
    expect(phraseReportee('2026-09-17', '2026-09-17')).toBe('Reportée à aujourd’hui');
    expect(phraseReportee('2026-09-18', '2026-09-17')).toBe('Reportée à demain');
  });

  it('ne dit jamais « En retard » pour un report vers hier, ni ne plante sans date', () => {
    expect(phraseReportee('2026-09-16', '2026-09-17')).toBe('Reportée au 16 sept.');
    expect(phraseReportee('', '2026-09-17')).toBe('Reportée');
  });
});

describe('Le quatrième report pose la question du découpage', () => {
  it('se tait avant quatre reports, comme le warning du serveur', () => {
    expect(proposeDecoupage(0)).toBe(false);
    expect(proposeDecoupage(3)).toBe(false);
  });

  it('propose à partir de quatre — la question doit pouvoir être répondue (§34)', () => {
    expect(proposeDecoupage(4)).toBe(true);
    expect(proposeDecoupage(9)).toBe(true);
  });
});
