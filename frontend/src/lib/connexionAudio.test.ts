import { describe, expect, it } from 'vitest';
import { deconnecterBrancheAudio } from './connexionAudio';

// Contrairement à l'ancien mock permissif, Web Audio lève une exception
// quand une destination précise ne fait plus partie du graphe.
class Noeud {
  sorties = new Set<Noeud>();
  connect(destination: Noeud) { this.sorties.add(destination); }
  disconnect(destination?: Noeud) {
    if (!destination) this.sorties.clear();
    else if (!this.sorties.delete(destination)) {
      throw new DOMException('The given destination is not connected', 'InvalidAccessError');
    }
  }
}

describe('§100 — le nettoyage du visualiseur ne fait pas tomber le chat', () => {
  it('accepte que le lecteur ait déjà retiré la branche avant React', () => {
    const source = new Noeud(), analyseur = new Noeud();
    source.connect(analyseur);
    source.disconnect(); // LectureVocale.arreter(), avant le cleanup de l’effet.
    expect(() => source.disconnect(analyseur), 'reproduction du défaut natif').toThrow('not connected');
    expect(() => deconnecterBrancheAudio(source as unknown as AudioNode, analyseur as unknown as AudioNode)).not.toThrow();
  });

  it('préserve le haut-parleur et une nouvelle branche même après deux nettoyages', () => {
    const source = new Noeud(), ancien = new Noeud(), nouveau = new Noeud(), enceinte = new Noeud();
    source.connect(ancien); source.connect(nouveau); source.connect(enceinte);
    for (let i = 0; i < 2; i++) deconnecterBrancheAudio(source as unknown as AudioNode, ancien as unknown as AudioNode);
    expect(source.sorties).toEqual(new Set([nouveau, enceinte]));
  });

  it('ne masque pas une autre erreur de programmation', () => {
    const erreur = new TypeError('destination invalide');
    const source = { disconnect: () => { throw erreur; } };
    expect(() => deconnecterBrancheAudio(source as unknown as AudioNode, {} as AudioNode)).toThrow(erreur);
  });
});
