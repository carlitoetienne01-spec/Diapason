import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { fondDeLaCloche, placerMenu } from './ApprovalBell';

// Le menu de la cloche portait 340 × 500 px en dur sous un `top-full` sans
// mesure : dans une fenêtre basse, les boutons Approuver/Refuser partaient
// sous le bord (audit du mini-panneau, 16 sept. 2026). Le placement est un
// calcul pur : c'est lui qu'on vérifie, pas le composant.

describe('le placement du menu des approbations', () => {
  it('s’ouvre vers le bas, plafonné à 500 px, quand la fenêtre est haute', () => {
    const placement = placerMenu({ top: 8, bottom: 40 }, 900);
    expect(placement.haut, 'la place ne manque pas dessous').toBe(false);
    expect(placement.hauteurMax, 'le plafond de 500 px tient').toBe(500);
  });

  it('se borne à la place restante sous l’ancre dans une fenêtre basse', () => {
    const placement = placerMenu({ top: 8, bottom: 40 }, 380);
    expect(placement.haut, 'la cloche est en haut : rien à retourner').toBe(false);
    expect(placement.hauteurMax, '380 − 40 − 12 px de marge').toBe(328);
  });

  it('retourne vers le haut quand la place manque dessous et abonde dessus', () => {
    const placement = placerMenu({ top: 500, bottom: 532 }, 600);
    expect(placement.haut, 'moins de 160 px dessous, 488 dessus').toBe(true);
    expect(placement.hauteurMax, 'borné par la place au-dessus').toBe(488);
  });

  it('ne retourne pas vers le haut quand il y a encore moins de place dessus', () => {
    const placement = placerMenu({ top: 60, bottom: 92 }, 200);
    expect(placement.haut, '48 px dessus contre 96 dessous').toBe(false);
    expect(placement.hauteurMax, 'jamais sous le plancher de 160 px : mieux vaut défiler que disparaître').toBe(160);
  });
});

/**
 * 27/09/2026, contre-épreuve du chantier « soyeux » (constat 7) : depuis que
 * la page défile jusqu'en haut de l'écran au téléphone, le contenu passe sous
 * la cloche. Sans fond, son icône se fondait dans le « › » des Tâches, et
 * sur le voile d'une fenêtre modale elle ne se distinguait plus.
 */
describe('le fond de la cloche', () => {
  it('au téléphone, pose une capsule opaque et plate, quel que soit l’état', () => {
    for (const ouverte of [false, true]) {
      for (const enAttente of [0, 3]) {
        const fond = fondDeLaCloche({ ouverte, enAttente, mobile: true });
        expect(fond.background, `ouverte=${ouverte}, en attente=${enAttente} : jamais transparent`).not.toMatch(/transparent/);
        expect(fond.boxShadow, 'un filet, sans flou').toBe('inset 0 0 0 1px var(--color-border)');
      }
    }
    expect(fondDeLaCloche({ ouverte: false, enAttente: 0, mobile: true }).background, 'au repos : la surface').toBe(
      'var(--color-surface)',
    );
  });

  it('au Mac et au mini-panneau, ne change rien', () => {
    expect(fondDeLaCloche({ ouverte: false, enAttente: 0, mobile: false })).toEqual({ background: 'transparent' });
    expect(fondDeLaCloche({ ouverte: true, enAttente: 0, mobile: false })).toEqual({ background: 'var(--color-bg-tertiary)' });
    expect(fondDeLaCloche({ ouverte: false, enAttente: 2, mobile: false })).toEqual({
      background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
    });
  });

  it('le bouton prend son fond de cette fonction, selon estMobile', () => {
    const cloche = readFileSync(join(__dirname, 'ApprovalBell.tsx'), 'utf8');
    expect(cloche).toContain('...fondDeLaCloche({ ouverte: open, enAttente: count, mobile: estMobile }),');
  });
});
