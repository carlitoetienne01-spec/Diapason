import { describe, expect, it, vi } from 'vitest';

import { cibleEstUnBouton, freresARendreInertes, rendreInertes, reponseAuRetour, toucherDuVoile } from './fermetureRoue';

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

describe('cibleEstUnBouton', () => {
  // 27/09/2026, contre-épreuve « soyeux » (mutant G) : `closest('button')`
  // devenu `closest('.roue-element')` faisait fermer la roue par Liste et
  // Parler, et laissait vitest vert. Monté comme la roue : les actions de
  // l'en-tête, la capsule d'un nom, le vide de la zone.
  function monter() {
    document.body.innerHTML = `
      <div role="dialog" id="voile">
        <div class="roue-entete"><div class="roue-actions">
          <button id="liste" class="roue-action"><svg id="icone-liste"></svg>Liste</button>
          <button id="parler" class="roue-action">Parler</button>
        </div></div>
        <div class="roue-zone" id="zone"><ul><li class="roue-place">
          <button id="nom" class="roue-element"><span id="texte" class="roue-nom">Tâches</span></button>
        </li></ul></div>
      </div>
      <button id="x" class="roue-bouton">X</button>`;
  }
  const el = (id: string) => document.getElementById(id);

  it('une action de l’en-tête, son icône, le X et la capsule d’un nom sont des boutons : le voile ne ferme pas', () => {
    monter();
    for (const id of ['liste', 'icone-liste', 'parler', 'x', 'nom', 'texte']) {
      expect(cibleEstUnBouton(el(id)), `« ${id} » doit compter comme un bouton`).toBe(true);
    }
  });

  it('le vide de la zone et le voile lui-même ne sont pas des boutons : le voile ferme', () => {
    monter();
    for (const id of ['zone', 'voile']) {
      expect(cibleEstUnBouton(el(id)), `« ${id} » n’est pas un bouton`).toBe(false);
    }
    expect(cibleEstUnBouton(null)).toBe(false);
    expect(cibleEstUnBouton(window), 'une cible qui n’est pas un élément').toBe(false);
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
