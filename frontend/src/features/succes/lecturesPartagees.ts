/** 19/09/2026 : deux montages réclamaient simultanément la même grosse liste.
 * On partage seulement le travail EN VOL. Une écriture invalide les lectures
 * à son départ et à sa fin : son rafraîchissement ne reprend pas un vieux GET.
 */
export function creerLecturesPartagees() {
  const enVol = new Map<string, Promise<unknown>>();
  const invalider = () => enVol.clear();
  const lire = <T,>(cle: string, charger: () => Promise<T>): Promise<T> => {
    let travail = enVol.get(cle) as Promise<T> | undefined;
    if (!travail) {
      travail = charger();
      enVol.set(cle, travail);
      const courant = travail;
      void travail.finally(() => {
        if (enVol.get(cle) === courant) enVol.delete(cle);
      }).catch(() => {});
    }
    // Les appelants peuvent travailler leur résultat sans altérer l'autre
    // page : seule la réception/parsing est partagée, jamais ses mutations.
    return travail.then((valeur) => structuredClone(valeur));
  };
  return { lire, invalider };
}

/** Chaque page n'applique que sa dernière demande, même si les réponses
 * reviennent dans le désordre ou après une mutation locale. */
export function creerDerniereLecture() {
  let version = 0;
  return {
    commencer: () => {
      const courant = ++version;
      return () => courant === version;
    },
    invalider: () => { version++; },
  };
}

/** L'ordre d'envoi des sauvegardes est aussi leur ordre de persistance.
 * Chaque travail lit le brouillon au départ, après le précédent. */
export function creerFileEcritures() {
  let precedente: Promise<unknown> = Promise.resolve();
  return <T,>(ecrire: () => Promise<T>): Promise<T> => {
    const courante = precedente.then(ecrire, ecrire);
    precedente = courante.catch(() => {});
    return courante;
  };
}
