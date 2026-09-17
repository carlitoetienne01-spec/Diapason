/**
 * Le panneau vient-il de s'ouvrir ? — et où le focus doit retourner.
 *
 * 17 sept. 2026, chantier « discussions dans le mini-panneau ». Rust signale
 * chaque présentation du mini-panneau (presenter_mini, agrandir_mini) par un
 * `CustomEvent('diapason:panneau-ouvert')` évalué dans la WKWebView. Deux
 * fois sur trois, personne ne l'entend : à la construction, le document est
 * encore vide (le bundle n'a pas chargé) ; à la re-navigation depuis un autre
 * module, la View Transition (.18 s) puis le rendu de React Router se font
 * APRÈS l'évaluation, et ChatPage se monte sur un signal déjà passé. Ce
 * module garde donc l'heure du dernier signal : une page qui se monte peut
 * demander « le panneau vient-il de s'ouvrir ? » sans avoir été là.
 *
 * Le focus, lui, ne se rend pas : il se DEMANDE. Toute couche qui se ferme
 * (menu de puce, palette, plus tard le sauteur) émet
 * `diapason:focus-compositeur`, et seul le compositeur décide s'il existe et
 * s'il peut prendre le focus. Aucun composant n'a à connaître le textarea.
 *
 * Même chemin pour le sauteur (⌘J) : App.tsx reçoit la touche mais le
 * sauteur est un état LOCAL de ChatArea (jamais une route, le rail réécrit
 * l'URL) — il s'ouvre sur `diapason:ouvrir-sauteur`. Et quand le sauteur
 * crée un fil depuis une requête sans résultat, le texte tapé rejoint le
 * compositeur par `diapason:deposer-texte` (detail : la chaîne), déposé et
 * jamais envoyé : InputArea seule connaît son champ.
 *
 * Et quand un résultat de recherche vient d'un MESSAGE (le sauteur ou la
 * barre latérale), le fil doit s'ouvrir « au message », pas en bas :
 * `diapason:montrer-message` (detail : l'id du message) est émis APRÈS la
 * sélection ; ChatArea, seule à tenir le conteneur de défilement, y défile
 * une fois les bulles rendues et surligne la cible 800 ms.
 */
export const EVENEMENT_PANNEAU_OUVERT = 'diapason:panneau-ouvert';
export const EVENEMENT_FOCUS_COMPOSITEUR = 'diapason:focus-compositeur';
export const EVENEMENT_OUVRIR_SAUTEUR = 'diapason:ouvrir-sauteur';
export const EVENEMENT_DEPOSER_TEXTE = 'diapason:deposer-texte';
export const EVENEMENT_MONTRER_MESSAGE = 'diapason:montrer-message';

// Une View Transition dure 180 ms et le rendu qui suit quelques dizaines ;
// 2 s laisse dix fois la marge et reste sous ce qu'une navigation VOULUE
// prend : revenir sur la Discussion depuis Tâches trois secondes plus tard
// n'est pas « ouvrir le panneau », et ne doit pas voler le focus.
export const FENETRE_OUVERTURE_MS = 2000;

let dernierSignal: number | null = null;

/** Pure : le dernier signal tombe-t-il dans la fenêtre ? */
export function ouvertureRecente(
  dernier: number | null,
  now: number,
  fenetreMs: number = FENETRE_OUVERTURE_MS,
): boolean {
  if (dernier === null) return false;
  const ecart = now - dernier;
  return ecart >= 0 && ecart < fenetreMs;
}

/** À appeler quand le signal arrive ; exposé pour les tests. */
export function noterOuverture(now: number = Date.now()): void {
  dernierSignal = now;
}

export function panneauVientDeSOuvrir(now: number = Date.now()): boolean {
  return ouvertureRecente(dernierSignal, now);
}

export function signalerPanneauOuvert(): void {
  window.dispatchEvent(new CustomEvent(EVENEMENT_PANNEAU_OUVERT));
}

export function demanderLeFocusDuCompositeur(): void {
  window.dispatchEvent(new CustomEvent(EVENEMENT_FOCUS_COMPOSITEUR));
}

export function demanderLOuvertureDuSauteur(): void {
  window.dispatchEvent(new CustomEvent(EVENEMENT_OUVRIR_SAUTEUR));
}

/** Dépose `texte` dans le compositeur, à la suite d'un brouillon éventuel. */
export function deposerLeTexteDansLeCompositeur(texte: string): void {
  window.dispatchEvent(new CustomEvent<string>(EVENEMENT_DEPOSER_TEXTE, { detail: texte }));
}

let messageAttendu: { id: string; at: number } | null = null;

/**
 * Demande au fil de défiler jusqu'au message `messageId` et de le surligner.
 * La demande est aussi GARDÉE : depuis la barre latérale, la sélection
 * navigue vers « / » et ChatArea n'est pas encore montée quand l'événement
 * part — elle relit la demande au montage, dans la même fenêtre que le
 * signal d'ouverture (au-delà, une demande périmée ferait défiler un fil
 * qu'on vient d'ouvrir soi-même).
 */
export function demanderDeMontrerLeMessage(messageId: string, now: number = Date.now()): void {
  messageAttendu = { id: messageId, at: now };
  window.dispatchEvent(new CustomEvent<string>(EVENEMENT_MONTRER_MESSAGE, { detail: messageId }));
}

/** Le message demandé récemment, une seule fois ; null sinon. */
export function consommerLeMessageAMontrer(now: number = Date.now()): string | null {
  const attendu = messageAttendu;
  messageAttendu = null;
  if (!attendu || !ouvertureRecente(attendu.at, now)) return null;
  return attendu.id;
}

// Écoute dès l'import — avant tout montage — pour que le signal ne soit
// jamais perdu entre l'évaluation de Rust et le premier effet React.
if (typeof window !== 'undefined') {
  window.addEventListener(EVENEMENT_PANNEAU_OUVERT, () => noterOuverture());
}
