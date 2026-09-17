import { afterEach, describe, expect, it, vi } from 'vitest';
import { inscrireSurfaceVitree, lireSurfacesVitrees, masqueTexture } from './verreTexture';

const decoupe = { x: 20, y: 600, largeur: 700, hauteur: 100, rayon: 24 };
const PLEIN = 'linear-gradient(#000 0 0)';
const DISQUE = 'radial-gradient(circle closest-side, #000 98%, transparent 100%)';
// Coupe une liste CSS sur ses virgules de premier niveau : un dégradé
// radial porte lui-même des virgules entre ses parenthèses.
const listeCss = (valeur: string) => {
  const parts: string[] = [];
  let profondeur = 0;
  let courant = '';
  for (const ch of valeur) {
    if (ch === '(') profondeur += 1;
    if (ch === ')') profondeur -= 1;
    if (ch === ',' && profondeur === 0) { parts.push(courant.trim()); courant = ''; } else courant += ch;
  }
  parts.push(courant.trim());
  return parts;
};
const calques = (masque: ReturnType<typeof masqueTexture>) => {
  if (!masque) throw new Error('pas de masque');
  const images = listeCss(masque.image);
  const tailles = listeCss(masque.taille);
  const positions = listeCss(masque.position);
  return images.map((image, i) => ({ image, taille: tailles[i], position: positions[i] }));
};
const lireMasque = () => document.documentElement.style.getPropertyValue('--diapason-verre-masque');
const lirePositions = () => document.documentElement.style.getPropertyValue('--diapason-verre-position');

