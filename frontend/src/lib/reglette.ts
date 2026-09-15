// La réglette de bord — l'onglet natif collé au bord de l'écran — ne doit
// apparaître que HORS de Diapason. C'est le frontend qui sait quand sa propre
// fenêtre gagne ou perd le focus : on cache la réglette quand Diapason est au
// premier plan, on la remontre quand une autre app le prend.
//
// Pourquoi ici et pas un observateur natif : NSWorkspace ne dit pas « MA
// fenêtre a le focus », il dit « telle app est active » — et le comparer au
// bundle de Diapason est fragile (ad hoc signing, aide, panneaux). La fenêtre,
// elle, connaît son propre focus sans ambiguïté.
//
// Sur navigateur (pas Tauri), il n'existe pas de réglette : no-op silencieux.

import { isTauri } from './api';

/**
 * Branche la réglette sur le focus de la fenêtre. Rend une fonction de
 * débranchement (pour le cleanup React). Toute erreur — commande absente sur
 * une plateforme sans réglette (Windows, Linux) — est avalée : la réglette est
 * un plus, jamais un point de panne pour l'app.
 */
export async function brancherReglette(): Promise<() => void> {
  if (!isTauri()) return () => {};
  try {
    const [{ getCurrentWindow }, { invoke }] = await Promise.all([
      import('@tauri-apps/api/window'),
      import('@tauri-apps/api/core'),
    ]);
    const fenetre = getCurrentWindow();
    const appliquer = (auPremierPlan: boolean) => {
      invoke(auPremierPlan ? 'reglette_hide' : 'reglette_show').catch(() => {});
    };
    // État initial : au lancement Diapason est au premier plan → cacher.
    appliquer(await fenetre.isFocused());
    return await fenetre.onFocusChanged(({ payload }) => appliquer(payload));
  } catch {
    return () => {};
  }
}
