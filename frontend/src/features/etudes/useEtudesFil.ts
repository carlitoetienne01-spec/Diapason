import { useCallback, useEffect, useRef, useState } from 'react';
import { listerEtudes } from './api';
import { erreurEtude, type Etude } from './etudes';
import { actualiserEtudes } from './filEtudes';

export function useEtudesFil(conversationId: string | null) {
  const [etat, setEtat] = useState<{ conversation: string | null; etudes: Etude[]; erreur: string }>({ conversation: null, etudes: [], erreur: '' });
  const revision = useRef(0);
  useEffect(() => {
    let termine = false;
    let enCours = false;
    setEtat({ conversation: conversationId, etudes: [], erreur: '' });
    if (!conversationId) return;
    const charger = async () => {
      if (enCours || document.hidden) return;
      enCours = true;
      const debut = revision.current;
      try {
        const resultat = await listerEtudes(conversationId);
        if (!termine && debut === revision.current) setEtat(e => ({ conversation: conversationId, etudes: actualiserEtudes(e.conversation === conversationId ? e.etudes : [], resultat.sessions), erreur: '' }));
      } catch (e) {
        if (!termine) setEtat(avant => ({ ...avant, conversation: conversationId, erreur: erreurEtude(e) }));
      } finally { enCours = false; }
    };
    void charger();
    // Une relève pour le fil entier, plutôt qu'une relève par carte ouverte.
    const minuterie = window.setInterval(() => void charger(), 2000);
    window.addEventListener('diapason:conversation-terminee', charger);
    document.addEventListener('visibilitychange', charger);
    return () => { termine = true; window.clearInterval(minuterie); window.removeEventListener('diapason:conversation-terminee', charger); document.removeEventListener('visibilitychange', charger); };
  }, [conversationId]);
  const adopter = useCallback((etude: Etude) => {
    revision.current++;
    setEtat(e => e.conversation === etude.conversationId ? { ...e, etudes: [etude, ...e.etudes.filter(a => a.id !== etude.id)] } : e);
  }, []);
  const retirer = useCallback((id: string) => {
    revision.current++;
    setEtat(e => ({ ...e, etudes: e.etudes.filter(a => a.id !== id) }));
  }, []);
  return { etudes: etat.conversation === conversationId ? etat.etudes : [], erreur: etat.conversation === conversationId ? etat.erreur : '', adopter, retirer };
}
