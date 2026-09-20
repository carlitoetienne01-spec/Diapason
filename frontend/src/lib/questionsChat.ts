import type { ChatMessage } from '../types';

export interface ChoixQuestion { id: string; label: string; description: string }
export interface QuestionChat { id: string; title: string; options: ChoixQuestion[] }
export interface QuestionsChat { id: string; intro: string; questions: QuestionChat[] }
export interface ReponsesQuestions {
  requestId: string;
  answers: Array<{ questionId: string; answer: string }>;
}
export interface EnvoiReponses { conversationId: string; messageId: string; reply: ReponsesQuestions }
export const EVENEMENT_REPONSES_CHAT = 'diapason:reponses-questions';

const objet = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const texte = (v: unknown, max: number, vide = false): v is string =>
  typeof v === 'string' && v.length <= max && (vide || !!v.trim());
const distincts = (valeurs: string[]) => new Set(valeurs).size === valeurs.length;
// 19/09/2026 : la quatrième question valide disparaissait côté interface.
// Le serveur borne son JSON à 16 Ko ; le client borne les textes à la même
// taille, sans compter les identifiants et champs par défaut qu'il ajoute.
const QUESTIONNAIRE_MAX_OCTETS = 16_000;
const encodeur = new TextEncoder();

/** Les données du modèle et d'un ancien historique ne deviennent jamais du JSX brut. */
export function lireQuestions(v: unknown): QuestionsChat | null {
  if (!objet(v) || !texte(v.id, 100) || !texte(v.intro, 300, true)
    || !Array.isArray(v.questions) || v.questions.length < 1) return null;
  let taille = encodeur.encode(v.intro).byteLength;
  const questions: QuestionChat[] = [];
  for (const q of v.questions) {
    if (!objet(q) || !texte(q.id, 100) || !texte(q.title, 240) || !Array.isArray(q.options)
      || q.options.length < 2 || q.options.length > 4) return null;
    taille += encodeur.encode(q.title).byteLength;
    const options: ChoixQuestion[] = [];
    for (const c of q.options) {
      if (!objet(c) || !texte(c.id, 100) || !texte(c.label, 100) || !texte(c.description, 180, true)) return null;
      taille += encodeur.encode(c.label + c.description).byteLength;
      if (taille > QUESTIONNAIRE_MAX_OCTETS) return null;
      options.push({ id: c.id, label: c.label, description: c.description });
    }
    if (!distincts(options.map(c => c.id))) return null;
    questions.push({ id: q.id, title: q.title, options });
  }
  if (!distincts(questions.map(q => q.id))) return null;
  return { id: v.id, intro: v.intro, questions };
}

export function composerReponses(demande: QuestionsChat, reponses: string[]): ReponsesQuestions | null {
  if (reponses.length !== demande.questions.length || reponses.some(r => !texte(r, 1500))) return null;
  return { requestId: demande.id, answers: demande.questions.map((q, i) => ({ questionId: q.id, answer: reponses[i].trim() })) };
}

export function texteQuestions(demande: QuestionsChat): string {
  const lignes = demande.intro ? [demande.intro] : [];
  demande.questions.forEach((q, i) => {
    lignes.push(`${i + 1}. ${q.title}`);
    lignes.push(...q.options.map(c => `- ${c.label}`));
  });
  return lignes.join('\n\n');
}

/** Revalidation au moment du clic : un formulaire quitté ne répond pas dans un autre fil. */
export function preparerEnvoiQuestions(messages: ChatMessage[], envoi: EnvoiReponses): string | null {
  const dernier = messages[messages.length - 1];
  const demande = lireQuestions(dernier?.questions);
  if (dernier?.id !== envoi.messageId || dernier.role !== 'assistant' || !demande
    || envoi.reply?.requestId !== demande.id || !Array.isArray(envoi.reply.answers)
    || envoi.reply.answers.length !== demande.questions.length) return null;
  const reponses = envoi.reply.answers;
  if (reponses.some((r, i) => !r || r.questionId !== demande.questions[i].id || !texte(r.answer, 1500))) return null;
  // Le modèle relit les libellés et les réponses, pas des indices « option 2 ».
  return demande.questions.map((q, i) => `${q.title}\n${reponses[i].answer.trim()}`).join('\n\n');
}
