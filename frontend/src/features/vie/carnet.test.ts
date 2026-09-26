import { describe, expect, it } from 'vitest';

import {
  JOURNAL_MAX,
  JOURNAL_SEUIL_COMPTEUR,
  carnetRempli,
  compteurCarnet,
  lignesDuCarnet,
  messageEchecCarnet,
} from './CarnetDeTache';

describe('Le repère « j’ai écrit ici » doit dire la vérité', () => {
  it('reconnaît un carnet qui porte quelque chose', () => {
    expect(carnetRempli('séance 1 : DNS résolu')).toBe(true);
  });

  it('ne s’allume pas pour du vide', () => {
    for (const rien of ['', '   ', '\n\n', '\t \n', undefined, null]) {
      expect(carnetRempli(rien)).toBe(false);
    }
  });

  it('ne s’allume pas pour un carnet ouvert puis effacé', () => {
    // Sans ce filtre, l'icône resterait allumée sur une tâche vide et le
    // repère cesserait de vouloir dire quoi que ce soit.
    expect(carnetRempli('   \n  \n ')).toBe(false);
  });

  it('compte les lignes qui portent du texte', () => {
    expect(lignesDuCarnet('a\n\nb\n   \nc')).toBe(3);
    expect(lignesDuCarnet('')).toBe(0);
    expect(lignesDuCarnet(undefined)).toBe(0);
  });
});

describe('Le plafond du carnet — 20 000 caractères, ceux de la route', () => {
  it('borne le carnet à ce que `TaskPatch.journal` accepte', () => {
    // Au-delà, un 422 anglais que le pied prenait pour un échec passager
    // (revue du 17 sept. 2026, défaut 10).
    expect(JOURNAL_MAX).toBe(20000);
    expect(JOURNAL_SEUIL_COMPTEUR).toBeLessThan(JOURNAL_MAX);
  });

  it('n’affiche le compteur qu’à l’approche de la limite', () => {
    expect(compteurCarnet(0)).toBeNull();
    expect(compteurCarnet(JOURNAL_SEUIL_COMPTEUR - 1)).toBeNull();
    expect(compteurCarnet(JOURNAL_SEUIL_COMPTEUR)).toMatch(/18.000 \/ 20.000/);
    expect(compteurCarnet(JOURNAL_MAX)).toMatch(/20.000 \/ 20.000/);
  });

  it('ne promet pas « il repartira » quand la longueur est la cause', () => {
    expect(messageEchecCarnet(JOURNAL_MAX)).not.toMatch(/repartira/);
    expect(messageEchecCarnet(JOURNAL_MAX)).toMatch(/plein/);
    expect(messageEchecCarnet(12)).toMatch(/repartira à la prochaine frappe/);
  });
});
