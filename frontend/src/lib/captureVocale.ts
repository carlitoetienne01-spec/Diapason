// Une URL data: serait refusée par la CSP de Tauri. Conserver un vrai
// fichier local, même sous le seuil d'inlining de Vite (4 Ko).
import moduleCapture from './captureVocale.worklet.js?url&no-inline';

export interface CaptureVocale {
  methode: 'worklet' | 'secours';
  arreter: () => void;
}

export async function creerCaptureVocale(
  contexte: AudioContext,
  source: AudioNode,
  recevoir: (pcm: ArrayBuffer) => void,
): Promise<CaptureVocale> {
  let processeur: AudioWorkletNode | ScriptProcessorNode | undefined;
  if (contexte.audioWorklet && typeof AudioWorkletNode !== 'undefined') {
    try {
      await contexte.audioWorklet.addModule(moduleCapture);
      const worklet = new AudioWorkletNode(contexte, 'diapason-capture-vocale', {
        numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
      });
      worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => recevoir(event.data);
      processeur = worklet;
    } catch (erreur) {
      if (contexte.state === 'closed') throw erreur;
      console.warn('[voice-live] AudioWorklet indisponible, capture de secours', erreur);
    }
  }
  if (!processeur) {
    // WKWebView peut refuser le module : 1024/16000 = 64 ms, au lieu
    // des 256 ms historiques. Ce repli reste muet, sans second micro.
    const secours = contexte.createScriptProcessor(1024, 1, 1);
    secours.onaudioprocess = (event) => {
      const entree = event.inputBuffer.getChannelData(0);
      const pcm = new ArrayBuffer(entree.length * 2);
      const vue = new DataView(pcm);
      for (let i = 0; i < entree.length; i++) {
        const valeur = Math.max(-1, Math.min(1, entree[i]));
        vue.setInt16(i * 2, valeur < 0 ? valeur * 32768 : valeur * 32767, true);
      }
      recevoir(pcm);
    };
    processeur = secours;
  }
  const silence = contexte.createGain();
  silence.gain.value = 0;
  source.connect(processeur);
  processeur.connect(silence);
  silence.connect(contexte.destination);
  return {
    methode: 'port' in processeur ? 'worklet' : 'secours',
    arreter() {
      if ('port' in processeur) {
        processeur.port.onmessage = null;
        processeur.port.close();
      } else {
        processeur.onaudioprocess = null;
      }
      source.disconnect(processeur);
      processeur.disconnect();
      silence.disconnect();
    },
  };
}
