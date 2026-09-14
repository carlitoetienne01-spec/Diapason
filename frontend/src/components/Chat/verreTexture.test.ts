import { afterEach, describe, expect, it, vi } from 'vitest';
import { inscrireSurfaceVitree, lireSurfacesVitrees, masqueTexture } from './verreTexture';

const decoupe = { x: 20, y: 600, largeur: 700, hauteur: 100, rayon: 24 };
const lireSvg = (masque: string) => decodeURIComponent(masque.slice('url("data:image/svg+xml,'.length, -2));

describe('verre — §5, la texture ne doit pas simuler une vitre opaque', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('conserve le quadrillage hors de la découpe arrondie', () => {
    const svg = lireSvg(masqueTexture(1000, 800, [decoupe]));
    expect(svg).toContain('viewBox="0 0 1000 800"');
    expect(svg).toContain('width="100%" height="100%" fill="white"');
    expect(svg).toContain('x="20" y="600" width="700" height="100" rx="24" fill="black"');
  });

  it('réunit les trous au lieu de refaire apparaître la grille à leur intersection', () => {
    const svg = lireSvg(masqueTexture(1000, 800, [decoupe, { ...decoupe, y: 550 }]));
    expect(svg.match(/fill="black"/g)).toHaveLength(2);
    expect(svg).toContain('<mask');
    expect(svg).not.toContain('evenodd');
  });

  it('ne masque rien sans surface visible ou avec une mesure invalide', () => {
    expect(masqueTexture(1000, 800, [])).toBe('none');
    expect(masqueTexture(0, 800, [decoupe])).toBe('none');
    expect(masqueTexture(1000, 800, [{ ...decoupe, x: NaN }])).toBe('none');
    expect(masqueTexture(1000, 800, [{ ...decoupe, y: 900 }])).toBe('none');
  });

  it('borne les arrondis sur un très petit écran sans déplacer la surface', () => {
    expect(lireSvg(masqueTexture(320, 740, [{ ...decoupe, x: -5, largeur: 30, rayon: 50 }]))).toContain('x="-5" y="600" width="30" height="100" rx="15"');
  });

  it('découpe une carte partiellement défilée sans arrondir artificiellement sa tranche coupée', () => {
    const limite = { x: 700, y: 40, largeur: 280, hauteur: 600 };
    const carte = { x: 720, y: 15, largeur: 240, hauteur: 60, rayon: 12, limite };
    const svg = lireSvg(masqueTexture(1000, 800, [carte]));
    expect(svg).toContain('clipPathUnits="userSpaceOnUse"');
    expect(svg).toContain('x="700" y="40" width="280" height="600"');
    expect(svg).toContain('x="720" y="15" width="240" height="60" rx="12" fill="black"');
    expect(svg).toContain('clip-path="url(#limite-0)"');
  });

  it('ne troue pas la texture quand la carte sort du panneau ou que sa fenêtre disparaît', () => {
    const carte = { ...decoupe, limite: { x: 0, y: 40, largeur: 1000, hauteur: 400 } };
    expect(masqueTexture(1000, 800, [carte])).toBe('none');
    expect(masqueTexture(1000, 800, [{ ...carte, y: 80, limite: { ...carte.limite, hauteur: 0 } }])).toBe('none');
    expect(masqueTexture(1000, 800, [{ ...carte, y: 80, limite: { ...carte.limite, x: NaN } }])).toBe('none');
  });

  it('réunit huit cartes et le compositeur sans collision entre les fenêtres de découpe', () => {
    const cartes = Array.from({ length: 8 }, (_, i) => ({
      x: 730, y: 50 + i * 70, largeur: 240, hauteur: 60, rayon: 12,
      limite: { x: 710, y: 40, largeur: 280, hauteur: 720 },
    }));
    const svg = lireSvg(masqueTexture(1000, 800, [decoupe, ...cartes]));
    expect(svg.match(/fill="black"/g)).toHaveLength(9);
    expect(new Set(svg.match(/id="limite-\d+"/g)).size).toBe(8);
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
      expect(lireSvg(document.documentElement.style.getPropertyValue('--diapason-decoupes-verre'))).toContain('x="20"');
      x = 90;
      window.dispatchEvent(new Event('resize'));
      expect(lireSurfacesVitrees()[0].x).toBe(90);
      expect(lireSvg(document.documentElement.style.getPropertyValue('--diapason-decoupes-verre'))).toContain('x="90"');
    } finally {
      enlever();
      parent.remove();
    }
    expect(observer.disconnect).toHaveBeenCalledOnce();
    expect(lireSurfacesVitrees()).toEqual([]);
    expect(document.documentElement.style.getPropertyValue('--diapason-decoupes-verre')).toBe('');
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
      const lire = () => lireSvg(document.documentElement.style.getPropertyValue('--diapason-decoupes-verre'));
      expect(lire().match(/fill="black"/g)).toHaveLength(2);
      enleverMenu();
      expect(lire().match(/fill="black"/g)).toHaveLength(1);
      x = 100;
      window.dispatchEvent(new Event('resize'));
      expect(lire()).toContain('x="100"');
    } finally {
      enleverMenu();
      enleverPanneau();
      panneau.remove();
      menu.remove();
    }
    expect(document.documentElement.style.getPropertyValue('--diapason-decoupes-verre')).toBe('');
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
      expect(document.documentElement.style.getPropertyValue('--diapason-decoupes-verre')).toBe('none');
    } finally {
      enlever();
      panneau.remove();
    }
    expect(lireSurfacesVitrees()).toEqual([]);
  });
});
