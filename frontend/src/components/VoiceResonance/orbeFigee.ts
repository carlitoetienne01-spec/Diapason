import type { VoiceLiveState } from '../../hooks/useVoiceLive';

/**
 * L'orbe de la voix arrête-t-elle sa boucle d'images ? Elle garde alors sa
 * dernière image, dessinée une fois.
 *
 * 26/09/2026, chantier de la fluidité (lot 3) : au téléphone, l'orbe tournait
 * sa scène WebGL à chaque image dès l'ouverture de la voix, même au repos —
 * quand rien ne parle ni n'écoute —, et le processeur graphique d'un
 * téléphone la payait en chaleur et en batterie pour une image immobile au
 * regard. Au repos elle se fige ; dès que la voix écoute ou parle, elle
 * reprend. Sur le Mac, rien ne change : seul le mouvement réduit la fige.
 */
export function orbeFigee(etat: VoiceLiveState, mouvementReduit: boolean, telephone: boolean): boolean {
  return mouvementReduit || (telephone && etat === 'idle');
}
