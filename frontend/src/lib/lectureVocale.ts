/** La lecture possède ses sources, jamais le micro de la conversation. */
export class LectureVocale {
  private contexte: AudioContext | null = null;
  private sortie: GainNode | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private prochaine = 0;

  constructor(private publier: (sortie: GainNode | null, parle: boolean) => void) {}

  ajouter(base64: string, frequence: number) {
    const binaire = atob(base64);
    if (!binaire.length) return;
    if (binaire.length % 2 || !Number.isFinite(frequence) || frequence < 8000 || frequence > 96000) {
      throw new Error('Trame audio vocale invalide');
    }
    let contexte = this.contexte;
    if (!contexte || contexte.state === 'closed') {
      contexte = new AudioContext({ sampleRate: frequence });
      this.contexte = contexte;
      this.prochaine = contexte.currentTime;
      this.sortie = contexte.createGain();
      this.sortie.connect(contexte.destination);
    }
    if (contexte.state === 'suspended') void contexte.resume().catch(() => {});
    const octets = Uint8Array.from(binaire, (caractere) => caractere.charCodeAt(0));
    const donnees = new DataView(octets.buffer);
    const pcm = new Float32Array(binaire.length / 2);
    for (let i = 0; i < pcm.length; i++) pcm[i] = donnees.getInt16(i * 2, true) / 32768;
    const tampon = contexte.createBuffer(1, pcm.length, frequence);
    tampon.copyToChannel(pcm, 0);
    const source = contexte.createBufferSource();
    source.buffer = tampon;
    source.connect(this.sortie!);
    this.sources.add(source);
    // 12 septembre 2026 : sans onended, une réponse terminée gardait
    // l'interface en « parle » et la forme n'observait plus le micro.
    source.onended = () => {
      source.disconnect();
      if (!this.sources.delete(source) || this.contexte !== contexte) return;
      if (!this.sources.size) this.publier(this.sortie, false);
    };
    const debut = Math.max(contexte.currentTime, this.prochaine);
    source.start(debut);
    this.prochaine = debut + tampon.duration;
    this.publier(this.sortie, true);
  }

  arreter() {
    // Les callbacks de l'ancienne file ne peuvent pas faire revenir une
    // nouvelle conversation à « écoute » après une interruption.
    const contexte = this.contexte;
    this.contexte = null;
    for (const source of this.sources) {
      source.onended = null;
      try { source.stop(); } catch { /* source déjà terminée */ }
      source.disconnect();
    }
    this.sources.clear();
    this.sortie?.disconnect();
    this.sortie = null;
    this.prochaine = 0;
    this.publier(null, false);
    if (contexte && contexte.state !== 'closed') void contexte.close().catch(() => {});
  }
}
