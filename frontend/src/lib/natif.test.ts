import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { localeDuDocument } from '../i18n/locale';
import {
  DELAIS_MS,
  PontNatif,
  VERBES_ENTRANTS,
  VERBES_SORTANTS,
  demanderAuTelephone,
  detecterCanal,
  estMobile,
  type CanalNatif,
} from './natif';

/** Un canal qui garde ce que le bundle envoie. */
function canalEspion(surMessage?: (m: Record<string, unknown>) => void) {
  const envoyes: Array<Record<string, unknown>> = [];
  const canal: CanalNatif = {
    postMessage(texte: string) {
      const m = JSON.parse(texte) as Record<string, unknown>;
      envoyes.push(m);
      surMessage?.(m);
    },
  };
  return { canal, envoyes };
}

describe('La coquille se reconnaît à son canal, pas à la largeur', () => {
  it('reconnaît un objet muni de postMessage', () => {
    expect(detecterCanal({ DiapasonNatif: { postMessage: () => {} } })).not.toBeNull();
  });

  it('refuse une fenêtre sans canal, ou un canal qui ne sait pas poster', () => {
    // Échec évité (26/09/2026) : un navigateur de 375 px n'est pas un
    // téléphone qui sait enregistrer — le prendre pour tel ferait échouer
    // chaque export sur un pont absent.
    expect(detecterCanal({})).toBeNull();
    expect(detecterCanal({ DiapasonNatif: {} })).toBeNull();
    expect(detecterCanal({ DiapasonNatif: { postMessage: 'oui' } })).toBeNull();
    expect(detecterCanal(null)).toBeNull();
  });

  it('dit « pas mobile » dans le banc jsdom, où rien n’a injecté de canal', () => {
    expect(estMobile).toBe(false);
    expect(document.documentElement.getAttribute('data-diapason-mobile')).toBeNull();
  });
});

describe('Aucun verbe ne rend un secret au JavaScript', () => {
  it('la liste des verbes est fermée', () => {
    // Le secret de session est un cookie HttpOnly (phase 2) : un verbe `cle`
    // ou `jeton` le rendrait lisible par toute page chargée dans la WebView.
    // Ajouter un verbe doit être une décision, donc un test à changer.
    expect([...VERBES_SORTANTS]).toEqual(['theme', 'enregistrer', 'ouvrirExterne']);
    expect([...VERBES_ENTRANTS]).toEqual(['retour']);
  });

  it('refuse un verbe hors de la liste sans rien poster', async () => {
    const { canal, envoyes } = canalEspion();
    const pont = new PontNatif(canal);
    await expect(pont.demander('cle' as never)).rejects.toThrow(/verbe inconnu/);
    expect(envoyes).toHaveLength(0);
  });
});

