// Le menu de l'app du téléphone, rangé dans l'écran « Aller à ».
//
// 26/09/2026, lot 4 de la fluidité : la coquille gardait au-dessus de la
// page une barre native de 40 px pour un seul bouton « ⋮ » (Recharger, Life
// OS, l'Entité, Appareils, Importer) — 5 % de la hauteur d'un écran de
// 812 px, prise à chaque page pour un menu qu'on ouvre rarement. Le bouton
// passe dans l'écran « Aller à », à côté de « Liste » et « Parler ».
//
// La poignée de main est mutuelle, pour que le menu reste atteignable dans
// les quatre combinaisons d'app et de bundle (§82) :
// - au montage, le bundle ANNONCE qu'il porte le bouton (`{ouvrir: false}`) ;
//   la coquille retire sa barre seulement après cette annonce ;
// - le bundle ne montre le bouton que si la coquille a répondu `ok` ; une
//   coquille plus ancienne répond `verbeInconnu`, et garde sa barre.

import type { ReponseNatif } from '../../lib/natif';

/** Les données du verbe `menuApp` : un seul champ, rien d'autre ne voyage. */
export type ChargeMenuApp = { ouvrir: boolean };

/** « Je porte le bouton du menu : ta barre peut partir. » */
export const ANNONCE_MENU_APP: ChargeMenuApp = { ouvrir: false };

/** « Ouvre ton menu, maintenant. » */
export const OUVRIR_MENU_APP: ChargeMenuApp = { ouvrir: true };

type Demander = (verbe: 'menuApp', donnees: ChargeMenuApp) => Promise<ReponseNatif>;

/**
 * Annonce le bouton à la coquille ; vrai seulement si elle a répondu `ok`.
 * Un refus, un délai ou une coquille qui ne connaît pas le verbe : faux,
 * et le bouton ne s'affiche pas — il n'ouvrirait rien.
 */
export async function annoncerLeMenuDeLApp(demander: Demander): Promise<boolean> {
  try {
    const reponse = await demander('menuApp', ANNONCE_MENU_APP);
    return reponse.ok === true;
  } catch {
    return false;
  }
}
