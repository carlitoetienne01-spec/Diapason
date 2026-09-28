import type { ChatMessage } from '../types';
import type { TranscriptLine, ToolEventLine } from '../hooks/useVoiceLive';

export interface SessionDuChat { id: string; conversationId: string; depuis: number; timestamp: number }

export function actionDuCompositeur(focus: boolean, texte: string, pieces = 0): 'envoyer' | 'parler' {
  return focus || texte.trim().length > 0 || pieces > 0 ? 'envoyer' : 'parler';
}

export function historiqueVocal(messages: ChatMessage[]) {
  return messages.filter(m => m.content.trim()).slice(-16).map(m => ({
    role: m.role,
    content: m.content + (m.documents?.map(d => `\n\n${d.nom}\n${d.texte}`).join('') ?? ''),
  }));
}

export function messagesVocaux(session: SessionDuChat, lignes: TranscriptLine[], outils: ToolEventLine[]): ChatMessage[] {
  return lignes.filter(l => l.at >= session.depuis && l.text.trim() && (l.role === 'assistant' || l.final)).map(l => {
    const precedentes = lignes.filter(x => x.role === 'user' && x.at < l.at);
    const debut = precedentes[precedentes.length - 1]?.at ?? session.depuis - 1;
    const fin = lignes.find(x => x.role === 'user' && x.at > l.at)?.at ?? Infinity;
    const appels = l.role === 'assistant' ? outils.filter(o => o.at > debut && o.at < fin).map(o => ({
      id: `${session.id}-outil-${o.at}`, tool: o.name, arguments: '',
      status: o.ok ? 'success' as const : 'error' as const, result: o.detail,
      engine: o.engine, numResults: o.numResults,
    })) : [];
    return { id: `${session.id}-${l.at}`, role: l.role, content: l.text,
      timestamp: l.timestamp ?? session.timestamp + l.at - session.depuis,
      ...(appels.length ? { toolCalls: appels } : {}),
      ...(l.interrupted ? { voice: { interrupted: true } } : {}),
    };
  });
}

/** Identités stables : une correction remplace sa bulle, jamais la dernière du fil. */
export function fusionnerMessagesVocaux(anciens: ChatMessage[], nouveaux: ChatMessage[]) {
  let resultat = anciens;
  for (const message of nouveaux) {
    const index = resultat.findIndex(m => m.id === message.id);
    const fusion = index >= 0 ? { ...resultat[index], ...message } : message;
    if (index >= 0 && JSON.stringify(resultat[index]) === JSON.stringify(fusion)) continue;
    if (resultat === anciens) resultat = [...anciens];
    if (index < 0) resultat.push(message);
    else resultat[index] = fusion;
  }
  return resultat;
}

let filVocal: string | null = null;
export function marquerFilVocal(id: string | null) { filVocal = id; }
export function conversationVocaleEnCours() { return filVocal !== null; }
