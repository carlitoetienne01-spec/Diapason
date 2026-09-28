import { useCallback, useEffect, useRef, useState } from 'react';
import { useVoixPartagee } from './contexteVoix';
import { generateId, useAppStore, viderSauvegardeConversations } from '../lib/store';
import { historiqueVocal, messagesVocaux, marquerFilVocal, type SessionDuChat } from '../lib/conversationVocale';
import { isCloudModel } from '../lib/cloud-models';

export function useConversationVocale() {
  const voix = useVoixPartagee();
  const courant = useRef(voix);
  courant.current = voix;
  const session = useRef<SessionDuChat | null>(null);
  const [visible, setVisible] = useState(false);
  const dernierFinal = useRef('');

  const conserver = useCallback((interrompre = false) => {
    if (!session.current) return;
    const v = courant.current;
    const lignes = interrompre ? v.transcripts.map(l =>
      l.role === 'assistant' && !l.final ? { ...l, final: true, interrupted: true } : l) : v.transcripts;
    useAppStore.getState().recevoirMessagesVocaux(session.current.conversationId,
      messagesVocaux(session.current, lignes, v.toolEvents));
  }, []);

  const arreter = useCallback(() => {
    conserver(true);
    session.current = null;
    marquerFilVocal(null);
    courant.current.stop();
    setVisible(false);
    viderSauvegardeConversations();
    window.dispatchEvent(new Event('diapason:conversation-terminee'));
  }, [conserver]);

  const demarrer = useCallback(async (conversationOnly = false) => {
    const etat = useAppStore.getState();
    if (etat.streamState.isStreaming || etat.modelLoading || !etat.selectedModel || isCloudModel(etat.selectedModel)) return;
    if (courant.current.isActive) { courant.current.mettreMicroEnPause(false); return; }
    const id = etat.activeId ?? etat.createConversation(etat.selectedModel);
    const lignes = courant.current.transcripts;
    session.current = { id: `voice-${generateId()}`, conversationId: id,
      depuis: Math.max(0, ...lignes.map(l => l.at), ...courant.current.toolEvents.map(l => l.at)) + 1,
      timestamp: Date.now() };
    marquerFilVocal(id);
    setVisible(true);
    await courant.current.start({ provider: 'local', model: etat.selectedModel,
      history: historiqueVocal(useAppStore.getState().messages), conversationOnly });
  }, []);

  useEffect(() => {
    conserver();
    const finales = voix.transcripts.filter(l => l.role === 'assistant' && l.final);
    const final = finales[finales.length - 1];
    const cle = final && session.current ? `${session.current.id}-${final.at}` : '';
    if (cle && cle !== dernierFinal.current) {
      dernierFinal.current = cle;
      viderSauvegardeConversations();
      window.dispatchEvent(new Event('diapason:conversation-terminee'));
    }
  }, [voix.transcripts, voix.toolEvents, conserver]);

  useEffect(() => {
    if (!session.current || voix.isActive) return;
    if (voix.finVocale) setVisible(false);
    conserver(true);
    session.current = null;
    marquerFilVocal(null);
    viderSauvegardeConversations();
    window.dispatchEvent(new Event('diapason:conversation-terminee'));
  }, [voix.isActive, voix.state, voix.finVocale, conserver]);

  useEffect(() => useAppStore.subscribe((etat, avant) => {
    if (etat.activeId !== avant.activeId && session.current && etat.activeId !== session.current.conversationId) arreter();
  }), [arreter]);
  useEffect(() => () => arreter(), [arreter]);

  useEffect(() => {
    const ouvrir = () => { if (courant.current.isActive) arreter(); else void demarrer(); };
    window.addEventListener('diapason-voice-inline', ouvrir);
    return () => window.removeEventListener('diapason-voice-inline', ouvrir);
  }, [arreter, demarrer]);

  return { ...voix, visible, demarrer, arreter };
}
