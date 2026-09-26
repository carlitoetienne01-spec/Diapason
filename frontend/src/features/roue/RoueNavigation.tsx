import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as KeyboardEventReact,
  type PointerEvent as PointerEventReact,
} from 'react';
import { useLocation, useNavigate } from 'react-router';
import {
  AudioLines,
  BriefcaseBusiness,
  CalendarRange,
  Compass,
  Database,
  Disc3,
  Gauge,
  LayoutDashboard,
  List,
  ListTodo,
  MessageSquare,
  MonitorSmartphone,
  NotebookPen,
  RefreshCw,
  Repeat2,
  Rocket,
  ScrollText,
  Settings,
  Smartphone,
  Trophy,
  Bot,
  Wallet,
  X,
  type LucideIcon,
} from 'lucide-react';

import { useTranslation } from '../../i18n/useTranslation';
import { demanderAuTelephone, pontNatif } from '../../lib/natif';
import { useAppStore } from '../../lib/store';
import { openTalkToDiapason } from '../../components/TalkToDiapasonHost';
import {
  chargeBordRoue,
  cibleAimantation,
  commenceDansLaBande,
  decisionDuBord,
  dureeAimantation,
  geometrieRoue,
  indexAllume,
  issueDuRelache,
  placerElement,
  rotationAuTemps,
  rotationDuGlisse,
  TOUCHER_PX,
  vitesseDuGlisse,
  type Cote,
  type Geometrie,
} from './geometrieRoue';
import { clavierOuvert, estUneSaisie, suivreHauteurMax } from './clavier';
import { freresARendreInertes, rendreInertes, reponseAuRetour } from './fermetureRoue';
import { annoncerLeMenuDeLApp, OUVRIR_MENU_APP } from './menuDeLApp';
import { PAGES_ROUE, indexDeLaPage } from './pagesRoue';
import './roue.css';

/** L'icône de chaque page — celles de la barre latérale du bureau. */
const ICONES: Record<string, LucideIcon> = {
  '/': MessageSquare,
  '/vie/dashboard': LayoutDashboard,
  '/vie/planner': CalendarRange,
  '/vie/tasks': ListTodo,
  '/vie/projects': BriefcaseBusiness,
  '/vie/finances': Wallet,
  '/vie/habits': Repeat2,
  '/vie/notes': NotebookPen,
  '/vie/year-review': Trophy,
  '/settings': Settings,
  '/devices': MonitorSmartphone,
  '/get-started': Rocket,
  '/data-sources': Database,
  '/agents': Bot,
  '/vie/sync': RefreshCw,
  '/dashboard': Gauge,
  '/logs': ScrollText,
};

/** La vue choisie (roue ou liste) : un confort de CE téléphone, rien de plus. */
const CLE_MODE = 'diapason-roue-mode';

function lireMode(): 'roue' | 'liste' {
  try {
    return localStorage.getItem(CLE_MODE) === 'liste' ? 'liste' : 'roue';
  } catch {
    return 'roue';
  }
}

