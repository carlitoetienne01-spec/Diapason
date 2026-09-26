// Le pont natif — quand le bundle tourne dans la coquille Flutter du
// téléphone (docs/development/diapason-mobile.md, phase 3, étape 3).
//
// La coquille injecte AVANT le chargement un canal JavaScript nommé
// `DiapasonNatif` (un `JavaScriptChannel` de webview_flutter : un objet qui
// n'a qu'une méthode, `postMessage(texte)`). Sa présence est LA seule preuve
// qu'on est dans le téléphone — ni la largeur, ni l'agent utilisateur : un
// navigateur de 375 px n'est pas un téléphone qui sait enregistrer un
// fichier. Comme `compact.ts`, on lit une fois et on normalise sur <html>
// (`data-diapason-mobile="1"`), sans course ni scintillement.
//
// Le secret de session reste un cookie HttpOnly que ce code ne voit jamais :
// aucun verbe ne rend une clé, un jeton ou un mot de passe au JavaScript.
// La liste des verbes est fermée et gardée par un test.

import { traduire } from '../i18n/translate';

/** Ce que le bundle demande à la coquille. */
export const VERBES_SORTANTS = ['theme', 'enregistrer', 'ouvrirExterne'] as const;
/** Ce que la coquille demande au bundle. */
export const VERBES_ENTRANTS = ['retour'] as const;

export type VerbeSortant = (typeof VERBES_SORTANTS)[number];
export type VerbeEntrant = (typeof VERBES_ENTRANTS)[number];

/**
 * Le délai de chaque verbe, en millisecondes.
 *
 * `enregistrer` attend une PERSONNE : Android peut ouvrir son sélecteur de
 * documents, où l'on choisit un dossier à son rythme. Deux minutes, parce
 * qu'au-delà le bouton « Export… » tournerait sans fin sur un sélecteur
 * oublié ; le fichier, lui, ne sera pas annoncé tant que la coquille ne l'a
 * pas écrit. Les deux autres ne font que traverser le canal (quelques
 * millisecondes) : dix secondes couvrent une coquille occupée à démarrer,
 * pas davantage.
 */
export const DELAIS_MS: Record<VerbeSortant, number> = {
  enregistrer: 120_000,
  theme: 10_000,
  ouvrirExterne: 10_000,
};

export interface CanalNatif {
  postMessage(message: string): void;
}

export type ReponseNatif = {
  type: 'reponse';
  id: string;
  ok: boolean;
  donnees?: unknown;
  /** `annule` quand la personne a renoncé ; sinon une phrase de la coquille. */
  erreur?: string;
};

type DemandeNatif = {
  type: 'demande';
  id: string;
  verbe: string;
  donnees?: unknown;
};

type Attente = {
  verbe: VerbeSortant;
  resoudre: (reponse: ReponseNatif) => void;
  rejeter: (erreur: Error) => void;
  minuteur: ReturnType<typeof setTimeout>;
};

export type OptionsPont = {
  /** Le texte de l'erreur de délai ; par défaut, dans la langue affichée. */
  messageDelai?: (verbe: VerbeSortant, secondes: number) => string;
  delais?: Partial<Record<VerbeSortant, number>>;
};

/** Un objet qui ressemble au canal injecté — et rien d'autre ne compte. */
export function detecterCanal(fenetre: unknown): CanalNatif | null {
  if (!fenetre || typeof fenetre !== 'object') return null;
  const canal = (fenetre as { DiapasonNatif?: unknown }).DiapasonNatif;
  if (!canal || typeof (canal as CanalNatif).postMessage !== 'function') return null;
  return canal as CanalNatif;
}

function lireMessage(brut: unknown): ReponseNatif | DemandeNatif | null {
  let objet: unknown = brut;
  if (typeof brut === 'string') {
    try {
      objet = JSON.parse(brut);
    } catch {
      return null;
    }
  }
  if (!objet || typeof objet !== 'object') return null;
  const m = objet as Record<string, unknown>;
  if (typeof m.id !== 'string' || !m.id) return null;
  if (m.type === 'reponse' && typeof m.ok === 'boolean') {
    return {
      type: 'reponse',
      id: m.id,
      ok: m.ok,
      donnees: m.donnees,
      erreur: typeof m.erreur === 'string' ? m.erreur : undefined,
    };
  }
  if (m.type === 'demande' && typeof m.verbe === 'string') {
    return { type: 'demande', id: m.id, verbe: m.verbe, donnees: m.donnees };
  }
  return null;
}

/**
 * Requête et réponse, appariées par identifiant, avec un délai limite.
 *
 * Trois cas que le protocole doit tenir (26/09/2026) :
 * - la réponse arrive AVANT que l'attente soit posée — une coquille qui
 *   répond pendant `postMessage` même. Sans la table `enAvance`, la réponse
 *   tombait dans le vide et la promesse attendait son délai pour échouer ;
 * - le délai expire : une erreur lisible, dans la langue affichée, plutôt
 *   qu'un bouton qui tourne pour toujours ;
 * - un identifiant inconnu (jamais émis, ou déjà expiré) est IGNORÉ : une
 *   réponse tardive ne doit pas résoudre la demande suivante.
 */
