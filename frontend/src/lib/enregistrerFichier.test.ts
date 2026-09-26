import { describe, expect, it } from 'vitest';

import {
  annonceDEnregistrement,
  enregistrerHorsBureau,
  lireReponseEnregistrer,
  type Environnement,
} from './enregistrerFichier';
import type { ReponseNatif } from './natif';

function environnement(mobile: boolean, reponse?: ReponseNatif | Error) {
  const demandes: Array<Record<string, unknown>> = [];
  const telechargements: string[] = [];
  const env: Environnement = {
    mobile,
    demander: async (_verbe, donnees) => {
      demandes.push(donnees as Record<string, unknown>);
      if (reponse instanceof Error) throw reponse;
      return reponse ?? { type: 'reponse', id: 'b1', ok: true };
    },
    telecharger: (_blob, nom) => {
      telechargements.push(nom);
    },
  };
  return { env, demandes, telechargements };
}

describe('Un export ne se dit réussi que sur la réponse de la coquille', () => {
  it('rend le nom que la coquille dit avoir écrit', async () => {
    const { env, demandes, telechargements } = environnement(true, {
      type: 'reponse',
      id: 'b1',
      ok: true,
      donnees: { nom: 'Téléchargements/pile.pdf' },
    });
    const blob = new Blob([new Uint8Array([37, 80, 68, 70])], { type: 'application/pdf' });
    expect(await enregistrerHorsBureau(blob, 'pile.pdf', env)).toBe('Téléchargements/pile.pdf');
    // Le contenu voyage en base64 : un canal JavaScript ne porte que du texte.
    expect(demandes).toEqual([{ nom: 'pile.pdf', mime: 'application/pdf', base64: 'JVBERg==' }]);
    // Échec évité (26/09/2026) : le clic blob: ne fait rien dans la WebView
    // d'Android. Dans le téléphone, on ne télécharge JAMAIS par ce chemin.
    expect(telechargements).toEqual([]);
  });

  it('rend null quand la personne a renoncé, sans erreur', async () => {
    const { env } = environnement(true, { type: 'reponse', id: 'b1', ok: false, erreur: 'annule' });
    expect(await enregistrerHorsBureau(new Blob(['{}']), 'x.json', env)).toBeNull();
  });

  it('lève la phrase de la coquille sur un vrai refus', async () => {
    const { env } = environnement(true, {
      type: 'reponse',
      id: 'b1',
      ok: false,
      erreur: 'Stockage plein',
    });
    await expect(enregistrerHorsBureau(new Blob(['{}']), 'x.json', env)).rejects.toThrow('Stockage plein');
  });

  it('laisse remonter un délai dépassé : pas de « exporté » sur un silence', async () => {
    const { env } = environnement(true, new Error('Le téléphone n’a pas répondu'));
    await expect(enregistrerHorsBureau(new Blob(['{}']), 'x.json', env)).rejects.toThrow(/pas répondu/);
  });

  it('hors du téléphone, télécharge et rend le nom proposé', async () => {
    const { env, demandes, telechargements } = environnement(false);
    expect(await enregistrerHorsBureau(new Blob(['{}']), 'x.json', env)).toBe('x.json');
    expect(telechargements).toEqual(['x.json']);
    expect(demandes).toEqual([]);
  });
});

describe('lireReponseEnregistrer', () => {
  it('ne compose pas de nom quand la coquille n’en rend pas', () => {
    // Échec évité (26/09/2026) : le nom PROPOSÉ était annoncé, alors
    // qu'Android renomme un doublon « diapason_2026 (1).json » (§100 : le
    // nom vient du récepteur). Enregistré, mais sans nom.
    expect(lireReponseEnregistrer({ type: 'reponse', id: 'b1', ok: true })).toBe('');
    expect(
      lireReponseEnregistrer({ type: 'reponse', id: 'b1', ok: true, donnees: { nom: '  ' } }),
    ).toBe('');
    expect(
      lireReponseEnregistrer({ type: 'reponse', id: 'b1', ok: true, donnees: { nom: 'a (1).pdf' } }),
    ).toBe('a (1).pdf');
  });

  it('dit un échec générique quand la coquille refuse sans phrase', () => {
    expect(() => lireReponseEnregistrer({ type: 'reponse', id: 'b1', ok: false })).toThrow();
  });
});

describe('annonceDEnregistrement', () => {
  it('se tait sur un renoncement, annonce sinon — avec le nom s’il y en a un', () => {
    expect(annonceDEnregistrement(null)).toBeNull();
    expect(annonceDEnregistrement('')).toEqual({});
    expect(annonceDEnregistrement('a.json')).toEqual({ description: 'a.json' });
  });
});
