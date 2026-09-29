/** Le corrigé reste absent de ce contrat tant que le serveur ne le rend pas. */
export const OUVRIR_ETUDES = 'diapason-ouvrir-etudes';
export interface EmplacementEtude { afterMessageId: string | null; openedAt: number }
export interface QuestionEtude {
  id: string; kind: 'choice' | 'open'; prompt: string; objective: string;
  choices: string[]; maxScore: number; criteria?: string[];
  answer?: string; explanation?: string; sourceIndex?: number | null; quote?: string;
}
export interface NoteEtude {
  score: number; maxScore: number; feedback: string;
  method: 'choice' | 'proposed' | 'empty'; criteriaMet?: boolean[];
}
export interface Etude {
  id: string; conversationId: string; mode: 'practice' | 'exam'; model: string; level: string;
  state: 'ready' | 'active' | 'finished'; version: number; updatedAt: number;
  createdAt?: number; placement?: EmplacementEtude | null;
  currentQuestionId?: string;
  title: string; objectives: string[]; lesson: string; essentials: string[];
  questions: QuestionEtude[]; responses: Record<string, { text: string }>;
  assisted: string[]; hints: Record<string, string>; grades: Record<string, NoteEtude>;
  sources: Array<{ name: string; characters: number }>;
}
export interface SourceEtude { name: string; text: string; truncated: boolean }
export interface DemandeEtude {
  conversationId: string; model: string; topic: string; level: string;
  mode: 'practice' | 'exam'; questionCount: number; sources: SourceEtude[];
  placement?: EmplacementEtude;
}
export function bilanEtude(etude: Etude) {
  const notes = Object.values(etude.grades);
  return {
    score: notes.reduce((s, n) => s + n.score, 0),
    maximum: etude.questions.reduce((s, q) => s + q.maxScore, 0),
    repondues: etude.questions.filter(q => etude.responses[q.id]?.text.trim()).length,
    nonEvalues: etude.objectives.filter(o => !etude.questions.some(q => q.objective === o && etude.grades[q.id])),
    aRevoir: [...new Set(etude.questions.filter(q => {
      const n = etude.grades[q.id];
      return n && (n.score < n.maxScore || etude.assisted.includes(q.id));
    }).map(q => q.objective))],
  };
}
export function reponseModifiee(etude: Etude, questionId: string, texte: string) {
  return (etude.responses[questionId]?.text ?? '') !== texte.trim();
}
export function erreurEtude(valeur: unknown): string {
  if (valeur instanceof Error) return valeur.message;
  return 'La demande a échoué. Les réponses déjà enregistrées sont conservées.';
}