export class PontNatif {
  private suivant = 0;
  private readonly attentes = new Map<string, Attente>();
  /** Émis, mais dont l'attente n'est pas encore posée. */
  private readonly emis = new Set<string>();
  private readonly enAvance = new Map<string, ReponseNatif>();
  private readonly retours: Array<() => boolean> = [];
  private readonly canal: CanalNatif;
  private readonly options: OptionsPont;

  constructor(canal: CanalNatif, options: OptionsPont = {}) {
    this.canal = canal;
    this.options = options;
  }

  demander(verbe: VerbeSortant, donnees?: unknown): Promise<ReponseNatif> {
    if (!(VERBES_SORTANTS as readonly string[]).includes(verbe)) {
      return Promise.reject(new Error(`verbe inconnu : ${String(verbe)}`));
    }
    this.suivant += 1;
    const id = `b${this.suivant}`;
    this.emis.add(id);
    try {
      this.canal.postMessage(JSON.stringify({ type: 'demande', id, verbe, donnees }));
    } catch (exc) {
      this.emis.delete(id);
      this.enAvance.delete(id);
      return Promise.reject(exc instanceof Error ? exc : new Error(String(exc)));
    }
    const deja = this.enAvance.get(id);
    if (deja) {
      this.enAvance.delete(id);
      this.emis.delete(id);
      return Promise.resolve(deja);
    }
    const delai = this.options.delais?.[verbe] ?? DELAIS_MS[verbe];
    return new Promise<ReponseNatif>((resoudre, rejeter) => {
      const minuteur = setTimeout(() => {
        this.attentes.delete(id);
        this.emis.delete(id);
        const secondes = Math.round(delai / 1000);
        const texte = this.options.messageDelai
          ? this.options.messageDelai(verbe, secondes)
          : traduire('natif.delai', { verbe, secondes });
        rejeter(new Error(texte));
      }, delai);
      this.attentes.set(id, { verbe, resoudre, rejeter, minuteur });
    });
  }

  /** Point d'entrée de la coquille : `window.diapasonNatifRecevoir(message)`. */
  recevoir(brut: unknown): void {
    const message = lireMessage(brut);
    if (!message) return;
    if (message.type === 'demande') {
      this.repondreA(message);
      return;
    }
    const attente = this.attentes.get(message.id);
    if (attente) {
      clearTimeout(attente.minuteur);
      this.attentes.delete(message.id);
      this.emis.delete(message.id);
      attente.resoudre(message);
      return;
    }
    if (this.emis.has(message.id)) this.enAvance.set(message.id, message);
    // Sinon : identifiant inconnu ou expiré — ignoré.
  }

  /**
   * Qui veut consommer le bouton retour d'Android. Le dernier inscrit parle
   * le premier (une feuille ouverte par-dessus la barre latérale se ferme
   * avant elle). Rend la désinscription.
   */
  surRetour(gestionnaire: () => boolean): () => void {
    this.retours.push(gestionnaire);
    return () => {
      const i = this.retours.lastIndexOf(gestionnaire);
      if (i >= 0) this.retours.splice(i, 1);
    };
  }

  private repondreA(demande: DemandeNatif): void {
    let reponse: ReponseNatif;
    if (demande.verbe === 'retour') {
      let traite = false;
      for (let i = this.retours.length - 1; i >= 0 && !traite; i -= 1) {
        try {
          traite = this.retours[i]() === true;
        } catch {
          traite = false;
        }
      }
      // `traite: false` n'est pas un échec : la coquille fait alors son propre
      // retour (historique de la WebView, puis arrière-plan).
      reponse = { type: 'reponse', id: demande.id, ok: true, donnees: { traite } };
    } else {
      reponse = { type: 'reponse', id: demande.id, ok: false, erreur: 'verbeInconnu' };
    }
    try {
      this.canal.postMessage(JSON.stringify(reponse));
    } catch {
      // Le canal est mort : la coquille verra son propre délai expirer.
    }
  }
}

const canal = typeof window === 'undefined' ? null : detecterCanal(window);

/** Vrai dans la coquille du téléphone, et seulement là. */
export const estMobile = canal !== null;

/** Le pont, ou `null` hors du téléphone. */
export const pontNatif: PontNatif | null = canal ? new PontNatif(canal) : null;

if (pontNatif && typeof document !== 'undefined') {
  document.documentElement.setAttribute('data-diapason-mobile', '1');
  (window as unknown as { diapasonNatifRecevoir?: (m: unknown) => void }).diapasonNatifRecevoir =
    (message: unknown) => pontNatif.recevoir(message);
}

/** Demander à la coquille, ou échouer lisiblement hors du téléphone. */
export function demanderAuTelephone(
  verbe: VerbeSortant,
  donnees?: unknown,
  pont: PontNatif | null = pontNatif,
): Promise<ReponseNatif> {
  if (!pont) return Promise.reject(new Error(traduire('natif.absent')));
  return pont.demander(verbe, donnees);
}
