// 12 septembre 2026 : les blocs de 4096 échantillons attendaient 256 ms
// à 16 kHz et leur callback partageait le fil du rendu. Ici 20 ms par trame,
// sur le fil audio ; aucun échantillon n'est recopié dans les haut-parleurs.
class CaptureVocale extends AudioWorkletProcessor {
  constructor() {
    super();
    this.taille = Math.round(sampleRate * 0.020);
    this.tampon = new ArrayBuffer(this.taille * 2);
    this.vue = new DataView(this.tampon);
    this.position = 0;
  }

  process(entrees) {
    const entree = entrees[0]?.[0];
    if (!entree) return true;
    for (let i = 0; i < entree.length; i++) {
      const valeur = Math.max(-1, Math.min(1, entree[i]));
      this.vue.setInt16(this.position * 2, valeur < 0 ? valeur * 32768 : valeur * 32767, true);
      if (++this.position === this.taille) {
        this.port.postMessage(this.tampon, [this.tampon]);
        this.tampon = new ArrayBuffer(this.taille * 2);
        this.vue = new DataView(this.tampon);
        this.position = 0;
      }
    }
    return true;
  }
}

registerProcessor('diapason-capture-vocale', CaptureVocale);
