import type { MeshFileReceived } from './types';

export type FileArrivalKind = 'image' | 'video' | 'audio' | 'file';

export function fileArrivalKind(
  receipt: Pick<MeshFileReceived, 'fileName' | 'mimeType'>,
): FileArrivalKind {
  const mime = receipt.mimeType.trim().toLowerCase();
  if (mime.startsWith('image/')) return 'image';
  if (mime.startsWith('video/')) return 'video';
  if (mime.startsWith('audio/')) return 'audio';

  const extension = receipt.fileName.split('.').pop()?.toLowerCase() ?? '';
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'avif'].includes(extension)) {
    return 'image';
  }
  if (['mp4', 'mov', 'mkv', 'webm', 'avi'].includes(extension)) return 'video';
  if (['mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg'].includes(extension)) return 'audio';
  return 'file';
}

export function formatFileArrivalSize(bytes: number): string {
  const safe = Number.isFinite(bytes) ? Math.max(0, Math.trunc(bytes)) : 0;
  if (safe >= 1024 ** 3) return `${(safe / 1024 ** 3).toFixed(1)} Gio`;
  if (safe >= 1024 ** 2) return `${(safe / 1024 ** 2).toFixed(1)} Mio`;
  if (safe >= 1024) return `${(safe / 1024).toFixed(1)} Kio`;
  return `${safe} o`;
}

/** A quiet three-note chime, generated locally without an audio asset. */
export async function playFileArrivalChime(): Promise<void> {
  type AudioContextConstructor = new () => AudioContext;
  const browser = window as typeof window & {
    webkitAudioContext?: AudioContextConstructor;
  };
  const AudioContextClass = window.AudioContext ?? browser.webkitAudioContext;
  if (!AudioContextClass) return;

  let context: AudioContext | null = null;
  try {
    context = new AudioContextClass();
    if (context.state === 'suspended') await context.resume();

    const now = context.currentTime;
    const master = context.createGain();
    master.gain.setValueAtTime(0.0001, now);
    master.gain.exponentialRampToValueAtTime(0.045, now + 0.025);
    master.gain.exponentialRampToValueAtTime(0.0001, now + 0.72);
    master.connect(context.destination);

    for (const [index, frequency] of [523.25, 659.25, 783.99].entries()) {
      const start = now + index * 0.075;
      const oscillator = context.createOscillator();
      const envelope = context.createGain();
      oscillator.type = index === 2 ? 'triangle' : 'sine';
      oscillator.frequency.setValueAtTime(frequency, start);
      envelope.gain.setValueAtTime(0.0001, start);
      envelope.gain.exponentialRampToValueAtTime(0.55, start + 0.018);
      envelope.gain.exponentialRampToValueAtTime(0.0001, start + 0.42);
      oscillator.connect(envelope);
      envelope.connect(master);
      oscillator.start(start);
      oscillator.stop(start + 0.45);
    }

    const toClose = context;
    window.setTimeout(() => void toClose.close().catch(() => {}), 900);
  } catch {
    if (context) void context.close().catch(() => {});
    // L'animation reste le signal principal. Un navigateur qui bloque
    // l'audio en arrière-plan ne doit ni casser ni masquer la réception.
  }
}
