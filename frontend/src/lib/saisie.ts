/**
 * L'utilisateur est-il en train d'écrire dans un champ ?
 *
 * 30 août 2026. `App.tsx` écoutait `keydown` sur `window` sans aucune garde
 * sur la cible et faisait `preventDefault()` pour Cmd/Ctrl+I. L'italique natif
 * ne fonctionnait donc JAMAIS dans une note : le raccourci ouvrait le panneau
 * système à la place. Cmd+K avait le même défaut.
 *
 * La garde correcte existait déjà, écrite deux fichiers plus loin dans
 * `TalkToDiapasonHost.tsx`. L'extraire ici la rend partageable — et testable :
 * ce dépôt n'a aucun test de composant React, et il ne faut pas en inventer
 * l'outillage (CLAUDE.md §3). Une fonction pure se teste sans monter quoi que
 * ce soit.
 */
export function estDansUneZoneDeSaisie(cible: EventTarget | null): boolean {
  const element = cible as HTMLElement | null;
  if (!element || typeof element.tagName !== 'string') return false;
  const balise = element.tagName;
  if (balise === 'INPUT' || balise === 'TEXTAREA' || balise === 'SELECT') return true;
  // Deux chemins, et il faut les DEUX.
  //
  // `isContentEditable` est vrai pour tout descendant d'une zone éditable —
  // et la cible d'une frappe dans l'éditeur de notes est presque toujours un
  // <p>, jamais l'hôte. Mais jsdom ne l'implémente pas : il rend `false` même
  // sur un élément dont `contentEditable` vaut « true ». S'en tenir à lui
  // rendrait cette garde intestable, et une garde qu'on ne peut pas tester
  // finit par se faire retirer sans que personne ne s'en aperçoive.
  //
  // `closest` couvre les descendants comme l'hôte, et fonctionne partout.
  if (element.isContentEditable) return true;
  return Boolean(
    element.closest?.('[contenteditable=""], [contenteditable="true"]'),
  );
}

/**
 * L'attribut qui marque le SEUL champ d'où les raccourcis globaux passent.
 *
 * 17 sept. 2026, chantier « discussions dans le mini-panneau ». La garde
 * ci-dessus était absolue : ⌘K était mort dès que le curseur était dans le
 * compositeur — c'est-à-dire presque toujours dans le mini-panneau, où l'on
 * arrive pour écrire. Il fallait cliquer dans le vide avant d'ouvrir la
 * palette. L'exception est NOMMÉE et posée à un seul endroit (le textarea
 * du compositeur, InputArea) : jamais sur l'éditeur de notes, où ⌘I est
 * l'italique et où un raccourci volé serait exactement le défaut du 30 août.
 */
export const ATTRIBUT_RACCOURCIS_GLOBAUX = 'data-raccourcis-globaux';

/** Ce qu'il faut d'un `KeyboardEvent` pour juger — sans en exiger un vrai. */
export interface FrappeClavier {
  key: string;
  code?: string;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}

interface RaccourciGlobal {
  /** Valeurs acceptées de `key` (minuscules ; les deux formes d'un crochet). */
  keys: readonly string[];
  /** Touche physique, pour les crochets dont `key` varie selon la disposition. */
  code?: string;
  shift: boolean;
}

// ⌘K (palette), ⌘N (nouvelle discussion), ⌘J (sauteur), ⌘⇧[ et ⌘⇧] (fil
// précédent / suivant). Rien d'autre : ⌘I, ⌘B et consorts restent ceux du
// champ. Les crochets portent aussi leur `code` : sur une disposition
// française, `[` n'existe qu'avec ⌥ et `key` ne dit plus rien de fiable,
// alors que `BracketLeft` désigne la même touche que ⌘⇧[ dans Safari et Arc.
const RACCOURCIS_GLOBAUX: readonly RaccourciGlobal[] = [
  { keys: ['k'], shift: false },
  { keys: ['n'], shift: false },
  { keys: ['j'], shift: false },
  { keys: ['[', '{'], code: 'BracketLeft', shift: true },
  { keys: [']', '}'], code: 'BracketRight', shift: true },
];

/** Ce qu'il faut d'un `Navigator` pour reconnaître un Mac — sans en exiger un vrai. */
export interface PlateformeNavigateur {
  platform?: string;
  userAgentData?: { platform?: string };
}

/**
 * Sommes-nous sur macOS ? `userAgentData.platform` (Chromium) d'abord,
 * `navigator.platform` (WebKit, « MacIntel ») sinon. Hors navigateur : non.
 */
export function estUnMac(nav: PlateformeNavigateur | undefined = globalThis.navigator): boolean {
  if (!nav) return false;
  const plateforme = nav.userAgentData?.platform || nav.platform || '';
  return /mac/i.test(plateforme);
}

/**
 * Vrai quand la frappe est l'un des raccourcis globaux ET vient d'un champ
 * qui porte `data-raccourcis-globaux`. Tout autre champ garde la garde
 * absolue ; tout autre raccourci reste au champ.
 *
 * Le modificateur dépend de la plateforme : ⌘ sur Mac, Ctrl ailleurs — et
 * JAMAIS Ctrl sur Mac. Contre-revue du 17 sept. 2026 : « metaKey ou
 * ctrlKey » laissait passer Ctrl+K et Ctrl+N depuis le compositeur, qui sont
 * dans toute zone de texte macOS les liaisons Cocoa « couper jusqu'à la fin
 * de la ligne » et « ligne suivante » ; Ctrl+N depuis un brouillon de trois
 * lignes vidait le fil au lieu de descendre d'une ligne — exactement le
 * raccourci confisqué du 30 août, sous un autre nom.
 */
export function laissePasserLeRaccourci(
  cible: EventTarget | null,
  frappe: FrappeClavier,
  surMac: boolean = estUnMac(),
): boolean {
  const element = cible as HTMLElement | null;
  if (!element || typeof element.hasAttribute !== 'function') return false;
  if (!element.hasAttribute(ATTRIBUT_RACCOURCIS_GLOBAUX)) return false;
  const modificateur = surMac ? frappe.metaKey : frappe.ctrlKey;
  if (!modificateur || frappe.altKey) return false;
  const key = frappe.key.toLowerCase();
  return RACCOURCIS_GLOBAUX.some(
    (r) =>
      r.shift === frappe.shiftKey &&
      (r.keys.includes(key) || (r.code !== undefined && r.code === frappe.code)),
  );
}
