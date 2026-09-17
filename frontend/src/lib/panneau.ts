/**
 * Le panneau vient-il de s'ouvrir ? — et où le focus doit retourner.
 *
 * 17 sept. 2026, chantier « discussions dans le mini-panneau ». Rust signale
 * une présentation du mini-panneau par un `CustomEvent` évalué dans la
 * WKWebView — `diapason:panneau-ouvert` quand le panneau était CACHÉ et se
 * montre, `diapason:panneau-repris` quand il était déjà là (re-clic du rail,
 * dépliage de la pastille). Deux fois sur trois, personne n'entend le
 * premier : à la construction, le document est encore vide (le bundle n'a
 * pas chargé) ; à la re-navigation depuis un autre module, la View
 * Transition (.18 s) puis le rendu de React Router se font APRÈS
 * l'évaluation, et ChatPage se monte sur un signal déjà passé. Ce module
 * garde donc l'heure du dernier signal : une page qui se monte peut
 * demander « le panneau vient-il de s'ouvrir ? » sans avoir été là.
 *
 * Les deux signaux ne se valent pas (contre-revue du 17 sept. 2026) : Rust
 * n'en émettait qu'un, à CHAQUE presenter_mini et agrandir_mini, et ChatPage
 * y rejouait l'atterrissage — re-cliquer « Discussion » sur le rail ou
 * déplier la pastille ramenait au fil chaud, en abandonnant le fil qu'on
 * venait de choisir par ⌘J et le brouillon tapé dedans. Seul « ouvert »
 * atterrit ; « repris » ne fait que rendre le curseur.
 *
 * Le focus, lui, ne se rend pas : il se DEMANDE. Toute couche qui se ferme
 * (menu de puce, palette, plus tard le sauteur) émet
 * `diapason:focus-compositeur`, et seul le compositeur décide s'il existe et
 * s'il peut prendre le focus. Aucun composant n'a à connaître le textarea.
 * La demande est aussi GARDÉE (même fenêtre que le signal d'ouverture) :
 * « Nouvelle discussion » depuis Tâches navigue vers « / » et l'événement
 * partait dans le vide, le compositeur n'étant pas encore monté — même
 * différée d'un tour, la demande arrivait 50 ms avant le textarea
 * (contre-revue du 17 sept. 2026). InputArea la relit au montage.
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
 *
 * `diapason:entree-a-vide` : ↩ dans un compositeur VIDE, sur un fil vide.
 * InputArea ne sait pas ce que la page vide propose (en compact, « Reprendre
 * « <titre> » ↩ ») ; elle dit seulement qu'on a appuyé, et ChatArea reprend
 * le fil si — et seulement si — l'invitation est affichée. Le ↩ du libellé
 * n'est jamais une promesse en l'air (§5).
 *
 * `diapason:fil-glisse` (detail : 'precedente' | 'suivante') précède le
 * changement de fil par ⌘⇧[ / ⌘⇧] : ChatArea, qui tient le conteneur du
 * fil, fait alors glisser le nouveau contenu de 24 px dans le sens du
 * geste — la seule preuve, avec le titre, qu'on a changé de fil ; pas de
 * toast.
 */
export const EVENEMENT_PANNEAU_OUVERT = 'diapason:panneau-ouvert';
export const EVENEMENT_PANNEAU_REPRIS = 'diapason:panneau-repris';
export const EVENEMENT_FOCUS_COMPOSITEUR = 'diapason:focus-compositeur';
export const EVENEMENT_OUVRIR_SAUTEUR = 'diapason:ouvrir-sauteur';
export const EVENEMENT_DEPOSER_TEXTE = 'diapason:deposer-texte';
export const EVENEMENT_MONTRER_MESSAGE = 'diapason:montrer-message';
export const EVENEMENT_ENTREE_A_VIDE = 'diapason:entree-a-vide';
export const EVENEMENT_FIL_GLISSE = 'diapason:fil-glisse';

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

let focusAttendu: number | null = null;

export function demanderLeFocusDuCompositeur(now: number = Date.now()): void {
  focusAttendu = now;
  window.dispatchEvent(new CustomEvent(EVENEMENT_FOCUS_COMPOSITEUR));
}

/**
 * Une demande de focus récente attend-elle encore ? Une seule fois : le
 * compositeur qui l'honore (à l'événement ou à son montage) la consomme,
 * sinon un retour sur la Discussion dans la seconde qui suit volerait le
 * curseur à un champ choisi entre-temps.
 */
export function consommerLaDemandeDeFocus(now: number = Date.now()): boolean {
  const attendu = focusAttendu;
  focusAttendu = null;
  return ouvertureRecente(attendu, now);
}

// Le brouillon du compositeur, publié par InputArea à chaque frappe : la
// seule chose que l'atterrissage a besoin d'en savoir, sans connaître le
// textarea. Vide quand le compositeur n'est pas monté.
let brouillon = '';

export function publierLeBrouillon(texte: string): void {
  brouillon = texte;
}

export function brouillonDuCompositeur(): string {
  return brouillon;
}

export function demanderLOuvertureDuSauteur(): void {
  window.dispatchEvent(new CustomEvent(EVENEMENT_OUVRIR_SAUTEUR));
}

/** Dépose `texte` dans le compositeur, à la suite d'un brouillon éventuel. */
export function deposerLeTexteDansLeCompositeur(texte: string): void {
  window.dispatchEvent(new CustomEvent<string>(EVENEMENT_DEPOSER_TEXTE, { detail: texte }));
}

/** Annonce le sens du prochain changement de fil, pour que le fil glisse avec lui. */
export function annoncerLeGlissement(sens: 'precedente' | 'suivante'): void {
  window.dispatchEvent(new CustomEvent(EVENEMENT_FIL_GLISSE, { detail: sens }));
}

/** ↩ dans un compositeur vide : à la page de décider si cela veut dire quelque chose. */
export function signalerEntreeAVide(): void {
  window.dispatchEvent(new CustomEvent(EVENEMENT_ENTREE_A_VIDE));
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
  // Repris (rail re-cliqué, pastille dépliée) : le curseur seulement, jamais
  // l'atterrissage. Ici et pas dans ChatPage : à la re-navigation depuis un
  // autre module, elle n'est pas montée quand Rust parle — la demande gardée
  // attend son compositeur.
  window.addEventListener(EVENEMENT_PANNEAU_REPRIS, () => demanderLeFocusDuCompositeur());
}
