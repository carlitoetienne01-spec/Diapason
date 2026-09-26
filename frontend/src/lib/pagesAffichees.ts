// Ce qui est vraiment à l'écran — pour qu'une navigation demandée par la
// coquille du téléphone ne soit acquittée qu'une fois la page montée.
//
// 26/09/2026, phase 3 étape 9 (docs/development/diapason-mobile.md). Au
// téléphone, `app.navigate` arrive à la coquille Flutter, qui demande
// l'écran au bundle (verbe `naviguer`). Répondre « ouvert » dès l'appel à
// `navigate()` rejouait le faux SUCCESS que le récepteur Python avait déjà
// payé le 25/09/2026 : les pages sont chargées paresseusement, et sur un
// réseau mobile le morceau peut ne jamais arriver — l'appareil qui a
// demandé lisait « L'écran est ouvert » devant un « Chargement… ».
//
// Une page signale sa montée depuis un effet : React ne lance les effets
// qu'après avoir posé l'arbre dans le document, et jamais pour un arbre
// resté suspendu derrière son `Suspense`.

type Attente = { chemin: string; resoudre: (affichee: boolean) => void };

export class PagesAffichees {
  private courante: string | null = null;
  private readonly attentes = new Set<Attente>();

  /** La page à `chemin` est montée ; rend son démontage. */
  signalerMontee(chemin: string): () => void {
    this.courante = chemin;
    for (const attente of [...this.attentes]) {
      if (attente.chemin === chemin) {
        this.attentes.delete(attente);
        attente.resoudre(true);
      }
    }
    return () => {
      if (this.courante === chemin) this.courante = null;
    };
  }

  /** La page affichée, ou `null` entre deux pages. */
  get affichee(): string | null {
    return this.courante;
  }

  /**
   * Vrai dès que `chemin` est monté (tout de suite s'il l'est déjà), faux
   * au bout de `delaiMs`. À poser AVANT de naviguer : la montée peut
   * arriver pendant `navigate()` même.
   */
  attendre(
    chemin: string,
    delaiMs: number,
    minuteur: Pick<typeof globalThis, 'setTimeout' | 'clearTimeout'> = globalThis,
  ): Promise<boolean> {
    if (this.courante === chemin) return Promise.resolve(true);
    return new Promise<boolean>((resoudre) => {
      const attente: Attente = {
        chemin,
        resoudre: (affichee) => {
          minuteur.clearTimeout(expiration);
          resoudre(affichee);
        },
      };
      const expiration = minuteur.setTimeout(() => {
        this.attentes.delete(attente);
        resoudre(false);
      }, delaiMs);
      this.attentes.add(attente);
    });
  }
}

export const pagesAffichees = new PagesAffichees();
