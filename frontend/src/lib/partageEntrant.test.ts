import { describe, expect, it, vi } from 'vitest';

import {
  BoiteDuPartage,
  CHEMIN_DE_LA_DISCUSSION,
  FICHIERS_MAX,
  OCTETS_MAX_PAR_FICHIER,
  TEXTE_MAX,
  fichiersDuPartage,
  lirePartage,
  recevoirUnPartage,
  type PartageLu,
} from './partageEntrant';

/**
 * « Partager vers Diapason » (phase 5 du plan mobile, 26/09/2026). Rien ne
 * monte le compositeur dans ce dépôt : la lecture, la boîte et l'ordre
 * « déposer puis naviguer » sont tenus ici.
 */

const base64 = (texte: string) => btoa(texte);

describe('Ce que la coquille apporte est lu, jamais deviné', () => {
  it('lit un lien partagé seul', () => {
    expect(lirePartage({ texte: '  https://exemple.org/article  ' })).toEqual({
      texte: 'https://exemple.org/article',
      fichiers: [],
    });
  });

  it('lit une image et un PDF avec leur nom et leur type', () => {
    const lu = lirePartage({
      fichiers: [
        { nom: 'photo.jpg', mime: 'image/jpeg', base64: base64('jpeg') },
        { nom: 'bail.pdf', mime: 'application/pdf', base64: base64('%PDF') },
      ],
    });
    expect(lu.fichiers.map((f) => f.nom)).toEqual(['photo.jpg', 'bail.pdf']);
  });

  it('refuse un partage vide, avec sa phrase', () => {
    expect(() => lirePartage({ texte: '   ', fichiers: [] })).toThrow(/ni texte ni fichier|neither text/);
  });

  it('refuse ce qui n’est pas une chaîne au lieu de le convertir', () => {
    // Échec évité : `String({})` aurait déposé « [object Object] » dans le
    // brouillon, et un nom absent aurait fabriqué un fichier sans nom.
    expect(() => lirePartage({ texte: 42 })).toThrow(/illisible|could not be read/);
    expect(() => lirePartage({ fichiers: 'photo.jpg' })).toThrow(/illisible|could not be read/);
    expect(() => lirePartage({ fichiers: [{ nom: '', mime: 'image/png', base64: '' }] })).toThrow(
      /illisible|could not be read/,
    );
    expect(() => lirePartage({ fichiers: [{ nom: 'x.png', mime: 'image/png', base64: 'pas du base64 !' }] })).toThrow(
      /illisible|could not be read/,
    );
    expect(() => lirePartage(null)).toThrow(/illisible|could not be read/);
  });

  it('refuse au-delà des bornes du compositeur, sans rien tronquer', () => {
    expect(() => lirePartage({ texte: 'x'.repeat(TEXTE_MAX + 1) })).toThrow(/20000|20 000/);
    const trop = Array.from({ length: FICHIERS_MAX + 1 }, (_, i) => ({
      nom: `p${i}.png`,
      mime: 'image/png',
      base64: base64('png'),
    }));
    expect(() => lirePartage({ fichiers: trop })).toThrow(/10 fichiers|10 files/);
    const lourd = 'A'.repeat(Math.ceil(((OCTETS_MAX_PAR_FICHIER + 3) * 4) / 3));
    expect(() => lirePartage({ fichiers: [{ nom: 'gros.pdf', mime: 'application/pdf', base64: lourd }] })).toThrow(
      /gros\.pdf/,
    );
  });

  it('rend des fichiers aux octets exacts, prêts pour « joindre »', async () => {
    const [fichier] = fichiersDuPartage(
      lirePartage({ fichiers: [{ nom: 'note.txt', mime: 'text/plain', base64: base64('bonjour') }] }),
    );
    expect(fichier.name).toBe('note.txt');
    expect(fichier.type).toBe('text/plain');
    expect(await fichier.text(), 'les octets doivent survivre au base64').toBe('bonjour');
  });
});

const partage: PartageLu = { texte: 'https://exemple.org', fichiers: [] };

