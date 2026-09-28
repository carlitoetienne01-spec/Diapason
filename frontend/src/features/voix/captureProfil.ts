import { apiFetch } from '../../lib/api';
import { creerCaptureVocale } from '../../lib/captureVocale';

export const PHRASES_PROFIL = [
  'Diapason, aide-moi à organiser ma journée et mes prochains rendez-vous.',
  'Je voudrais apprendre quelque chose de nouveau et en discuter tranquillement.',
  'Peux-tu reprendre la dernière explication avec un exemple plus simple ?',
  'Aujourd’hui, je parle naturellement, à ma distance habituelle du microphone.',
  'Demain matin, rappelle-moi de vérifier mes notes avant de commencer.',
  'Oui, c’est bien ça.', 'Non, pas maintenant.', 'Très bien, merci beaucoup.',
] as const;

export interface EtatProfil { enrolled: boolean; sampleCount: number; revision: string }
export class ErreurProfil extends Error {
  constructor(public motif: string, public indice?: number) { super(motif); }
}
export async function requeteProfil<T>(suffixe = '', methode = 'GET', contenu?: unknown): Promise<T> {
  const r = await apiFetch(`/v1/voice/profile${suffixe}`, {
    method: methode,
    ...(contenu === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(contenu) }),
  });
  if (!r.ok) {
    const corps = await r.json().catch(() => null);
    throw new ErreurProfil(r.status === 404 ? 'notLoaded' : corps?.detail?.reason ?? 'network', corps?.detail?.index);
  }
  return r.json();
}

export function assemblerPcm(blocs: ArrayBuffer[]): string {
  const taille = blocs.reduce((total, bloc) => total + bloc.byteLength, 0);
  if (!taille || taille > 256000 || taille % 2) throw new ErreurProfil('invalidSample');
  const octets = new Uint8Array(taille);
  let position = 0;
  for (const bloc of blocs) { octets.set(new Uint8Array(bloc), position); position += bloc.byteLength; }
  let binaire = '';
  for (let i = 0; i < octets.length; i += 4096) binaire += String.fromCharCode(...octets.subarray(i, i + 4096));
  return btoa(binaire);
}

/** §78 : un clic, huit secondes au maximum ; une permission tardive ne rallume rien. */
export async function capturerProfil({ signal, fin, pret, niveau }: {
  signal: AbortSignal; fin: Promise<void>; pret: () => void; niveau: (valeur: number) => void;
}): Promise<string> {
  let flux: MediaStream | undefined, contexte: AudioContext | undefined;
  let capture: Awaited<ReturnType<typeof creerCaptureVocale>> | undefined;
  let minuterie: ReturnType<typeof setTimeout> | undefined;
  let refuser!: () => void;
  const abandon = new Promise<never>((_, rejeter) => {
    refuser = () => rejeter(new DOMException('Annulé', 'AbortError'));
  });
  signal.addEventListener('abort', refuser, { once: true });
  const blocs: ArrayBuffer[] = [];
  try {
    if (signal.aborted) throw new DOMException('Annulé', 'AbortError');
    flux = await Promise.race([navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    }).then((media) => {
      if (signal.aborted) { media.getTracks().forEach(p => p.stop()); throw new DOMException('Annulé', 'AbortError'); }
      return media;
    }), abandon]);
    contexte = new AudioContext({ sampleRate: 16000 });
    if (contexte.sampleRate !== 16000) throw new ErreurProfil('capture');
    await Promise.race([contexte.resume(), abandon]);
    if (signal.aborted) throw new DOMException('Annulé', 'AbortError');
    let taille = 0;
    capture = await Promise.race([creerCaptureVocale(contexte, contexte.createMediaStreamSource(flux), (bloc) => {
      if (signal.aborted || taille >= 256000) return;
      const portion = bloc.slice(0, 256000 - taille);
      taille += portion.byteLength;
      blocs.push(portion);
      const vue = new Int16Array(portion);
      let somme = 0;
      for (const valeur of vue) somme += (valeur / 32768) ** 2;
      niveau(Math.min(1, Math.sqrt(somme / Math.max(1, vue.length)) * 12));
    }).then((controle) => {
      if (signal.aborted) { controle.arreter(); throw new DOMException('Annulé', 'AbortError'); }
      return controle;
    }), abandon]);
    if (signal.aborted) throw new DOMException('Annulé', 'AbortError');
    pret();
    await Promise.race([fin, abandon, new Promise<void>(resolve => { minuterie = setTimeout(resolve, 8000); })]);
    return assemblerPcm(blocs);
  } finally {
    signal.removeEventListener('abort', refuser);
    clearTimeout(minuterie);
    try { capture?.arreter(); } catch { /* Un nœud déjà fermé ne garde pas le micro ouvert. */ }
    flux?.getTracks().forEach(piste => piste.stop());
    if (contexte && contexte.state !== 'closed') await contexte.close().catch(() => {});
    niveau(0);
  }
}
