import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installerGesteCartables } from './installerGesteCartables';
import { rangerNoteMobile } from './classementNotesMobile';

let nettoyer: (() => void) | undefined;
beforeEach(() => vi.useFakeTimers());
afterEach(() => { nettoyer?.(); vi.useRealTimers(); vi.restoreAllMocks(); document.body.replaceChildren(); });
function banc(filtre = false) {
  const grille = document.createElement('div');
  grille.innerHTML = '<section data-categorie-note="Travail"><article data-note-mobile="a"><button>Alpha</button><div data-actions-note><button>Modifier</button></div></article><article data-note-mobile="b"><button>Beta</button></article></section><section data-categorie-note="Personnel"><h2>Personnel</h2></section>';
  document.body.append(grille);
  const a = grille.querySelector('[data-note-mobile="a"]') as HTMLElement;
  let cible = grille.querySelector('[data-note-mobile="b"]') as HTMLElement;
  const notes = [{ id: 'a', category: 'Travail' }, { id: 'b', category: 'Travail' }];
  const o = {
    attributCarte: 'data-note-mobile', attributActions: 'data-actions-note', attributZone: 'data-categorie-note',
    courant: () => ({ ids: ['a', 'b'], occupe: false, filtre }),
    classer: (ids: string[], id: string, vers: string | null, zone: string) => rangerNoteMobile(notes, ids, id, vers, zone),
    choisir: vi.fn(), poserOrdre: vi.fn(), poserFantome: vi.fn(), taireClic: vi.fn(), ranger: vi.fn(),
  };
  Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: () => cible });
  vi.spyOn(cible, 'getBoundingClientRect').mockReturnValue({ left: 200, right: 350, top: 0, bottom: 200 } as DOMRect);
  nettoyer = installerGesteCartables(grille, o);
  const toucher = (type: string, x = 50, y = 100, depart: HTMLElement = a) => {
    const e = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(e, 'touches', { value: /end|cancel/.test(type) ? [] : [{ identifier: 1, clientX: x, clientY: y }] });
    depart.dispatchEvent(e); return e;
  };
  const prendre = () => { toucher('touchstart'); vi.advanceTimersByTime(400); };
  return { ...o, prendre, toucher, grille, autreCategorie: () => { cible = grille.querySelector('h2')!; } };
}
describe('§82 — contrôleur tactile des notes, sans boutons de déplacement', () => {
  it('un toucher court et un défilement ne sélectionnent pas', () => {
    const b = banc(); b.toucher('touchstart'); b.toucher('touchend');
    b.toucher('touchstart'); expect(b.toucher('touchmove', 50, 120).defaultPrevented).toBe(false);
    vi.advanceTimersByTime(500); expect(b.choisir).not.toHaveBeenCalled(); expect(b.ranger).not.toHaveBeenCalled();
  });
  it('400 ms révèle les actions sans ouvrir ni écrire', () => {
    const b = banc(); b.prendre(); b.toucher('touchend');
    expect(b.choisir).toHaveBeenCalledExactlyOnceWith('a'); expect(b.taireClic).toHaveBeenCalled(); expect(b.ranger).not.toHaveBeenCalled();
  });
  it('le déplacement publie une seule fois la nouvelle position dans sa catégorie', () => {
    const b = banc(); b.prendre(); expect(b.toucher('touchmove', 250).defaultPrevented).toBe(true);
    vi.advanceTimersByTime(48); b.toucher('touchend', 250);
    expect(b.ranger).toHaveBeenCalledExactlyOnceWith(['b', 'a'], { id: 'a', zone: 'Travail' });
  });
  it('un en-tête vide reçoit la note dans la catégorie choisie', () => {
    const b = banc(); b.autreCategorie(); b.prendre(); b.toucher('touchmove', 250, 350); vi.advanceTimersByTime(32); b.toucher('touchend', 250, 350);
    expect(b.ranger).toHaveBeenCalledExactlyOnceWith(['b', 'a'], { id: 'a', zone: 'Personnel' });
  });
  it('une annulation du système abandonne le classement entre catégories', () => {
    const b = banc(); b.autreCategorie(); b.prendre(); b.toucher('touchmove', 250, 350); vi.advanceTimersByTime(32); b.toucher('touchcancel');
    expect(b.ranger).not.toHaveBeenCalled(); expect(b.poserOrdre).toHaveBeenLastCalledWith(null);
  });
  it('le défilement au bord actualise la destination même si le doigt reste immobile', () => {
    const b = banc(); b.grille.classList.add('overflow-y-auto');
    vi.spyOn(b.grille, 'getBoundingClientRect').mockReturnValue({ top: 0, bottom: 110 } as DOMRect);
    b.prendre(); b.toucher('touchmove', 250); vi.advanceTimersByTime(16);
    b.autreCategorie(); vi.advanceTimersByTime(32); b.toucher('touchend', 250);
    expect(b.grille.scrollTop).toBeGreaterThan(0);
    expect(b.ranger).toHaveBeenCalledExactlyOnceWith(['b', 'a'], { id: 'a', zone: 'Personnel' });
  });
  it('une recherche permet la sélection sans enregistrer un ordre incomplet', () => {
    const b = banc(true); b.prendre(); b.toucher('touchmove', 250); vi.advanceTimersByTime(32); b.toucher('touchend');
    expect(b.choisir).toHaveBeenCalledWith('a'); expect(b.ranger).not.toHaveBeenCalled();
  });
  it('les boutons modifier et supprimer ne commencent aucun glissé', () => {
    const b = banc(); b.toucher('touchstart', 50, 100, b.grille.querySelector<HTMLElement>('[data-actions-note] button')!); vi.advanceTimersByTime(500);
    expect(b.choisir).not.toHaveBeenCalled(); expect(b.ranger).not.toHaveBeenCalled();
  });
});
