import { afterEach, describe, expect, it, vi } from 'vitest';
import { refractionDuBiseau, suivreReflet } from './cristal';

const vitre = { x: 100, y: 200, largeur: 600, hauteur: 120, rayon: 24 };

describe('cristal — §5, la réfraction agit sur le fond et reste bornée aux bords', () => {
  it('laisse le centre, le dehors et les coins découpés intacts', () => {
    for (const [x, y] of [[400, 260], [99, 260], [701, 260], [400, 199], [400, 321], [101, 201]]) {
      expect(refractionDuBiseau(x, y, vitre), `${x},${y} ne doit pas être déformé`).toBeNull();
    }
  });

  it('courbe les quatre tranches vers l’intérieur, symétriquement', () => {
    const gauche = refractionDuBiseau(108, 260, vitre)!;
    const droite = refractionDuBiseau(692, 260, vitre)!;
    const haut = refractionDuBiseau(400, 208, vitre)!;
    const bas = refractionDuBiseau(400, 312, vitre)!;
    expect(gauche.dx).toBeCloseTo(2.8);
    expect(droite.dx).toBeCloseTo(-gauche.dx);
    expect(haut.dy).toBeCloseTo(2.8);
    expect(bas.dy).toBeCloseTo(-haut.dy);
    expect(gauche.echelleY).toBe(1);
    expect(haut.echelleX).toBe(1);
  });

  it('n’introduit pas de saut aux limites du biseau', () => {
    expect(refractionDuBiseau(100, 260, vitre)).toBeNull();
    expect(refractionDuBiseau(116, 260, vitre)).toBeNull();
    expect(refractionDuBiseau(100.001, 260, vitre)!.dx).toBeLessThan(0.001);
    expect(refractionDuBiseau(115.999, 260, vitre)!.dx).toBeLessThan(0.001);
  });

  it('garde les déformations finies et discrètes sur une petite vitre arrondie', () => {
    const petite = { x: 0, y: 0, largeur: 28, hauteur: 24, rayon: 24 };
    for (let x = 0; x <= 28; x += 1) for (let y = 0; y <= 24; y += 1) {
      const d = refractionDuBiseau(x, y, petite);
      if (!d) continue;
      expect(Math.hypot(d.dx, d.dy)).toBeLessThanOrEqual(2.800001);
      expect(d.echelleX).toBeGreaterThanOrEqual(1);
      expect(d.echelleX).toBeLessThanOrEqual(1.14 + Number.EPSILON);
      expect(d.echelleY).toBeGreaterThanOrEqual(1);
      expect(d.echelleY).toBeLessThanOrEqual(1.14 + Number.EPSILON);
    }
  });
});

describe('cristal — le reflet suit la souris sans boucle permanente', () => {
  afterEach(() => vi.unstubAllGlobals());

  function banc() {
    const frames = new Map<number, FrameRequestCallback>();
    let sequence = 0;
    const demander = vi.fn((cb: FrameRequestCallback) => { frames.set(++sequence, cb); return sequence; });
    const annuler = vi.fn((id: number) => frames.delete(id));
    const media = { matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() };
    vi.stubGlobal('requestAnimationFrame', demander);
    vi.stubGlobal('cancelAnimationFrame', annuler);
    vi.stubGlobal('matchMedia', () => media);
    const surface = document.createElement('div');
    vi.spyOn(surface, 'getBoundingClientRect').mockReturnValue({ left: 10, top: 20, width: 200, height: 100 } as DOMRect);
    const mouvement = (x: number, y: number, type = 'mouse') => {
      const e = new MouseEvent('pointermove', { clientX: x, clientY: y });
      Object.defineProperty(e, 'pointerType', { value: type });
      surface.dispatchEvent(e);
    };
    const dessiner = () => {
      const copie = [...frames.values()];
      frames.clear();
      copie.forEach((cb) => cb(0));
    };
    return { surface, mouvement, dessiner, media, demander, annuler, frames };
  }

  it('regroupe les mouvements d’une image et utilise le dernier point', () => {
    const b = banc();
    const retirer = suivreReflet(b.surface);
    try {
      b.mouvement(50, 40);
      b.mouvement(160, 100);
      expect(b.demander).toHaveBeenCalledOnce();
      b.dessiner();
      expect(b.surface.style.getPropertyValue('--composer-reflet-x')).toBe('75.00%');
      expect(b.surface.style.getPropertyValue('--composer-reflet-y')).toBe('80.00%');
      expect(b.surface.dataset.reflet).toBe('actif');
      expect(b.frames.size).toBe(0);
    } finally { retirer(); }
    expect(b.surface.dataset.reflet).toBeUndefined();
    expect(b.surface.style.getPropertyValue('--composer-reflet-x')).toBe('');
    b.mouvement(10, 20);
    expect(b.demander).toHaveBeenCalledOnce();
  });

  it('annule le dessin en attente quand la souris sort', () => {
    const b = banc();
    const retirer = suivreReflet(b.surface);
    try {
      b.mouvement(50, 40);
      b.surface.dispatchEvent(new Event('pointerleave'));
      expect(b.annuler).toHaveBeenCalledOnce();
      b.dessiner();
      expect(b.surface.dataset.reflet).toBeUndefined();
    } finally { retirer(); }
  });

  it('reste immobile au toucher et lorsque les mouvements sont réduits', () => {
    const b = banc();
    const retirer = suivreReflet(b.surface);
    try {
      b.mouvement(50, 40, 'touch');
      b.media.matches = true;
      b.mouvement(50, 40);
      expect(b.demander).not.toHaveBeenCalled();
    } finally { retirer(); }
    expect(b.media.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function));
  });
});