describe('Requête et réponse, appariées par identifiant', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('résout la promesse sur la réponse de même identifiant', async () => {
    const { canal, envoyes } = canalEspion();
    const pont = new PontNatif(canal);
    const promesse = pont.demander('ouvrirExterne', { url: 'https://exemple.org' });
    expect(envoyes[0]).toMatchObject({ type: 'demande', verbe: 'ouvrirExterne' });
    pont.recevoir({ type: 'reponse', id: envoyes[0].id, ok: true });
    await expect(promesse).resolves.toMatchObject({ ok: true });
  });

  it('accepte une réponse arrivée AVANT que l’attente soit posée', async () => {
    // Échec évité (26/09/2026) : une coquille qui répond pendant
    // `postMessage` même voyait sa réponse tomber dans le vide, et la
    // promesse n'échouait qu'au bout de son délai.
    let pont: PontNatif;
    const { canal } = canalEspion((m) =>
      pont.recevoir(JSON.stringify({ type: 'reponse', id: m.id, ok: true, donnees: { nom: 'x.pdf' } })),
    );
    pont = new PontNatif(canal);
    await expect(pont.demander('enregistrer', {})).resolves.toMatchObject({
      ok: true,
      donnees: { nom: 'x.pdf' },
    });
  });

  it('échoue au délai, en français quand l’interface est en français', async () => {
    const { canal } = canalEspion();
    document.documentElement.setAttribute('lang', 'fr');
    try {
      const pont = new PontNatif(canal);
      const promesse = pont.demander('theme', {});
      const verdict = expect(promesse).rejects.toThrow(
        `Le téléphone n’a pas répondu à « theme » en ${DELAIS_MS.theme / 1000} s.`,
      );
      await vi.advanceTimersByTimeAsync(DELAIS_MS.theme);
      await verdict;
    } finally {
      document.documentElement.removeAttribute('lang');
    }
  });

  it('ignore un identifiant jamais émis', async () => {
    const { canal, envoyes } = canalEspion();
    const pont = new PontNatif(canal);
    const promesse = pont.demander('ouvrirExterne', {});
    pont.recevoir({ type: 'reponse', id: 'inconnu', ok: false, erreur: 'boum' });
    pont.recevoir('pas du JSON');
    pont.recevoir(42);
    pont.recevoir({ type: 'reponse', id: envoyes[0].id, ok: true });
    await expect(promesse).resolves.toMatchObject({ ok: true });
  });

  it('ignore une réponse tardive : elle ne résout pas la demande suivante', async () => {
    const { canal, envoyes } = canalEspion();
    const pont = new PontNatif(canal, { delais: { theme: 50 } });
    const premiere = pont.demander('theme', {});
    const echec = expect(premiere).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(50);
    await echec;
    const seconde = pont.demander('theme', {});
    // La réponse à la PREMIÈRE arrive maintenant : ignorée.
    pont.recevoir({ type: 'reponse', id: envoyes[0].id, ok: false, erreur: 'tard' });
    pont.recevoir({ type: 'reponse', id: envoyes[1].id, ok: true });
    await expect(seconde).resolves.toMatchObject({ ok: true });
  });

  it('hors du téléphone, demander échoue lisiblement au lieu de se taire', async () => {
    await expect(demanderAuTelephone('enregistrer', {}, null)).rejects.toThrow();
  });
});

describe('Le retour Android demande d’abord au bundle', () => {
  it('répond « non traité » quand personne ne veut le retour', () => {
    // La coquille fait alors son propre retour : historique, puis arrière-plan.
    const { canal, envoyes } = canalEspion();
    const pont = new PontNatif(canal);
    pont.recevoir({ type: 'demande', id: 'n1', verbe: 'retour' });
    expect(envoyes).toEqual([{ type: 'reponse', id: 'n1', ok: true, donnees: { traite: false } }]);
  });

  it('donne la parole au dernier inscrit, et la désinscription la lui retire', () => {
    const { canal, envoyes } = canalEspion();
    const pont = new PontNatif(canal);
    const appels: string[] = [];
    pont.surRetour(() => {
      appels.push('barre');
      return true;
    });
    const retirer = pont.surRetour(() => {
      appels.push('feuille');
      return true;
    });
    pont.recevoir({ type: 'demande', id: 'n1', verbe: 'retour' });
    expect(appels).toEqual(['feuille']);
    retirer();
    pont.recevoir({ type: 'demande', id: 'n2', verbe: 'retour' });
    expect(appels).toEqual(['feuille', 'barre']);
    expect(envoyes.map((m) => (m.donnees as { traite: boolean }).traite)).toEqual([true, true]);
  });

  it('refuse un verbe entrant inconnu au lieu de laisser la coquille attendre', () => {
    const { canal, envoyes } = canalEspion();
    const pont = new PontNatif(canal);
    pont.recevoir({ type: 'demande', id: 'n1', verbe: 'donneMoiLaCle' });
    expect(envoyes).toEqual([{ type: 'reponse', id: 'n1', ok: false, erreur: 'verbeInconnu' }]);
  });
});

describe('La langue des erreurs hors de React', () => {
  it('suit <html lang> posé par l’interface', () => {
    expect(localeDuDocument('fr')).toBe('fr');
    expect(localeDuDocument('en')).toBe('en');
  });

  it('retombe sur la détection quand lang est absent ou inconnu', () => {
    expect(localeDuDocument(null, ['fr-CA'])).toBe('fr');
    expect(localeDuDocument('de', ['en-GB'])).toBe('en');
  });
});
