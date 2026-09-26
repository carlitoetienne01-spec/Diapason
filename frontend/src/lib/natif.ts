// Le pont natif — quand le bundle tourne dans la coquille Flutter du
// téléphone (docs/development/diapason-mobile.md, phase 3, étape 3).
//
// La coquille injecte AVANT le chargement un objet nommé `DiapasonNatif`,
// muni de `postMessage(texte)`. Sa présence est LA seule preuve
// qu'on est dans le téléphone — ni la largeur, ni l'agent utilisateur : un
// navigateur de 375 px n'est pas un téléphone qui sait enregistrer un
// fichier. Comme `compact.ts`, on lit une fois et on normalise sur <html>
// (`data-diapason-mobile="1"`), sans course ni scintillement.
//
// Le secret de session reste un cookie HttpOnly que ce code ne voit jamais :
// aucun verbe ne rend une clé, un jeton ou un mot de passe au JavaScript.
// La liste des verbes est fermée et gardée par un test.
//
// Deux formes du canal (26/09/2026, constat 2 de la seconde contre-épreuve,
// docs/development/diapason-mobile.md) :
// - le canal LIÉ, `WebViewCompat.addWebMessageListener` : Android ne
//   l'injecte que dans les pages de l'origine du Mac, et la coquille répond
//   par la voie de retour de CETTE page — l'événement `message` de l'objet.
//   Aucun point d'entrée n'est posé sur `window` ;
// - l'ancien `JavaScriptChannel` (APK jusqu'à `c8d0d09`), injecté dans toute
//   page chargée, qui répond en exécutant `window.diapasonNatifRecevoir(…)`.
//   Gardé tant qu'un téléphone porte cette app : sans lui, chacun de ses
//   `enregistrer` attendrait deux minutes pour échouer.

import { traduire } from '../i18n/translate';

/**
 * Ce que le bundle demande à la coquille.
 *
 * `bordRoue` (26/09/2026, lot 3 de la fluidité) : le côté de la roue de
 * navigation, `{ cote: 'droite' | 'gauche' }`, pour que la coquille retire
 * le bas de ce bord aux gestes d'Android. Sans lui, sur un téléphone en
 * navigation par gestes, le glissé depuis le bord droit était pris par le
 * système pour un « retour » et n'atteignait jamais la page. Il ne rend
 * rien — aucun secret.
 */
export const VERBES_SORTANTS = ['theme', 'enregistrer', 'ouvrirExterne', 'bordRoue'] as const;
/**
 * Ce que la coquille demande au bundle.
 *
 * `naviguer` (26/09/2026, phase 3 étape 9) : au téléphone, une commande du
 * maillage (`app.navigate`, `app.show_resource`) arrive à la coquille, pas à
 * la boîte du Mac ; la coquille traduit la route et demande l'écran. Il ne
 * rend qu'un chemin déjà connu d'elle — aucun secret.
 *
 * `approbations` et `partager` (26/09/2026, phase 5) : la notification
 * d'approbation touchée ouvre la cloche — jamais une décision : la coquille
 * ne rapporte que le nombre de demandes affichées — ; un « Partager vers
 * Diapason » dépose texte et fichiers dans le compositeur de la Discussion,
 * sans rien envoyer. Aucun des deux ne rend autre chose qu'un décompte.
 */
export const VERBES_ENTRANTS = ['retour', 'naviguer', 'approbations', 'partager'] as const;

/** Les verbes entrants qui attendent la page (réponse différée, un gestionnaire). */
type VerbeEntrantDiffere = Exclude<VerbeEntrant, 'retour'>;

export type VerbeSortant = (typeof VERBES_SORTANTS)[number];
export type VerbeEntrant = (typeof VERBES_ENTRANTS)[number];

/**
 * Le délai de chaque verbe, en millisecondes.
 *
 * `enregistrer` attend une PERSONNE : Android peut ouvrir son sélecteur de
 * documents, où l'on choisit un dossier à son rythme. Deux minutes, parce
 * qu'au-delà le bouton « Export… » tournerait sans fin sur un sélecteur
 * oublié ; le fichier, lui, ne sera pas annoncé tant que la coquille ne l'a
 * pas écrit. Les trois autres ne font que traverser le canal (quelques
 * millisecondes) : dix secondes couvrent une coquille occupée à démarrer,
 * pas davantage.
 */
