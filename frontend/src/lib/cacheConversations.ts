import type { ConversationStore } from '../types';

// 19/09/2026 : chaque fragment reparsait/réécrivait TOUT l'historique.
// Un point de reprise par seconde réduit le texte perdu à un arrêt brutal
// (les minuteurs suspendus peuvent retarder ce point) ; la fin du flux et
// les événements de fermeture vident immédiatement ce qui reste.
export const POINT_REPRISE_MS = 1000;

export function creerCacheConversations(
  lire: () => string | null,
  ecrire: (texte: string) => void,
) {
  let courant: ConversationStore | null = null;
  let sale = false;
  let panne = false;
  let minuteur: ReturnType<typeof setTimeout> | null = null;

  function charger(): ConversationStore {
    if (courant) return courant;
    try {
      const brut = lire();
      const donnees = brut ? JSON.parse(brut) : null;
      if (donnees?.version === 1 && donnees.conversations
        && typeof donnees.conversations === 'object' && !Array.isArray(donnees.conversations)) {
        courant = donnees;
      }
    } catch { /* Le serveur peut restaurer un cache absent ou illisible. */ }
    courant ??= { version: 1, conversations: {}, activeId: null };
    return courant;
  }

  function vider(): boolean {
    if (minuteur !== null) clearTimeout(minuteur);
    minuteur = null;
    if (!sale || !courant) return true;
    try {
      ecrire(JSON.stringify(courant));
      sale = false;
      if (panne) console.warn('[conversations] sauvegarde locale rétablie');
      panne = false;
      return true;
    } catch {
      // Le prochain essai relit la copie EN MÉMOIRE : l'ancien code relisait
      // le disque après un quota plein et poussait au serveur un vieux texte.
      if (!panne) console.warn('[conversations] sauvegarde locale indisponible ; copie conservée en mémoire');
      panne = true;
      return false;
    }
  }

  function sauver(suivant: ConversationStore, differe = false): void {
    courant = suivant;
    sale = true;
    if (!differe) { vider(); return; }
    // Pas de debounce glissant : un flux continu doit aussi avoir des points
    // de reprise. L'appelant émet la modification même si le disque échoue.
    minuteur ??= setTimeout(vider, POINT_REPRISE_MS);
  }

  return { charger, sauver, vider };
}
