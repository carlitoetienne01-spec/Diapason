// « Partager vers Diapason » du côté du bundle : lire ce que la coquille
// apporte, le déposer dans le compositeur de la Discussion, et ne répondre
// qu'une fois qu'il y est.
//
// 26/09/2026, phase 5 du plan mobile (docs/development/diapason-mobile.md).
// Android remet à la coquille le texte, le lien, l'image ou le PDF qu'une
// autre app partage ; la coquille le passe ici par le verbe entrant
// `partager`. Deux règles, et les deux se tiennent dans des fonctions pures
// parce qu'aucun test ne peut monter un composant dans ce dépôt :
//
// - rien n'est ENVOYÉ : le partage atterrit dans le compositeur, comme le
//   texte du sauteur (`diapason:deposer-texte`), et part seulement quand la
//   personne l'envoie. Un lien partagé qui partirait seul poserait une
//   question que personne n'a relue ;
// - la coquille n'apprend « déposé » que du compositeur lui-même (§100). Une
//   réponse donnée dès `navigate('/')` rejouerait le faux SUCCESS de
//   `naviguer` : sur un réseau mobile, le morceau de la Discussion peut ne
//   jamais arriver, et le partage serait perdu sous une phrase qui dit le
//   contraire.

import { traduire } from '../i18n/translate';

/**
 * Au plus neuf fichiers : les sept images et les deux documents que le
 * compositeur accepte par message (`piecesJointes.ts`). Au-delà, le
 * compositeur refuserait le surplus fichier par fichier ; la coquille, elle,
 * n'en envoie pas davantage.
 */
export const FICHIERS_MAX = 9;

/**
 * Dix mégaoctets par fichier : le plus grand que le compositeur accepte (un
 * document, `DOCUMENT_TAILLE_MAX`). Une image de plus de 4 Mo passe ici et
 * se fait refuser par le compositeur, avec sa phrase : la règle fine vit là,
 * celle-ci ne borne que ce qui traverse le pont.
 */
export const OCTETS_MAX_PAR_FICHIER = 10 * 1024 * 1024;

/**
 * Vingt mille signes, une dizaine de pages : un extrait qu'on partage, pas
 * un livre. Au-delà, partager le texte comme fichier (.txt) le fait lire par
 * le serveur, qui dit s'il le coupe ; un texte plus long est refusé ici avec
 * sa phrase plutôt que tronqué sans le dire. La coquille applique la même
 * borne avant d'envoyer.
 */
export const TEXTE_MAX = 20_000;

export interface FichierPartage {
  nom: string;
  mime: string;
  /** Le contenu en base64, sans en-tête `data:`. */
  base64: string;
}

export interface PartageLu {
  texte: string;
  fichiers: FichierPartage[];
}

/** Ce que le compositeur dit avoir reçu — la réponse rendue à la coquille. */
export interface AccuseDePartage {
  texte: boolean;
  fichiers: number;
}

/** Octets d'un base64 sans le décoder : 3 octets pour 4 signes, moins le bourrage. */
function octetsDuBase64(b64: string): number {
  const bourrage = b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0;
  return Math.floor((b64.length * 3) / 4) - bourrage;
}

/**
 * Lit la demande de la coquille ; lève avec la phrase à lui rendre sinon.
 * Tout ce qui n'est pas une chaîne est illisible — jamais deviné.
 */
export function lirePartage(donnees: unknown): PartageLu {
  if (!donnees || typeof donnees !== 'object') throw new Error(traduire('natif.partage.illisible'));
  const brut = donnees as { texte?: unknown; fichiers?: unknown };
  if (brut.texte !== undefined && typeof brut.texte !== 'string') {
    throw new Error(traduire('natif.partage.illisible'));
  }
  const texte = (brut.texte ?? '').trim();
  if (texte.length > TEXTE_MAX) {
    throw new Error(traduire('natif.partage.texteTropLong', { max: TEXTE_MAX }));
  }
  if (brut.fichiers !== undefined && !Array.isArray(brut.fichiers)) {
    throw new Error(traduire('natif.partage.illisible'));
  }
  const entrees = (brut.fichiers ?? []) as unknown[];
  if (entrees.length > FICHIERS_MAX) {
    throw new Error(traduire('natif.partage.tropDeFichiers', { nombre: entrees.length, max: FICHIERS_MAX }));
  }
  const fichiers: FichierPartage[] = [];
  for (const entree of entrees) {
    const f = entree as { nom?: unknown; mime?: unknown; base64?: unknown } | null;
    if (
      !f ||
      typeof f.nom !== 'string' ||
      !f.nom.trim() ||
      typeof f.mime !== 'string' ||
      typeof f.base64 !== 'string' ||
      !/^[A-Za-z0-9+/]*={0,2}$/.test(f.base64)
    ) {
      throw new Error(traduire('natif.partage.illisible'));
    }
    if (octetsDuBase64(f.base64) > OCTETS_MAX_PAR_FICHIER) {
      throw new Error(traduire('natif.partage.fichierTropLourd', { nom: f.nom.trim() }));
    }
    fichiers.push({ nom: f.nom.trim(), mime: f.mime.trim(), base64: f.base64 });
  }
  if (!texte && fichiers.length === 0) throw new Error(traduire('natif.partage.vide'));
  return { texte, fichiers };
}

