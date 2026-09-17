/**
 * Les discussions vues depuis le fil — logique pure, sans React.
 *
 * 17 sept. 2026, chantier « discussions dans le mini-panneau ». Le fil se
 * lisait sans jamais dire dans QUELLE discussion on écrivait : la barre
 * latérale seule le savait, et le mini-panneau n'en a pas. Ce module porte
 * les règles que l'en-tête du fil, le store et le moteur de sync partagent,
 * pour qu'elles soient testées une fois et appliquées partout (CLAUDE.md §3 :
 * pas de test de composant — la logique s'extrait).
 */
import type { Conversation } from '../types';

/** Ce que ce module demande au catalogue : rien de plus que ces clés. */
export type TraduireTitre = (key: 'sidebar.newChat') => string;

// Au-delà, ni la pastille réduite du mini-panneau (≈ 200 px de texte) ni un
// onglet n'affichent quoi que ce soit ; un titre collé de 2 000 caractères
// finissait dans `document.title` en entier.
export const TITRE_MAX = 80;

/**
 * Le titre à afficher pour la discussion active : celui de la conversation,
 * sinon « Nouvelle discussion » — quand rien n'est actif OU quand la
 * conversation active n'a pas encore de nom (elle en reçoit un au premier
 * message). Toujours tronqué à TITRE_MAX.
 */
export function titreDiscussion(
  conversations: readonly Conversation[],
  activeId: string | null,
  t: TraduireTitre,
): string {
  const active = activeId ? conversations.find((c) => c.id === activeId) : undefined;
  const brut = active?.title.trim() ?? '';
  if (!brut) return t('sidebar.newChat');
  return brut.length > TITRE_MAX ? `${brut.slice(0, TITRE_MAX - 1)}…` : brut;
}

/** Vrai quand l'en-tête affiche le libellé de repli plutôt qu'un vrai titre. */
export function titreProvisoire(
  conversations: readonly Conversation[],
  activeId: string | null,
): boolean {
  const active = activeId ? conversations.find((c) => c.id === activeId) : undefined;
  return !active || !active.title.trim();
}
