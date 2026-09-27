import { describe, expect, it, vi } from 'vitest';

import { freresARendreInertes, rendreInertes, reponseAuRetour, toucherDuVoile } from './fermetureRoue';

/**
 * La roue et le bouton retour d'Android, et la page sous l'écran « Aller à »
 * (26/09/2026, contre-épreuve de la fluidité : mutants A6 et A7).
 */
describe('reponseAuRetour', () => {
  it('roue ouverte : le retour la ferme et s’arrête là', () => {
    const fermer = vi.fn();
    expect(reponseAuRetour(true, fermer), 'le retour est consommé').toBe(true);
    expect(fermer, 'la roue se ferme — sinon le bouton retour ne fait plus rien').toHaveBeenCalledTimes(1);
  });

  it('roue fermée : la coquille recule, rien ne se ferme', () => {
    const fermer = vi.fn();
    expect(reponseAuRetour(false, fermer), 'la coquille garde son retour').toBe(false);
    expect(fermer).not.toHaveBeenCalled();
  });
});

describe('toucherDuVoile', () => {
  // 26/09/2026, surimpression : Échap, le retour d'Android ET le voile
  // ferment (§82 : jamais un seul chemin). Sans le garde du clic fantôme,
  // chaque rotation relâchée sur le voile refermait la roue.
  it('un toucher du voile ferme', () => {
    expect(toucherDuVoile(false, false)).toBe('fermer');
  });

  it('un toucher qui atteint un bouton ne ferme pas : le bouton sait quoi faire', () => {
    expect(toucherDuVoile(true, false)).toBe('rien');
  });

  it('le clic fantôme qui suit un glissé ne ferme pas la roue que le pouce vient d’ouvrir', () => {
    expect(toucherDuVoile(false, true)).toBe('rien');
    expect(toucherDuVoile(true, true)).toBe('rien');
  });
});

describe('freresARendreInertes et rendreInertes', () => {
  function monter() {
    document.body.innerHTML = `
      <div id="layout">
        <div id="cloche"><button>Cloche</button></div>
        <div id="page"><button>Ajouter</button></div>
        <div id="deja"></div>
        <div id="roue"></div>
      </div>`;
    const deja = document.getElementById('deja') as HTMLElement;
    deja.inert = true;
    return document.getElementById('roue') as HTMLElement;
  }

  it('rend inertes la cloche et la page, pas la roue', () => {
    const roue = monter();
    const freres = freresARendreInertes(roue);
    expect(freres.map((el) => el.id), 'les frères encore vivants').toEqual(['cloche', 'page']);
    const reveiller = rendreInertes(freres);
    expect((document.getElementById('page') as HTMLElement).inert, 'la page ne se lit plus').toBe(true);
    expect((document.getElementById('cloche') as HTMLElement).inert).toBe(true);
    expect(roue.inert, 'la roue reste lisible').not.toBe(true);
    reveiller();
    expect((document.getElementById('page') as HTMLElement).inert, 'la page revient à la fermeture').not.toBe(true);
    expect((document.getElementById('deja') as HTMLElement).inert, 'un élément déjà inerte le reste').toBe(true);
  });

  it('sans parent, rien à rendre inerte', () => {
    expect(freresARendreInertes(document.createElement('div'))).toEqual([]);
  });
});
