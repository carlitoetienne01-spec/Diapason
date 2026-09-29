/** La lecture possède ses sources, jamais le micro de la conversation. */
export class LectureVocale {
  private contexte: AudioContext | null = null;
  private sortie: GainNode | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private prochaine = 0;
  private reveil: { attente: Promise<void>; annuler: () => void } | null = null;

  constructor(
    private publier: (sortie: GainNode | null, parle: boolean) => void,
    private signalerEchec: (cause: unknown) => void = (cause) => console.error('[voice-live] audio playback failed', cause),
  ) {}

  private assurerContexte(frequence = 24000) {
    if (this.contexte && this.contexte.state !== 'closed') return this.contexte;
    const contexte = new AudioContext({ sampleRate: frequence });
    this.contexte = contexte;
    this.prochaine = contexte.currentTime;
    this.sortie = contexte.createGain();
    this.sortie.connect(contexte.destination);
    contexte.onstatechange = () => {
      if (this.contexte === contexte && this.sources.size) this.publier(this.sortie, contexte.state === 'running');
    };
    return contexte;
  }

  private reprendre(contexte: AudioContext): Promise<void> {
    if (contexte.state === 'running') return Promise.resolve();
    if (this.reveil) return this.reveil.attente;
    let annuler!: () => void;
    let garde: ReturnType<typeof setTimeout>;
    // 28/09/2026 : resume() peut rester pendant sans rejet si Android attend
    // un geste. Deux secondes bornent cette attente locale (aucun réseau),
    // sinon « Parle » restait affiché sans un seul échantillon joué.
    const attente = new Promise<void>((resolve, reject) => {
      annuler = () => reject(new DOMException('Lecture fermée', 'AbortError'));
      garde = setTimeout(() => reject(new Error('La sortie audio reste suspendue')), 2000);
      contexte.resume().then(() => {
        if (this.contexte !== contexte) { annuler(); return; }
        if (contexte.state !== 'running') reject(new Error('La sortie audio ne démarre pas'));
        else resolve();
      }, reject);
    }).finally(() => {
      clearTimeout(garde);
      if (this.reveil?.attente === attente) this.reveil = null;
    });
    this.reveil = { attente, annuler };
    return attente;
  }

  /** Appel synchrone depuis le bouton, avant toute attente réseau. */
  async preparer(): Promise<void> {
    // 28/09/2026 : créé à la première trame WebSocket, le lecteur n'était
    // plus lié au toucher « Parler » et pouvait rester muet sur téléphone.
    await this.reprendre(this.assurerContexte());
  }

  ajouter(base64: string, frequence: number) {
    const binaire = atob(base64);
    if (!binaire.length) return;
    if (binaire.length % 2 || !Number.isFinite(frequence) || frequence < 8000 || frequence > 96000) {
      throw new Error('Trame audio vocale invalide');
    }
    const contexte = this.assurerContexte(frequence);
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
    // 27/09/2026 : lancer au temps courant ne laissait aucune marge au
    // moteur audio de WebKit. 60 ms couvrent plusieurs quanta de rendu ;
    // les paquets suivants restent collés, sans rajouter ce délai chacun.
    const debut = this.prochaine > contexte.currentTime
      ? this.prochaine : contexte.currentTime + 0.06;
    source.start(debut);
    this.prochaine = debut + tampon.duration;
    this.publier(this.sortie, contexte.state === 'running');
    if (contexte.state !== 'running') {
      void this.reprendre(contexte).then(() => {
        if (this.contexte === contexte && this.sources.size) this.publier(this.sortie, true);
      }).catch((cause) => {
        if (this.contexte !== contexte || !this.sources.size) return;
        this.interrompre();
        this.signalerEchec(cause);
      });
    }
  }

  interrompre() {
    // Les callbacks de l'ancienne file ne peuvent pas faire revenir une
    // nouvelle conversation à « écoute » après une interruption.
    for (const source of this.sources) {
      source.onended = null;
      try { source.stop(); } catch { /* source déjà terminée */ }
      source.disconnect();
    }
    this.sources.clear();
    this.prochaine = this.contexte?.currentTime ?? 0;
    this.publier(this.sortie, false);
  }

  arreter() {
    const contexte = this.contexte;
    this.contexte = null;
    if (contexte) contexte.onstatechange = null;
    this.reveil?.annuler();
    this.reveil = null;
    this.interrompre();
    this.sortie?.disconnect();
    this.sortie = null;
    this.prochaine = 0;
    this.publier(null, false);
    if (contexte && contexte.state !== 'closed') void contexte.close().catch(() => {});
  }
}
