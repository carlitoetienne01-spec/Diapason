import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { localeDuDocument } from '../i18n/locale';
import {
  DELAIS_MS,
  PontNatif,
  VERBES_ENTRANTS,
  VERBES_SORTANTS,
  demanderAuTelephone,
  detecterCanal,
  doitPasserParLaCoquille,
  installerPont,
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

describe('Le pont se branche sur la fenêtre que la coquille a préparée', () => {
  /** Une fausse fenêtre munie du canal, et un faux document qui garde ses écouteurs. */
  function fenetreDeTelephone() {
    const { canal, envoyes } = canalEspion();
    const attributs: Record<string, string> = {};
    const ecouteurs: Array<(e: MouseEvent) => void> = [];
    const fenetre: Record<string, unknown> = {
      DiapasonNatif: canal,
      location: { origin: 'https://atelier.exemple.ts.net' },
    };
    const doc = {
      documentElement: { setAttribute: (n: string, v: string) => (attributs[n] = v) },
      addEventListener: (_t: 'click', fn: (e: MouseEvent) => void) => ecouteurs.push(fn),
    };
    return { fenetre, doc, envoyes, attributs, ecouteurs };
  }

  it('pose le point d’entrée : une réponse de la coquille résout la demande', async () => {
    // Échec évité (26/09/2026) : sans `diapasonNatifRecevoir`, chaque
    // `enregistrer` attendait deux minutes pour échouer — et retirer
    // l'affectation laissait toute la suite verte.
    const { fenetre, doc, envoyes, attributs } = fenetreDeTelephone();
    const pont = installerPont(fenetre, doc);
    expect(pont).not.toBeNull();
    expect(attributs['data-diapason-mobile']).toBe('1');
    const promesse = pont!.demander('enregistrer', { nom: 'a.json' });
    const recevoir = fenetre.diapasonNatifRecevoir as (m: unknown) => void;
    expect(typeof recevoir).toBe('function');
    recevoir(JSON.stringify({ type: 'reponse', id: envoyes[0].id, ok: true, donnees: { nom: 'a.json' } }));
    await expect(promesse).resolves.toMatchObject({ ok: true });
  });

  it('le retour d’Android arrive par le même point d’entrée', () => {
    const { fenetre, doc, envoyes } = fenetreDeTelephone();
    const pont = installerPont(fenetre, doc)!;
    pont.surRetour(() => true);
    (fenetre.diapasonNatifRecevoir as (m: unknown) => void)({ type: 'demande', id: 'c1', verbe: 'retour' });
    expect(envoyes[envoyes.length - 1]).toEqual({ type: 'reponse', id: 'c1', ok: true, donnees: { traite: true } });
  });

  it('ne fait rien sans canal : ni attribut, ni point d’entrée', () => {
    const fenetre: Record<string, unknown> = {};
    const attributs: Record<string, string> = {};
    const doc = {
      documentElement: { setAttribute: (n: string, v: string) => (attributs[n] = v) },
      addEventListener: () => {},
    };
    expect(installerPont(fenetre, doc)).toBeNull();
    expect(fenetre.diapasonNatifRecevoir).toBeUndefined();
    expect(attributs).toEqual({});
  });

  it('envoie un lien vers une autre origine à la coquille au lieu de le suivre', () => {
    const { fenetre, doc, envoyes, ecouteurs } = fenetreDeTelephone();
    installerPont(fenetre, doc);
    const lien = { getAttribute: () => 'https://exemple.org/source' };
    let empeche = false;
    const clic = {
      defaultPrevented: false,
      target: { closest: () => lien },
      preventDefault: () => (empeche = true),
    } as unknown as MouseEvent;
    ecouteurs[0](clic);
    expect(empeche, 'la WebView ne doit pas suivre le lien elle-même').toBe(true);
    expect(envoyes[0]).toMatchObject({
      verbe: 'ouvrirExterne',
      donnees: { url: 'https://exemple.org/source' },
    });
  });
});

describe('Quels liens la coquille ouvre', () => {
  const mac = 'https://atelier.exemple.ts.net';
  it('une autre origine en http(s) : oui', () => {
    expect(doitPasserParLaCoquille('https://exemple.org/a', mac)).toBe(true);
    expect(doitPasserParLaCoquille('http://exemple.org', mac)).toBe(true);
  });
  it('l’origine du Mac, un chemin relatif, un schéma étranger : non', () => {
    expect(doitPasserParLaCoquille('/vie/tasks', mac)).toBe(false);
    expect(doitPasserParLaCoquille(`${mac}/settings`, mac)).toBe(false);
    expect(doitPasserParLaCoquille('javascript:alert(1)', mac)).toBe(false);
    expect(doitPasserParLaCoquille('mailto:a@b.c', mac)).toBe(false);
    expect(doitPasserParLaCoquille('#ancre', mac)).toBe(false);
  });
});

describe('Les identifiants et les réponses tardives', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('deux chargements n’émettent pas le même premier identifiant', () => {
    // Échec évité (26/09/2026) : `b1` à chaque chargement — une réponse en
    // route à travers un rechargement aurait résolu la nouvelle `b1`.
    const a = canalEspion();
    const b = canalEspion();
    void new PontNatif(a.canal).demander('theme', {}).catch(() => undefined);
    void new PontNatif(b.canal).demander('theme', {}).catch(() => undefined);
    expect(a.envoyes[0].id).not.toBe(b.envoyes[0].id);
  });

  it('une réponse arrivée après le délai se dit, sans résoudre autre chose', async () => {
    // Échec évité (26/09/2026) : un `ok` arrivé après les deux minutes
    // d'`enregistrer` était jeté — « pas de réponse » pour un fichier écrit.
    const { canal, envoyes } = canalEspion();
    const tardives: Array<[string, unknown]> = [];
    const pont = new PontNatif(canal, {
      delais: { enregistrer: 50 },
      surReponseTardive: (verbe, r) => tardives.push([verbe, r.donnees]),
    });
    const promesse = pont.demander('enregistrer', {});
    const echec = expect(promesse).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(50);
    await echec;
    pont.recevoir({ type: 'reponse', id: envoyes[0].id, ok: true, donnees: { nom: 'x.pdf' } });
    pont.recevoir({ type: 'reponse', id: envoyes[0].id, ok: true, donnees: { nom: 'x.pdf' } });
    expect(tardives, 'dite une fois, pas deux').toEqual([['enregistrer', { nom: 'x.pdf' }]]);
  });
});
