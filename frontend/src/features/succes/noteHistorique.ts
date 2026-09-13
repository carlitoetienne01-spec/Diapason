// L'historique d'une note — Annuler et Rétablir, à nous.
//
// La pile d'annulation du navigateur ne tient pas dans cet éditeur : la
// pagination manipule le DOM (des cales posées et retirées) et « détruit la
// pile en permanence » (voir RichNoteEditor.tsx), et les gestes de bloc
// (liste, séparateur, citation, code, tableau — noteEdition.ts) ne passent
// plus par `execCommand`, donc n'y entrent pas. Au banc WebKit du 13 septembre
// 2026, Annuler après « liste puis frappe » retirait la frappe et gardait la
// liste. Ici : des instantanés du contenu (sans les cales) et du caret,
// regroupés pour que la frappe ne fasse pas un pas par caractère.

export interface Instantane {
  /** Le HTML de la note, cales de pagination retirées. */
  html: string;
  /** Où était le caret — bloc de premier niveau et rang du caractère. */
  place: { bloc: number; rang: number } | null;
}

/** Deux frappes séparées de moins que ça sont un seul pas d'annulation. */
export const FENETRE_FRAPPE_MS = 800;
/** Au-delà, les plus anciens pas tombent : une note de 20 pages n'a pas besoin de 10 000 retours. */
export const PROFONDEUR_MAX = 200;

export class Historique {
  private passe: Instantane[] = [];
  private futur: Instantane[] = [];
  private derniereFrappe = -Infinity;

  constructor(private readonly profondeur = PROFONDEUR_MAX) {}

  /** Un geste distinct (bouton de la barre, gras, liste…) : toujours un pas. */
  noterGeste(avant: Instantane): void {
    this.empiler(avant);
    this.derniereFrappe = -Infinity;
  }

  /**
   * Une frappe : un pas seulement si la précédente remonte à plus de
   * FENETRE_FRAPPE_MS — sinon elle rejoint le pas en cours.
   */
  noterFrappe(avant: Instantane, maintenant: number): void {
    if (maintenant - this.derniereFrappe > FENETRE_FRAPPE_MS) this.empiler(avant);
    this.derniereFrappe = maintenant;
  }

  /** Le pas à restaurer, ou null s'il n'y a rien à annuler. `courant` va dans le futur. */
  annuler(courant: Instantane): Instantane | null {
    const cible = this.passe.pop();
    if (!cible) return null;
    // Un pas identique au présent (rien n'a changé entre les deux) ne vaut
    // pas un clic : on remonte encore d'un cran.
    if (cible.html === courant.html) return this.annuler(courant);
    this.futur.push(courant);
    this.derniereFrappe = -Infinity;
    return cible;
  }

  retablir(courant: Instantane): Instantane | null {
    const cible = this.futur.pop();
    if (!cible) return null;
    this.passe.push(courant);
    this.derniereFrappe = -Infinity;
    return cible;
  }

  get peutAnnuler(): boolean {
    return this.passe.length > 0;
  }

  get peutRetablir(): boolean {
    return this.futur.length > 0;
  }

  /**
   * Après un geste, la frappe qui suit ouvre TOUJOURS un nouveau pas — sans
   * cette coupure, « liste puis “deux” » ne faisait qu'un pas, et Annuler
   * sautait la liste seule.
   */
  couper(): void {
    this.derniereFrappe = -Infinity;
  }

  /** Changer de note : on repart de zéro. */
  vider(): void {
    this.passe = [];
    this.futur = [];
    this.derniereFrappe = -Infinity;
  }

  private empiler(avant: Instantane): void {
    // Un nouveau pas rend le futur caduc — comme partout.
    this.futur = [];
    const dernier = this.passe[this.passe.length - 1];
    if (dernier && dernier.html === avant.html) return;
    this.passe.push(avant);
    if (this.passe.length > this.profondeur) this.passe.shift();
  }
}
