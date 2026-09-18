import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { Check, ChevronRight, CirclePlus, HelpCircle, Link2, List, Loader2, Network } from 'lucide-react';

import { CadreVitre } from '../../components/Glass/CadreVitre';
import {
  aBouge,
  aretesDeChaine,
  aretesLiberees,
  chaineComplete,
  chaineLaPlusLongue,
  cheminElastique,
  cibleClavier,
  comptes,
  consigneLiaison,
  consigneTirage,
  construireReseau,
  disposer,
  dispositionBouge,
  dureeDe,
  estOrpheline,
  faisables,
  fermeraitUneBoucle,
  impact,
  interpolerPositions,
  libelleEnTete,
  libelleRevue,
  lignesParNiveau,
  mentionLigne,
  phraseBoucle,
  phraseDepot,
  revue,
  statuts,
  traitArete,
  verdictDepot,
  type EtatArete,
  type Point,
  type StatutTache,
  type ToucheFleche,
  type VueReseau,
} from './reseau';
import { dureeImpulsion, longueurApprochee } from './synapses';
import type { SuccesTask, SuccesTaskEdge } from './types';
import { loadReseauVue, saveReseauVue } from './uiPrefs';

type Props = {
  tasks: SuccesTask[];
  edges: SuccesTaskEdge[];
  saving?: boolean;
  onToggle: (task: SuccesTask) => Promise<void>;
  onLink: (fromTaskId: string, toTaskId: string) => Promise<void>;
  onUnlink: (fromTaskId: string, toTaskId: string) => Promise<void>;
  onCreate: (input: { title: string }) => Promise<void>;
  onSelect?: (task: SuccesTask) => void;
  /**
   * La tâche ouverte dans la fiche « Branches » : sa chaîne amont + aval
   * reste nette, le reste du graphe passe à 0.3. Elle prime sur le focus
   * clavier et le survol, que la vue suit d'elle-même.
   */
  miseEnAvantId?: string | null;
  /**
   * « Relier depuis ici » de la fiche : entrer en mode liaison avec cette
   * source. Le jeton change à chaque demande, pour qu'une seconde demande
   * sur la même tâche soit encore entendue.
   */
  liaisonDemandee?: { sourceId: string; jeton: number } | null;
};

// Des cartes HTML vitrées (chantier réseau, 18 sept. 2026). Jusque-là la
// carte était un <rect> SVG : `truncate(title, 20)` donnait « Avoir les bons
// agri… » sur 6 des 7 titres d'AgriCulture, et le <svg width="100%">
// mettait le graphe À L'ÉCHELLE — 3 colonnes = 762 px de viewBox rendus dans
// les 340 px du mini-panneau, texte de 13 px affiché à ~6 px.
// 210 × 76 : deux lignes de 13 px (interligne 1,3 → 34 px), une ligne d'état
// de 11 px, 10 px de marge en haut et en bas ; il reste 6 px pour la bordure
// de 2 px du focus et l'arrondi.
const CARD_W = 210;
const CARD_H = 76;
const GAP_X = 72;
const GAP_Y = 26;
const PAD = 24;
// 260 ms : le temps qu'une carte change de ligne sans qu'on la perde de vue ;
// à 160 ms elle saute encore, à 400 ms le graphe traîne derrière la coche.
const GLISSEMENT_MS = 260;
// Le halo sur la carte que l'impulsion vient d'atteindre : 320 ms, le temps
// de l'apercevoir après la comète ; à 600 ms (le halo de l'arbre, rare et
// aléatoire) il traînait derrière un toast déjà lu.
const HALO_MS = 320;
const DANGER = 'var(--color-error, var(--color-text-secondary))';

const TON_ARETE: Record<EtatArete, string> = {
  satisfaite: 'var(--color-border)',
  prochaine: 'var(--color-accent)',
  'en-attente': 'var(--color-text-tertiary)',
};
const LEGENDE: Array<{ etat: EtatArete; libelle: string }> = [
  { etat: 'satisfaite', libelle: 'Satisfaite' },
  { etat: 'prochaine', libelle: 'Se libère au prochain geste' },
  { etat: 'en-attente', libelle: 'Encore loin' },
];

// Le raisonnement (niveaux, statuts, faisables, colonnes) vit dans
// `reseau.ts`, testé sur AgriCulture (chantier réseau, 18 sept. 2026) :
// ici on ne fait que dessiner.

/**
 * Le commutateur Graphe · Liste. Rendu DEUX fois tant que rien n'a été
 * choisi — l'un `sm:hidden` pressé sur Liste, l'autre `hidden sm:inline`
 * pressé sur Graphe — parce que la vue par défaut dépend de la largeur et
 * que la largeur se lit en CSS, jamais en JS (règle 2 du mini-panneau) :
 * `aria-pressed` dit ainsi toujours ce qui est réellement affiché.
 */
function Commutateur({ actif, onChoisir }: { actif: VueReseau; onChoisir: (vue: VueReseau) => void }) {
  return (
    <div
      role="group"
      aria-label="Forme du réseau"
      className="inline-flex rounded-xl p-0.5"
      style={{ border: '1px solid var(--color-border)' }}
    >
      {(['graphe', 'liste'] as const).map((vue) => {
        const presse = actif === vue;
        return (
          <button
            key={vue}
            type="button"
            aria-pressed={presse}
            onClick={() => onChoisir(vue)}
            className="px-2.5 py-1.5 rounded-[10px] text-xs font-medium cursor-pointer inline-flex items-center gap-1.5"
            style={
              presse
                ? { background: 'var(--color-accent)', color: 'var(--color-on-accent)' }
                : { color: 'var(--color-text-secondary)' }
            }
          >
            {vue === 'graphe' ? <Network size={13} aria-hidden="true" /> : <List size={13} aria-hidden="true" />}
            {vue === 'graphe' ? 'Graphe' : 'Liste'}
          </button>
        );
      })}
    </div>
  );
}

/** La coche et le glyphe d'état par la forme : plein = faite, cerclé = faisable, pointillé = bloquée. */
function BoutonCoche({
  task,
  status,
  saving,
  onClick,
}: {
  task: SuccesTask;
  status: StatutTache;
  saving: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={saving}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      aria-label={task.done ? `Rouvrir « ${task.title} »` : `Terminer « ${task.title} »`}
      className="mt-0.5 size-5 rounded-full flex items-center justify-center cursor-pointer shrink-0 disabled:opacity-50"
      style={{
        border: `1.5px ${status === 'bloquee' ? 'dashed' : 'solid'} ${
          task.done || status === 'faisable' ? 'var(--color-accent)' : 'var(--color-border)'
        }`,
        background: task.done ? 'var(--color-accent)' : 'transparent',
        color: 'var(--color-on-accent)',
      }}
    >
      {task.done && <Check size={12} />}
    </button>
  );
}