export const DELAIS_MS: Record<VerbeSortant, number> = {
  enregistrer: 120_000,
  theme: 10_000,
  ouvrirExterne: 10_000,
  bordRoue: 10_000,
};

export interface CanalNatif {
  postMessage(message: string): void;
}

/**
 * Le canal lié à l'origine du Mac (`PontLie.kt` de la coquille) : l'objet de
 * `addWebMessageListener` porte aussi les messages de la coquille, en
 * événements `message` dont `data` est le texte.
 */
export interface CanalLie extends CanalNatif {
  addEventListener(type: 'message', ecouteur: (evenement: { data?: unknown }) => void): void;
}

/** Vrai pour le canal lié ; faux pour l'ancien `JavaScriptChannel`. */
export function estCanalLie(canal: CanalNatif): canal is CanalLie {
  return typeof (canal as Partial<CanalLie>).addEventListener === 'function';
}

/**
 * Ce que le bundle poste en premier sur le canal lié.
 *
 * La coquille ne peut parler qu'à une page qui lui a parlé : la voie de
 * retour d'Android naît du premier message. Sans lui, un bouton retour
 * pressé avant tout échange n'atteindrait pas la page. Il ne porte rien —
 * ni identifiant, ni verbe — et la coquille n'y répond pas.
 */
export const BONJOUR = { type: 'bonjour' } as const;

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
  /** Le préfixe des identifiants ; par défaut, un aléa tiré au chargement. */
  prefixe?: string;
  /**
   * Une réponse arrivée APRÈS le délai de sa demande. La promesse a déjà
   * échoué ; ce qui a eu lieu doit pourtant se dire (§100).
   */
  surReponseTardive?: (verbe: VerbeSortant, reponse: ReponseNatif) => void;
};

/**
 * Un préfixe propre à ce chargement de la page.
 *
 * 26/09/2026 : les identifiants repartaient de `b1` à chaque chargement.
 * Une réponse de la coquille encore en route à travers un rechargement
 * aurait résolu la NOUVELLE `b1` — un « enregistré » rendu à une demande de
 * thème, ou l'inverse.
 */
export function tirerPrefixe(): string {
  try {
    const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
    if (c?.randomUUID) return `b${c.randomUUID().slice(0, 8)}`;
  } catch {
    // Pas d'aléa cryptographique : le repli suffit, ce n'est pas un secret.
  }
  return `b${Math.random().toString(36).slice(2, 10)}`;
}

