import { APPUI_PROJET_MS, doigtDeplace, pasDefilementProjet, rangerProjet } from './gesteProjet';
export type FantomeCartable = { id: string; x: number; y: number; largeur: number };
export type PlacementCartable = { id: string; zone?: string };
export type OptionsGesteCartables = {
  attributCarte: string;
  attributActions: string;
  attributZone?: string;
  classer?: (ids: string[], id: string, cible: string | null, zone: string) => string[];
  courant: () => { ids: string[]; occupe: boolean; filtre: boolean };
  choisir: (id: string | null) => void;
  poserOrdre: (ids: string[] | null, placement?: PlacementCartable) => void;
  poserFantome: (p: FantomeCartable | null) => void;
  taireClic: (jusqua: number) => void;
  ranger: (ids: string[], placement: PlacementCartable) => void;
};

// 28/09/2026 : Notes employait encore le drag HTML, contrairement aux Projets.
// Un seul contrôleur garde le même seuil, la même réserve et les annulations.
export function installerGesteCartables(grille: HTMLElement, o: OptionsGesteCartables) {
  const selecteurCarte = `[${o.attributCarte}]`;
  const selecteurZone = o.attributZone ? `[${o.attributZone}]` : null;
  const lireZone = (element: Element): string | undefined => selecteurZone
    ? element.closest(selecteurZone)?.getAttribute(o.attributZone!) ?? undefined : undefined;
  const { choisir, poserOrdre, poserFantome } = o;
  let prise: { id: string; doigt: number; x: number; y: number; x0: number; y0: number; actif: boolean; bouge: boolean; largeur: number; ids: string[]; zone?: string; zoneOrigine?: string } | null = null;
  let dernierRectangle: DOMRect | null = null;
  let dernierFantome: FantomeCartable | null = null;
  let delai = 0;
  let image = 0;
  const arreter = () => {
    clearTimeout(delai);
    cancelAnimationFrame(image);
    prise = null;
    dernierRectangle = null;
    dernierFantome = null;
    poserFantome(null);
    poserOrdre(null);
  };
  const peindre = () => {
    const p = prise;
    if (!p?.actif || !p.bouge) return;
    const defileur = grille.closest<HTMLElement>('.overflow-y-auto');
    if (defileur) {
      const r = defileur.getBoundingClientRect();
      const avant = defileur.scrollTop;
      defileur.scrollTop += pasDefilementProjet(p.y, Math.max(0, r.top), Math.min(innerHeight, r.bottom));
      // Les cartes bougent aussi sous un doigt immobile au bord de la page.
      if (defileur.scrollTop !== avant) dernierRectangle = null;
    }
    if (dernierRectangle && (p.x < dernierRectangle.left || p.x > dernierRectangle.right || p.y < dernierRectangle.top || p.y > dernierRectangle.bottom)) dernierRectangle = null;
    const element = document.elementFromPoint(p.x, p.y);
    const carte = element?.closest<HTMLElement>(selecteurCarte);
    const zoneElement = selecteurZone ? element?.closest<HTMLElement>(selecteurZone) : null;
    const cible = carte ?? zoneElement;
    const cibleId = carte?.getAttribute(o.attributCarte) ?? null;
    const zone = cible ? lireZone(cible) : undefined;
    if (!dernierRectangle && cible && grille.contains(cible) && cibleId !== p.id && (carte || zone !== p.zone)) {
      if (carte) dernierRectangle = carte.getBoundingClientRect();
      const suivant = o.classer ? o.classer(p.ids, p.id, cibleId, zone ?? '') : rangerProjet(p.ids, p.id, cibleId ?? '');
      if (suivant.join('\u0000') !== p.ids.join('\u0000') || zone !== p.zone) {
        p.ids = suivant;
        p.zone = zone;
        poserOrdre(p.ids, { id: p.id, zone });
      }
    }
    if (!dernierFantome || dernierFantome.x !== p.x || dernierFantome.y !== p.y) {
      dernierFantome = { id: p.id, x: p.x, y: p.y, largeur: p.largeur };
      poserFantome(dernierFantome);
    }
    image = requestAnimationFrame(peindre);
  };
  const debut = (e: TouchEvent) => {
    if (e.touches.length !== 1 || o.courant().occupe) { arreter(); return; }
    const cible = e.target instanceof Element ? e.target : null;
    if (cible?.closest(`[${o.attributActions}]`)) return;
    const carte = cible?.closest<HTMLElement>(selecteurCarte);
    const t = e.touches[0];
    if (!carte || !t) return;
    const p = { id: carte.getAttribute(o.attributCarte)!, doigt: t.identifier, x: t.clientX, y: t.clientY, x0: t.clientX, y0: t.clientY, actif: false, bouge: false, largeur: carte.offsetWidth, ids: o.courant().ids, zone: lireZone(carte), zoneOrigine: lireZone(carte) };
    prise = p;
    delai = window.setTimeout(() => {
      if (prise !== p) return;
      p.actif = true;
      choisir(p.id);
      o.taireClic(performance.now() + 700);
    }, APPUI_PROJET_MS);
  };
  const mouvement = (e: TouchEvent) => {
    const p = prise;
    if (!p) return;
    if (e.touches.length !== 1) { arreter(); return; }
    const t = [...e.touches].find(t => t.identifier === p.doigt);
    if (!t) return;
    p.x = t.clientX;
    p.y = t.clientY;
    const bouge = doigtDeplace({ x: p.x0, y: p.y0 }, p);
    if (!p.actif && bouge) { arreter(); return; }
    if (!p.actif || o.courant().filtre) return;
    e.preventDefault();
    if (bouge && !p.bouge) {
      p.bouge = true;
      image = requestAnimationFrame(peindre);
    }
  };
  const fin = (e: TouchEvent) => {
    const p = prise;
    if (!p) return;
    if (p.actif) {
      o.taireClic(performance.now() + 700);
      if (e.cancelable) e.preventDefault();
    }
    const nouveau = p.ids;
    const enregistrer = e.type === 'touchend' && p.bouge && !o.courant().filtre && !o.courant().occupe && (nouveau.join('\u0000') !== o.courant().ids.join('\u0000') || p.zone !== p.zoneOrigine);
    arreter();
    if (enregistrer) o.ranger(nouveau, { id: p.id, zone: p.zone });
  };
  const dehors = (e: Event) => {
    if (e.target instanceof Node && !grille.contains(e.target)) choisir(null);
  };
  const clavier = (e: KeyboardEvent) => { if (e.key === 'Escape') { arreter(); choisir(null); } };
  grille.addEventListener('touchstart', debut, { passive: true });
  grille.addEventListener('touchmove', mouvement, { passive: false });
  grille.addEventListener('touchend', fin, { passive: false });
  grille.addEventListener('touchcancel', fin, { passive: false });
  document.addEventListener('pointerdown', dehors);
  document.addEventListener('keydown', clavier);
  window.addEventListener('blur', arreter);
  return () => {
    clearTimeout(delai);
    cancelAnimationFrame(image);
    prise = null;
    grille.removeEventListener('touchstart', debut);
    grille.removeEventListener('touchmove', mouvement);
    grille.removeEventListener('touchend', fin);
    grille.removeEventListener('touchcancel', fin);
    document.removeEventListener('pointerdown', dehors);
    document.removeEventListener('keydown', clavier);
    window.removeEventListener('blur', arreter);
  };
}
