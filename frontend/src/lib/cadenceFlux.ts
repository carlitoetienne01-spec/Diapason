// 19/09/2026 : la bulle était limitée à 80 ms, mais le store de progression
// changeait à CHAQUE fragment. Une rafale refaisait quand même tout le chat.
// Premier texte immédiat, dernier fragment au plus 80 ms après, même si le
// fournisseur s'arrête entre deux mots. Aucun rAF requis hors écran.
export function creerCadenceFlux(publier: () => void, intervalle = 80) {
  let dernier = -Infinity;
  let attente = false;
  let minuteur: ReturnType<typeof setTimeout> | null = null;

  const annuler = () => {
    if (minuteur !== null) clearTimeout(minuteur);
    minuteur = null;
    attente = false;
  };
  const vider = () => {
    const necessaire = attente;
    annuler();
    if (!necessaire) return;
    dernier = performance.now();
    publier();
  };
  const demander = () => {
    attente = true;
    const reste = intervalle - (performance.now() - dernier);
    if (reste <= 0) vider();
    else minuteur ??= setTimeout(vider, reste);
  };
  return { demander, vider, annuler };
}
