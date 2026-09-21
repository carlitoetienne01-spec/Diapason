// 21/09/2026 : « Le premier ministre du Canada en 2026 est Justin Trudeau
// [3] » — cité, daté, faux. Le signal de vérification ne se limite plus à
// « non retrouvé dans les sources » : il dit aussi quand la réponse nomme
// quelqu'un que les sources ne désignent pas comme titulaire, quand les
// sources sont trop vieilles pour la question — et, depuis le même jour, le
// NIVEAU calculé par le serveur : vérifié en ligne, partiel, de mémoire
// (P1 du jury). « ⚠︎ Non vérifié en ligne » était un préfixe de texte : il
// se copiait avec la réponse et se prononçait à voix haute.
import type { ChatMessage } from '../../types';
import type { MessageKey, Vars } from '../../i18n/translate';
import { dateCourte } from './sourcesDeReponse';

export type Verification = NonNullable<ChatMessage['verification']>;
export type NiveauDeVerification = NonNullable<Verification['level']>;

type Traduire = (key: MessageKey, vars?: Vars) => string;

const NIVEAUX: ReadonlySet<string> = new Set(['verified', 'partial', 'memory']);

function texte(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

/** Ce que le serveur a lu d'un événement `verification`, ou undefined si vide.
 *  Les clés du fil sont anglaises ; celles du 20/09 (nonRetrouves, sourcesDatees,
 *  desaccord) sont encore lues pour les messages enregistrés ce jour-là. */
export function lireVerification(brut: unknown): Verification | undefined {
  if (!brut || typeof brut !== 'object') return undefined;
  const data = brut as Record<string, unknown>;
  const brutNotFound = data.notFound ?? data.nonRetrouves;
  const notFound = Array.isArray(brutNotFound)
    ? brutNotFound.map(String).filter((s) => s.trim().length > 0)
    : [];
  const sourcesDatedAt = texte(data.sourcesDatedAt) || texte(data.sourcesDatees);
  const d = (data.disagreement ?? data.desaccord) as Record<string, unknown> | undefined;
  const answer = d && typeof d === 'object' ? texte(d.answer) || texte(d.reponse) : '';
  const disagreement =
    d && typeof d === 'object' && answer && Array.isArray(d.sources)
      ? { answer, sources: d.sources.map(String).filter((s) => s.length > 0) }
      : undefined;
  const level = NIVEAUX.has(texte(data.level)) ? (texte(data.level) as NiveauDeVerification) : undefined;
  if (!level && !notFound.length && !sourcesDatedAt && !(disagreement && disagreement.sources.length)) {
    return undefined;
  }
  const verification: Verification = { notFound };
  if (level) verification.level = level;
  if (data.searchTried === true) verification.searchTried = true;
  if (sourcesDatedAt) verification.sourcesDatedAt = sourcesDatedAt;
  if (disagreement && disagreement.sources.length) verification.disagreement = disagreement;
  return verification;
}

/** Les lignes à afficher sous la réponse, dans l'ordre de gravité : le
 *  désaccord sur le titulaire d'abord (c'est une réponse fausse), l'âge des
 *  sources, puis ce qui n'a pas été retrouvé. */
export function notesDeVerification(
  verification: Verification | undefined,
  t: Traduire,
): string[] {
  // Un message enregistré le 20/09 porte encore les clés françaises : on le
  // relit par lireVerification plutôt que de planter sur notFound.length.
  verification = lireVerification(verification);
  if (!verification) return [];
  const lignes: string[] = [];
  if (verification.disagreement && verification.disagreement.sources.length > 0) {
    lignes.push(
      t('chat.verification.desaccord', {
        sources: verification.disagreement.sources.join(', '),
        reponse: verification.disagreement.answer,
      }),
    );
  }
  if (verification.sourcesDatedAt) {
    lignes.push(
      t('chat.verification.sourcesDatees', {
        date: dateCourte(verification.sourcesDatedAt) || verification.sourcesDatedAt,
      }),
    );
  }
  if (verification.notFound.length > 0) {
    lignes.push(`${t('chat.verification.nonRetrouves')} ${verification.notFound.join(', ')}`);
  }
  return lignes;
}

export interface BadgeDeVerification {
  cle: MessageKey;
  /** ok : vérifié ; warn : partiel ou de mémoire — jamais plus fort que ça,
   *  c'est un état, pas une alerte. */
  ton: 'ok' | 'warn';
}

/** Le badge sous la bulle, ou null quand le serveur n'a pas jugé (question
 *  qui ne dépend pas du moment). Une recherche tentée sans résultat se dit
 *  telle quelle : « De mémoire — recherche sans résultat ». */
export function badgeDeVerification(verification: Verification | undefined): BadgeDeVerification | null {
  verification = lireVerification(verification);
  if (!verification || !verification.level) return null;
  switch (verification.level) {
    case 'verified':
      return { cle: 'chat.verification.niveau.verifie', ton: 'ok' };
    case 'partial':
      return { cle: 'chat.verification.niveau.partiel', ton: 'warn' };
    case 'memory':
      return {
        cle: verification.searchTried
          ? 'chat.verification.niveau.memoireSansResultat'
          : 'chat.verification.niveau.memoire',
        ton: 'warn',
      };
  }
}

/** Le bouton « Vérifier en ligne » n'a de sens que quand il peut changer
 *  quelque chose : une réponse de mémoire, partielle — ou sans niveau du tout,
 *  c'est le cas pour lequel il existe (le lexique a raté la question). Jamais
 *  sur une réponse vérifiée, ni après une recherche qui n'a rien rendu :
 *  relancer la même recherche boucle sur Ollama (`-np 1`) pour rien. */
export function peutVerifierEnLigne(verification: Verification | undefined): boolean {
  const v = lireVerification(verification);
  if (!v || !v.level) return true;
  if (v.level === 'verified') return false;
  return !(v.level === 'memory' && v.searchTried === true);
}

/** Le bouton « Vérifier en ligne » d'une bulle demande un nouveau tour, sous
 *  la réponse, qui la qualifie sans la remplacer. InputArea écoute. */
export interface DemandeDeVerification { conversationId: string; messageId: string }
export const EVENEMENT_VERIFIER_EN_LIGNE = 'diapason:verifier-en-ligne';