describe('verre — §5, la texture ne doit pas simuler une vitre opaque', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('est fait de dégradés, jamais d’une image à décoder', () => {
    // 17 sept. 2026 : un SVG en data-URI régénéré à chaque défilement
    // pâlissait les cartes le temps de son décodage.
    const masque = masqueTexture(1000, 800, [decoupe]);
    expect(masque).not.toBeNull();
    expect(masque!.image).not.toContain('url(');
    expect(masque!.image).not.toContain('data:');
  });

  it('conserve le quadrillage hors de la découpe arrondie : un plein qui soustrait, des trous qui s’ajoutent', () => {
    const masque = masqueTexture(1000, 800, [decoupe]);
    const c = calques(masque);
    expect(c[0], 'le calque plein est premier, plein écran').toEqual({ image: PLEIN, taille: '100% 100%', position: '0 0' });
    expect(masque!.composite.split(', ')[0]).toBe('subtract');
    expect(new Set(masque!.composite.split(', ').slice(1))).toEqual(new Set(['add']));
    expect(masque!.compositeWebkit.split(', ')[0]).toBe('source-out');
    // colonne (sans les coins), rangée (sans les coins), quatre disques
    expect(c[1]).toEqual({ image: PLEIN, taille: '652px 100px', position: '44px 600px' });
    expect(c[2]).toEqual({ image: PLEIN, taille: '700px 52px', position: '20px 624px' });
    expect(c.slice(3).map((x) => x.image)).toEqual([DISQUE, DISQUE, DISQUE, DISQUE]);
    expect(c.slice(3).map((x) => x.position)).toEqual(['20px 600px', '672px 600px', '672px 652px', '20px 652px']);
    expect(c[3].taille).toBe('48px 48px');
  });

  it('réunit les trous au lieu de refaire apparaître la grille à leur intersection', () => {
    const masque = masqueTexture(1000, 800, [decoupe, { ...decoupe, y: 550 }]);
    const c = calques(masque);
    expect(c).toHaveLength(1 + 2 * 6);
    expect(masque!.composite, 'jamais d’exclusion (xor) : deux trous qui se recouvrent restent un trou').not.toContain('exclude');
  });

  it('ne masque rien sans surface visible ou avec une mesure invalide', () => {
    expect(masqueTexture(1000, 800, [])).toBeNull();
    expect(masqueTexture(0, 800, [decoupe])).toBeNull();
    expect(masqueTexture(1000, 800, [{ ...decoupe, x: NaN }])).toBeNull();
    expect(masqueTexture(1000, 800, [{ ...decoupe, y: 900 }])).toBeNull();
  });

  it('borne les arrondis sur un très petit écran sans déplacer la surface', () => {
    const c = calques(masqueTexture(320, 740, [{ ...decoupe, x: -5, largeur: 30, rayon: 50 }]));
    expect(c[1], 'rayon borné à 15 : la colonne fait 30 − 2 × 15 = 0 → absente ; la rangée reste').toEqual({ image: PLEIN, taille: '30px 70px', position: '-5px 615px' });
    expect(c[2].taille, 'les disques font 2 × 15').toBe('30px 30px');
  });

  it('découpe une carte partiellement défilée sans arrondir artificiellement sa tranche coupée', () => {
    const limite = { x: 700, y: 40, largeur: 280, hauteur: 600 };
    const carte = { x: 720, y: 15, largeur: 240, hauteur: 60, rayon: 12, limite };
    const c = calques(masqueTexture(1000, 800, [carte]));
    // Coupée en haut par la fenêtre : la rangée monte jusqu'au bord (y = 40),
    // les deux coins du haut sont carrés, seuls les deux du bas sont ronds.
    expect(c[1]).toEqual({ image: PLEIN, taille: '216px 35px', position: '732px 40px' });
    expect(c[2]).toEqual({ image: PLEIN, taille: '240px 23px', position: '720px 40px' });
    expect(c.slice(3)).toHaveLength(2);
    expect(c.slice(3).map((x) => x.position)).toEqual(['936px 51px', '720px 51px']);
  });

  it('ne troue pas la texture quand la carte sort du panneau ou que sa fenêtre disparaît', () => {
    const carte = { ...decoupe, limite: { x: 0, y: 40, largeur: 1000, hauteur: 400 } };
    expect(masqueTexture(1000, 800, [carte])).toBeNull();
    expect(masqueTexture(1000, 800, [{ ...carte, y: 80, limite: { ...carte.limite, hauteur: 0 } }])).toBeNull();
    expect(masqueTexture(1000, 800, [{ ...carte, y: 80, limite: { ...carte.limite, x: NaN } }])).toBeNull();
  });

  it('réunit huit cartes et le compositeur sans collision entre les fenêtres de découpe', () => {
    const cartes = Array.from({ length: 8 }, (_, i) => ({
      x: 730, y: 50 + i * 70, largeur: 240, hauteur: 60, rayon: 12,
      limite: { x: 710, y: 40, largeur: 280, hauteur: 720 },
    }));
    const masque = masqueTexture(1000, 800, [decoupe, ...cartes]);
    expect(calques(masque)).toHaveLength(1 + 9 * 6);
  });

  it('suit les ancêtres et enlève le masque lorsque Discussion se ferme', () => {
    const observer = { observe: vi.fn(), disconnect: vi.fn() };
    vi.stubGlobal('ResizeObserver', class { observe = observer.observe; disconnect = observer.disconnect; });
    const parent = document.createElement('div');
    const panneau = document.createElement('div');
    parent.append(panneau);
    document.body.append(parent);
    let x = 20;
    vi.spyOn(panneau, 'getBoundingClientRect').mockImplementation(() => ({ left: x, top: 600, width: 700, height: 100 }) as DOMRect);
    const enlever = inscrireSurfaceVitree(panneau);
    try {
      expect(observer.observe).toHaveBeenCalledWith(parent);
      expect(lireSurfacesVitrees()[0].x).toBe(20);
      expect(lirePositions()).toContain('20px 600px');
      x = 90;
      window.dispatchEvent(new Event('resize'));
      expect(lireSurfacesVitrees()[0].x).toBe(90);
      expect(lirePositions()).toContain('90px 600px');
    } finally {
      enlever();
      parent.remove();
    }
    expect(observer.disconnect).toHaveBeenCalledOnce();
    expect(lireSurfacesVitrees()).toEqual([]);
    expect(lireMasque()).toBe('');
  });

  it('garde le suivi du panneau quand son menu se ferme', () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
    const panneau = document.createElement('div');
    const menu = document.createElement('div');
    document.body.append(panneau, menu);
    let x = 20;
    vi.spyOn(panneau, 'getBoundingClientRect').mockImplementation(() => ({ left: x, top: 600, width: 700, height: 100 }) as DOMRect);
    vi.spyOn(menu, 'getBoundingClientRect').mockReturnValue({ left: 30, top: 550, width: 260, height: 120 } as DOMRect);
    const enleverPanneau = inscrireSurfaceVitree(panneau);
    const enleverMenu = inscrireSurfaceVitree(menu);
    try {
      // jsdom ne calcule pas de rayon : un trou = colonne + rangée.
      const nbCalques = () => listeCss(lireMasque()).length;
      expect(nbCalques()).toBe(1 + 2 * 2);
      enleverMenu();
      expect(nbCalques()).toBe(1 + 2);
      x = 100;
      window.dispatchEvent(new Event('resize'));
      expect(lirePositions()).toContain('100px 600px');
    } finally {
      enleverMenu();
      enleverPanneau();
      panneau.remove();
      menu.remove();
    }
    expect(lireMasque()).toBe('');
  });

  it('suit le défilement réel du panneau et oublie ses cartes au démontage', () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
    const panneau = document.createElement('div');
    panneau.setAttribute('data-verre-defilement', '');
    const carte = document.createElement('div');
    panneau.append(carte);
    document.body.append(panneau);
    vi.spyOn(panneau, 'getBoundingClientRect').mockReturnValue({ left: 700, top: 40 } as DOMRect);
    Object.defineProperties(panneau, {
      clientWidth: { value: 280 }, clientHeight: { value: 600 }, clientLeft: { value: 1 },
    });
    let y = 80;
    vi.spyOn(carte, 'getBoundingClientRect').mockImplementation(() => ({ left: 720, top: y, width: 240, height: 60 }) as DOMRect);
    const enlever = inscrireSurfaceVitree(carte);
    try {
      expect(lireSurfacesVitrees()[0].limite).toEqual({ x: 701, y: 40, largeur: 280, hauteur: 600 });
      y = -50;
      panneau.dispatchEvent(new Event('scroll'));
      expect(lireMasque(), 'carte sortie du panneau : plus aucun trou, le masque est retiré').toBe('');
    } finally {
      enlever();
      panneau.remove();
    }
    expect(lireSurfacesVitrees()).toEqual([]);
  });
});
