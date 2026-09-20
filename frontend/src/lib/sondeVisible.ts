/** Une sonde de données secondaires : jamais deux lectures simultanées,
 * aucun réveil périodique hors écran, annulation à la sortie. */
export function creerSondeVisible(
  lire: (signal: AbortSignal) => Promise<void>,
  visible: () => boolean,
  intervalleMs: number,
) {
  let fermee = false;
  let controle: AbortController | null = null;
  let attente: Promise<void> | null = null;
  let minuteur: ReturnType<typeof setTimeout> | null = null;
  const suspendre = () => {
    if (minuteur !== null) clearTimeout(minuteur);
    minuteur = null;
    controle?.abort();
    controle = null;
    attente = null;
  };
  const rafraichir = (): Promise<void> => {
    if (fermee || !visible()) return Promise.resolve();
    if (attente) return attente;
    if (minuteur !== null) clearTimeout(minuteur);
    minuteur = null;
    const courant = new AbortController();
    controle = courant;
    attente = Promise.resolve()
      .then(() => { if (!courant.signal.aborted) return lire(courant.signal); })
      .catch(() => {})
      .finally(() => {
        if (controle !== courant) return;
        attente = null;
        controle = null;
        if (!fermee && visible()) minuteur = setTimeout(() => void rafraichir(), intervalleMs);
      });
    return attente;
  };
  return {
    rafraichir,
    suspendre,
    fermer: () => {
      fermee = true;
      suspendre();
    },
  };
}
