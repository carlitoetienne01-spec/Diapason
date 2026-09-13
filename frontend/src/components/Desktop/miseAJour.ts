// La mise à jour de l'app — la logique, sans écran.
//
// Le bandeau vivait en haut de la fenêtre, en surimpression, dans les
// couleurs d'un autre thème (Catppuccin en dur). Demandé le 13 septembre
// 2026 : « en bas, au-dessus de Réglages et Parler, un clic pour
// installer ». La logique est ici, en fonctions pures et en un crochet ;
// `BandeauMiseAJour.tsx` la dessine dans la barre latérale.

export type EtatMiseAJour = 'aucune' | 'disponible' | 'installation' | 'prete' | 'echec';

/** Vérification au lancement, puis toutes les 30 minutes — comme avant. */
export const INTERVALLE_VERIFICATION_MS = 30 * 60 * 1000;
const CLE_DESACTIVEE = 'oj-auto-update-disabled';
/** Pour voir le bandeau sans version publiée : `localStorage['diapason-simuler-maj'] = '1.2.3'`. */
export const CLE_SIMULATION = 'diapason-simuler-maj';

export function isAutoUpdateDisabled(): boolean {
  try {
    return localStorage.getItem(CLE_DESACTIVEE) === '1';
  } catch {
    return false;
  }
}

export function setAutoUpdateDisabled(disabled: boolean): void {
  try {
    if (disabled) localStorage.setItem(CLE_DESACTIVEE, '1');
    else localStorage.removeItem(CLE_DESACTIVEE);
  } catch {
    // Pas de stockage (navigation privée) : le réglage ne survit pas, c'est tout.
  }
}

/** La version à simuler, ou vide. Ne lit rien dans une app de bureau réelle. */
export function versionSimulee(estTauri: boolean): string {
  if (estTauri) return '';
  try {
    return (localStorage.getItem(CLE_SIMULATION) || '').trim();
  } catch {
    return '';
  }
}

/**
 * Le pourcentage téléchargé, borné et entier. Sans taille annoncée, on ne
 * peut rien dire : 0, et la barre reste indéterminée.
 */
export function pourcentage(telecharge: number, total: number | null | undefined): number {
  if (!total || total <= 0 || !Number.isFinite(telecharge)) return 0;
  return Math.max(0, Math.min(100, Math.round((telecharge / total) * 100)));
}

/**
 * Faut-il interroger le serveur de mises à jour ? Jamais hors de l'app de
 * bureau (un navigateur n'a rien à installer), jamais si l'utilisateur l'a
 * éteint dans Réglages, jamais si le développeur a posé
 * `VITE_DIAPASON_NO_UPDATER=1` pour ne pas polluer ses journaux.
 */
export function doitVerifier(options: {
  estTauri: boolean;
  desactivee: boolean;
  variableDev: string | undefined;
}): boolean {
  if (!options.estTauri) return false;
  if (options.desactivee) return false;
  const v = (options.variableDev || '').trim().toLowerCase();
  if (v === '1' || v === 'true') return false;
  return true;
}