export function NetworkView({
  tasks,
  edges,
  saving = false,
  onToggle,
  onLink,
  onUnlink,
  onCreate,
  onSelect,
  miseEnAvantId = null,
  liaisonDemandee = null,
}: Props) {
  const [linkMode, setLinkMode] = useState(false);
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<{ from: string; to: string } | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [survolId, setSurvolId] = useState<string | null>(null);
  const [legendeOuverte, setLegendeOuverte] = useState(false);
  const [filActif, setFilActif] = useState(false);
  const [revueOuverte, setRevueOuverte] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [error, setError] = useState<string | null>(null);
  // Le tirage (18 sept. 2026) : la poignée au bord droit d'une carte se tire
  // jusqu'à la cible, un trait élastique suit le pointeur dans le SVG
  // supérieur, et le dépôt appelle le même `onLink` que le mode Relier.
  // Relier = bouton, clic source, clic cible en lisant une consigne : trois
  // gestes pour un trait, le geste répété le plus lent de la vue. Ce qui est
  // AFFICHÉ (`tirage`) ne porte que la source, la cible survolée et la pointe
  // du trait ; le reste (pointeur capturé, point de départ, si le seuil de
  // 4 px est franchi) vit hors rendu, il change à chaque mouvement.
  const [tirage, setTirage] = useState<{ sourceId: string; cibleId: string | null; pointe: Point } | null>(null);
  const tirageEnCours = useRef<{
    pointerId: number;
    sourceId: string;
    depart: Point;
    franchi: boolean;
    pointeur: Point;
    cibleId: string | null;
  } | null>(null);
  // Vrai entre le dépôt et le `click` qui le suit : le clic sur la poignée
  // ne doit pas, en plus, entrer en mode liaison. Remis à faux par ce clic
  // ou par le `pointerdown` suivant — pas par une minuterie, qui laissait
  // passer un clic arrivé un peu tard.
  const vientDeTirer = useRef(false);
  // Le point du `pointerdown` sur le titre d'une carte : le clic n'ouvre la
  // fiche que si le pointeur n'a pas bougé de plus de 4 px.
  const departClic = useRef<Point | null>(null);
  const canevas = useRef<HTMLDivElement>(null);
  // Le clavier suit les arêtes (§82, 18 sept. 2026) : les boutons des
  // cartes, par id, pour que ← → ↑ ↓ donnent le focus à la carte calculée
  // par `cibleClavier` — Tab suivait l'ordre du tableau, sans rapport avec
  // les liens, et aucune flèche ne faisait rien.
  const boutons = useRef(new Map<string, HTMLButtonElement>());
  const aideClavierId = useId();
  // Graphe ou Liste (18 sept. 2026). `undefined` tant que rien n'a été
  // choisi : le CSS montre alors la Liste sous `sm` et le Graphe au-delà —
  // à 340 px un graphe est une illustration, pas un outil. Le choix est
  // retenu par origine (fenêtre et mini-panneau ont chacun le leur).
  const [vue, setVue] = useState<VueReseau | undefined>(() => loadReseauVue());
  const choisirVue = (choix: VueReseau) => {
    setVue(choix);
    saveReseauVue(choix);
  };
  const classeGraphe = vue === 'graphe' ? '' : vue === 'liste' ? 'hidden' : 'hidden sm:block';
  const classeListe = vue === 'liste' ? '' : vue === 'graphe' ? 'hidden' : 'sm:hidden';

  const reseau = useMemo(() => construireReseau(tasks, edges), [tasks, edges]);
  const byId = reseau.parId;
  const visibleEdges = reseau.aretes;
  const statusById = useMemo(() => statuts(reseau), [reseau]);
  const feasible = useMemo(() => faisables(reseau), [reseau]);
  const nombres = useMemo(() => comptes(reseau), [reseau]);
  // La revue (18 sept. 2026) : chaînes séparées, orphelines, goulots. Une
  // tâche oubliée sans lien passait pour « faisable » ; le goulot
  // d'AgriCulture n'était nommé nulle part.
  const laRevue = useMemo(() => revue(reseau), [reseau]);
  const niveauxListe = useMemo(() => lignesParNiveau(reseau), [reseau]);

  // Le fil : la chaîne la plus longue en tâches ouvertes (18 sept. 2026).
  // Ce n'est PAS un « chemin critique » — sans durée, seule la profondeur
  // en tâches est vraie (§5). Rien ne distinguait le vrai fil du projet de
  // « tracteur », qui ne bloque personne. Un fil d'une seule tâche n'en est
  // pas un : le bouton se désactive.
  const fil = useMemo(() => chaineLaPlusLongue(reseau), [reseau]);
  const filIds = useMemo(() => new Set(fil), [fil]);
  const filAretes = useMemo(() => aretesDeChaine(fil), [fil]);
  const filVisible = filActif && fil.length >= 2;
  const horsFil = (...ids: string[]) => filVisible && !ids.every((id) => filIds.has(id));

  // La mise en avant suit la fiche, sinon le focus clavier, sinon le survol.
  // Dans le mini-panneau non activant, le NSPanel ne livre pas le survol :
  // la sélection et le focus suffisent, la souris n'est pas l'unique chemin.
  // Pendant un tirage, rien ne s'estompe par le survol : la poignée est
  // survolée, la chaîne de la source restait nette et TOUT le reste passait à
  // 0.3 — les cibles possibles avaient l'air impossibles.
  const misEnAvantId = tirage ? null : (miseEnAvantId ?? focusedId ?? survolId);
  const chaineNette = useMemo(
    () => (misEnAvantId && byId.has(misEnAvantId) ? chaineComplete(reseau, misEnAvantId) : null),
    [reseau, byId, misEnAvantId],
  );
  const estompe = (...ids: string[]) =>
    chaineNette !== null && !ids.every((id) => chaineNette.has(id));

  useEffect(() => {
    if (!liaisonDemandee || !byId.has(liaisonDemandee.sourceId)) return;
    setError(null);
    setSelectedEdge(null);
    setLinkMode(true);
    setLinkFrom(liaisonDemandee.sourceId);
  }, [liaisonDemandee]); // eslint-disable-line react-hooks/exhaustive-deps -- une demande, une fois

  // Les colonnes sont ordonnées par barycentre (reseau.ts) : triées par
  // alphabet, 5 arêtes suffisaient à croiser deux flèches sur AgriCulture.
  // Les composantes sans rapport sont empilées l'une sous l'autre avec un
  // filet pointillé, au lieu d'être entrelacées dans les mêmes colonnes.
  // Dès qu'une tâche porte une catégorie, ce sont des couloirs par
  // catégorie qui s'empilent à la place (18 sept. 2026) — le rang reste
  // global, une arête peut traverser un couloir ; sans catégorie, rien.
  const layout = useMemo(
    () =>
      disposer(reseau, {
        largeurCarte: CARD_W,
        hauteurCarte: CARD_H,
        ecartX: GAP_X,
        ecartY: GAP_Y,
        marge: PAD,
      }),
    [reseau],
  );

  // Quand une arête change et qu'une carte change de ligne, elle glisse en
  // 260 ms au lieu de sauter — cartes et arêtes lisent les mêmes positions
  // interpolées, sinon les flèches arrivaient avant les cartes. Le départ est
  // ce qui est AFFICHÉ, pas la cible précédente : un second changement en
  // plein vol repart d'où la carte est. Coupé sous `prefers-reduced-motion`.
  const [posAffichees, setPosAffichees] = useState<Map<string, Point>>(layout.pos);
  const affichees = useRef<Map<string, Point>>(layout.pos);
  useEffect(() => {
    const depart = affichees.current;
    const poser = (positions: Map<string, Point>) => {
      affichees.current = positions;
      setPosAffichees(positions);
    };
    const immobile = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    if (immobile || !dispositionBouge(depart, layout.pos)) {
      poser(layout.pos);
      return undefined;
    }
    const debut = performance.now();
    let raf = 0;
    const pas = (maintenant: number) => {
      const t = (maintenant - debut) / GLISSEMENT_MS;
      poser(interpolerPositions(depart, layout.pos, t));
      if (t < 1) raf = requestAnimationFrame(pas);
    };
    raf = requestAnimationFrame(pas);
    return () => cancelAnimationFrame(raf);
  }, [layout]);
  const posDe = (id: string): Point | undefined => posAffichees.get(id) ?? layout.pos.get(id);

  /**
   * La courbe d'une arête, du bord droit de la source au bord gauche de la
   * cible. `raccourci` arrête la courbe avant la pointe : le trait double du
   * fil est un trait de surface posé sur un trait accent, et sans ce retrait
   * il effaçait le milieu de la pointe.
   */
  const cheminArete = (fromId: string, toId: string, raccourci = 0): string | null => {
    const from = posDe(fromId);
    const to = posDe(toId);
    if (!from || !to) return null;
    const x1 = from.x + CARD_W;
    const y1 = from.y + CARD_H / 2;
    const x2 = to.x - 2 - raccourci;
    const y2 = to.y + CARD_H / 2;
    const dx = Math.max(28, Math.abs(x2 - x1) / 2);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  };

  // L'impulsion (18 sept. 2026) : quand une coche RECHARGÉE libère une
  // successeure, une comète unique part de la carte cochée le long de l'arête
  // libérée, puis la carte atteinte porte un halo. Calculée en comparant les
  // statuts d'avant et d'après (`aretesLiberees`), jamais depuis le clic :
  // une coche refusée par le serveur n'allume rien (§100). Rien ne clignote
  // en permanence — à la différence des synapses de l'arbre, qui sont un
  // flux — et tout est éteint sous `prefers-reduced-motion`.
  const [impulsions, setImpulsions] = useState<
    Array<{ cle: string; from: string; to: string; dureeMs: number }>
  >([]);
  const [halos, setHalos] = useState<Set<string>>(new Set());
  const statutsAvant = useRef<Map<string, StatutTache> | null>(null);
  const minuteries = useRef<Set<number>>(new Set());
  useEffect(() => {
    const encours = minuteries.current;
    return () => {
      for (const t of encours) window.clearTimeout(t);
    };
  }, []);
  useEffect(() => {
    const avant = statutsAvant.current;
    statutsAvant.current = statusById;
    if (!avant) return;
    const liberees = aretesLiberees(avant, reseau);
    if (liberees.length === 0) return;
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    const poser = (fn: () => void, delai: number) => {
      const t = window.setTimeout(() => {
        minuteries.current.delete(t);
        fn();
      }, delai);
      minuteries.current.add(t);
    };
    for (const { from, to } of liberees) {
      const a = layout.pos.get(from);
      const b = layout.pos.get(to);
      if (!a || !b) continue;
      const dureeMs = dureeImpulsion(
        longueurApprochee({ x1: a.x + CARD_W, y1: a.y + CARD_H / 2, x2: b.x, y2: b.y + CARD_H / 2 }),
      );
      const cle = `imp-${from}-${to}-${performance.now()}`;
      setImpulsions((liste) => [...liste, { cle, from, to, dureeMs }]);
      poser(() => {
        setHalos((h) => new Set(h).add(to));
        poser(
          () =>
            setHalos((h) => {
              const suivant = new Set(h);
              suivant.delete(to);
              return suivant;
            }),
          HALO_MS,
        );
        poser(() => setImpulsions((liste) => liste.filter((i) => i.cle !== cle)), 400);
      }, dureeMs);
    }
  }, [statusById]); // eslint-disable-line react-hooks/exhaustive-deps -- `reseau` et `layout` sont lus à l'instant du changement

  // À l'ouverture, la première colonne faisable est visible : le graphe
  // défile désormais au lieu de rétrécir, et un projet dont les racines sont
  // faites aurait montré deux colonnes de cartes barrées à 340 px.
  const defilement = useRef<HTMLDivElement>(null);
  const dejaCadre = useRef(false);
  useLayoutEffect(() => {
    if (dejaCadre.current || tasks.length === 0) return;
    const conteneur = defilement.current;
    // Caché (la Liste s'affiche), le conteneur n'a pas de largeur et un
    // `scrollLeft` posé dessus ne fait rien : on réessaie quand le Graphe
    // est choisi, au lieu de croire le cadrage fait.
    if (!conteneur || conteneur.clientWidth === 0) return;
    dejaCadre.current = true;
    let xMin = Number.POSITIVE_INFINITY;
    for (const task of feasible) {
      const p = layout.pos.get(task.id);
      if (p) xMin = Math.min(xMin, p.x);
    }
    if (Number.isFinite(xMin)) conteneur.scrollLeft = Math.max(0, xMin - PAD);
  }, [tasks.length, feasible, layout, vue]);

  useEffect(() => {
    if (!linkMode && !selectedEdge && !filActif && !tirage) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        // Consommé : le mini-panneau ne se ferme qu'au second Échap (contrat du 17 sept. 2026, lib.rs lit `defaultPrevented`).
        event.preventDefault();
        setLinkMode(false);
        setLinkFrom(null);
        setSelectedEdge(null);
        setFilActif(false);
        // Un tirage en cours est abandonné : le `pointerup` qui suivra ne
        // trouvera plus rien à déposer.
        tirageEnCours.current = null;
        setTirage(null);
        // « … fermerait une boucle » ne commente qu'une liaison en cours :
        // laissé là après l'annulation, il accusait un lien qu'on ne fait plus.
        setError(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [linkMode, selectedEdge, filActif, tirage]);

  // L'élastique : la pointe du trait rejoint le pointeur avec un peu de
  // retard (35 % du chemin par image, ~90 ms pour se poser), et se pose sur
  // le bord gauche de la cible dès qu'elle est possible. Sous
  // `prefers-reduced-motion`, la pointe est le pointeur, sans élastique.
  useEffect(() => {
    if (!tirage) return undefined;
    const immobile = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    let raf = 0;
    const pas = () => {
      const etat = tirageEnCours.current;
      if (!etat) return;
      const cible = etat.cibleId ? affichees.current.get(etat.cibleId) : undefined;
      const visee =
        cible && verdictDepot(reseau, etat.sourceId, etat.cibleId) === 'ok'
          ? { x: cible.x - 2, y: cible.y + CARD_H / 2 }
          : etat.pointeur;
      setTirage((t) => {
        if (!t) return t;
        const pointe = immobile
          ? visee
          : { x: t.pointe.x + (visee.x - t.pointe.x) * 0.35, y: t.pointe.y + (visee.y - t.pointe.y) * 0.35 };
        if (t.cibleId === etat.cibleId && Math.abs(pointe.x - t.pointe.x) < 0.1 && Math.abs(pointe.y - t.pointe.y) < 0.1) {
          return t;
        }
        return { sourceId: t.sourceId, cibleId: etat.cibleId, pointe };
      });
      raf = requestAnimationFrame(pas);
    };
    raf = requestAnimationFrame(pas);
    return () => cancelAnimationFrame(raf);
  }, [tirage !== null, reseau]); // eslint-disable-line react-hooks/exhaustive-deps -- la boucle tourne tant qu'un tirage existe

  /** Le pointeur en coordonnées du canevas (celles des cartes et des arêtes). */
  const pointDuCanevas = (event: ReactPointerEvent): Point => {
    const rect = canevas.current?.getBoundingClientRect();
    return rect ? { x: event.clientX - rect.left, y: event.clientY - rect.top } : { x: event.clientX, y: event.clientY };
  };

  /** La carte sous le pointeur, ou null — le tirage a capturé le pointeur, `elementFromPoint` regarde en dessous. */
  const carteSousLePointeur = (event: ReactPointerEvent): string | null => {
    const el = document.elementFromPoint(event.clientX, event.clientY);
    const cadre = el?.closest<HTMLElement>('[data-carte-cadre]');
    const id = cadre?.dataset.carteCadre ?? null;
    return id && byId.has(id) ? id : null;
  };

  const debutPoignee = (event: ReactPointerEvent<HTMLButtonElement>, sourceId: string) => {
    if (event.button !== 0 || saving) return;
    // Sans lui, le `mousedown` de compatibilité entamait une sélection de
    // texte à travers les cartes pendant le tirage.
    event.preventDefault();
    vientDeTirer.current = false;
    const depart = { x: event.clientX, y: event.clientY };
    tirageEnCours.current = {
      pointerId: event.pointerId,
      sourceId,
      depart,
      franchi: false,
      pointeur: pointDuCanevas(event),
      cibleId: null,
    };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Un pointeur déjà relâché (événement synthétique, ou relâché entre
      // deux images) ne se capture pas : le tirage suit alors le pointeur
      // tant qu'il reste sur la poignée, puis s'annule de lui-même.
    }
  };

  const mouvementPoignee = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const etat = tirageEnCours.current;
    if (!etat || etat.pointerId !== event.pointerId) return;
    etat.pointeur = pointDuCanevas(event);
    if (!etat.franchi) {
      if (!aBouge(etat.depart, { x: event.clientX, y: event.clientY })) return;
      etat.franchi = true;
      // Le message d'erreur précédent reste jusqu'au dépôt : retiré ici,
      // sa ligne disparaissait et le graphe remontait de 32 px sous le
      // pointeur, dès le premier mouvement.
      setSelectedEdge(null);
      setSurvolId(null);
      setTirage({ sourceId: etat.sourceId, cibleId: null, pointe: etat.pointeur });
    }
    const cibleId = carteSousLePointeur(event);
    if (cibleId !== etat.cibleId) {
      etat.cibleId = cibleId;
      // La cible change ici même, pas à la prochaine image : le verdict
      // (impossible, doublon, possible) se lit dès que le pointeur entre.
      setTirage((t) => (t ? { ...t, cibleId } : t));
    }
  };

  const finPoignee = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const etat = tirageEnCours.current;
    if (!etat || etat.pointerId !== event.pointerId) return;
    tirageEnCours.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    // Sous le seuil : un clic, que `onClick` traite (mode liaison).
    if (!etat.franchi) return;
    vientDeTirer.current = true;
    setTirage(null);
    const cibleId = carteSousLePointeur(event);
    // Boucle ou doublon : dit ici, sans rien envoyer. Un lien possible part
    // au serveur, qui reste le juge (une arête arrivée d'un pair entre-temps).
    const phrase = phraseDepot(reseau, etat.sourceId, cibleId);
    setError(phrase);
    if (phrase) return;
    if (cibleId && verdictDepot(reseau, etat.sourceId, cibleId) === 'ok') {
      void run(() => onLink(etat.sourceId, cibleId));
    }
  };

  const annulerPoignee = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const etat = tirageEnCours.current;
    if (!etat || etat.pointerId !== event.pointerId) return;
    tirageEnCours.current = null;
    setTirage(null);
  };

  /** Entrer en mode liaison avec cette source : la touche L, le clic sur la poignée, la fiche. */
  const relierDepuis = (sourceId: string) => {
    setError(null);
    setSelectedEdge(null);
    setLinkMode(true);
    setLinkFrom(sourceId);
  };

  const run = async (action: () => Promise<void>) => {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const keyActivate = (action: () => void) => (event: ReactKeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      event.stopPropagation();
      action();
    }
  };

  const activateCard = (task: SuccesTask) => {
    setSelectedEdge(null);
    if (linkMode) {
      if (!linkFrom) {
        setLinkFrom(task.id);
        return;
      }
      if (linkFrom === task.id) {
        setLinkFrom(null);
        return;
      }
      if (fermeraitUneBoucle(reseau, linkFrom, task.id)) {
        // Prévenu AVANT le clic : la cible est déjà atténuée et son libellé
        // le dit ; ici, on ne fait que le redire. Le serveur reste le juge
        // (workspace.py refuse la boucle avec sa phrase) pour tout ce que le
        // client ne voit pas — une arête arrivée d'un pair entre-temps.
        setError(phraseBoucle(reseau, linkFrom, task.id));
        return;
      }
      const from = linkFrom;
      setLinkMode(false);
      setLinkFrom(null);
      void run(() => onLink(from, task.id));
      return;
    }
    onSelect?.(task);
  };

  // La source d'un lien en cours : celle du tirage, sinon celle du mode Relier.
  const sourceLiaison = tirage?.sourceId ?? (linkMode ? linkFrom : null);

  /** Une fois la source choisie (Relier ou tirage) : cette cible fermerait-elle une boucle ? */
  const cibleImpossible = (id: string) =>
    sourceLiaison !== null && sourceLiaison !== id && fermeraitUneBoucle(reseau, sourceLiaison, id);

  /** Même atténuation dans le dessin et dans la Liste : chaîne nette, cible impossible (0.3 pendant le tirage), hors fil, faite. */
  const opaciteDe = (task: SuccesTask) =>
    estompe(task.id)
      ? 0.3
      : cibleImpossible(task.id)
        ? tirage
          ? 0.3
          : 0.4
        : horsFil(task.id)
          ? 0.5
          : task.done
            ? 0.72
            : 1;

  const toggleTask = (task: SuccesTask) => {
    if (saving) return;
    void run(() => onToggle(task));
  };

  const unlinkSelected = () => {
    if (!selectedEdge || saving) return;
    const { from, to } = selectedEdge;
    void run(async () => {
      await onUnlink(from, to);
      setSelectedEdge(null);
    });
  };

  const focaliser = (id: string | null) => {
    if (!id) return;
    boutons.current.get(id)?.focus();
  };

  /**
   * Le clavier sur le canevas (§82). Depuis une carte : ← → suivent les
   * arêtes, ↑ ↓ la colonne, L la prend pour source de liaison (Entrée sur
   * la cible conclut, par `activateCard`). Depuis un lien focalisé : ← → vont
   * à ses deux bouts, Suppr le retire. Avec un lien choisi (le « × »
   * visible), Suppr le retire aussi, d'où que vienne le focus. Rien n'est
   * dit ici sur le résultat : la phrase vient du rechargement (§100).
   */
  const clavierCanevas = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const cible = event.target as HTMLElement;
    const arete = cible.dataset.arete;
    const [areteDe, areteVers] = arete ? arete.split('->') : [null, null];
    const carte = cible.dataset.carte ?? null;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      if (areteDe && areteVers) {
        event.preventDefault();
        focaliser(event.key === 'ArrowLeft' ? areteDe : areteVers);
        return;
      }
      if (carte) {
        event.preventDefault();
        focaliser(cibleClavier(reseau, layout.pos, carte, event.key));
      }
      return;
    }
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      if (!carte) return;
      event.preventDefault();
      focaliser(cibleClavier(reseau, layout.pos, carte, event.key as ToucheFleche));
      return;
    }
    if ((event.key === 'l' || event.key === 'L') && carte && tasks.length >= 2) {
      event.preventDefault();
      relierDepuis(carte);
      return;
    }
    if (event.key === 'Delete' || event.key === 'Backspace') {
      if (areteDe && areteVers && !saving) {
        event.preventDefault();
        void run(async () => {
          await onUnlink(areteDe, areteVers);
          setSelectedEdge(null);
        });
        return;
      }
      if (selectedEdge) {
        event.preventDefault();
        unlinkSelected();
      }
    }
  };

  const addTask = () => {
    const title = newTitle.trim();
    if (!title || saving) return;
    void run(async () => {
      await onCreate({ title });
      setNewTitle('');
    });
  };

  const statusLabel = (status: StatutTache) =>
    status === 'faite' ? 'Faite' : status === 'faisable' ? 'Faisable maintenant' : 'Bloquée';

  const statusColor = (status: StatutTache) =>
    status === 'faite'
      ? 'var(--color-text-secondary)'
      : status === 'faisable'
        ? 'var(--color-accent)'
        : 'var(--color-text-tertiary)';

  return (
    <div className="grid gap-4">
      <section
        className="grid gap-2 rounded-2xl p-4"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-3 flex-wrap">
          {/* Trois chiffres honnêtes : faisables, bloquées, profondeur. Le
              dernier est la chaîne la plus longue en tâches ouvertes — pas un
              chemin critique, qui demanderait des durées. */}
          <p
            className="text-sm font-medium flex flex-wrap items-baseline gap-x-1.5"
            style={{ color: 'var(--color-text)' }}
            aria-label={libelleEnTete(nombres)}
          >
            <span>
              <span style={{ color: 'var(--color-accent)' }}>{nombres.faisables}</span>{' '}
              {nombres.faisables > 1 ? 'faisables' : 'faisable'}
            </span>
            <span aria-hidden="true" style={{ color: 'var(--color-text-tertiary)' }}>·</span>
            <span>
              {nombres.bloquees} {nombres.bloquees > 1 ? 'bloquées' : 'bloquée'}
            </span>
            <span aria-hidden="true" style={{ color: 'var(--color-text-tertiary)' }}>·</span>
            <span title="Chaîne la plus longue, en tâches ouvertes">
              profondeur {nombres.profondeur}
            </span>
            {/* Dès qu'une durée existe (18 sept. 2026) : les jours du chemin
                critique, projetés depuis aujourd'hui — jamais une date
                promise. Sans durée, rien : on ne compte pas des jours que
                personne n'a estimés. */}
            {nombres.joursProjetes !== null && (
              <>
                <span aria-hidden="true" style={{ color: 'var(--color-text-tertiary)' }}>·</span>
                <span title="Les jours du chemin critique, depuis aujourd’hui — pas une date promise">
                  fin projetée <span className="tabular-nums">~{nombres.joursProjetes} j</span>
                </span>
              </>
            )}
          </p>
          <button
            type="button"
            onClick={() => setFilActif((v) => !v)}
            aria-pressed={filActif}
            disabled={fil.length < 2}
            title={
              nombres.joursProjetes !== null
                ? 'Mettre en évidence le chemin critique (Échap pour l’éteindre)'
                : 'Mettre en évidence la chaîne la plus longue (Échap pour l’éteindre)'
            }
            className="ml-auto px-2.5 py-1 rounded-full text-xs font-medium cursor-pointer disabled:opacity-50 disabled:cursor-default"
            style={
              filVisible
                ? { background: 'var(--color-accent)', color: 'var(--color-on-accent)' }
                : { border: '1px solid var(--color-border)', color: 'var(--color-text)' }
            }
          >
            Fil
          </button>
        </div>
        <p className="text-[11px] font-medium tracking-[0.12em] uppercase" style={{ color: 'var(--color-text-tertiary)' }}>
          Faisable maintenant
        </p>
        {feasible.length === 0 ? (
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Aucune tâche débloquée pour l’instant.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {/* Triées par ce qu'elles libèrent (`faisables`, reseau.ts) : la
                première puce est la tâche à faire ce soir. « → 2 » dit
                combien de tâches ouvertes attendent celle-ci, de près ou de
                loin ; rien quand elle n'ouvre rien seule. */}
            {feasible.map((task) => {
              const n = impact(reseau, task.id);
              return (
                <button
                  key={task.id}
                  type="button"
                  onClick={() => onSelect?.(task)}
                  aria-label={
                    n >= 1 ? `${task.title} — débloque ${n} tâche${n > 1 ? 's' : ''}` : task.title
                  }
                  className="px-2.5 py-1 rounded-full text-xs cursor-pointer inline-flex items-center gap-1.5"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                >
                  <span>{task.title}</span>
                  {n >= 1 && (
                    <span
                      className="font-medium tabular-nums whitespace-nowrap"
                      style={{ color: 'var(--color-accent)' }}
                    >
                      → {n}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
        {tasks.length > 0 && (
          <div className="grid gap-1">
            {/* Repliée par défaut : une ligne de revue ouverte en permanence
                ferait de l'en-tête un tableau de bord. Le chevron et le
                texte tertiaire suffisent ; `aria-expanded` pour le clavier. */}
            <button
              type="button"
              onClick={() => setRevueOuverte((v) => !v)}
              aria-expanded={revueOuverte}
              className="flex items-center gap-1 text-[11px] cursor-pointer self-start"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              <ChevronRight
                size={12}
                className="transition-transform motion-reduce:transition-none"
                style={{ transform: revueOuverte ? 'rotate(90deg)' : undefined }}
                aria-hidden="true"
              />
              Revue du réseau
            </button>
            {revueOuverte && (
              <p
                className="text-[11px] leading-relaxed pl-4"
                style={{ color: 'var(--color-text-tertiary)' }}
                aria-label={libelleRevue(reseau, laRevue)}
              >
                {laRevue.chaines === 0
                  ? 'aucune chaîne'
                  : laRevue.chaines === 1
                    ? '1 chaîne'
                    : `${laRevue.chaines} chaînes indépendantes`}
                {' · '}
                {laRevue.orphelines.length} orpheline{laRevue.orphelines.length > 1 ? 's' : ''}
                {' · '}
                {laRevue.goulots.length === 0 ? (
                  'aucun goulot'
                ) : (
                  <>
                    goulot{laRevue.goulots.length > 1 ? 's' : ''} :{' '}
                    {laRevue.goulots.map((g, i) => {
                      const t = byId.get(g.id);
                      if (!t) return null;
                      return (
                        <span key={g.id}>
                          {i > 0 && ', '}
                          <button
                            type="button"
                            onClick={() => onSelect?.(t)}
                            className="cursor-pointer underline-offset-2 hover:underline"
                            style={{ color: 'var(--color-text-secondary)' }}
                          >
                            « {t.title} »
                          </button>{' '}
                          (débloque {g.debloque})
                        </span>
                      );
                    })}
                  </>
                )}
              </p>
            )}
          </div>
        )}
      </section>

      <div className="flex items-center gap-3 flex-wrap">
        {tasks.length > 0 &&
          (vue ? (
            <Commutateur actif={vue} onChoisir={choisirVue} />
          ) : (
            <>
              <span className="sm:hidden">
                <Commutateur actif="liste" onChoisir={choisirVue} />
              </span>
              <span className="hidden sm:inline">
                <Commutateur actif="graphe" onChoisir={choisirVue} />
              </span>
            </>
          ))}
        <button
          type="button"
          disabled={saving || tasks.length < 2}
          onClick={() => {
            setError(null);
            setSelectedEdge(null);
            setLinkFrom(null);
            setLinkMode((value) => !value);
          }}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer disabled:opacity-50"
          style={
            linkMode
              ? { background: 'var(--color-accent)', color: 'var(--color-on-accent)' }
              : { border: '1px solid var(--color-border)', color: 'var(--color-text)' }
          }
        >
          {saving ? <Loader2 size={15} className="animate-spin" /> : <Link2 size={15} />}
          {linkMode ? 'Annuler la liaison' : 'Relier'}
        </button>
        {/* Toujours montée, pour qu'un lecteur d'écran l'entende changer :
            `aria-live` ne lit pas ce qui apparaît avec sa région. Elle nomme
            la source dès qu'elle est choisie — au clic, à L, ou depuis la
            fiche — et dit les deux chemins, souris et clavier. */}
        {/* Pendant un tirage, la consigne reste hors flux (`sr-only`, lue
            quand même) et se montre en pastille SUR le graphe : affichée ici,
            elle prenait une ligne et décalait les cartes de 57 px sous un
            pointeur immobile — le dépôt tombait dans le vide entre deux
            cartes. */}
        <span
          aria-live="polite"
          aria-atomic="true"
          className={linkMode && !tirage ? 'text-xs' : 'sr-only'}
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {tirage
            ? consigneTirage(reseau, tirage.sourceId, tirage.cibleId)
            : linkMode
              ? consigneLiaison(linkFrom ? (byId.get(linkFrom)?.title ?? null) : null)
              : ''}
        </span>
        {tasks.length > 0 && vue !== 'liste' && (
          <>
            {/* Sous `sm` la légende vit derrière un « ? » : trois entrées de
                11 px tiennent à 640 px, pas à 340. Sans choix explicite,
                sous `sm` c'est la Liste qui s'affiche : pas de « ? ». */}
            {vue === 'graphe' && (
              <button
                type="button"
                onClick={() => setLegendeOuverte((v) => !v)}
                aria-expanded={legendeOuverte}
                aria-label="Légende des traits"
                className="ml-auto sm:hidden size-8 rounded-lg flex items-center justify-center cursor-pointer"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                <HelpCircle size={15} />
              </button>
            )}
            <ul
              aria-label="Légende des traits"
              className={`${legendeOuverte ? 'flex' : 'hidden sm:flex'} sm:ml-auto basis-full sm:basis-auto flex-wrap items-center gap-x-3 gap-y-1 text-[11px]`}
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              {LEGENDE.map(({ etat, libelle }) => {
                const trait = traitArete(
                  etat === 'satisfaite' ? 'faite' : etat === 'prochaine' ? 'faisable' : 'bloquee',
                );
                return (
                  <li key={etat} className="flex items-center gap-1.5">
                    <svg aria-hidden="true" width={26} height={8} viewBox="0 0 26 8">
                      <path
                        d="M0,4 L18,4"
                        stroke={TON_ARETE[etat]}
                        strokeWidth={trait.epaisseur}
                        strokeDasharray={trait.pointilles}
                        fill="none"
                      />
                      <path
                        d="M18,0.5 L25,4 L18,7.5 Z"
                        fill={trait.pointe === 'creuse' ? 'var(--color-surface)' : TON_ARETE[etat]}
                        stroke={TON_ARETE[etat]}
                        strokeWidth={trait.pointe === 'creuse' ? 1 : 0}
                      />
                    </svg>
                    {libelle}
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>

      {error && (
        <p className="text-xs" role="alert" style={{ color: DANGER }}>
          {error}
        </p>
      )}

      {tasks.length === 0 ? (
        <div
          className="rounded-2xl py-12 text-center"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <p className="font-medium" style={{ color: 'var(--color-text)' }}>
            Aucune tâche dans le réseau
          </p>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
            Ajoutez une première tâche ci-dessous, puis reliez-les avec « Relier ».
          </p>
        </div>
      ) : (
        <>
        {/* `hidden` / `sm:block` : sans choix, la Liste sous `sm` et le Graphe au-delà. */}
        <div className={`relative ${classeGraphe}`}>
        {tirage && (
          <p
            aria-hidden="true"
            className="absolute left-3 top-1.5 z-10 pointer-events-none max-w-[calc(100%-24px)] truncate rounded-full px-2.5 py-1 text-xs"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-secondary)',
            }}
          >
            {consigneTirage(reseau, tirage.sourceId, tirage.cibleId)}
          </p>
        )}
        <div
          ref={defilement}
          className="rounded-2xl p-2 overflow-x-auto"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          {/* Le canevas prend sa largeur RÉELLE en pixels : à 340 px il défile,
              il ne rétrécit plus. Les cartes sont posées en absolu aux
              positions de `positionner`, à taille fixe (`overflow-hidden`,
              titre replié sur deux lignes) : la géométrie des arêtes est donc
              celle du layout, sans mesure du DOM — une carte ne peut pas
              grandir sans que la disposition le sache. */}
          <div
            role="group"
            aria-label={
              layout.couloirs.length > 0
                ? `Réseau des tâches reliées par « débloque », en couloirs : ${layout.couloirs
                    .map((c) => c.libelle)
                    .join(', ')}`
                : 'Réseau des tâches reliées par « débloque »'
            }
            ref={canevas}
            aria-describedby={aideClavierId}
            className="relative isolate"
            style={{
              width: layout.largeur,
              height: layout.hauteur,
              cursor: tirage ? 'grabbing' : undefined,
              userSelect: tirage ? 'none' : undefined,
            }}
            onClick={() => setSelectedEdge(null)}
            onKeyDown={clavierCanevas}
            // Un défilement à la molette déplace les cartes sous un pointeur
            // immobile sans `pointerleave` sur la carte quittée : la mise en
            // avant restait sur elle. Quitter le canevas remet tout à net.
            onPointerLeave={() => setSurvolId(null)}
          >
            <p id={aideClavierId} className="sr-only">
              Au clavier : flèche gauche et droite suivent les liens, haut et bas parcourent une
              colonne ; L prend la carte comme source d’un lien, Entrée choisit la cible ; sur un
              lien, Suppr le retire. À la souris, la poignée au bord droit d’une carte se tire
              jusqu’à la tâche à débloquer.
            </p>
            <svg
              className="absolute inset-0 -z-10 pointer-events-none"
              width={layout.largeur}
              height={layout.hauteur}
              viewBox={`0 0 ${layout.largeur} ${layout.hauteur}`}
              aria-hidden="true"
            >
              <defs>
                {/* Pointes en unités d'espace utilisateur : sinon la pointe
                    grandit avec l'épaisseur, et la « prochaine » à 1,75 px
                    portait une pointe double de la satisfaite. */}
                {(['satisfaite', 'prochaine', 'en-attente'] as EtatArete[]).map((etat) => (
                  <marker
                    key={etat}
                    id={`nv-pointe-${etat}`}
                    viewBox="0 0 10 10"
                    refX="9"
                    refY="5"
                    markerWidth={etat === 'prochaine' ? 11 : 9}
                    markerHeight={etat === 'prochaine' ? 11 : 9}
                    markerUnits="userSpaceOnUse"
                    orient="auto-start-reverse"
                  >
                    <path
                      d="M1,1 L9,5 L1,9 Z"
                      fill={etat === 'satisfaite' ? 'var(--color-surface)' : TON_ARETE[etat]}
                      stroke={TON_ARETE[etat]}
                      strokeWidth={etat === 'satisfaite' ? 1.25 : 0}
                      strokeLinejoin="round"
                    />
                  </marker>
                ))}
              </defs>
              {/* Un filet pointillé entre deux composantes sans rapport. */}
              {layout.separateurs.map((y) => (
                <line
                  key={y}
                  x1={PAD / 2}
                  x2={layout.largeur - PAD / 2}
                  y1={y}
                  y2={y}
                  stroke="var(--color-border)"
                  strokeWidth={1}
                  strokeDasharray="2 5"
                />
              ))}
              {visibleEdges.map((edge) => {
                const d = cheminArete(edge.fromTaskId, edge.toTaskId);
                if (!d) return null;
                const trait = traitArete(statusById.get(edge.fromTaskId) ?? 'faisable');
                const isSelected =
                  selectedEdge?.from === edge.fromTaskId && selectedEdge?.to === edge.toTaskId;
                const cle = `${edge.fromTaskId}->${edge.toTaskId}`;
                const opacite = estompe(edge.fromTaskId, edge.toTaskId)
                  ? 0.3
                  : horsFil(edge.fromTaskId, edge.toTaskId)
                    ? 0.5
                    : 1;
                if (filVisible && filAretes.has(cle)) {
                  // Le trait double du fil : deux traits de 1 px espacés de
                  // 2 px — un trait accent de 4 px sous un trait de surface
                  // de 2 px, arrêté 8 px avant la pointe. Lisible en
                  // Ardéchine, où l'accent est l'encre : la forme, pas la teinte.
                  const dCourt = cheminArete(edge.fromTaskId, edge.toTaskId, 8);
                  return (
                    <g key={cle} className="reseau-estompable" style={{ opacity: opacite }}>
                      <path
                        d={d}
                        fill="none"
                        stroke="var(--color-accent)"
                        strokeWidth={4}
                        markerEnd="url(#nv-pointe-prochaine)"
                      />
                      {dCourt && <path d={dCourt} fill="none" stroke="var(--color-surface)" strokeWidth={2} />}
                    </g>
                  );
                }
                return (
                  <path
                    key={cle}
                    className="reseau-estompable"
                    d={d}
                    fill="none"
                    stroke={TON_ARETE[trait.etat]}
                    strokeWidth={isSelected ? trait.epaisseur + 1 : trait.epaisseur}
                    strokeDasharray={trait.pointilles}
                    markerEnd={`url(#nv-pointe-${trait.etat})`}
                    style={{ opacity: opacite }}
                  />
                );
              })}
              {impulsions.map((imp) => {
                // La comète relit l'arête au rendu : la carte cochée glisse
                // vers le bas de sa colonne pendant le voyage, et la lumière
                // suit la flèche au lieu de flotter dans le vide. Deux tirets
                // de même période dont les fronts coïncident (synapses de
                // l'arbre, index.css) : la queue diaphane épouse la tête.
                const d = cheminArete(imp.from, imp.to);
                if (!d) return null;
                return (
                  <g key={imp.cle} aria-hidden="true">
                    <path
                      d={d}
                      pathLength={100}
                      fill="none"
                      stroke="var(--color-accent)"
                      strokeWidth={1.5}
                      strokeLinecap="round"
                      style={{
                        strokeDasharray: '18 100',
                        strokeDashoffset: 18,
                        animation: `synapse-queue ${imp.dureeMs}ms linear forwards`,
                        opacity: 0.35,
                      }}
                    />
                    <path
                      d={d}
                      pathLength={100}
                      fill="none"
                      stroke="var(--color-accent)"
                      strokeWidth={2.5}
                      strokeLinecap="round"
                      style={{
                        strokeDasharray: '6 112',
                        strokeDashoffset: 6,
                        animation: `synapse-tete ${imp.dureeMs}ms linear forwards`,
                        filter: 'drop-shadow(0 0 5px var(--color-accent))',
                      }}
                    />
                  </g>
                );
              })}
            </svg>

            {/* Le libellé d'un couloir, discret, en marge gauche au-dessus de
                sa première ligne ; « — » pour les tâches sans catégorie. */}
            {layout.couloirs.map((c) => (
              <span
                key={c.categorie || '—'}
                aria-hidden="true"
                className="absolute text-[11px] font-medium tracking-[0.12em] uppercase pointer-events-none truncate"
                style={{
                  left: PAD,
                  top: c.y + 6,
                  maxWidth: layout.largeur - PAD * 2,
                  color: 'var(--color-text-tertiary)',
                }}
              >
                {c.libelle}
              </span>
            ))}

            {tasks.map((task) => {
              const p = posDe(task.id);
              if (!p) return null;
              const status = statusById.get(task.id) ?? 'faisable';
              const isLinkSource = sourceLiaison === task.id;
              const isFocused = focusedId === task.id;
              const enHalo = halos.has(task.id);
              // La cible possible sous le trait tiré : le même trait de 2 px
              // que le focus, le dépôt est annoncé avant d'avoir lieu.
              const cibleDuTirage =
                tirage !== null &&
                tirage.cibleId === task.id &&
                verdictDepot(reseau, tirage.sourceId, task.id) === 'ok';
              const highlighted = isLinkSource || isFocused || enHalo || cibleDuTirage;
              // « ↓3 » seulement à partir de deux tâches ouvertes en aval :
              // à une, la flèche vers la carte suivante le dit déjà.
              const aval = task.done ? 0 : impact(reseau, task.id);
              // Sans aucun lien : un trait en pointillés, et « sans lien »
              // sous le titre — elle passe pour faisable sans que rien ne
              // l'ait placée.
              const orpheline = !task.done && estOrpheline(reseau, task.id);
              // En mode liaison, une cible qui fermerait une boucle est
              // atténuée à 0.4 et son libellé le dit, avant le clic.
              const impossible = cibleImpossible(task.id);
              // « ~3 j » : la durée estimée, seulement quand elle existe et
              // que la tâche est ouverte — une faite ne pèse plus.
              const jours = task.done ? 0 : dureeDe(reseau, task.id);
              return (
                <CadreVitre
                  compact
                  key={task.id}
                  className="group reseau-carte reseau-estompable rounded-xl p-2.5 flex items-start gap-2 overflow-hidden"
                  data-statut={status}
                  data-orpheline={orpheline ? 'true' : undefined}
                  data-carte-cadre={task.id}
                  onPointerEnter={() => setSurvolId(task.id)}
                  onPointerLeave={() => setSurvolId((id) => (id === task.id ? null : id))}
                  // `position` en inline : `.composer-glass { position: relative }`
                  // (ComposerGlass.css, hors couche) l'emporte sur l'utilitaire
                  // `absolute` de Tailwind (couche utilities) — les cartes
                  // s'empilaient en flux, décalées de leur `left/top`.
                  style={{
                    position: 'absolute',
                    left: p.x,
                    top: p.y,
                    width: CARD_W,
                    height: CARD_H,
                    background: 'var(--color-surface)',
                    // La carte ne dispute plus l'accent à la flèche : seul le
                    // glyphe d'état le porte. La bordure ne dit que le focus
                    // et la source de liaison, par un trait de 2 px.
                    border: `1px solid ${highlighted ? 'var(--color-accent)' : 'var(--color-border)'}`,
                    borderWidth: highlighted ? 2 : undefined,
                    borderStyle: isLinkSource || orpheline ? 'dashed' : undefined,
                    boxShadow: enHalo
                      ? '0 0 14px color-mix(in srgb, var(--color-accent) 35%, transparent)'
                      : undefined,
                    opacity: opaciteDe(task),
                  }}
                >
                  <BoutonCoche task={task} status={status} saving={saving} onClick={() => toggleTask(task)} />
                  <button
                    type="button"
                    ref={(el) => {
                      if (el) boutons.current.set(task.id, el);
                      else boutons.current.delete(task.id);
                    }}
                    data-carte={task.id}
                    onPointerDown={(event) => {
                      departClic.current = { x: event.clientX, y: event.clientY };
                    }}
                    onClick={(event) => {
                      // Un pointeur qui a bougé de plus de 4 px n'était pas un
                      // clic : la fiche ne s'ouvre pas. Au clavier, il n'y a
                      // pas eu de `pointerdown` : rien ne retient.
                      const depart = departClic.current;
                      departClic.current = null;
                      if (depart && event.detail > 0 && aBouge(depart, { x: event.clientX, y: event.clientY })) return;
                      activateCard(task);
                    }}
                    onFocus={() => setFocusedId(task.id)}
                    onBlur={() => setFocusedId(null)}
                    aria-label={`${task.title} — ${statusLabel(status)}${orpheline ? ', sans lien' : ''}${
                      jours > 0 ? `, environ ${jours} jour${jours > 1 ? 's' : ''}` : ''
                    }${aval >= 2 ? `, ${aval} tâches en aval` : ''}${
                      impossible
                        ? '. Impossible : fermerait une boucle'
                        : linkMode
                          ? linkFrom
                            ? '. Choisir comme cible'
                            : '. Choisir comme source'
                          : ''
                    }`}
                    aria-disabled={impossible || undefined}
                    title={impossible ? 'Impossible : fermerait une boucle' : task.title}
                    className="flex-1 min-w-0 pr-4 text-left cursor-pointer grid gap-0.5 outline-none"
                  >
                    <span
                      className="text-[13px] font-semibold leading-[1.3] line-clamp-2 break-words"
                      style={{
                        color: 'var(--color-text)',
                        textDecoration: task.done ? 'line-through' : undefined,
                      }}
                    >
                      {task.title}
                    </span>
                    <span className="text-[11px] leading-none flex items-center gap-2">
                      <span className="truncate" style={{ color: statusColor(status) }}>
                        {statusLabel(status)}
                        {orpheline && (
                          <span style={{ color: 'var(--color-text-tertiary)' }}> · sans lien</span>
                        )}
                        {jours > 0 && (
                          <span className="tabular-nums" style={{ color: 'var(--color-text-tertiary)' }}>
                            {' '}· ~{jours} j
                          </span>
                        )}
                      </span>
                      {aval >= 2 && (
                        <span
                          aria-hidden="true"
                          className="ml-auto shrink-0 tabular-nums"
                          style={{ color: 'var(--color-text-tertiary)' }}
                        >
                          ↓{aval}
                        </span>
                      )}
                    </span>
                  </button>
                  {/* La poignée (18 sept. 2026) : révélée au survol, toujours
                      visible dans le mini-panneau et sous `sm` (le NSPanel non
                      activant ne livre pas le survol). La tirer trace le lien ;
                      la cliquer entre en mode liaison avec cette source — le
                      même chemin que L et que « Relier depuis ici ». Ronde et
                      cerclée d'accent, pleine sur la source en cours. */}
                  {tasks.length >= 2 && (
                    <button
                      type="button"
                      aria-label={`Tirer un lien depuis « ${task.title} »`}
                      title="Tirer jusqu’à la tâche à débloquer, ou cliquer pour choisir la cible"
                      disabled={saving}
                      onPointerDown={(event) => debutPoignee(event, task.id)}
                      onPointerMove={mouvementPoignee}
                      onPointerUp={finPoignee}
                      onPointerCancel={annulerPoignee}
                      onClick={(event) => {
                        event.stopPropagation();
                        if (vientDeTirer.current) {
                          vientDeTirer.current = false;
                          return;
                        }
                        if (isLinkSource) {
                          setLinkMode(false);
                          setLinkFrom(null);
                          return;
                        }
                        relierDepuis(task.id);
                      }}
                      className={`absolute right-2 top-1/2 -translate-y-1/2 size-3.5 rounded-full transition-opacity motion-reduce:transition-none focus-visible:opacity-100 max-sm:opacity-100 compact:opacity-100 disabled:opacity-0 ${
                        isLinkSource ? 'opacity-100 cursor-grabbing' : 'opacity-0 group-hover:opacity-100 cursor-grab'
                      }`}
                      style={{
                        border: '1.5px solid var(--color-accent)',
                        background: isLinkSource ? 'var(--color-accent)' : 'var(--color-surface)',
                        touchAction: 'none',
                      }}
                    />
                  )}
                </CadreVitre>
              );
            })}

            {/* Au-dessus des cartes, les arêtes cliquables : un trait invisible de
                14 px qui n'attrape que sa propre épaisseur, et le « × » de
                suppression quand une arête est choisie. */}
            <svg
              className="absolute inset-0 pointer-events-none"
              width={layout.largeur}
              height={layout.hauteur}
              viewBox={`0 0 ${layout.largeur} ${layout.hauteur}`}
            >
              {visibleEdges.map((edge) => {
                const d = cheminArete(edge.fromTaskId, edge.toTaskId);
                const fromTask = byId.get(edge.fromTaskId);
                const toTask = byId.get(edge.toTaskId);
                if (!d || !fromTask || !toTask) return null;
                return (
                  <path
                    key={`${edge.fromTaskId}->${edge.toTaskId}`}
                    d={d}
                    fill="none"
                    stroke="transparent"
                    strokeWidth={14}
                    role="button"
                    tabIndex={0}
                    data-arete={`${edge.fromTaskId}->${edge.toTaskId}`}
                    aria-label={`Lien : « ${fromTask.title} » débloque « ${toTask.title} ». Entrée pour le choisir, Suppr pour le retirer.`}
                    // Pendant un tirage, les arêtes ne prennent plus le
                    // pointeur : `elementFromPoint` doit trouver la carte
                    // en dessous, pas le trait de 14 px qui la traverse.
                    style={{ cursor: 'pointer', outline: 'none', pointerEvents: tirage ? 'none' : 'stroke' }}
                    onClick={(event: ReactMouseEvent<SVGPathElement>) => {
                      event.stopPropagation();
                      setSelectedEdge({ from: edge.fromTaskId, to: edge.toTaskId });
                    }}
                    onKeyDown={keyActivate(() =>
                      setSelectedEdge({ from: edge.fromTaskId, to: edge.toTaskId }),
                    )}
                  />
                );
              })}

              {tirage &&
                (() => {
                  // Le trait tiré : pointillé tant qu'il n'est posé sur rien,
                  // plein avec sa pointe (le trait « prochaine ») dès que la
                  // cible est possible, pointillé en teinte d'erreur sur une
                  // cible qui fermerait une boucle ou un doublon — la forme
                  // le dit aussi en Ardéchine, où l'accent est l'encre.
                  const src = posDe(tirage.sourceId);
                  if (!src) return null;
                  const verdict = verdictDepot(reseau, tirage.sourceId, tirage.cibleId);
                  const refuse = verdict === 'boucle' || verdict === 'deja';
                  return (
                    <path
                      aria-hidden="true"
                      d={cheminElastique({ x: src.x + CARD_W, y: src.y + CARD_H / 2 }, tirage.pointe)}
                      fill="none"
                      stroke={refuse ? DANGER : 'var(--color-accent)'}
                      strokeWidth={1.75}
                      strokeLinecap="round"
                      strokeDasharray={verdict === 'ok' ? undefined : '6 4'}
                      markerEnd={verdict === 'ok' ? 'url(#nv-pointe-prochaine)' : undefined}
                      style={{ pointerEvents: 'none' }}
                    />
                  );
                })()}

              {selectedEdge &&
                (() => {
                  const from = posDe(selectedEdge.from);
                  const to = posDe(selectedEdge.to);
                  if (!from || !to) return null;
                  const mx = (from.x + CARD_W + to.x - 2) / 2;
                  const my = (from.y + CARD_H / 2 + to.y + CARD_H / 2) / 2;
                  return (
                    <g
                      transform={`translate(${mx} ${my})`}
                      role="button"
                      tabIndex={0}
                      aria-label="Supprimer ce lien"
                      style={{ cursor: 'pointer', outline: 'none', pointerEvents: 'all' }}
                      onClick={(event: ReactMouseEvent<SVGGElement>) => {
                        event.stopPropagation();
                        unlinkSelected();
                      }}
                      onKeyDown={keyActivate(unlinkSelected)}
                    >
                      <circle r={11} fill="var(--color-surface)" stroke={DANGER} strokeWidth={1.5} />
                      <text
                        textAnchor="middle"
                        dominantBaseline="central"
                        fontSize={14}
                        fontWeight={600}
                        fill={DANGER}
                      >
                        ×
                      </text>
                    </g>
                  );
                })()}
            </svg>
          </div>
        </div>
        </div>

        {/* La Liste (18 sept. 2026) : les mêmes tâches en ordre topologique,
            groupées par niveau, la première ligne étant la tâche à faire ce
            soir. Mêmes coche, fiche et Relier que le dessin ; les mentions
            « attend : X » et « libère : Z » sont les arêtes elles-mêmes, que
            l'on choisit puis supprime ici aussi — aucune action n'existe que
            dans le dessin (§82). */}
        <div className={classeListe}>
          <div
            role="group"
            aria-label="Réseau des tâches, en liste par niveau"
            className="rounded-2xl p-2 grid gap-3"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          >
            {niveauxListe.map(({ niveau, lignes }) => (
              <section key={niveau} className="grid gap-0.5" aria-label={`Niveau ${niveau + 1}`}>
                <p
                  className="text-[11px] font-medium tracking-[0.12em] uppercase px-2 pt-1"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  Niveau {niveau + 1}
                </p>
                {lignes.map((ligne) => {
                  const task = byId.get(ligne.id);
                  if (!task) return null;
                  const status = ligne.statut;
                  const isLinkSource = linkFrom === task.id;
                  const isFocused = focusedId === task.id;
                  const impossible = cibleImpossible(task.id);
                  const mention = mentionLigne(reseau, ligne);
                  const orpheline = !task.done && estOrpheline(reseau, task.id);
                  // Les voisines citées : en amont pour une bloquée (ce qu'elle
                  // attend), en aval pour une faisable (ce qu'elle libère).
                  const voisines = status === 'bloquee' ? ligne.attend : ligne.libere;
                  return (
                    <div
                      key={task.id}
                      className="reseau-ligne flex items-start gap-2 rounded-xl px-2 py-1.5"
                      data-statut={status}
                      style={{
                        opacity: opaciteDe(task),
                        // Le focus et la source de liaison par un trait, pas une teinte.
                        outline: isLinkSource
                          ? '2px dashed var(--color-accent)'
                          : isFocused
                            ? '2px solid var(--color-accent)'
                            : 'none',
                        outlineOffset: -2,
                      }}
                    >
                      <BoutonCoche task={task} status={status} saving={saving} onClick={() => toggleTask(task)} />
                      <div className="flex-1 min-w-0 grid gap-0.5">
                        <button
                          type="button"
                          onClick={() => activateCard(task)}
                          onFocus={() => setFocusedId(task.id)}
                          onBlur={() => setFocusedId(null)}
                          aria-label={`${task.title} — ${statusLabel(status)}${orpheline ? ', sans lien' : ''}${
                            mention ? `, ${mention}` : ''
                          }${ligne.aval >= 2 ? `, ${ligne.aval} tâches en aval` : ''}${
                            impossible
                              ? '. Impossible : fermerait une boucle'
                              : linkMode
                                ? linkFrom
                                  ? '. Choisir comme cible'
                                  : '. Choisir comme source'
                                : ''
                          }`}
                          aria-disabled={impossible || undefined}
                          title={impossible ? 'Impossible : fermerait une boucle' : undefined}
                          className="text-left cursor-pointer outline-none text-[13px] font-medium leading-snug whitespace-normal break-words"
                          style={{
                            color: 'var(--color-text)',
                            textDecoration: task.done ? 'line-through' : undefined,
                          }}
                        >
                          {task.title}
                          {orpheline && (
                            <span className="font-normal" style={{ color: 'var(--color-text-tertiary)' }}>
                              {' '}· sans lien
                            </span>
                          )}
                          {task.category && (
                            // Le couloir du dessin, dit en mot dans la Liste.
                            <span className="font-normal" style={{ color: 'var(--color-text-tertiary)' }}>
                              {' '}· {task.category}
                            </span>
                          )}
                          {!task.done && dureeDe(reseau, task.id) > 0 && (
                            <span className="font-normal tabular-nums" style={{ color: 'var(--color-text-tertiary)' }}>
                              {' '}· ~{dureeDe(reseau, task.id)} j
                            </span>
                          )}
                        </button>
                        {mention && (
                          <p
                            className="text-[11px] leading-relaxed flex flex-wrap items-center gap-x-1"
                            style={{ color: 'var(--color-text-tertiary)' }}
                          >
                            <span>{status === 'bloquee' ? 'attend :' : 'libère :'}</span>
                            {voisines.map((vid, i) => {
                              const voisine = byId.get(vid);
                              if (!voisine) return null;
                              const from = status === 'bloquee' ? vid : task.id;
                              const to = status === 'bloquee' ? task.id : vid;
                              const choisi = selectedEdge?.from === from && selectedEdge?.to === to;
                              return (
                                <span key={vid} className="inline-flex items-center gap-1">
                                  <button
                                    type="button"
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      setSelectedEdge(choisi ? null : { from, to });
                                    }}
                                    aria-pressed={choisi}
                                    aria-label={`Lien : « ${byId.get(from)?.title ?? ''} » débloque « ${
                                      byId.get(to)?.title ?? ''
                                    } ». Sélectionner pour supprimer.`}
                                    className="cursor-pointer text-left underline-offset-2 hover:underline"
                                    style={{
                                      color: choisi ? 'var(--color-text)' : 'var(--color-text-secondary)',
                                      textDecoration: choisi ? 'underline' : undefined,
                                    }}
                                  >
                                    {voisine.title}
                                    {i < voisines.length - 1 ? ',' : ''}
                                  </button>
                                  {choisi && (
                                    <button
                                      type="button"
                                      disabled={saving}
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        unlinkSelected();
                                      }}
                                      aria-label="Supprimer ce lien"
                                      className="size-5 rounded-full flex items-center justify-center cursor-pointer text-sm font-semibold leading-none disabled:opacity-50"
                                      style={{
                                        border: `1.5px solid ${DANGER}`,
                                        color: DANGER,
                                        background: 'var(--color-surface)',
                                      }}
                                    >
                                      ×
                                    </button>
                                  )}
                                </span>
                              );
                            })}
                          </p>
                        )}
                      </div>
                      {ligne.aval >= 2 && (
                        <span
                          aria-hidden="true"
                          className="shrink-0 text-[11px] tabular-nums mt-1"
                          style={{ color: 'var(--color-text-tertiary)' }}
                        >
                          ↓{ligne.aval}
                        </span>
                      )}
                    </div>
                  );
                })}
              </section>
            ))}
          </div>
        </div>
        </>
      )}

      <section
        className="flex gap-2 rounded-2xl p-3"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <input
          value={newTitle}
          onChange={(event) => setNewTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') addTask();
          }}
          placeholder="+ Tâche : titre…"
          maxLength={200}
          aria-label="Titre de la nouvelle tâche"
          className="flex-1 rounded-xl px-3 py-2 text-sm bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
        />
        <button
          type="button"
          disabled={!newTitle.trim() || saving}
          onClick={addTask}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
          style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
        >
          {saving ? <Loader2 size={15} className="animate-spin" /> : <CirclePlus size={15} />}
          Ajouter
        </button>
      </section>
    </div>
  );
}
