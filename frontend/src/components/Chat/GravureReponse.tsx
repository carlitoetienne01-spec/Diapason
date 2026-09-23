import { useCallback, useEffect, useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react';
import './TerminalDiscussion.css';

export function dernierTexteVisible(racine: HTMLElement): { noeud: Text; fin: number } | null {
  const parcours = document.createTreeWalker(racine, NodeFilter.SHOW_TEXT);
  // Partir de la fin : un tableau de 400 verbes ne doit pas être reparcouru
  // en entier à chaque fragment reçu pour placer un simple curseur.
  while (parcours.lastChild()) { /* dernier texte descendant */ }
  for (let noeud: Node | null = parcours.currentNode; noeud && noeud !== racine; noeud = parcours.previousNode()) {
    const texte = noeud.textContent?.trimEnd() ?? '';
    const parent = noeud.parentElement;
    if (!texte || !parent || parent.closest('button, [aria-hidden="true"], .katex-mathml, .visuel-discussion, [hidden]')) continue;
    return { noeud: noeud as Text, fin: texte.length };
  }
  return null;
}

export function GravureReponse({ children, texte, enDirect, contenu, arrivee }: {
  children: ReactNode;
  texte: string;
  enDirect: boolean;
  contenu: RefObject<HTMLDivElement | null>;
  arrivee?: number;
}) {
  const cadre = useRef<HTMLDivElement>(null);
  const laser = useRef<HTMLSpanElement>(null);
  const precedent = useRef('');
  const actif = useRef(false);
  const mesurer = useCallback(() => {
    if (!cadre.current || !laser.current || !contenu.current || !actif.current || document.hidden) return;
    const dernier = dernierTexteVisible(contenu.current);
    if (!dernier) { laser.current.hidden = true; return; }
    const plage = document.createRange();
    plage.setStart(dernier.noeud, Math.max(0, dernier.fin - 1));
    plage.setEnd(dernier.noeud, dernier.fin);
    const rects = plage.getClientRects();
    const rect = rects[rects.length - 1];
    const boite = cadre.current.getBoundingClientRect();
    if (!rect || !rect.height || rect.right > boite.right || rect.left < boite.left) {
      laser.current.hidden = true;
      return;
    }
    laser.current.style.transform = `translate(${Math.min(boite.width - 2, rect.right - boite.left)}px, ${rect.top - boite.top}px)`;
    laser.current.style.height = `${rect.height}px`;
    laser.current.hidden = false;
  }, [contenu]);

  useLayoutEffect(() => {
    const ajout = texte !== precedent.current && texte.length > precedent.current.length;
    precedent.current = texte;
    actif.current = ajout && (enDirect || (arrivee != null && Date.now() - arrivee < 1200));
    if (!actif.current) { if (laser.current) laser.current.hidden = true; return; }
    mesurer();
    // 22/09 : le premier fragment et la clôture peuvent partager un rendu.
    // Garder le faisceau 1,2 s après réception, même si le flux vient de
    // finir ; aucune réécriture ni attente imposée au texte.
    const timer = window.setTimeout(() => {
      actif.current = false;
      if (laser.current) laser.current.hidden = true;
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [texte, arrivee, mesurer]);

  useEffect(() => {
    const el = cadre.current;
    if (!enDirect || !el) return;
    const observateur = new ResizeObserver(mesurer);
    observateur.observe(el);
    el.addEventListener('scroll', mesurer, true);
    const visibilite = () => { if (document.hidden && laser.current) laser.current.hidden = true; };
    document.addEventListener('visibilitychange', visibilite);
    return () => {
      observateur.disconnect();
      el.removeEventListener('scroll', mesurer, true);
      document.removeEventListener('visibilitychange', visibilite);
    };
  }, [enDirect, mesurer]);

  return <div ref={cadre} className="gravure-reponse">
    {children}
    <span ref={laser} className="gravure-laser" hidden aria-hidden="true" />
  </div>;
}
