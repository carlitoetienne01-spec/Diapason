import { describe, expect, it } from 'vitest';
import { actionDuCompositeur, historiqueVocal, documentsEtudeVocaux, messagesVocaux, fusionnerMessagesVocaux } from './conversationVocale';
import type { ChatMessage } from '../types';
import type { TranscriptLine } from '../hooks/useVoiceLive';
const session = { id: 'voix', conversationId: 'anglais', depuis: 3, timestamp: 1000 };
const ligne = (at: number, role: 'user' | 'assistant', text: string, final: boolean): TranscriptLine => ({ at, role, text, final });

describe('le chat écrit et parlé partage ses messages', () => {
  it('transmet les documents originaux à Étudier même au-delà des seize messages vocaux', () => {
    const messages: ChatMessage[] = Array.from({ length: 20 }, (_, i) => ({ id: String(i), role: 'user', content: `texte ${i}`, timestamp: i }));
    messages[0].documents = [{ nom: 'cours.pdf', texte: 'Original', tronque: true }];
    messages[19].role = 'assistant';
    messages[19].documents = [{ nom: 'imaginé', texte: 'Ne pas prendre' }];
    expect(documentsEtudeVocaux(messages)).toEqual([{ name: 'cours.pdf', text: 'Original', truncated: true }]);
    expect(documentsEtudeVocaux([])).toBeUndefined();
  });
  it('ignore les brouillons révisables et les transcriptions de la séance précédente', () => {
    const lignes = [ligne(1, 'user', 'ancien', true), ligne(3, 'user', 'dix mois', false)];
    expect(messagesVocaux(session, lignes, [])).toEqual([]);
    const fin = messagesVocaux(session, [ligne(3, 'user', 'dis-moi', true)], []);
    expect(fin).toHaveLength(1);
    expect(fin[0].content).toBe('dis-moi');
  });
  it('complète une seule réponse et préserve les autres messages', () => {
    const debut = messagesVocaux(session, [ligne(3, 'user', 'anglais', true), ligne(4, 'assistant', 'Écoute.', false)], []);
    const fin = messagesVocaux(session, [ligne(3, 'user', 'anglais', true), ligne(4, 'assistant', 'Écoute. Puis répète.', true)], []);
    const fusion = fusionnerMessagesVocaux(debut, fin);
    expect(fusion).toHaveLength(2);
    expect(fusion[0]).toBe(debut[0]);
    expect(fusion[1].id).toBe(debut[1].id);
    expect(debut[1].content).toBe('Écoute.');
    expect(fusionnerMessagesVocaux(fusion, fin)).toBe(fusion);
  });
  it('rattache chaque outil à son propre tour, y compris zéro résultat', () => {
    const lignes = [ligne(3, 'user', 'Cherche', true), ligne(5, 'assistant', 'Rien.', true), ligne(6, 'user', 'Encore', true), ligne(8, 'assistant', 'Trouvé.', true)];
    const outils = [{at: 4, name: 'web_search', ok: true, detail: '', numResults: 0}, {at: 7, name: 'web_search', ok: true, detail: 'page', numResults: 1}];
    const messages = messagesVocaux(session, lignes, outils);
    expect(messages[1].toolCalls?.[0].numResults).toBe(0);
    expect(messages[3].toolCalls).toHaveLength(1);
    expect(messages[3].toolCalls?.[0].numResults).toBe(1);
  });
  it('conserve le contexte récent et le texte des documents, sans métadonnée système', () => {
    const messages: ChatMessage[] = Array.from({ length: 20 }, (_, i) => ({ id: String(i), role: i % 2 ? 'assistant' : 'user', content: `texte ${i}`, timestamp: i }));
    messages[19].documents = [{nom: 'cours', texte: 'Les verbes'}];
    const historique = historiqueVocal(messages);
    expect(historique).toHaveLength(16);
    expect(historique[0].content).toBe('texte 4');
    expect(historique[15]).toEqual({ role: 'assistant', content: 'texte 19\n\ncours\nLes verbes' });
  });
});

describe('une seule action principale', () => {
  it('réserve la flèche au clavier, au brouillon ou aux pièces jointes', () => {
    expect(actionDuCompositeur(false, '')).toBe('parler');
    expect(actionDuCompositeur(true, '')).toBe('envoyer');
    expect(actionDuCompositeur(false, 'Bonjour')).toBe('envoyer');
    expect(actionDuCompositeur(false, '', 1)).toBe('envoyer');
    expect(actionDuCompositeur(false, '   ')).toBe('parler');
  });
});
