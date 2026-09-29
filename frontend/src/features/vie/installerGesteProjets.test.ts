import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installerGesteProjets } from './installerGesteProjets';

let nettoyer: (() => void) | undefined;
beforeEach(() => vi.useFakeTimers());
afterEach(() => { nettoyer?.(); vi.useRealTimers(); vi.restoreAllMocks(); document.body.replaceChildren(); });
function banc(filtre = false) {
  const grille = document.createElement('div');
  grille.innerHTML = '<article data-projet-mobile="a"><button>Alpha</button></article><article data-projet-mobile="b"><button>Beta</button></article>';
  document.body.append(grille);
  const a = grille.children[0] as HTMLElement, b = grille.children[1] as HTMLElement;
  const o = { courant: () => ({ ids: ['a', 'b'], occupe: false, filtre }), choisir: vi.fn(), poserOrdre: vi.fn(), poserFantome: vi.fn(), taireClic: vi.fn(), ranger: vi.fn() };
  Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: () => b });
  vi.spyOn(b, 'getBoundingClientRect').mockReturnValue({ left: 200, right: 350, top: 0, bottom: 200 } as DOMRect);
  nettoyer = installerGesteProjets(grille, o);
  const toucher = (type: string, x = 50, y = 100) => {
    const e = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(e, 'touches', { value: type === 'touchend' || type === 'touchcancel' ? [] : [{ identifier: 1, clientX: x, clientY: y }] });
    a.dispatchEvent(e);
    return e;
  };
  return { ...o, toucher, grille };
}
describe('§82 — le vrai contrôleur tactile des projets', () => {
  it('un toucher court ouvre normalement, sans sélectionner ni écrire', () => {
    const b = banc(); b.toucher('touchstart'); vi.advanceTimersByTime(150); b.toucher('touchend'); vi.advanceTimersByTime(500);
    expect(b.choisir).not.toHaveBeenCalled(); expect(b.ranger).not.toHaveBeenCalled(); expect(b.taireClic).not.toHaveBeenCalled();
  });
  it('un défilement avant 400 ms reste natif', () => {
    const b = banc(); b.toucher('touchstart');
    expect(b.toucher('touchmove', 50, 120).defaultPrevented).toBe(false);
    vi.advanceTimersByTime(450); expect(b.choisir).not.toHaveBeenCalled();
  });
  it('un appui long sélectionne, puis déplace et enregistre une seule fois', () => {
    const b = banc(); b.toucher('touchstart'); vi.advanceTimersByTime(400);
    expect(b.choisir).toHaveBeenLastCalledWith('a');
    expect(b.toucher('touchmove', 250).defaultPrevented).toBe(true);
    vi.advanceTimersByTime(32); expect(b.poserOrdre).toHaveBeenCalledWith(['b', 'a']);
    b.toucher('touchend', 250); expect(b.ranger).toHaveBeenCalledExactlyOnceWith(['b', 'a']);
    expect(b.taireClic).toHaveBeenCalled();
  });
  it('une annulation Android ne publie pas le déplacement', () => {
    const b = banc(); b.toucher('touchstart'); vi.advanceTimersByTime(400); b.toucher('touchmove', 250); vi.advanceTimersByTime(32); b.toucher('touchcancel');
    expect(b.ranger).not.toHaveBeenCalled(); expect(b.poserOrdre).toHaveBeenLastCalledWith(null);
  });
  it('une recherche conserve les actions mais interdit un ordre partiel', () => {
    const b = banc(true); b.toucher('touchstart'); vi.advanceTimersByTime(400); b.toucher('touchmove', 250); vi.advanceTimersByTime(32); b.toucher('touchend');
    expect(b.choisir).toHaveBeenCalledWith('a'); expect(b.ranger).not.toHaveBeenCalled();
  });
  it('démonter pendant l’attente retire le minuteur et les écouteurs', () => {
    const b = banc(); b.toucher('touchstart'); nettoyer?.(); vi.advanceTimersByTime(500);
    expect(b.choisir).not.toHaveBeenCalled(); expect(b.ranger).not.toHaveBeenCalled();
  });
});