describe('La boîte remet le partage au compositeur, et à lui seul', () => {
  it('remet tout de suite quand le compositeur écoute', async () => {
    const boite = new BoiteDuPartage();
    const pris: PartageLu[] = [];
    boite.ecouter((p) => {
      pris.push(p);
      return { texte: true, fichiers: 0 };
    });
    await expect(boite.deposer(partage, 1000)).resolves.toEqual({ texte: true, fichiers: 0 });
    expect(pris).toEqual([partage]);
  });

  it('garde le partage jusqu’à la montée du compositeur', async () => {
    const boite = new BoiteDuPartage();
    const accuse = boite.deposer(partage, 1000);
    boite.ecouter(() => ({ texte: true, fichiers: 0 }));
    await expect(accuse).resolves.toEqual({ texte: true, fichiers: 0 });
  });

  it('retire le partage expiré : il ne réapparaît pas dans un compositeur monté plus tard', async () => {
    // Échec évité : la coquille a dit « rien n'a été déposé », puis le lien
    // surgit dans le brouillon dix secondes après — un dépôt que personne
    // n'attend plus, sous une phrase qui le niait.
    vi.useFakeTimers();
    try {
      const boite = new BoiteDuPartage();
      const accuse = boite.deposer(partage, 8000);
      vi.advanceTimersByTime(8000);
      await expect(accuse).resolves.toBeNull();
      const pris: PartageLu[] = [];
      boite.ecouter((p) => {
        pris.push(p);
        return { texte: true, fichiers: 0 };
      });
      expect(pris, 'un partage expiré ne doit plus être remis').toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it('un second partage remplace le premier, qui est dit non déposé', async () => {
    const boite = new BoiteDuPartage();
    const premier = boite.deposer({ texte: 'un', fichiers: [] }, 1000);
    const second = boite.deposer({ texte: 'deux', fichiers: [] }, 1000);
    const pris: string[] = [];
    boite.ecouter((p) => {
      pris.push(p.texte);
      return { texte: true, fichiers: 0 };
    });
    await expect(premier).resolves.toBeNull();
    await expect(second).resolves.toEqual({ texte: true, fichiers: 0 });
    expect(pris, 'jamais deux partages mêlés dans le brouillon').toEqual(['deux']);
  });

  it('un compositeur qui lève ne fait pas passer le dépôt pour fait', async () => {
    const boite = new BoiteDuPartage();
    boite.ecouter(() => {
      throw new Error('textarea absent');
    });
    await expect(boite.deposer(partage, 1000)).resolves.toBeNull();
  });
});

describe('Recevoir un partage : déposer, puis naviguer vers la Discussion', () => {
  it('le compositeur monté PENDANT navigate() reçoit le partage', async () => {
    // Échec évité : la réponse de `naviguer` partait dès l'appel ; ici,
    // l'accusé n'existe que si le compositeur a pris le partage.
    const boite = new BoiteDuPartage();
    const journal: string[] = [];
    const accuse = await recevoirUnPartage(
      { texte: 'https://exemple.org' },
      {
        boite,
        delaiMs: 1000,
        naviguer: (chemin) => {
          journal.push(`naviguer ${chemin}`);
          boite.ecouter((p) => {
            journal.push(`pris ${p.texte}`);
            return { texte: true, fichiers: 0 };
          });
        },
      },
    );
    expect(journal).toEqual([`naviguer ${CHEMIN_DE_LA_DISCUSSION}`, 'pris https://exemple.org']);
    expect(accuse).toEqual({ texte: true, fichiers: 0 });
  });

  it('dit « rien n’a été déposé » si la Discussion ne monte pas', async () => {
    const boite = new BoiteDuPartage();
    await expect(
      recevoirUnPartage({ texte: 'x' }, { boite, delaiMs: 10, naviguer: () => undefined }),
    ).rejects.toThrow(/rien n’y a été déposé|nothing was placed/);
  });

  it('un partage illisible ne navigue pas', async () => {
    const naviguer = vi.fn();
    await expect(
      recevoirUnPartage({ texte: 3 }, { boite: new BoiteDuPartage(), delaiMs: 10, naviguer }),
    ).rejects.toThrow();
    expect(naviguer, 'rien ne doit bouger pour un partage refusé').not.toHaveBeenCalled();
  });
});