/** Les fichiers du partage, prêts pour `joindre` du compositeur. */
export function fichiersDuPartage(partage: PartageLu): File[] {
  return partage.fichiers.map((f) => {
    const binaire = atob(f.base64);
    const octets = new Uint8Array(binaire.length);
    for (let i = 0; i < binaire.length; i += 1) octets[i] = binaire.charCodeAt(i);
    return new File([octets], f.nom, { type: f.mime });
  });
}

type Minuteur = Pick<typeof globalThis, 'setTimeout' | 'clearTimeout'>;

/** Le compositeur prend le partage et dit ce qu'il a pris. */
export type Preneur = (partage: PartageLu) => AccuseDePartage;

/**
 * La boîte entre le verbe `partager` et le compositeur.
 *
 * Le partage peut arriver avant que la Discussion soit montée (la coquille
 * le remet dès que la page est là, peut-être sur les Tâches) : il attend
 * dans la boîte, et le compositeur le prend à sa montée. Une seule place :
 * un second partage arrivé avant que le premier soit pris le remplace, et
 * le premier est dit non déposé — jamais deux partages mêlés dans le même
 * brouillon sans que personne l'ait voulu.
 */
export class BoiteDuPartage {
  private preneur: Preneur | null = null;
  private enAttente: {
    partage: PartageLu;
    resoudre: (accuse: AccuseDePartage | null) => void;
  } | null = null;

  /**
   * Remet le partage au compositeur, tout de suite s'il écoute, sinon dès
   * qu'il s'inscrit ; `null` si personne ne l'a pris dans `delaiMs`. Un
   * partage expiré est RETIRÉ de la boîte : il ne doit pas apparaître plus
   * tard dans un compositeur, après que la coquille a dit « non déposé ».
   */
  deposer(partage: PartageLu, delaiMs: number, minuteur: Minuteur = globalThis): Promise<AccuseDePartage | null> {
    this.enAttente?.resoudre(null);
    this.enAttente = null;
    if (this.preneur) return Promise.resolve(this.remettre(this.preneur, partage));
    return new Promise((resoudre) => {
      const place = {
        partage,
        resoudre: (accuse: AccuseDePartage | null) => {
          minuteur.clearTimeout(expiration);
          resoudre(accuse);
        },
      };
      const expiration = minuteur.setTimeout(() => {
        if (this.enAttente === place) this.enAttente = null;
        resoudre(null);
      }, delaiMs);
      this.enAttente = place;
    });
  }

  /** Le compositeur écoute ; rend la désinscription. */
  ecouter(preneur: Preneur): () => void {
    this.preneur = preneur;
    const place = this.enAttente;
    if (place) {
      this.enAttente = null;
      place.resoudre(this.remettre(preneur, place.partage));
    }
    return () => {
      if (this.preneur === preneur) this.preneur = null;
    };
  }

  private remettre(preneur: Preneur, partage: PartageLu): AccuseDePartage | null {
    try {
      return preneur(partage);
    } catch {
      return null;
    }
  }
}

export interface DependancesDuPartage {
  /** `navigate()` du routeur, vers la Discussion. */
  naviguer: (chemin: string) => void;
  boite: Pick<BoiteDuPartage, 'deposer'>;
  delaiMs: number;
}

/** Le chemin de la Discussion (`<Route index element={<ChatPage />} />`). */
export const CHEMIN_DE_LA_DISCUSSION = '/';

/**
 * Lit, dépose, puis navigue. La boîte garde le partage jusqu'au compositeur,
 * qu'il soit déjà monté, qu'il monte pendant `navigate()` ou après : l'ordre
 * ne décide pas du dépôt, seul l'accusé le fait. Un partage illisible est
 * refusé avant tout mouvement de page. Rend l'accusé du compositeur ; lève
 * avec la phrase à rendre sinon.
 */
export async function recevoirUnPartage(donnees: unknown, d: DependancesDuPartage): Promise<AccuseDePartage> {
  const partage = lirePartage(donnees);
  const accuse = d.boite.deposer(partage, d.delaiMs);
  d.naviguer(CHEMIN_DE_LA_DISCUSSION);
  const recu = await accuse;
  if (!recu) throw new Error(traduire('natif.partage.pasDepose'));
  return recu;
}

/** La boîte du bundle, une par page. */
export const boiteDuPartage = new BoiteDuPartage();
