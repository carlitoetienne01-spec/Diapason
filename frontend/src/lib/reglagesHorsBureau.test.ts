import { describe, expect, it } from 'vitest';

import {
  choixDeSourceAffiche,
  etatDeLaCle,
  indicationCle,
  sourceEnregistrable,
  type LectureSource,
} from './reglagesHorsBureau';

describe('Les pastilles et les champs de clé disent ce que le Mac a', () => {
  it('une clé lue présente est présente, partout', () => {
    // Échec évité (26/09/2026) : hors de l'app de bureau, les pastilles
    // restaient grises pour un Mac qui avait les clés.
    const lecture = { statut: { OPENAI_API_KEY: true, GEMINI_API_KEY: false } };
    expect(etatDeLaCle(lecture, 'OPENAI_API_KEY')).toBe('presente');
    expect(etatDeLaCle(lecture, 'GEMINI_API_KEY')).toBe('absente');
    expect(etatDeLaCle(lecture, 'ANTHROPIC_API_KEY')).toBe('absente');
  });

  it('un échec de lecture ne se déguise pas en « absente »', () => {
    expect(etatDeLaCle({ echec: true }, 'OPENAI_API_KEY')).toBe('illisible');
    expect(etatDeLaCle(null, 'OPENAI_API_KEY')).toBe('attente');
  });

  it('hors de l’app de bureau, le champ dit où est la clé', () => {
    expect(indicationCle({ bureau: false, outilServeur: false, etat: 'presente' })).toBe('surLeMac');
    expect(indicationCle({ bureau: false, outilServeur: false, etat: 'absente' })).toBe('ajouterSurLeBureau');
    expect(indicationCle({ bureau: false, outilServeur: false, etat: 'illisible' })).toBe('illisible');
    expect(indicationCle({ bureau: true, outilServeur: false, etat: 'presente' })).toBe('savedSecure');
    expect(indicationCle({ bureau: false, outilServeur: true, etat: 'presente' })).toBe('savedServer');
  });
});

describe('La source d’inférence non lue n’est jamais « Ollama »', () => {
  it('en attente et après un échec : inconnue, et rien à enregistrer', () => {
    // Échec évité (26/09/2026) : « Ollama intégré (par défaut) » s'affichait
    // juste au-dessus de « Impossible de lire la source … (HTTP 429) ».
    for (const lecture of [{ etat: 'attente' }, { etat: 'echec', message: '429' }] as LectureSource[]) {
      expect(choixDeSourceAffiche(lecture, 'ollama')).toBe('inconnue');
      expect(sourceEnregistrable(lecture)).toBe(false);
    }
  });

  it('lue : la valeur choisie', () => {
    const lue: LectureSource = { etat: 'lue', source: { kind: 'custom' } };
    expect(choixDeSourceAffiche(lue, 'custom')).toBe('custom');
    expect(sourceEnregistrable(lue)).toBe(true);
  });
});
