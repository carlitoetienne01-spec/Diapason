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
