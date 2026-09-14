// Banc visuel DEV uniquement : aucun appel vocal, aucun micro, aucun fichier
// utilisateur. Les états et les paroles d'exemple sont explicitement simulés.
import { StrictMode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { TalkOrb } from '../Chat/TalkOrb';
import { TranslationProvider, useTranslation } from '../../i18n/useTranslation';
import type { VoiceLiveState } from '../../hooks/useVoiceLive';
import { creerCaptureVocale } from '../../lib/captureVocale';
import '../../index.css';

function Apercu() {
  const [etat, setEtat] = useState<VoiceLiveState>('idle');
  const [ouvert, setOuvert] = useState(true);
  const [fil, setFil] = useState(false);
  const [reduit, setReduit] = useState(false);
  const [signal, setSignal] = useState<AudioNode | null>(null);
  const [bilan, setBilan] = useState('');
  const nettoyage = useRef<(() => void) | null>(null);
  const { setLocale } = useTranslation();
  useEffect(() => { setLocale('fr'); }, [setLocale]);
  useEffect(() => () => nettoyage.current?.(), []);
  const testerSignal = async () => {
    nettoyage.current?.();
    const contexte = new AudioContext({ sampleRate: 16000 });
    const oscillateur = contexte.createOscillator();
    const enveloppe = contexte.createGain();
    oscillateur.frequency.value = 220;
    oscillateur.connect(enveloppe);
    let paquets = 0;
    let echantillons = 0;
    let maximum = 0;
    let timer = 0;
    let capture: Awaited<ReturnType<typeof creerCaptureVocale>> | null = null;
    let ferme = false;
    const terminer = () => {
      if (ferme) return;
      ferme = true;
      window.clearTimeout(timer);
      oscillateur.disconnect();
      capture?.arreter();
      enveloppe.disconnect();
      void contexte.close();
      setSignal(null);
      setEtat('idle');
    };
    nettoyage.current = terminer;
    setBilan('Test synthétique en cours — aucun micro, aucun son dans les enceintes');
    try {
      capture = await creerCaptureVocale(contexte, enveloppe, (pcm) => {
        const valeurs = new DataView(pcm);
        for (let i = 0; i < valeurs.byteLength; i += 2) maximum = Math.max(maximum, Math.abs(valeurs.getInt16(i, true)));
        paquets++; echantillons += pcm.byteLength / 2;
      });
      if (ferme) { capture.arreter(); return; }
      await contexte.resume();
      if (ferme) return;
      const debut = contexte.currentTime;
      enveloppe.gain.setValueAtTime(0, debut);
      for (let i = 0; i < 5; i++) {
        enveloppe.gain.linearRampToValueAtTime(0.12, debut + i * 0.5 + 0.12);
        enveloppe.gain.linearRampToValueAtTime(0, debut + i * 0.5 + 0.35);
      }
      oscillateur.start();
      setSignal(enveloppe); setEtat('listening'); setOuvert(true);
      timer = window.setTimeout(() => {
        setBilan(`Test synthétique terminé : ${capture!.methode} · ${paquets} trames · ${echantillons} échantillons · pic PCM ${maximum} · ${contexte.sampleRate} Hz`);
        terminer();
      }, 2800);
    } catch (erreur) {
      setBilan(`Test impossible : ${String(erreur)}`);
      terminer();
    }
  };
  return <>
    <div style={{ position: 'fixed', zIndex: 80, top: 0, left: 0, right: 0, background: '#211a2d', color: '#ede5fa', font: '12px system-ui', padding: 8, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
      <span>Aperçu graphique · états simulés · aucun micro</span>
      <select aria-label="État simulé" value={etat} onChange={(e) => { setEtat(e.target.value as VoiceLiveState); setOuvert(true); }}>
        <option value="idle">Au repos</option><option value="connecting">Connexion</option>
        <option value="listening">Écoute</option><option value="speaking">Réponse</option><option value="error">Erreur</option>
      </select>
      <label><input type="checkbox" checked={fil} onChange={(e) => setFil(e.target.checked)} /> Conversation d’exemple</label>
      <label><input type="checkbox" checked={reduit} onChange={(e) => setReduit(e.target.checked)} /> Fenêtre étroite</label>
      <button onClick={() => void testerSignal()} disabled={!!signal}>Tester le signal sans micro</button>
      {bilan && <output aria-live="polite">{bilan}</output>}
      {!ouvert && <button onClick={() => setOuvert(true)}>Rouvrir</button>}
    </div>
    <div className={reduit ? 'resonance-banc-etroit' : ''}>
      <TalkOrb open={ouvert} state={etat} statusLabel={`Aperçu : ${etat}`} error={etat === 'error' ? 'voice-connection-failed' : null}
        serviceReady={true} checkingService={false} provider="local"
        micSource={signal}
        transcripts={fil ? [
          { at: 1, role: 'user', text: 'J’aimerais donner une nouvelle présence à Diapason.', final: true },
          { at: 2, role: 'assistant', text: 'Une forme lumineuse qui accompagne la conversation.\n\nDes voiles violets, une lumière nacrée et de fines ondulations portées par la voix. Le reste reste simple : parler, écouter, reprendre la parole.', final: true },
          { at: 3, role: 'user', text: 'Et quand je ne parle pas ?', final: true },
          { at: 4, role: 'assistant', text: 'Une respiration lente. Le micro ne s’ouvre que lorsque tu démarres la conversation.', final: true },
        ] : []} onProviderChange={() => {}} onStart={() => setEtat('listening')} onStop={() => setEtat('idle')}
        onInterrupt={() => setEtat('listening')} onClose={() => setOuvert(false)} />
    </div>
    <style>{`body { background: var(--color-bg); } .resonance-rideau { padding-top: 96px; }
      .resonance-rideau .composer-glass.resonance-dialogue { max-height: calc(100dvh - 120px); }
      .resonance-banc-etroit .composer-glass.resonance-dialogue { width: min(380px, 100%); }
      .resonance-banc-etroit .resonance-corps { flex-direction: column; }
      .resonance-banc-etroit .resonance-presence, .resonance-banc-etroit .resonance-conversation { width: 100%; }
      .resonance-banc-etroit .resonance-conversation { flex-shrink: 0; }
      .resonance-banc-etroit .resonance-fil { max-height: 220px; }
      .resonance-banc-etroit .resonance-sous-titre { display: none; }
    `}</style>
  </>;
}

if (import.meta.env.DEV) {
  const racine = createRoot(document.getElementById('root')!);
  racine.render(<StrictMode><TranslationProvider><Apercu /></TranslationProvider></StrictMode>);
  import.meta.hot?.dispose(() => racine.unmount());
}
