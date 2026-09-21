// 21/09/2026 : « Le premier ministre du Canada en 2026 est Justin Trudeau
// [3] » — cité, daté, faux. Le signal de vérification ne se limite plus à
// « non retrouvé dans les sources » : il dit aussi quand la réponse nomme
// quelqu'un que les sources ne désignent pas comme titulaire, et quand les
// sources sont trop vieilles pour la question. Trois constats, trois lignes,
// chacune seulement si le serveur l'a établie.
import type { ChatMessage } from '../../types';
import type { MessageKey, Vars } from '../../i18n/translate';
import { dateCourte } from './sourcesDeReponse';

export type Verification = NonNullable<ChatMessage['verification']>;

type Traduire = (key: MessageKey, vars?: Vars) => string;

/** Ce que le serveur a lu d'un événement `verification`, ou undefined si vide. */
export function lireVerification(brut: unknown): Verification | undefined {
  if (!brut || typeof brut !== 'object') return undefined;
  const data = brut as Record<string, unknown>;
  const nonRetrouves = Array.isArray(data.nonRetrouves)
    ? data.nonRetrouves.map(String).filter((s) => s.trim().length > 0)
    : [];
  const sourcesDatees = typeof data.sourcesDatees === 'string' ? data.sourcesDatees : '';
  const d = data.desaccord as Record<string, unknown> | undefined;
  const desaccord =
    d && typeof d === 'object' && typeof d.reponse === 'string' && Array.isArray(d.sources)
      ? { reponse: d.reponse, sources: d.sources.map(String).filter((s) => s.length > 0) }
      : undefined;
  if (!nonRetrouves.length && !sourcesDatees && !(desaccord && desaccord.sources.length)) {
    return undefined;
  }
  const verification: Verification = { nonRetrouves };
  if (sourcesDatees) verification.sourcesDatees = sourcesDatees;
  if (desaccord && desaccord.sources.length) verification.desaccord = desaccord;
  return verification;
}

/** Les lignes à afficher sous la réponse, dans l'ordre de gravité : le
 *  désaccord sur le titulaire d'abord (c'est une réponse fausse), l'âge des
 *  sources, puis ce qui n'a pas été retrouvé. */
export function notesDeVerification(
  verification: Verification | undefined,
  t: Traduire,
): string[] {
  if (!verification) return [];
  const lignes: string[] = [];
  if (verification.desaccord && verification.desaccord.sources.length > 0) {
    lignes.push(
      t('chat.verification.desaccord', {
        sources: verification.desaccord.sources.join(', '),
        reponse: verification.desaccord.reponse,
      }),
    );
  }
  if (verification.sourcesDatees) {
    lignes.push(
      t('chat.verification.sourcesDatees', {
        date: dateCourte(verification.sourcesDatees) || verification.sourcesDatees,
      }),
    );
  }
  if (verification.nonRetrouves.length > 0) {
    lignes.push(`${t('chat.verification.nonRetrouves')} ${verification.nonRetrouves.join(', ')}`);
  }
  return lignes;
}
