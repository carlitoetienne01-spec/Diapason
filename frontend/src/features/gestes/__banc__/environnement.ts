/**
 * La fenêtre, la caméra et le canevas — en toc, et sous contrôle.
 *
 * Le mode gestes passe par `window.setInterval`, `document.createElement`
 * et `navigator.mediaDevices.getUserMedia`. Sous node, rien de tout cela
 * n'existe. Plutôt que d'installer jsdom (ce dépôt n'en a pas et n'en veut
 * pas), on pose exactement les quatre objets que le code touche — et on
 * garde la main sur l'horloge, faute de quoi « douze images par seconde »
 * et « trois images par seconde » se ressembleraient trop pour être
 * distingués.
 *
 * AUCUN code de production ne l'importe.
 */

type Tache = { echeance: number; periode: number | null; fn: () => void };

/** Rendre la main aux promesses en vol avant de faire tourner l'horloge. */
export function vider(): Promise<void> {
  return new Promise<void>((r) => setImmediate(r));
}

export class Horloge {
  private t = 0;
  private prochainId = 1;
  private readonly taches = new Map<number, Tache>();

  readonly setTimeout = (fn: () => void, ms = 0): number => {
    const id = this.prochainId++;
    this.taches.set(id, { echeance: this.t + ms, periode: null, fn });
    return id;
  };

  readonly setInterval = (fn: () => void, ms = 0): number => {
    const id = this.prochainId++;
    this.taches.set(id, {
      echeance: this.t + Math.max(ms, 1),
      periode: Math.max(ms, 1),
      fn,
    });
    return id;
  };

  readonly clearTimeout = (id?: number | null): void => {
    if (typeof id === 'number') this.taches.delete(id);
  };

  readonly clearInterval = this.clearTimeout;

  /** Les périodes des minuteurs répétitifs encore armés, en ms. */
  periodes(): number[] {
    return [...this.taches.values()]
      .filter((x): x is Tache & { periode: number } => x.periode !== null)
      .map((x) => x.periode)
      .sort((a, b) => a - b);
  }

  /** Combien de minuteurs, tous types confondus, restent armés. */
  get armes(): number {
    return this.taches.size;
  }

  async avancer(ms: number): Promise<void> {
    // D'abord rendre la main : une promesse en vol peut n'avoir pas encore
    // posé son minuteur, et l'horloge passerait devant sans le voir.
    await vider();
    const fin = this.t + ms;
    for (;;) {
      let choisi: [number, Tache] | null = null;
      for (const entree of this.taches) {
        if (entree[1].echeance > fin) continue;
        if (choisi === null || entree[1].echeance < choisi[1].echeance) {
          choisi = entree;
        }
      }
      if (choisi === null) break;
      const [id, tache] = choisi;
      this.t = tache.echeance;
      if (tache.periode === null) this.taches.delete(id);
      else tache.echeance = this.t + tache.periode;
      tache.fn();
      await vider();
    }
    this.t = fin;
  }
}

export type Piste = { arretee: boolean; stop: () => void };

export type Environnement = {
  horloge: Horloge;
  /** Les pistes vidéo ouvertes — leur arrêt éteint le voyant vert. */
  pistes: Piste[];
  pistesArretees: () => number;
  /** Combien de fois getUserMedia a été appelé. */
  camerasOuvertes: () => number;
  /** Combien d'images ont été encodées en JPEG par le canevas. */
  imagesEncodees: () => number;
  /** Faire échouer la prochaine ouverture de caméra. */
  refuser: (nom: string, message: string) => void;
  restaurer: () => void;
};

function poser(nom: string, valeur: unknown): () => void {
  const global = globalThis as unknown as Record<string, unknown>;
  const avait = Object.prototype.hasOwnProperty.call(global, nom);
  const avant = global[nom];
  Object.defineProperty(global, nom, {
    value: valeur,
    configurable: true,
    writable: true,
  });
  return () => {
    if (avait) {
      Object.defineProperty(global, nom, {
        value: avant,
        configurable: true,
        writable: true,
      });
    } else {
      delete global[nom];
    }
  };
}

export function installerEnvironnement(): Environnement {
  const horloge = new Horloge();
  const pistes: Piste[] = [];
  let ouvertures = 0;
  let images = 0;
  let refus: { nom: string; message: string } | null = null;

  const fenetre = {
    setTimeout: horloge.setTimeout,
    clearTimeout: horloge.clearTimeout,
    setInterval: horloge.setInterval,
    clearInterval: horloge.clearInterval,
  };

  const document = {
    createElement(balise: string): unknown {
      if (balise === 'video') {
        return {
          srcObject: null as unknown,
          muted: false,
          playsInline: false,
          // Une vraie image, sinon `capturer` renonce avant d'encoder.
          videoWidth: 1280,
          videoHeight: 720,
          play: async () => undefined,
        };
      }
      if (balise === 'canvas') {
        return {
          width: 0,
          height: 0,
          getContext: (sorte: string) =>
            sorte === '2d' ? { drawImage: () => undefined } : null,
          toDataURL: () => {
            images += 1;
            return 'data:image/jpeg;base64,SU1BR0U=';
          },
        };
      }
      throw new Error(`Le banc ne sait pas fabriquer un <${balise}>.`);
    },
  };

  const navigateur = {
    mediaDevices: {
      getUserMedia: async () => {
        ouvertures += 1;
        if (refus) {
          const exc = new Error(refus.message);
          exc.name = refus.nom;
          refus = null;
          throw exc;
        }
        const piste: Piste = {
          arretee: false,
          stop: () => {
            piste.arretee = true;
          },
        };
        pistes.push(piste);
        return { getTracks: () => [piste] };
      },
    },
  };

  const defaire = [
    poser('window', fenetre),
    poser('document', document),
    poser('navigator', navigateur),
  ];

  return {
    horloge,
    pistes,
    pistesArretees: () => pistes.filter((p) => p.arretee).length,
    camerasOuvertes: () => ouvertures,
    imagesEncodees: () => images,
    refuser: (nom, message) => {
      refus = { nom, message };
    },
    restaurer: () => {
      for (const d of defaire) d();
    },
  };
}
