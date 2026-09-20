import { describe, expect, it } from 'vitest';
import { composerReponses, lireQuestions, preparerEnvoiQuestions, type QuestionsChat } from './questionsChat';
import type { ChatMessage, Conversation } from '../types';
import { fusionnerConversations } from './convSync';

const demande: QuestionsChat = { id: 'demande', intro: 'Pour adapter le programme.', questions: [
  { id: 'q1', title: 'Ton objectif ?', options: [{ id: 'o1', label: 'Parler', description: '' }, { id: 'o2', label: 'Étudier', description: '' }] },
  { id: 'q2', title: 'Combien de temps ?', options: [{ id: 'o1', label: '15 min', description: '' }, { id: 'o2', label: '30 min', description: '' }] },
] };
const message: ChatMessage = { id: 'assistant', role: 'assistant', timestamp: 1, content: 'Ton objectif ?', questions: demande };
const reply = composerReponses(demande, ['Parler', '20 minutes le soir'])!;
const envoi = { conversationId: 'discussion', messageId: message.id, reply };

describe('questions de cadrage du chat', () => {
  it('refuse les formulaires incomplets, immenses et les identifiants ambigus', () => {
    for (const v of [null, {}, { ...demande, questions: [] }, { ...demande, questions: [demande.questions[0], demande.questions[0]] },
      { ...demande, intro: 'x'.repeat(301) }, { ...demande, questions: [{ ...demande.questions[0], options: [] }] }]) {
      expect(lireQuestions(v)).toBeNull();
    }
    expect(lireQuestions(demande)).toEqual(demande);
  });
  it('envoie les questions et les mots choisis, y compris une réponse libre', () => {
    expect(preparerEnvoiQuestions([message], envoi)).toBe('Ton objectif ?\nParler\n\nCombien de temps ?\n20 minutes le soir');
    expect(composerReponses(demande, ['Parler', '  '])).toBeNull();
    expect(composerReponses(demande, ['Parler'])).toBeNull();
    expect(composerReponses(demande, ['Parler', 'x'.repeat(1501)])).toBeNull();
  });
  it('conserve toutes les questions et toutes les réponses au-delà de trois étapes', () => {
    const longue: QuestionsChat = { ...demande, questions: Array.from({ length: 12 }, (_, i) => ({
      ...demande.questions[0], id: `q${i + 1}`, title: `Précision ${i + 1} ?`,
    })) };
    expect(lireQuestions(longue)).toEqual(longue);
    const reponses = longue.questions.map((_, i) => `Réponse ${i + 1}`);
    const reply = composerReponses(longue, reponses)!;
    expect(reply.answers).toHaveLength(12);
    expect(preparerEnvoiQuestions([{ ...message, questions: longue }], { ...envoi, reply }))
      .toBe(longue.questions.map((q, i) => `${q.title}\n${reponses[i]}`).join('\n\n'));
    expect(composerReponses(longue, reponses.slice(0, 3))).toBeNull();
  });
  it('borne toujours les textes reçus même avec des questions individuellement valides', () => {
    const longue = { ...demande, questions: Array.from({ length: 100 }, (_, i) => ({
      ...demande.questions[0], id: `q${i + 1}`, title: `${i} ${'é'.repeat(200)}`,
    })) };
    expect(lireQuestions(longue)).toBeNull();
  });
  it('un double clic ou un ancien questionnaire ne crée pas une nouvelle réponse', () => {
    const suivant: ChatMessage = { id: 'utilisateur', role: 'user', content: 'Réponses', timestamp: 2, questionReply: reply };
    expect(preparerEnvoiQuestions([message, suivant], envoi)).toBeNull();
    expect(preparerEnvoiQuestions([{ ...message, id: 'autre' }], envoi)).toBeNull();
    expect(preparerEnvoiQuestions([message], { ...envoi, reply: { ...reply, requestId: 'ancienne-demande' } })).toBeNull();
  });
  it('refuse une réponse tronquée ou réordonnée par un client', () => {
    expect(preparerEnvoiQuestions([message], { ...envoi, reply: { ...reply, answers: [] } })).toBeNull();
    expect(preparerEnvoiQuestions([message], { ...envoi, reply: { ...reply, answers: [...reply.answers].reverse() } })).toBeNull();
  });
  it('la fusion entre la fenêtre et le mini-panneau conserve les formulaires et les réponses', () => {
    const a = { id: 'fil', title: 'Anglais', createdAt: 1, updatedAt: 2, model: 'local', messages: [message] };
    const b: Conversation = { ...a, updatedAt: 3, messages: [{ ...message, questions: undefined }, { id: 'reponse', role: 'user', timestamp: 3, content: 'Parler', questionReply: reply }] };
    // Une vraie ancienne copie ne possède pas encore la clé questions.
    delete b.messages[0].questions;
    for (const fusion of [fusionnerConversations(a, b), fusionnerConversations(b, a)]) {
      expect(fusion.messages[0].questions).toEqual(demande);
      expect(fusion.messages[1].questionReply).toEqual(reply);
    }
  });
});
