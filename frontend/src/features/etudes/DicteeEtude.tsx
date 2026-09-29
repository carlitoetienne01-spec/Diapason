import { useEffect, useRef, useState } from 'react';
import { Mic, Square } from 'lucide-react';
import { useSpeech } from '../../hooks/useSpeech';
import { conversationVocaleEnCours } from '../../lib/conversationVocale';

export function DicteeEtude({ disabled, onTexte, onActivite }: { disabled: boolean; onTexte: (texte: string) => void; onActivite: (active: boolean) => void }) {
  const micro = useSpeech();
  const [avis, setAvis] = useState('');
  const [ouverture, setOuverture] = useState(false);
  const present = useRef(true);
  const arreter = useRef(micro.stopRecording);
  const signaler = useRef(onActivite);
  signaler.current = onActivite;
  arreter.current = micro.stopRecording;
  useEffect(() => { signaler.current(ouverture || micro.state !== 'idle'); }, [ouverture, micro.state]);
  useEffect(() => {
    present.current = true;
    return () => { present.current = false; signaler.current(false); void arreter.current().catch(() => undefined); };
  }, []);
  const terminer = async () => {
    try {
      const texte = await micro.stopRecording();
      if (present.current) { onTexte(texte); setAvis('Relis la transcription avant de valider ta réponse.'); }
    } catch (e) { if (present.current) setAvis(e instanceof Error ? e.message : 'La dictée a échoué.'); }
  };
  useEffect(() => {
    if (!micro.isRecording) return;
    // Une capture est un brouillon, pas une séance vocale : 120 s évitent
    // un micro oublié sans limiter la durée de l'examen, qui reste sauvegardé.
    const delai = window.setTimeout(() => { void terminer(); }, 120_000);
    return () => window.clearTimeout(delai);
  }, [micro.isRecording]);
  return <div>
    <button type="button" disabled={disabled || ouverture || micro.isTranscribing || !micro.available}
      onClick={() => {
        if (micro.isRecording) { void terminer(); return; }
        if (conversationVocaleEnCours()) { setAvis('Mets la conversation vocale en pause avant de dicter cette réponse.'); return; }
        setAvis(''); setOuverture(true); signaler.current(true);
        void micro.startRecording().finally(() => { if (present.current) setOuverture(false); });
      }}>
      {micro.isRecording ? <Square size={16} /> : <Mic size={16} />}
      {micro.isRecording ? 'Terminer la dictée' : ouverture ? 'Ouverture du micro…' : micro.isTranscribing ? 'Transcription…' : 'Dicter ma réponse'}
    </button>
    {(micro.error || avis) && <p role="status" className="etude-secondaire">{micro.error || avis}</p>}
  </div>;
}
