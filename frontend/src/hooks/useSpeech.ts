import { useState, useCallback, useRef, useEffect } from 'react';
import { transcribeAudio, fetchSpeechHealth } from '../lib/api';
import { traduire } from '../i18n/translate';
import { cleErreurVocale } from '../lib/erreursVocales';
import {
  classerEchecMicro,
  doitLireEtatAndroid,
  lireEtatDuMicro,
  messageDuMicro,
  ouvrirLesReglagesDuMicro,
  type AvisDesReglages,
  type DemanderMicro,
  type EtapeDuMicro,
  type EtatMicroLu,
} from '../lib/echecMicro';
import { demanderAuTelephone } from '../lib/natif';
import { serviParLeTailnet } from '../lib/tailnet';

export type SpeechState = 'idle' | 'recording' | 'transcribing';

/** Sous la phrase d'une dictée dont le micro ne s'est pas ouvert. */
export interface DicteeSansMicro {
  /** « NotReadableError · Could not start audio source » ; au téléphone seulement. */
  technique: string | null;
  /** Le bouton « Ouvrir les réglages » (verbe `micro/reglages`). */
  reglages: boolean;
}

const demanderMicro: DemanderMicro = (verbe, donnees) => demanderAuTelephone(verbe, donnees);

export function useSpeech() {
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [micro, setMicro] = useState<DicteeSansMicro | null>(null);
  const [available, setAvailable] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  // Le numéro de la dernière demande du micro ; un relâcher l'incrémente.
  const demandeRef = useRef(0);
  // Le numéro du dernier APPUI ; seul un nouvel appui l'incrémente. Distinct
  // de `demandeRef` : le doigt qui se lève pour répondre « Refuser » à
  // l'invite d'Android incrémente la demande AVANT que getUserMedia ne
  // rejette — garder l'échec sur la demande taisait précisément ce refus.
  const appuiRef = useRef(0);

  // Check if speech backend is available on mount
  useEffect(() => {
    fetchSpeechHealth()
      .then((health) => setAvailable(health.available))
      .catch(() => setAvailable(false));
  }, []);

  /**
   * 28/09/2026 : la dictée « maintenir pour parler » disait « Microphone
   * access denied », en anglais et en dur, pour TOUTE erreur — le
   * NotReadableError d'une WebView sans MODIFY_AUDIO_SETTINGS compris. Le
   * même classement et les mêmes phrases que « Parler » (lib/echecMicro.ts).
   * L'état d'Android est attendu AVANT de parler : un toast dit une chose,
   * une fois.
   *
   * 28/09/2026 (revue) : la réponse de micro/etat n'était pas rapportée à
   * son appui. Un premier appui refusé, un relâcher, un second appui que
   * l'invite accorde : la réponse tardive du premier posait « Android n'a
   * pas donné le micro à Diapason » et « Ouvrir les réglages » PENDANT que
   * le micro enregistrait (§5) — sur toute la fenêtre de 10 s d'une
   * coquille lente.
   */
  const signalerEchecMicro = useCallback(async (erreur: unknown, etape: EtapeDuMicro, appui: number) => {
    const echec = classerEchecMicro(erreur, etape);
    console.error('[dictée] le micro ne s’est pas ouvert', { classe: echec.classe, technique: echec.technique }, erreur);
    const auTelephone = serviParLeTailnet();
    const etat: EtatMicroLu = auTelephone && doitLireEtatAndroid(echec.classe)
      ? await lireEtatDuMicro(demanderMicro)
      : 'inconnu';
    if (appui !== appuiRef.current) return;
    const message = messageDuMicro({ classe: echec.classe, auTelephone, etat });
    setMicro({ technique: auTelephone ? echec.technique : null, reglages: message.reglages });
    setError(traduire(cleErreurVocale(message.code)));
  }, []);

  const startRecording = useCallback(async (): Promise<void> => {
    setError(null);
    setMicro(null);
    const demande = ++demandeRef.current;
    const appui = ++appuiRef.current;

    let stream: MediaStream;
    try {
      // Sans `navigator.mediaDevices` (page non sécurisée), l'appel lève un
      // TypeError, classé « page sans micro » comme les autres.
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setState('idle');
      await signalerEchecMicro(err, 'avantLeFlux', appui);
      return;
    }

    // 28/09/2026 (audit du micro au téléphone) : l'invite d'Android
    // apparaît sous le doigt qui tient le bouton. Le doigt se lève pour
    // répondre, `stopRecording` ne trouvait encore aucun enregistreur et
    // son refus était avalé ; l'accord arrivait ensuite et démarrait un
    // MediaRecorder que plus rien n'arrêtait — voyant vert compris,
    // jusqu'au toucher suivant (§78). Relâché avant l'accord : le flux se
    // referme aussitôt, rien n'enregistre.
    if (demande !== demandeRef.current) {
      stream.getTracks().forEach((piste) => piste.stop());
      setState('idle');
      return;
    }

    try {
      streamRef.current = stream;

      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setState('recording');
    } catch (err) {
      // Le flux était ouvert : sans cet arrêt, un MediaRecorder refusé
      // laissait le voyant du micro allumé jusqu'au rechargement (§78).
      stream.getTracks().forEach((piste) => piste.stop());
      streamRef.current = null;
      setState('idle');
      await signalerEchecMicro(err, 'apresLeFlux', appui);
    }
  }, [signalerEchecMicro]);

  /** Le bouton du toast ; rend ce qu'il faut dire si les réglages ne se sont pas ouverts. */
  const ouvrirReglagesMicro = useCallback(
    (): Promise<AvisDesReglages | null> => ouvrirLesReglagesDuMicro(demanderMicro),
    [],
  );

  const stopRecording = useCallback(async (): Promise<string> => {
    return new Promise((resolve, reject) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state !== 'recording') {
        // Une demande encore en attente (l'invite d'Android) est annulée.
        demandeRef.current += 1;
        reject(new Error('Not recording'));
        return;
      }

      recorder.onstop = async () => {
        setState('transcribing');

        // Stop all audio tracks
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;

        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        chunksRef.current = [];

        try {
          const result = await transcribeAudio(blob);
          setState('idle');
          resolve(result.text);
        } catch (err) {
          setState('idle');
          const msg = err instanceof Error ? err.message : 'Transcription failed';
          setError(msg);
          reject(err);
        }
      };

      recorder.stop();
    });
  }, []);

  return {
    state,
    error,
    micro,
    available,
    startRecording,
    stopRecording,
    ouvrirReglagesMicro,
    isRecording: state === 'recording',
    isTranscribing: state === 'transcribing',
  };
}