function mouvementReduit(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/** Un geste du pouce en cours, quel que soit l'élément qui le reçoit. */
type Geste = {
  id: number;
  x0: number;
  y0: number;
  /** Rotation au moment où le pouce a commencé à tourner la roue. */
  depart: number;
  /** Le pouce a-t-il bougé au-delà d'un toucher ? */
  tourne: boolean;
  /** Geste continu : posé au bord ou sur le bouton, glissé, relâché. */
  continu: boolean;
  deplacement: number;
  echantillons: { t: number; y: number }[];
};

/**
 * La roue du téléphone : un bouton rond et un glissé depuis le bord ouvrent
 * l'écran « Aller à », où toutes les pages sont posées sur un arc.
 *
 * 26/09/2026, chantier de la fluidité (lot 3) : la barre latérale du bureau
 * devenait au téléphone un tiroir de 260 px sur un voile — deux touchers,
 * une liste à parcourir des yeux, et le tiroir à refermer. Monté seulement
 * sous `estMobile` (Layout.tsx) ; le bureau et le mini-panneau n'en ont rien.
 *
 * §82 : chaque page reste atteignable par un simple toucher (la vue
 * « Liste »), au clavier (flèches, Entrée, Échap) et à la voix, qui passe
 * par le verbe `naviguer` du maillage sans rien savoir de la roue.
 */
export function RoueNavigation() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const cote: Cote = useAppStore((s) => (s.settings.roueAGauche ? 'gauche' : 'droite'));

  const [ouverte, setOuverte] = useState(false);
  const [mode, setMode] = useState<'roue' | 'liste'>(lireMode);
  const [allume, setAllume] = useState(0);
  // Le bouton « Menu de l'app » : seulement quand la coquille a répondu
  // qu'elle sait l'ouvrir (menuDeLApp.ts).
  const [menuApp, setMenuApp] = useState(false);

  const racineRef = useRef<HTMLDivElement>(null);
  const zoneRef = useRef<HTMLDivElement>(null);
  const boutonRef = useRef<HTMLButtonElement>(null);
  const arcRef = useRef<SVGCircleElement>(null);
  const repereRef = useRef<SVGPathElement>(null);
  const placesRef = useRef<(HTMLLIElement | null)[]>([]);
  const pastillesRef = useRef<(HTMLSpanElement | null)[]>([]);
  const elementsRef = useRef<(HTMLButtonElement | null)[]>([]);
  const lignesRef = useRef<(HTMLButtonElement | null)[]>([]);

  const rotationRef = useRef(0);
  const allumeRef = useRef(0);
  const geoRef = useRef<Geometrie | null>(null);
  const animationRef = useRef<number | null>(null);
  const gesteRef = useRef<Geste | null>(null);
  /**
   * Le clic qui suit un glissé n'est pas un toucher : ignoré s'il arrive
   * dans les 300 ms du relâché. Un drapeau sans échéance (26/09/2026, banc)
   * survivait au glissé depuis le bord — aucun clic ne le suit — et mangeait
   * le toucher suivant du bouton : la roue ne s'ouvrait plus.
   */
  const ignorerClicJusquaRef = useRef(0);
  const ignorerLeProchainClic = () => {
    ignorerClicJusquaRef.current = performance.now() + 300;
  };
  const clicAIgnorer = () => {
    const oui = performance.now() < ignorerClicJusquaRef.current;
    ignorerClicJusquaRef.current = 0;
    return oui;
  };
  const ouverteRef = useRef(false);
  ouverteRef.current = ouverte;
  const n = PAGES_ROUE.length;

  /** Écrire la rotation dans le document : transform et opacity seulement. */
  const appliquer = useCallback(() => {
    const g = geoRef.current;
    const rotation = rotationRef.current;
    if (g) {
      for (let i = 0; i < n; i += 1) {
        const place = placesRef.current[i];
        if (!place) continue;
        const p = placerElement(i, rotation, g);
        // La pastille (40 px, 6 px du bord de la capsule) tombe sur l'arc.
        const tx = g.cote === 'droite' ? `${p.x + 26}px` : `${p.x - 26}px`;
        place.style.transform =
          g.cote === 'droite'
            ? `translate3d(${tx}, ${p.y}px, 0) translate(-100%, -50%)`
            : `translate3d(${tx}, ${p.y}px, 0) translateY(-50%)`;
        place.style.opacity = String(p.opacite);
        place.style.pointerEvents = p.visible ? 'auto' : 'none';
        const pastille = pastillesRef.current[i];
        if (pastille) pastille.style.transform = `scale(${p.echelle})`;
      }
    }
    const index = indexAllume(rotation, n);
    if (index !== allumeRef.current) {
      allumeRef.current = index;
      setAllume(index);
    }
  }, [n]);

  const arreterAnimation = () => {
    if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
    animationRef.current = null;
  };

  /** Aimanter la roue sur `cible`, puis `ensuite` (ouvrir une page). */
  const animerVers = useCallback(
    (cible: number, ensuite?: () => void) => {
      arreterAnimation();
      const depuis = rotationRef.current;
      const duree = dureeAimantation(depuis, cible, mouvementReduit());
      if (duree === 0) {
        rotationRef.current = cible;
        appliquer();
        ensuite?.();
        return;
      }
      const debut = performance.now();
      const pas = (maintenant: number) => {
        rotationRef.current = rotationAuTemps(depuis, cible, maintenant - debut, duree);
        appliquer();
        if (maintenant - debut < duree) {
          animationRef.current = requestAnimationFrame(pas);
        } else {
          animationRef.current = null;
          ensuite?.();
        }
      };
      animationRef.current = requestAnimationFrame(pas);
    },
    [appliquer],
  );

  const ouvrir = useCallback(() => {
    arreterAnimation();
    const index = indexDeLaPage(pathname);
    rotationRef.current = index;
    allumeRef.current = index;
    setAllume(index);
    setOuverte(true);
  }, [pathname]);

  const fermer = useCallback(() => {
    arreterAnimation();
    gesteRef.current = null;
    setOuverte(false);
  }, []);

  /** Fermer et rendre le focus au bouton : Échap et le retour d'Android. */
  const fermerEtRendreLeFocus = useCallback(() => {
    fermer();
    boutonRef.current?.focus({ preventScroll: true });
  }, [fermer]);

  const ouvrirPage = useCallback(
    (index: number) => {
      const chemin = PAGES_ROUE[index]?.chemin;
      fermer();
      if (chemin && chemin !== pathname) navigate(chemin);
      // Le focus revient au bouton : la page suivante le trouve là où il
      // était, pas sur un élément devenu invisible.
      boutonRef.current?.focus({ preventScroll: true });
    },
    [fermer, navigate, pathname],
  );

  // La géométrie suit la taille de la zone ; mesurée avant la peinture pour
  // que la roue n'apparaisse jamais en tas au coin de l'écran.
  useLayoutEffect(() => {
    const zone = zoneRef.current;
    if (!ouverte || mode !== 'roue' || !zone) return undefined;
    const mesurer = () => {
      const r = zone.getBoundingClientRect();
      // La place du bouton flottant, en bas : aucun élément ne passe dessous.
      const g = geometrieRoue({ largeur: r.width, hauteur: r.height, cote, haut: 0, bas: r.height - 68 });
      geoRef.current = g;
      const cx = g.cote === 'droite' ? g.centreX : g.largeur - g.centreX;
      arcRef.current?.setAttribute('cx', String(cx));
      arcRef.current?.setAttribute('cy', String(g.centreY));
      arcRef.current?.setAttribute('r', String(g.rayon));
      // Le repère : un chevron entre la pastille allumée et le bord.
      const rx = g.cote === 'droite' ? g.xAllume + 44 : g.xAllume - 44;
      const s = g.cote === 'droite' ? 1 : -1;
      repereRef.current?.setAttribute(
        'd',
        `M ${rx + 6 * s} ${g.centreY - 7} L ${rx} ${g.centreY} L ${rx + 6 * s} ${g.centreY + 7}`,
      );
      for (const el of elementsRef.current) {
        const nom = el?.querySelector<HTMLElement>('.roue-nom');
        // Le nom le plus long garde la place entre la pastille et le bord.
        if (nom) nom.style.maxWidth = `${Math.max(80, (g.cote === 'droite' ? g.xAllume : g.largeur - g.xAllume) - 60)}px`;
      }
      appliquer();
    };
    mesurer();
    const observateur = new ResizeObserver(mesurer);
    observateur.observe(zone);
    return () => observateur.disconnect();
  }, [ouverte, mode, cote, appliquer]);

  // Le focus suit l'élément allumé, et l'écran s'annonce à l'ouverture.
  useEffect(() => {
    if (!ouverte) return;
    const cible = mode === 'roue' ? elementsRef.current[allumeRef.current] : lignesRef.current[allumeRef.current];
    cible?.focus({ preventScroll: mode === 'roue' });
    // Seulement à l'ouverture et au changement de vue : les flèches
    // déplacent le focus elles-mêmes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ouverte, mode]);

  // La coquille retire le bas de ce bord aux gestes d'Android (verbe
  // `bordRoue`) : sans quoi, en navigation par gestes, le glissé depuis le
  // bord est un « retour » du système et n'arrive jamais ici. Une coquille
  // ancienne répond `verbeInconnu` : le bouton reste, rien ne casse.
  useEffect(() => {
    if (!pontNatif) return;
    void demanderAuTelephone('bordRoue', chargeBordRoue(cote)).catch(() => {});
  }, [cote]);

  // La coquille retire sa barre native de 40 px quand la page porte le
  // menu de l'app (lot 4, 26/09/2026) ; le bouton n'apparaît qu'après son
  // `ok`, sans quoi il n'ouvrirait rien.
  useEffect(() => {
    if (!pontNatif) return;
    let vivant = true;
    void annoncerLeMenuDeLApp((verbe, donnees) => demanderAuTelephone(verbe, donnees)).then((ok) => {
      if (vivant) setMenuApp(ok);
    });
    return () => {
      vivant = false;
    };
  }, []);

  // Roue ouverte, la page dessous est inerte. `aria-modal` seul ne suffisait
  // pas : au banc (arbre d'accessibilité de Chromium, 26/09/2026), 44
  // boutons de la page des Tâches et la cloche restaient exposés sous
  // l'écran « Aller à », et un lecteur d'écran y passait en balayant.
  useEffect(() => {
    const moi = racineRef.current;
    if (!ouverte || !moi) return undefined;
    return rendreInertes(freresARendreInertes(moi));
  }, [ouverte]);

  // Le bouton retour d'Android ferme d'abord la roue (verbe `retour`).
  useEffect(() => {
    if (!ouverte || !pontNatif) return undefined;
    return pontNatif.surRetour(() => reponseAuRetour(ouverteRef.current, fermerEtRendreLeFocus));
  }, [ouverte, fermerEtRendreLeFocus]);

  // Clavier ouvert, le bouton et sa bande se retirent (clavier.ts, index.css).
  useEffect(() => {
    const racine = document.documentElement;
    const maxima = new Map<number, number>();
    const evaluer = () => {
      const hauteur = Math.min(window.innerHeight, window.visualViewport?.height ?? window.innerHeight);
      const hauteurMax = suivreHauteurMax(maxima, window.innerWidth, hauteur);
      const ouvert = clavierOuvert({ hauteur, hauteurMax, saisie: estUneSaisie(document.activeElement) });
      if (ouvert) racine.setAttribute('data-clavier-ouvert', '');
      else racine.removeAttribute('data-clavier-ouvert');
    };
    // Le focus sort avant d'entrer ailleurs : on lit après la bascule.
    const plusTard = () => window.setTimeout(evaluer, 0);
    evaluer();
    window.addEventListener('resize', evaluer);
    window.visualViewport?.addEventListener('resize', evaluer);
    document.addEventListener('focusin', evaluer);
    document.addEventListener('focusout', plusTard);
    return () => {
      window.removeEventListener('resize', evaluer);
      window.visualViewport?.removeEventListener('resize', evaluer);
      document.removeEventListener('focusin', evaluer);
      document.removeEventListener('focusout', plusTard);
      racine.removeAttribute('data-clavier-ouvert');
    };
  }, []);

  // Une navigation venue d'ailleurs (le maillage, la voix) ferme la roue.
  const cheminOuvert = useRef(pathname);
  useEffect(() => {
    if (cheminOuvert.current !== pathname && ouverteRef.current) fermer();
    cheminOuvert.current = pathname;
  }, [pathname, fermer]);

  useEffect(() => () => arreterAnimation(), []);

  // ── Le pouce ───────────────────────────────────────────────────────
  const commencer = (e: { pointerId: number; clientX: number; clientY: number }, continu: boolean) => {
    arreterAnimation();
    gesteRef.current = {
      id: e.pointerId,
      x0: e.clientX,
      y0: e.clientY,
      depart: rotationRef.current,
      tourne: false,
      continu,
      deplacement: 0,
      echantillons: [{ t: performance.now(), y: e.clientY }],
    };
  };

  const suivre = (e: { pointerId: number; clientY: number }) => {
    const geste = gesteRef.current;
    if (!geste || geste.id !== e.pointerId) return;
    const dy = e.clientY - geste.y0;
    geste.deplacement = Math.max(geste.deplacement, Math.abs(dy));
    if (!geste.tourne && Math.abs(dy) < TOUCHER_PX) return;
    geste.tourne = true;
    geste.echantillons.push({ t: performance.now(), y: e.clientY });
    if (geste.echantillons.length > 12) geste.echantillons.shift();
    rotationRef.current = rotationDuGlisse(geste.depart, dy, n);
    appliquer();
  };

  const relacher = (e: { pointerId: number }) => {
    const geste = gesteRef.current;
    if (!geste || geste.id !== e.pointerId) return;
    gesteRef.current = null;
    if (!geste.tourne) return;
    ignorerLeProchainClic();
    const cible = cibleAimantation(rotationRef.current, vitesseDuGlisse(geste.echantillons), n, mouvementReduit());
    const issue = issueDuRelache({ continu: geste.continu, deplacementPx: geste.deplacement });
    animerVers(cible, issue === 'ouvrir' ? () => ouvrirPage(cible) : undefined);
  };

  // Dans la roue ouverte : tourner ; le toucher d'un élément est un clic.
  const surZoneBas = (e: PointerEventReact<HTMLDivElement>) => {
    if (mode !== 'roue') return;
    commencer(e, false);
  };
  const surZoneMouvement = (e: PointerEventReact<HTMLDivElement>) => {
    const geste = gesteRef.current;
    if (!geste || geste.continu) return;
    const avant = geste.tourne;
    suivre(e);
    // Capturé dès qu'il tourne : le pouce peut sortir d'un élément sans le
    // perdre ; pas avant, sinon le clic d'un simple toucher n'arrive plus.
    if (!avant && gesteRef.current?.tourne) zoneRef.current?.setPointerCapture(e.pointerId);
  };
  const surZoneHaut = (e: PointerEventReact<HTMLDivElement>) => {
    if (gesteRef.current?.continu) return;
    relacher(e);
  };

  const toucherElement = (index: number) => {
    if (clicAIgnorer()) return;
    if (index === allumeRef.current) ouvrirPage(index);
    else animerVers(index);
  };

  // Le bouton : un toucher ouvre ; posé puis glissé, c'est le geste continu.
  const boutonGeste = useRef<{ id: number; x: number; y: number; continu: boolean } | null>(null);
  const surBoutonBas = (e: PointerEventReact<HTMLButtonElement>) => {
    if (ouverteRef.current) return;
    boutonGeste.current = { id: e.pointerId, x: e.clientX, y: e.clientY, continu: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const surBoutonMouvement = (e: PointerEventReact<HTMLButtonElement>) => {
    const b = boutonGeste.current;
    if (!b || b.id !== e.pointerId) return;
    if (!b.continu && Math.abs(e.clientY - b.y) >= TOUCHER_PX) {
      b.continu = true;
      ouvrir();
      commencer({ pointerId: e.pointerId, clientX: b.x, clientY: b.y }, true);
    }
    if (b.continu) suivre(e);
  };
  const surBoutonHaut = (e: PointerEventReact<HTMLButtonElement>) => {
    const b = boutonGeste.current;
    if (!b || b.id !== e.pointerId) return;
    if (b.continu) {
      relacher(e);
      ignorerLeProchainClic();
    }
    boutonGeste.current = null;
  };
  const surBoutonClic = () => {
    if (clicAIgnorer()) return;
    if (ouverteRef.current) fermer();
    else ouvrir();
  };

  // Le glissé depuis le bord : glisser vers l'intérieur ouvre, puis tourne.
  // Écouté sur la fenêtre, en PASSIF, sans rien poser sur la page
  // (geometrieRoue.ts, `decisionDuBord`) : un départ vertical fait défiler
  // la page. Des événements tactiles, pas de pointeur : dès que le navigateur
  // prend le glissé pour un défilement, il annule le pointeur
  // (`pointercancel` après 4 mouvements au banc du 26/09/2026) mais continue
  // d'envoyer chaque `touchmove` — 25 sur 28, et la page ne défile pas, le
  // geste étant parti à l'horizontale.
  const bordGeste = useRef<{ id: number; x: number; y: number; ouvert: boolean } | null>(null);
  const suiteDuBord = useRef({ ouvrir, commencer, suivre, relacher, cote });
  suiteDuBord.current = { ouvrir, commencer, suivre, relacher, cote };
  useEffect(() => {
    const doigt = (e: TouchEvent, id: number) => [...e.changedTouches].find((t) => t.identifier === id);
    const debut = (e: TouchEvent) => {
      const t = e.changedTouches[0];
      if (ouverteRef.current || e.touches.length !== 1 || !t) return;
      const { cote: c } = suiteDuBord.current;
      if (!commenceDansLaBande(t.clientX, t.clientY, window.innerWidth, window.innerHeight, c)) return;
      bordGeste.current = { id: t.identifier, x: t.clientX, y: t.clientY, ouvert: false };
    };
    const mouvement = (e: TouchEvent) => {
      const b = bordGeste.current;
      const t = b && doigt(e, b.id);
      if (!b || !t) return;
      const suite = suiteDuBord.current;
      if (b.ouvert) {
        suite.suivre({ pointerId: b.id, clientY: t.clientY });
        return;
      }
      const decision = decisionDuBord(t.clientX - b.x, t.clientY - b.y, suite.cote);
      if (decision === 'laisser') {
        bordGeste.current = null;
      } else if (decision === 'ouvrir') {
        b.ouvert = true;
        suite.ouvrir();
        // La rotation part d'ICI : le chemin horizontal ne tourne rien.
        suite.commencer({ pointerId: b.id, clientX: t.clientX, clientY: t.clientY }, true);
      }
    };
    const fin = (e: TouchEvent) => {
      const b = bordGeste.current;
      if (!b || !doigt(e, b.id)) return;
      bordGeste.current = null;
      // Un glissé repris par le système (touchcancel) ne choisit rien : la
      // roue reste ouverte, rien ne s'ouvre à la place du pouce.
      if (b.ouvert && e.type === 'touchend') suiteDuBord.current.relacher({ pointerId: b.id });
      else if (b.ouvert) gesteRef.current = null;
    };
    const options = { passive: true } as const;
    window.addEventListener('touchstart', debut, options);
    window.addEventListener('touchmove', mouvement, options);
    window.addEventListener('touchend', fin, options);
    window.addEventListener('touchcancel', fin, options);
    return () => {
      window.removeEventListener('touchstart', debut);
      window.removeEventListener('touchmove', mouvement);
      window.removeEventListener('touchend', fin);
      window.removeEventListener('touchcancel', fin);
    };
  }, []);

  // ── Le clavier ─────────────────────────────────────────────────────
  const surTouche = (e: KeyboardEventReact<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      fermerEtRendreLeFocus();
      return;
    }
    if (mode !== 'roue') return;
    const actuel = allumeRef.current;
    const sauts: Record<string, number> = {
      ArrowUp: actuel - 1,
      ArrowLeft: actuel - 1,
      ArrowDown: actuel + 1,
      ArrowRight: actuel + 1,
      PageUp: actuel - 5,
      PageDown: actuel + 5,
      Home: 0,
      End: n - 1,
    };
    if (!(e.key in sauts)) return;
    e.preventDefault();
    const cible = Math.min(n - 1, Math.max(0, sauts[e.key]));
    animerVers(cible);
    elementsRef.current[cible]?.focus({ preventScroll: true });
  };

  const basculerMode = () => {
    const suivant = mode === 'roue' ? 'liste' : 'roue';
    setMode(suivant);
    try {
      localStorage.setItem(CLE_MODE, suivant);
    } catch {
      // Stockage refusé : la vue reste celle de cette ouverture.
    }
  };

  const nomAllume = t(PAGES_ROUE[allume].cle);
  const courant = indexDeLaPage(pathname);

  return (
    <div ref={racineRef} data-roue="" style={{ display: 'contents' }}>
      <div
        className="roue-ecran"
        data-ouverte={ouverte ? '' : undefined}
        role="dialog"
        aria-modal="true"
        aria-labelledby="roue-titre"
        inert={!ouverte}
        onKeyDown={surTouche}
      >
        <div className="roue-entete">
          <h2 id="roue-titre" className="roue-titre">
            {t('roue.titre')}
          </h2>
          <p className="roue-aide">{mode === 'roue' ? t('roue.aide') : t('roue.aideListe')}</p>
          <div className="roue-actions">
            <button type="button" className="roue-action" onClick={basculerMode} aria-pressed={mode === 'liste'}>
              {mode === 'roue' ? <List size={16} aria-hidden="true" /> : <Disc3 size={16} aria-hidden="true" />}
              {mode === 'roue' ? t('roue.voirListe') : t('roue.voirRoue')}
            </button>
            <button
              type="button"
              className="roue-action"
              onClick={() => {
                fermer();
                openTalkToDiapason();
              }}
            >
              <AudioLines size={16} aria-hidden="true" />
              {t('chat.talk.navLabel')}
            </button>
            {menuApp && (
              <button
                type="button"
                className="roue-action"
                onClick={() => {
                  fermer();
                  void demanderAuTelephone('menuApp', OUVRIR_MENU_APP).catch(() => {});
                }}
              >
                <Smartphone size={16} aria-hidden="true" />
                {t('roue.menuApp')}
              </button>
            )}
          </div>
        </div>

        {mode === 'roue' ? (
          <div
            ref={zoneRef}
            className="roue-zone"
            onPointerDown={surZoneBas}
            onPointerMove={surZoneMouvement}
            onPointerUp={surZoneHaut}
            onPointerCancel={surZoneHaut}
          >
            <svg className="roue-arc" aria-hidden="true">
              <circle ref={arcRef} fill="none" stroke="var(--color-border)" strokeWidth="1" />
              <path
                ref={repereRef}
                fill="none"
                stroke="var(--roue-allume)"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <ul className="roue-liste" aria-label={t('roue.pages')}>
              {PAGES_ROUE.map((page, i) => {
                const Icone = ICONES[page.chemin] ?? Compass;
                return (
                  <li
                    key={page.chemin}
                    ref={(el) => {
                      placesRef.current[i] = el;
                    }}
                    className="roue-place"
                    data-cote={cote}
                  >
                    <button
                      type="button"
                      ref={(el) => {
                        elementsRef.current[i] = el;
                      }}
                      className="roue-element"
                      data-allume={i === allume ? '' : undefined}
                      data-cible-libre=""
                      tabIndex={i === allume ? 0 : -1}
                      aria-current={i === courant ? 'page' : undefined}
                      onClick={() => toucherElement(i)}
                    >
                      <span className="roue-nom">{t(page.cle)}</span>
                      <span
                        className="roue-pastille"
                        ref={(el) => {
                          pastillesRef.current[i] = el;
                        }}
                      >
                        <Icone size={18} aria-hidden="true" />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {/* L'élément allumé s'annonce : « Tâches, 4 sur 17. Toucher pour ouvrir. » */}
            <p className="sr-only" aria-live="polite">
              {ouverte ? t('roue.annonce', { nom: nomAllume, rang: allume + 1, total: n }) : ''}
            </p>
          </div>
        ) : (
          <ul className="roue-simple" aria-label={t('roue.pages')}>
            {PAGES_ROUE.map((page, i) => {
              const Icone = ICONES[page.chemin] ?? Compass;
              return (
                <li key={page.chemin}>
                  <button
                    type="button"
                    ref={(el) => {
                      lignesRef.current[i] = el;
                    }}
                    className="roue-ligne"
                    aria-current={i === courant ? 'page' : undefined}
                    onClick={() => ouvrirPage(i)}
                  >
                    <Icone size={18} aria-hidden="true" />
                    {t(page.cle)}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <button
        ref={boutonRef}
        type="button"
        className="roue-bouton"
        data-cote={cote}
        data-cible-libre=""
        aria-label={ouverte ? t('roue.fermer') : t('roue.ouvrir')}
        aria-expanded={ouverte}
        title={ouverte ? t('roue.fermer') : t('roue.ouvrir')}
        onPointerDown={surBoutonBas}
        onPointerMove={surBoutonMouvement}
        onPointerUp={surBoutonHaut}
        onPointerCancel={surBoutonHaut}
        onClick={surBoutonClic}
      >
        {ouverte ? <X size={22} aria-hidden="true" /> : <Compass size={22} aria-hidden="true" />}
      </button>
    </div>
  );
}
