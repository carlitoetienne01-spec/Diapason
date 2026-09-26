/**
 * Le titre de la vue Semaine affichait deux dates ISO brutes — « Semaine du
 * 2026-09-14 – 2026-09-20 », 33 caractères coincés entre deux chevrons dans
 * un mini-panneau de 340 px (audit du mini-panneau, 16 sept. 2026). On rend
 * une date humaine, courte, qui tient à toute largeur : « 14 – 20 sept. ».
 */

function analyserIso(iso: string) {
  const [annee, mois, jour] = iso.split('-').map(Number);
  return new Date(annee, mois - 1, jour, 12);
}

/**
 * Libellé humain d'un intervalle de jours (bornes incluses).
 *
 * - même mois : « 14 – 20 sept. » ;
 * - deux mois : « 28 sept. – 4 oct. » ;
 * - l'année n'apparaît que si elle diffère de l'année courante ou change en
 *   cours d'intervalle — sinon elle ne dit rien et prend la place du reste.
 */
export function libelleIntervalle(
  debutIso: string,
  finIso: string,
  anneeCourante: number = new Date().getFullYear(),
  locale = 'fr-CA',
): string {
  const debut = analyserIso(debutIso);
  const fin = analyserIso(finIso);
  const memeAnnee = debut.getFullYear() === fin.getFullYear();
  const anneeUtile = !memeAnnee || debut.getFullYear() !== anneeCourante;

  const jour = new Intl.DateTimeFormat(locale, { day: 'numeric' });
  const jourMois = new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    ...(anneeUtile ? { year: 'numeric' as const } : {}),
  });

  const memeMois = memeAnnee && debut.getMonth() === fin.getMonth();
  const gauche = memeMois ? jour.format(debut) : jourMois.format(debut);
  return `${gauche} – ${jourMois.format(fin)}`;
}