/** Combien d'identifiants expirés on se rappelle, pour une réponse tardive. */
const EXPIREES_MAX = 32;

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
  private readonly differes = new Map<VerbeEntrantDiffere, (donnees: unknown) => Promise<unknown>>();
  /** Expirés, avec leur verbe : une réponse tardive se dit encore. */
  private readonly expirees = new Map<string, VerbeSortant>();
  private readonly canal: CanalNatif;
  private readonly options: OptionsPont;
  private readonly prefixe: string;

  constructor(canal: CanalNatif, options: OptionsPont = {}) {
    this.canal = canal;
    this.options = options;
    this.prefixe = options.prefixe ?? tirerPrefixe();
  }

  demander(verbe: VerbeSortant, donnees?: unknown): Promise<ReponseNatif> {
    if (!(VERBES_SORTANTS as readonly string[]).includes(verbe)) {
      return Promise.reject(new Error(`verbe inconnu : ${String(verbe)}`));
    }
    this.suivant += 1;
    const id = `${this.prefixe}-${this.suivant}`;
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
        this.expirees.set(id, verbe);
        if (this.expirees.size > EXPIREES_MAX) {
          this.expirees.delete(this.expirees.keys().next().value as string);
        }
        const secondes = Math.round(delai / 1000);
        const texte = this.options.messageDelai
          ? this.options.messageDelai(verbe, secondes)
          : traduire('natif.delai', { verbe, secondes });
        rejeter(new Error(texte));
      }, delai);
      this.attentes.set(id, { verbe, resoudre, rejeter, minuteur });
    });
  }

  /**
   * Point d'entrée de la coquille : l'événement `message` du canal lié, ou
   * `window.diapasonNatifRecevoir(message)` pour l'ancien canal.
   */
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
    if (this.emis.has(message.id)) {
      this.enAvance.set(message.id, message);
      return;
    }
    const verbe = this.expirees.get(message.id);
    if (verbe) {
      // 26/09/2026 : jetée, une réponse `ok` arrivée après les deux minutes
      // d'`enregistrer` (sélecteur d'Android laissé ouvert) laissait la page
      // dire « le téléphone n'a pas répondu » alors que le fichier était
      // écrit. Elle ne résout rien — la promesse a échoué —, mais elle se dit.
      this.expirees.delete(message.id);
      try {
        this.options.surReponseTardive?.(verbe, message);
      } catch {
        // Un annonceur qui échoue ne casse pas le pont.
      }
    }
    // Sinon : identifiant inconnu — ignoré.
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

  /**
   * Qui ouvre un écran quand la coquille le demande (`naviguer`). Un seul :
   * deux navigateurs se disputeraient l'écran. Le gestionnaire rend ce qui
   * est affiché, ou lève une erreur dont le message est rendu tel quel à la
   * coquille — puis à l'appareil qui a demandé. Rend la désinscription.
   */
  surNaviguer(gestionnaire: (donnees: unknown) => Promise<unknown>): () => void {
    return this.inscrire('naviguer', gestionnaire);
  }

  /**
   * Qui ouvre la cloche quand une notification d'approbation est touchée
   * (26/09/2026, phase 5). Le gestionnaire rend `{nombre}` une fois la
   * cloche OUVERTE sur les demandes lues — il ne décide jamais rien.
   */
  surApprobations(gestionnaire: (donnees: unknown) => Promise<unknown>): () => void {
    return this.inscrire('approbations', gestionnaire);
  }

  /**
   * Qui reçoit un « Partager vers Diapason » (26/09/2026, phase 5). Le
   * gestionnaire rend son accusé une fois le texte et les fichiers DÉPOSÉS
   * dans le compositeur ; rien n'est envoyé sans le geste de la personne.
   */
  surPartager(gestionnaire: (donnees: unknown) => Promise<unknown>): () => void {
    return this.inscrire('partager', gestionnaire);
  }

  private inscrire(
    verbe: VerbeEntrantDiffere,
    gestionnaire: (donnees: unknown) => Promise<unknown>,
  ): () => void {
    this.differes.set(verbe, gestionnaire);
    return () => {
      if (this.differes.get(verbe) === gestionnaire) this.differes.delete(verbe);
    };
  }

  private poster(reponse: ReponseNatif): void {
    try {
      this.canal.postMessage(JSON.stringify(reponse));
    } catch {
      // Le canal est mort : la coquille verra son propre délai expirer.
    }
  }

  private repondreA(demande: DemandeNatif): void {
    if (
      demande.verbe === 'naviguer' ||
      demande.verbe === 'approbations' ||
      demande.verbe === 'partager'
    ) {
      void this.differer(demande.verbe, demande);
      return;
    }
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
    this.poster(reponse);
  }

  private async differer(verbe: VerbeEntrantDiffere, demande: DemandeNatif): Promise<void> {
    const gestionnaire = this.differes.get(verbe);
    if (!gestionnaire) {
      // Le bundle n'est pas encore monté (ou plus) : le dire tout de suite,
      // plutôt que laisser la coquille attendre son délai pour un écran qui
      // ne s'ouvrira pas.
      this.poster({ type: 'reponse', id: demande.id, ok: false, erreur: 'pasPret' });
      return;
    }
    try {
      const donnees = await gestionnaire(demande.donnees);
      this.poster({ type: 'reponse', id: demande.id, ok: true, donnees });
    } catch (exc) {
      const erreur = exc instanceof Error && exc.message ? exc.message : String(exc);
      this.poster({ type: 'reponse', id: demande.id, ok: false, erreur });
    }
  }
}

/**
 * Un lien que la WebView ne doit pas suivre elle-même : http(s) vers une
 * AUTRE origine que celle du Mac.
 *
 * 26/09/2026 : seuls trois points d'appel passaient par `ouvrirExterne`. Les
 * sources d'une recherche, les pastilles de citation, les liens des
 * réponses, ceux des Réglages, des Agents et des Sources étaient des
 * `<a target="_blank">` bruts : dans la WebView d'Android, ils naviguent
 * dans la même vue, que la coquille refuse (elle ne laisse passer que
 * l'origine du Mac) — un lien mort, sans un mot. Et tant que la coquille
 * n'est pas écrite, rien ne garantit ce refus : une page tierce chargée
 * dans la WebView verrait le canal `DiapasonNatif`.
 */
export function doitPasserParLaCoquille(href: string, origine: string): boolean {
  try {
    const url = new URL(href, origine);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
    return url.origin !== new URL(origine).origin;
  } catch {
    return false;
  }
}

type FenetreNatif = {
  DiapasonNatif?: unknown;
  diapasonNatifRecevoir?: (message: unknown) => void;
  location?: { origin?: string };
};

type DocumentNatif = {
  documentElement: { setAttribute(nom: string, valeur: string): void };
  addEventListener(type: 'click', ecouteur: (e: MouseEvent) => void, capture: boolean): void;
};

/**
 * Brancher le pont sur une fenêtre : rend le pont, ou `null` sans canal.
 *
 * Pose `data-diapason-mobile`, le point d'entrée de la coquille — l'écoute
 * des `message` du canal lié, ou `window.diapasonNatifRecevoir` pour
 * l'ancien canal ; SANS lui, chaque `enregistrer` attendait deux minutes
 * pour échouer et le retour d'Android n'était jamais traité — et l'écouteur
 * qui envoie les liens externes à la coquille.
 * Une fonction, pas du code de module, pour qu'un test l'éprouve sur une
 * fausse fenêtre (26/09/2026 : retirer l'affectation laissait les 1 340
 * tests verts).
 */
export function installerPont(
  fenetre: FenetreNatif,
  doc: DocumentNatif | null,
  options: OptionsPont = {},
): PontNatif | null {
  const canal = detecterCanal(fenetre);
  if (!canal) return null;
  const pont = new PontNatif(canal, options);
  if (estCanalLie(canal)) {
    canal.addEventListener('message', (evenement) => pont.recevoir(evenement?.data));
    try {
      canal.postMessage(JSON.stringify(BONJOUR));
    } catch {
      // Le canal est mort : les demandes le diront par leur délai.
    }
  } else {
    fenetre.diapasonNatifRecevoir = (message: unknown) => pont.recevoir(message);
  }
  if (doc) {
    doc.documentElement.setAttribute('data-diapason-mobile', '1');
    const origine = fenetre.location?.origin ?? '';
    // En capture : avant que la WebView ne suive le lien. Les boutons qui
    // appellent déjà `ouvrirLienExterne` ne sont pas des liens `<a>`.
    doc.addEventListener(
      'click',
      (e: MouseEvent) => {
        if (e.defaultPrevented) return;
        const cible = e.target as { closest?: (s: string) => Element | null } | null;
        const lien = cible?.closest?.('a[href]') as HTMLAnchorElement | null | undefined;
        const href = lien?.getAttribute('href');
        if (!href || !doitPasserParLaCoquille(href, origine)) return;
        e.preventDefault();
        const url = new URL(href, origine).toString();
        void pont.demander('ouvrirExterne', { url }).catch(() => undefined);
      },
      true,
    );
  }
  return pont;
}

/** Ce qu'un enregistrement arrivé trop tard a finalement écrit, dit une fois. */
function annoncerEnregistrementTardif(verbe: VerbeSortant, reponse: ReponseNatif): void {
  if (verbe !== 'enregistrer' || !reponse.ok) return;
  const nom = (reponse.donnees as { nom?: unknown } | undefined)?.nom;
  void import('sonner').then(({ toast }) =>
    toast.success(traduire('natif.enregistreTardif'), {
      description: typeof nom === 'string' && nom.trim() ? nom : undefined,
    }),
  );
}

/** Le pont, ou `null` hors du téléphone. */
export const pontNatif: PontNatif | null =
  typeof window === 'undefined'
    ? null
    : installerPont(
        window as unknown as FenetreNatif,
        typeof document === 'undefined' ? null : (document as unknown as DocumentNatif),
        { surReponseTardive: annoncerEnregistrementTardif },
      );

/** Vrai dans la coquille du téléphone, et seulement là. */
export const estMobile = pontNatif !== null;

/** Demander à la coquille, ou échouer lisiblement hors du téléphone. */
export function demanderAuTelephone(
  verbe: VerbeSortant,
  donnees?: unknown,
  pont: PontNatif | null = pontNatif,
): Promise<ReponseNatif> {
  if (!pont) return Promise.reject(new Error(traduire('natif.absent')));
  return pont.demander(verbe, donnees);
}
