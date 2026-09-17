// Une photo en plein cadre, dans son éventail.
//
// Demandé le 13 septembre 2026 : « la précédente s'en va à gauche, la
// suivante prend le milieu, celle d'après se trouve à droite ; je veux voir
// un aperçu des autres ». Deux voisines de chaque côté, inclinées et
// décroissantes ; les flèches font glisser toute la file. Le centre se
// zoome à la molette, se retouche (rotation, cadre — sans toucher à
// l'original) et s'annote (un calque SVG). Un diaporama fait défiler seul.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  Crop,
  FileText,
  Link2,
  Loader2,
  Maximize2,
  NotebookPen,
  PenLine,
  Play,
  Pause,
  RotateCcw,
  RotateCw,
  Star,
  Trash2,
  Undo2,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { toast } from 'sonner';

import type { useConfirm } from '../../components/ConfirmDialog';
import { AnnotationsCalque } from './AnnotationsCalque';
import { deleteSuccesPhoto, updateSuccesPhoto, updateSuccesPhotoPile } from './api';
import {
  COULEURS_ANNOTATION,
  ZOOM_DOUBLE_CLIC,
  ZOOM_NEUTRE,
  bornerZoom,
  cadreDepuisCoins,
  composerCadres,
  deRecadrerAnnotations,
  distanceCirculaire,
  facteurMolette,
  libelleDate,
  libelleTaille,
  libelleZoom,
  placeEventail,
  recadrerAnnotations,
  tournerAnnotations,
  tournerCadre,
  zoomerAutour,
  type Zoom,
} from './photos';
import { apercuRetouche, rendrePhoto } from './photosClient';
import { chargerOriginal, insererDansNote, notesDisponibles } from './photosExport';
import type {
  SuccesAnnotation,
  SuccesAnnotationType,
  SuccesCadre,
  SuccesNote,
  SuccesPhoto,
  SuccesPhotoPile,
  SuccesTask,
} from './types';

// La capture du pointeur lève `NotFoundError` quand l'événement ne vient pas
// d'un vrai pointeur (un test, un geste synthétique) : le geste doit
// s'achever quand même, capture ou pas.
function capturer(e: { currentTarget: Element; pointerId: number }) {
  try {
    e.currentTarget.setPointerCapture(e.pointerId);
  } catch {
    // Pas de pointeur actif : rien à capturer.
  }
}
function relacher(e: { currentTarget: Element; pointerId: number }) {
  try {
    e.currentTarget.releasePointerCapture(e.pointerId);
  } catch {
    // Déjà relâché.
  }
}

interface Props {
  photos: SuccesPhoto[];
  index: number;
  /** La pile, quand on feuillette une pile (couverture possible) ; absente en recherche. */
  pile?: SuccesPhotoPile | null;
  tasks: SuccesTask[];
  tachesParId: Map<string, SuccesTask>;
  onAller: (index: number) => void;
  onFermer: () => void;
  /** Après un changement enregistré : le parent relit ses listes. */
  onMisAJour: () => Promise<void>;
  onSupprimee: () => Promise<void>;
  confirm: ReturnType<typeof useConfirm>;
}

type Mode = 'vue' | 'retouche' | 'annoter';

/** Le rendu d'un original : sa source à afficher et sa taille. */
interface Rendu {
  src: string;
  largeur: number;
  hauteur: number;
  /** L'original décodé, pour re-rendre après une retouche. */
  original: HTMLImageElement;
  /** Ce qui a été rendu, pour savoir si le cache tient encore. */
  cle: string;
}

const DUREE_DIAPORAMA_MS = 5000;
const EPAISSEURS: Array<{ label: string; valeur: number }> = [
  { label: 'Fin', valeur: 2 },
  { label: 'Moyen', valeur: 4 },
  { label: 'Épais', valeur: 8 },
];

const cleRendu = (p: SuccesPhoto) => `${p.id}:${p.rotation}:${JSON.stringify(p.crop)}`;

/** Les tâches aplaties dans l'ordre de l'arbre, avec leur profondeur. */
function aplatirTaches(tasks: SuccesTask[]): Array<{ tache: SuccesTask; profondeur: number }> {
  const parParent = new Map<string, SuccesTask[]>();
  for (const t of tasks) {
    const cle = t.parentTaskId || '';
    const liste = parParent.get(cle) ?? [];
    liste.push(t);
    parParent.set(cle, liste);
  }
  const sortie: Array<{ tache: SuccesTask; profondeur: number }> = [];
  const marcher = (parent: string, profondeur: number) => {
    for (const t of parParent.get(parent) ?? []) {
      sortie.push({ tache: t, profondeur });
      if (profondeur < 3) marcher(t.id, profondeur + 1);
    }
  };
  marcher('', 0);
  return sortie;
}

export function PhotoPleinCadre({
  photos,
  index,
  pile,
  tasks,
  tachesParId,
  onAller,
  onFermer,
  onMisAJour,
  onSupprimee,
  confirm,
}: Props) {
  const photo = photos[index];
  const total = photos.length;
  const [mode, setMode] = useState<Mode>('vue');
  const [zoom, setZoom] = useState<Zoom>(ZOOM_NEUTRE);
  const [legende, setLegende] = useState(photo?.caption ?? '');
  const [occupe, setOccupe] = useState(false);
  const [diaporama, setDiaporama] = useState(false);
  const [texteLu, setTexteLu] = useState(false);
  const [scene, setScene] = useState({ largeur: 1, hauteur: 1 });
  /** Les rendus des originaux, bornés à une dizaine. */
  const rendus = useRef<Map<string, Rendu>>(new Map());
  const [, forcer] = useState(0);
  const cadreRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<HTMLDivElement>(null);
  const glisser = useRef<{ x: number; y: number; zx: number; zy: number } | null>(null);
  // Annotations : brouillon local, enregistré avec un petit délai.
  const [calque, setCalque] = useState<SuccesAnnotation[]>(photo?.annotations ?? []);
  const [outil, setOutil] = useState<SuccesAnnotationType>('arrow');
  const [couleur, setCouleur] = useState(COULEURS_ANNOTATION[0]);
  const [epaisseur, setEpaisseur] = useState(4);
  const [selection, setSelection] = useState<string | null>(null);
  const minuteurCalque = useRef<number | null>(null);
  // Recadrage : le rectangle en cours, en fractions de l'image affichée.
  const [dessinCadre, setDessinCadre] = useState<{ a: { x: number; y: number }; b: { x: number; y: number } } | null>(null);
  // Le même tracé dans une ref : deux événements de pointeur dans la même
  // image d'écran lisent l'état AVANT le rendu, et le second croyait qu'aucun
  // tracé n'avait commencé.
  const dessinRef = useRef<{ a: { x: number; y: number }; b: { x: number; y: number } } | null>(null);
  const poserDessin = (d: { a: { x: number; y: number }; b: { x: number; y: number } } | null) => {
    dessinRef.current = d;
    setDessinCadre(d);
  };
  const [cadreDessine, setCadreDessine] = useState<SuccesCadre | null>(null);
  // Vers une note.
  const [notes, setNotes] = useState<SuccesNote[] | null>(null);
  const [choixNote, setChoixNote] = useState(false);

  const aplaties = useMemo(() => aplatirTaches(tasks), [tasks]);

  // ── La scène suit la fenêtre ─────────────────────────────────────────
  useEffect(() => {
    const el = sceneRef.current;
    if (!el) return;
    const mesurer = () => {
      const r = el.getBoundingClientRect();
      setScene({ largeur: Math.max(1, r.width), hauteur: Math.max(1, r.height) });
    };
    mesurer();
    const observateur = new ResizeObserver(mesurer);
    observateur.observe(el);
    return () => observateur.disconnect();
  }, []);

  useEffect(() => {
    cadreRef.current?.focus();
  }, []);

  // ── Changement de photo : tout se remet à plat ───────────────────────
  useEffect(() => {
    setZoom(ZOOM_NEUTRE);
    setMode('vue');
    setSelection(null);
    poserDessin(null);
    setCadreDessine(null);
    setChoixNote(false);
    setTexteLu(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photo?.id]);

  useEffect(() => {
    setLegende(photo?.caption ?? '');
  }, [photo?.caption, photo?.id]);

  useEffect(() => {
    setCalque(photo?.annotations ?? []);
  }, [photo?.annotations, photo?.id]);

  // ── Le rendu de l'original, pour le centre (et les voisines par avance) ─
  const rendre = useCallback(async (p: SuccesPhoto) => {
    const cle = cleRendu(p);
    const existant = rendus.current.get(p.id);
    if (existant && existant.cle === cle) return existant;
    try {
      const original = existant?.original ?? (await chargerOriginal(p));
      let rendu: Rendu;
      if (p.rotation || p.crop) {
        const r = rendrePhoto(original, p.rotation, p.crop);
        rendu = {
          src: r.canvas.toDataURL('image/jpeg', 0.92),
          largeur: r.largeur,
          hauteur: r.hauteur,
          original,
          cle,
        };
      } else {
        rendu = { src: original.src, largeur: original.naturalWidth, hauteur: original.naturalHeight, original, cle };
      }
      rendus.current.set(p.id, rendu);
      // Une dizaine d'originaux en mémoire, pas plus : une pile de cent
      // photos de 4 Mo ne doit pas finir dans la RAM du WebView.
      while (rendus.current.size > 10) {
        const premiere = rendus.current.keys().next().value;
        if (premiere === undefined) break;
        rendus.current.delete(premiere);
      }
      forcer((n) => n + 1);
      return rendu;
    } catch {
      // L'aperçu reste : une photo un peu floue vaut mieux qu'une erreur.
      return null;
    }
  }, []);

  useEffect(() => {
    if (!photo) return;
    let annule = false;
    void rendre(photo).then(() => {
      if (annule || total < 2) return;
      // Les deux voisines immédiates, pour que la flèche ne fasse pas attendre.
      void rendre(photos[(index + 1) % total]);
      void rendre(photos[(index - 1 + total) % total]);
    });
    return () => {
      annule = true;
    };
  }, [photo, photos, index, total, rendre]);

  const rendu = photo ? rendus.current.get(photo.id) : undefined;
  const renduValide = rendu && rendu.cle === cleRendu(photo);

  // ── Géométrie de l'éventail ──────────────────────────────────────────
  const carte = useMemo(() => {
    const largeur = Math.min(scene.largeur * 0.64, scene.largeur - 96);
    const hauteur = scene.hauteur - 24;
    return { largeur: Math.max(120, largeur), hauteur: Math.max(120, hauteur) };
  }, [scene]);
  const ecart = scene.largeur * 0.26;
  const seul = mode !== 'vue' || zoom.echelle > 1;

  /** La taille de l'image centrale ajustée à la carte, à l'échelle 1. */
  const image = useMemo(() => {
    const natL = renduValide ? rendu.largeur : photo?.width || 1;
    const natH = renduValide ? rendu.hauteur : photo?.height || 1;
    // Seule au centre (retouche, annotation, zoom), l'image prend toute la scène.
    const boiteL = (seul ? scene.largeur - 32 : carte.largeur) - 16;
    const boiteH = (seul ? scene.hauteur - 16 : carte.hauteur) - 16;
    const facteur = Math.min(boiteL / natL, boiteH / natH);
    return {
      largeur: Math.max(1, Math.floor(natL * facteur)),
      hauteur: Math.max(1, Math.floor(natH * facteur)),
    };
  }, [renduValide, rendu, photo, seul, scene, carte]);

  // ── Navigation ───────────────────────────────────────────────────────
  const aller = useCallback(
    (sens: 1 | -1) => {
      if (total <= 1) return;
      onAller((index + sens + total) % total);
    },
    [index, total, onAller],
  );

  // `aller` change à chaque photo ; l'intervalle, lui, ne doit pas se
  // réarmer à chaque rendu — il lit la version courante par une ref.
  const allerRef = useRef(aller);
  allerRef.current = aller;
  useEffect(() => {
    if (!diaporama || total < 2) return;
    const id = window.setInterval(() => allerRef.current(1), DUREE_DIAPORAMA_MS);
    return () => window.clearInterval(id);
  }, [diaporama, total]);

  // ── Zoom ─────────────────────────────────────────────────────────────
  const zoomerA = useCallback(
    (facteur: number, point?: { x: number; y: number }) => {
      const centre = { x: scene.largeur / 2, y: scene.hauteur / 2 };
      setZoom((z) => zoomerAutour(z, facteur, point ?? centre, scene, image));
    },
    [scene, image],
  );

  const pointDans = (e: { clientX: number; clientY: number }) => {
    const r = sceneRef.current?.getBoundingClientRect();
    return { x: e.clientX - (r?.left ?? 0), y: e.clientY - (r?.top ?? 0) };
  };

  const zoomerRef = useRef(zoomerA);
  zoomerRef.current = zoomerA;
  const modeRef = useRef(mode);
  modeRef.current = mode;
  useEffect(() => {
    const el = sceneRef.current;
    if (!el) return;
    const surMolette = (e: WheelEvent) => {
      if (modeRef.current !== 'vue') return;
      e.preventDefault();
      zoomerRef.current(facteurMolette(e.deltaY), pointDans(e));
    };
    el.addEventListener('wheel', surMolette, { passive: false });
    return () => el.removeEventListener('wheel', surMolette);
  }, []);

  // ── Clavier, sur la fenêtre (le focus se perd sur les boutons désactivés) ─
  // Un seul écouteur pour toute la vie du plein cadre ; il lit l'état du
  // moment par une ref. Réabonner à chaque rendu laissait une fenêtre où
  // deux écouteurs pouvaient coexister — et une flèche avançait de deux.
  const surToucheRef = useRef<(e: KeyboardEvent) => void>(() => undefined);
  surToucheRef.current = (e: KeyboardEvent) => {
      const cible = e.target as HTMLElement | null;
      const dansChamp =
        !!cible &&
        (cible.tagName === 'INPUT' || cible.tagName === 'SELECT' || cible.tagName === 'TEXTAREA');
      if (e.key === 'Escape') {
        e.stopPropagation();
        // Consommé : le mini-panneau ne se ferme qu'au second Échap (contrat du 17 sept. 2026, lib.rs lit `defaultPrevented`). (stopPropagation ne suffit pas : le script natif écoute
        // `document`, avant `window`.)
        e.preventDefault();
        if (dansChamp) cible.blur();
        else if (choixNote || texteLu) {
          setChoixNote(false);
          setTexteLu(false);
        }
        else if (mode !== 'vue') {
          setMode('vue');
          poserDessin(null);
          setCadreDessine(null);
        } else if (diaporama) setDiaporama(false);
        else if (zoom.echelle > 1) setZoom(ZOOM_NEUTRE);
        else onFermer();
        return;
      }
      if (dansChamp) return;
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        aller(1);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        aller(-1);
      } else if (e.key === ' ') {
        e.preventDefault();
        setDiaporama((d) => !d);
      } else if (e.key === '+' || e.key === '=') {
        e.preventDefault();
        zoomerA(1.25);
      } else if (e.key === '-') {
        e.preventDefault();
        zoomerA(0.8);
      } else if (e.key === '0') {
        e.preventDefault();
        setZoom(ZOOM_NEUTRE);
      } else if ((e.key === 'Backspace' || e.key === 'Delete') && mode === 'annoter' && selection) {
        e.preventDefault();
        changerCalque(calque.filter((a) => a.id !== selection));
        setSelection(null);
      }
  };
  useEffect(() => {
    const relais = (e: KeyboardEvent) => surToucheRef.current(e);
    window.addEventListener('keydown', relais, true);
    return () => window.removeEventListener('keydown', relais, true);
  }, []);

  // ── Enregistrements ──────────────────────────────────────────────────
  const patcher = async (patch: Parameters<typeof updateSuccesPhoto>[1], message?: string) => {
    if (!photo) return;
    setOccupe(true);
    try {
      await updateSuccesPhoto(photo.id, patch);
      await onMisAJour();
      if (message) toast.success(message);
    } catch (error) {
      toast.error("La modification n'a pas été enregistrée.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setOccupe(false);
    }
  };

  const enregistrerLegende = () => {
    const propre = legende.trim();
    if (!photo || propre === photo.caption) return;
    void patcher({ caption: propre });
  };

  const changerCalque = (suivant: SuccesAnnotation[]) => {
    setCalque(suivant);
    if (minuteurCalque.current) window.clearTimeout(minuteurCalque.current);
    // Un demi-seconde après le dernier trait : un stylo enregistre à chaque
    // levée de doigt sans envoyer une requête par point.
    minuteurCalque.current = window.setTimeout(() => {
      void patcher({ annotations: suivant });
    }, 500);
  };

  const tourner = async (sens: 1 | -1) => {
    if (!photo) return;
    const r = rendus.current.get(photo.id);
    const original = r?.original ?? (await chargerOriginal(photo).catch(() => null));
    if (!original) {
      toast.error("L'original ne peut pas être lu.");
      return;
    }
    const rotation = (photo.rotation + sens * 90 + 360) % 360;
    const crop = tournerCadre(photo.crop, sens);
    const annotations = tournerAnnotations(calque, sens);
    await patcher(
      { rotation, crop: crop ?? undefined, effacerCadre: !crop, annotations, thumbBase64: apercuRetouche(original, rotation, crop) },
      'Photo tournée',
    );
  };

  const appliquerCadre = async () => {
    if (!photo || !cadreDessine) return;
    const r = rendus.current.get(photo.id);
    const original = r?.original ?? (await chargerOriginal(photo).catch(() => null));
    if (!original) return;
    const crop = composerCadres(photo.crop, cadreDessine);
    const annotations = recadrerAnnotations(calque, cadreDessine);
    setCadreDessine(null);
    setMode('vue');
    await patcher(
      { crop, annotations, thumbBase64: apercuRetouche(original, photo.rotation, crop) },
      'Photo recadrée — l’original est gardé',
    );
  };

  const retablirOriginal = async () => {
    if (!photo) return;
    const r = rendus.current.get(photo.id);
    const original = r?.original ?? (await chargerOriginal(photo).catch(() => null));
    if (!original) return;
    // Les annotations reviennent dans le repère de l'image entière.
    const annotations = tournerAnnotations(
      deRecadrerAnnotations(calque, photo.crop),
      -Math.round(photo.rotation / 90),
    );
    setMode('vue');
    await patcher(
      { rotation: 0, effacerCadre: true, annotations, thumbBase64: apercuRetouche(original, 0, null) },
      'Original rétabli',
    );
  };

  const mettreEnCouverture = async () => {
    if (!pile || !photo) return;
    setOccupe(true);
    try {
      await updateSuccesPhotoPile(pile.id, { coverPhotoId: photo.id });
      await onMisAJour();
      toast.success('Couverture de la pile mise à jour');
    } catch (error) {
      toast.error("La couverture n'a pas changé.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setOccupe(false);
    }
  };

  const supprimer = async () => {
    if (!photo) return;
    const ok = await confirm({
      title: 'Supprimer cette photo ?',
      description: 'Elle sera effacée du disque. Ça ne se récupère pas.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!ok) return;
    setOccupe(true);
    try {
      await deleteSuccesPhoto(photo.id);
      toast.success('Photo supprimée');
      await onSupprimee();
    } catch (error) {
      toast.error('La suppression a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setOccupe(false);
    }
  };

  const ouvrirChoixNote = async () => {
    if (choixNote) {
      setChoixNote(false);
      return;
    }
    setTexteLu(false);
    setChoixNote(true);
    if (notes === null) {
      try {
        setNotes(await notesDisponibles());
      } catch (error) {
        toast.error('Les notes ne peuvent pas être chargées.', {
          description: error instanceof Error ? error.message : String(error),
        });
        setChoixNote(false);
      }
    }
  };

  const mettreDansNote = async (note: SuccesNote) => {
    if (!photo) return;
    setChoixNote(false);
    setOccupe(true);
    try {
      await insererDansNote(photo, note);
      toast.success(`Ajoutée à la note « ${note.title || 'Sans titre'} »`);
    } catch (error) {
      toast.error("La photo n'a pas été ajoutée à la note.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setOccupe(false);
    }
  };

  if (!photo) return null;
  const estCouverture = !!pile && pile.coverPhotoId === photo.id;

  const fractionDans = (e: { clientX: number; clientY: number }, el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
      y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)),
    };
  };

  return (
    <div
      ref={cadreRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-label={photo.caption || photo.fileName}
      className="voile-modal z-[60] flex flex-col outline-none"
      style={{ background: 'rgba(0,0,0,0.94)' }}
      onClick={(e) => {
        e.stopPropagation();
        // Un clic hors d'un panneau (texte lu, choix de note) le referme.
        // Ils ne se fermaient que par leur bouton ou Échap : « je clique
        // n'importe où pour fermer et ça refuse » (13 septembre 2026).
        const cible = e.target as HTMLElement;
        if ((choixNote || texteLu) && !cible.closest('[data-panneau]')) {
          setChoixNote(false);
          setTexteLu(false);
        }
      }}
    >
      {/* ── En-tête ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-3 px-4 py-2.5 text-xs" style={{ color: 'rgba(255,255,255,0.7)' }}>
        <span className="truncate">
          {pile ? `${pile.name} · ` : ''}
          {index + 1}/{total} · {photo.fileName}
          {photo.width && photo.height ? ` · ${photo.width}×${photo.height}` : ''} · {libelleTaille(photo.bytes)}
          {photo.createdAtMs ? ` · ${libelleDate(photo.createdAtMs)}` : ''}
        </span>
        <div className="flex items-center gap-0.5 shrink-0">
          {occupe && <Loader2 size={14} className="animate-spin mr-1" />}
          <Bouton titre="Réduire (−)" onClick={() => zoomerA(0.8)} disabled={zoom.echelle <= 1 || mode !== 'vue'}>
            <ZoomOut size={16} />
          </Bouton>
          <button
            type="button"
            onClick={() => setZoom(ZOOM_NEUTRE)}
            disabled={zoom.echelle <= 1}
            aria-label="Ajuster au cadre (0)"
            title="Ajuster au cadre (0)"
            className="rounded-lg px-1.5 py-2 cursor-pointer disabled:opacity-40 text-[11px] tabular-nums min-w-[52px]"
            style={{ color: '#fff' }}
          >
            {zoom.echelle > 1 ? libelleZoom(zoom.echelle) : <Maximize2 size={14} className="inline" />}
          </button>
          <Bouton titre="Agrandir (+) — molette ou double-clic" onClick={() => zoomerA(1.25)} disabled={zoom.echelle >= 8 || mode !== 'vue'}>
            <ZoomIn size={16} />
          </Bouton>
          <Separateur />
          <Bouton titre="Tourner à gauche" onClick={() => void tourner(-1)} disabled={occupe}>
            <RotateCcw size={16} />
          </Bouton>
          <Bouton titre="Tourner à droite" onClick={() => void tourner(1)} disabled={occupe}>
            <RotateCw size={16} />
          </Bouton>
          <Bouton
            titre={mode === 'retouche' ? 'Quitter le recadrage' : 'Recadrer'}
            onClick={() => {
              setZoom(ZOOM_NEUTRE);
              poserDessin(null);
              setCadreDessine(null);
              setMode((m) => (m === 'retouche' ? 'vue' : 'retouche'));
            }}
            actif={mode === 'retouche'}
            disabled={occupe}
          >
            <Crop size={16} />
          </Bouton>
          <Bouton
            titre={mode === 'annoter' ? "Terminer l'annotation" : 'Annoter'}
            onClick={() => {
              setZoom(ZOOM_NEUTRE);
              setSelection(null);
              setMode((m) => (m === 'annoter' ? 'vue' : 'annoter'));
            }}
            actif={mode === 'annoter'}
            disabled={occupe}
          >
            <PenLine size={16} />
          </Bouton>
          <Separateur />
          <Bouton titre={diaporama ? 'Arrêter le diaporama (Espace)' : 'Diaporama (Espace)'} onClick={() => setDiaporama((d) => !d)} actif={diaporama} disabled={total < 2}>
            {diaporama ? <Pause size={16} /> : <Play size={16} />}
          </Bouton>
          {/* Les deux boutons portent le marqueur des panneaux : le clic qui
              ouvre l'un ne doit pas être pris pour un clic « ailleurs » qui
              le refermerait aussitôt. */}
          <span data-panneau="boutons" className="contents">
            <Bouton titre="Mettre dans une note" onClick={() => void ouvrirChoixNote()} actif={choixNote} disabled={occupe}>
              <NotebookPen size={16} />
            </Bouton>
            <Bouton titre={photo.ocrText ? 'Texte lu dans la photo' : 'Aucun texte lu'} onClick={() => { setChoixNote(false); setTexteLu((t) => !t); }} actif={texteLu} disabled={!photo.ocrText}>
              <FileText size={16} />
            </Bouton>
          </span>
          {pile && (
            <Bouton titre={estCouverture ? 'Déjà la couverture' : 'Mettre en couverture de la pile'} onClick={() => void mettreEnCouverture()} disabled={estCouverture || occupe} couleur={estCouverture ? '#ffd166' : undefined}>
              <Star size={16} />
            </Bouton>
          )}
          <Bouton titre="Supprimer la photo" onClick={() => void supprimer()} disabled={occupe} couleur="#ff8a8a">
            <Trash2 size={16} />
          </Bouton>
          <Bouton titre="Fermer (Échap)" onClick={onFermer}>
            <X size={18} />
          </Bouton>
        </div>
      </div>

      {/* ── La scène : l'éventail ────────────────────────────────────── */}
      <div ref={sceneRef} className="flex-1 min-h-0 relative overflow-hidden">
        {total > 1 && !seul && (
          <button type="button" onClick={() => aller(-1)} aria-label="Photo précédente" className="absolute left-3 top-1/2 -translate-y-1/2 z-20 rounded-full p-2 cursor-pointer" style={{ background: 'rgba(255,255,255,0.12)', color: '#fff' }}>
            <ChevronLeft size={20} />
          </button>
        )}
        {photos.map((p, i) => {
          const d = distanceCirculaire(i, index, total);
          const place = placeEventail(d);
          const centre = d === 0;
          if (!place.visible && !centre) return null;
          if (seul && !centre) return null;
          // Toutes les cartes ont la MÊME boîte ; seule leur transformation
          // change. Le centre avait la taille de son image et l'animait :
          // à chaque flèche, la carte gonflait comme une bulle avant de
          // reprendre sa forme (signalé le 13 septembre 2026). Plus rien
          // n'anime une taille — que des glissements.
          const boite = seul
            ? { largeur: scene.largeur - 32, hauteur: scene.hauteur - 16 }
            : carte;
          const style = {
            left: '50%',
            top: '50%',
            width: boite.largeur,
            height: boite.hauteur,
            marginLeft: -boite.largeur / 2,
            marginTop: -boite.hauteur / 2,
            transform: centre
              ? 'translate(0, 0) scale(1) rotate(0deg)'
              : `translate(${place.x * ecart}px, ${place.y * carte.hauteur}px) scale(${place.echelle}) rotate(${place.rotation}deg)`,
            opacity: centre ? 1 : place.opacite,
            transition: 'transform 520ms cubic-bezier(0.2, 0.8, 0.2, 1), opacity 520ms ease',
            zIndex: centre ? 10 : place.z,
          };
          return (
            <div
              key={p.id}
              className="absolute select-none"
              style={{ ...style, willChange: 'transform' }}
              onDoubleClick={centre && mode === 'vue' ? (e) => {
                if (zoom.echelle > 1) setZoom(ZOOM_NEUTRE);
                else zoomerA(ZOOM_DOUBLE_CLIC, pointDans(e));
              } : undefined}
              onClick={!centre ? () => onAller(i) : undefined}
              role={!centre ? 'button' : undefined}
              aria-label={!centre ? `Aller à « ${p.caption || p.fileName} »` : undefined}
              onPointerDown={centre && mode === 'vue' ? (e) => {
                if (zoom.echelle <= 1 || e.button !== 0) return;
                capturer(e);
                glisser.current = { x: e.clientX, y: e.clientY, zx: zoom.x, zy: zoom.y };
              } : undefined}
              onPointerMove={centre && mode === 'vue' ? (e) => {
                const g = glisser.current;
                if (!g) return;
                setZoom((z) => bornerZoom({ echelle: z.echelle, x: g.zx + (e.clientX - g.x), y: g.zy + (e.clientY - g.y) }, scene, image));
              } : undefined}
              onPointerUp={centre ? (e) => {
                if (glisser.current) relacher(e);
                glisser.current = null;
              } : undefined}
            >
              {centre ? (
                <div
                  className="absolute rounded-md overflow-hidden"
                  style={{
                    left: '50%',
                    top: '50%',
                    width: image.largeur,
                    height: image.hauteur,
                    marginLeft: -image.largeur / 2,
                    marginTop: -image.hauteur / 2,
                    transform: `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.echelle})`,
                    transition: glisser.current ? 'none' : 'transform 160ms ease-out',
                    cursor: mode === 'vue' ? (zoom.echelle > 1 ? 'grab' : 'zoom-in') : undefined,
                    background: '#000',
                  }}
                >
                  <img
                    src={renduValide ? rendu.src : p.thumb}
                    alt={p.caption || p.fileName}
                    draggable={false}
                    className="w-full h-full block"
                    style={{ objectFit: 'fill' }}
                  />
                  <AnnotationsCalque
                    annotations={mode === 'annoter' ? calque : p.annotations}
                    largeur={image.largeur}
                    hauteur={image.hauteur}
                    edition={mode === 'annoter'}
                    outil={outil}
                    couleur={couleur}
                    epaisseur={epaisseur}
                    selection={selection}
                    onSelection={setSelection}
                    onChange={changerCalque}
                  />
                  {mode === 'retouche' && (
                    <div
                      className="absolute inset-0"
                      style={{ cursor: 'crosshair', touchAction: 'none' }}
                      onPointerDown={(e) => {
                        if (e.button !== 0) return;
                        capturer(e);
                        const a = fractionDans(e, e.currentTarget);
                        poserDessin({ a, b: a });
                        setCadreDessine(null);
                      }}
                      onPointerMove={(e) => {
                        const d = dessinRef.current;
                        if (!d) return;
                        poserDessin({ a: d.a, b: fractionDans(e, e.currentTarget) });
                      }}
                      onPointerUp={(e) => {
                        const d = dessinRef.current;
                        if (!d) return;
                        relacher(e);
                        setCadreDessine(cadreDepuisCoins(d.a, fractionDans(e, e.currentTarget)));
                        poserDessin(null);
                      }}
                    >
                      {(() => {
                        const c = dessinCadre ? cadreDepuisCoins(dessinCadre.a, dessinCadre.b) : cadreDessine;
                        if (!c) return <div className="absolute inset-0" style={{ background: 'rgba(0,0,0,0.25)' }} />;
                        return (
                          <>
                            <div className="absolute inset-0" style={{ background: 'rgba(0,0,0,0.55)' }} />
                            <div
                              className="absolute"
                              style={{
                                left: `${c.x * 100}%`,
                                top: `${c.y * 100}%`,
                                width: `${c.w * 100}%`,
                                height: `${c.h * 100}%`,
                                boxShadow: '0 0 0 9999px rgba(0,0,0,0.55)',
                                outline: '2px solid #fff',
                                background: 'transparent',
                              }}
                            />
                          </>
                        );
                      })()}
                    </div>
                  )}
                </div>
              ) : (
                <div className="w-full h-full rounded-md overflow-hidden flex items-center justify-center cursor-pointer" style={{ background: 'rgba(255,255,255,0.04)' }}>
                  <img src={p.thumb} alt="" draggable={false} className="max-w-full max-h-full object-contain rounded-md" />
                </div>
              )}
            </div>
          );
        })}
        {total > 1 && !seul && (
          <button type="button" onClick={() => aller(1)} aria-label="Photo suivante" className="absolute right-3 top-1/2 -translate-y-1/2 z-20 rounded-full p-2 cursor-pointer" style={{ background: 'rgba(255,255,255,0.12)', color: '#fff' }}>
            <ChevronRight size={20} />
          </button>
        )}

        {texteLu && photo.ocrText && (
          <div data-panneau="texte-lu" className="absolute right-4 top-3 z-30 max-w-sm max-h-[70%] overflow-y-auto rounded-xl p-3 text-xs whitespace-pre-wrap" style={{ background: 'rgba(0,0,0,0.85)', color: 'rgba(255,255,255,0.9)', border: '1px solid rgba(255,255,255,0.15)' }}>
            <div className="mb-1 font-medium" style={{ color: 'rgba(255,255,255,0.6)' }}>Texte lu par Vision</div>
            {photo.ocrText}
          </div>
        )}

        {choixNote && (
          <div data-panneau="note" className="absolute right-4 top-3 z-30 w-80 max-h-[70%] overflow-y-auto rounded-xl p-2 text-sm" style={{ background: 'rgba(0,0,0,0.9)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)' }}>
            <div className="px-2 py-1 text-[11px]" style={{ color: 'rgba(255,255,255,0.6)' }}>Mettre cette photo à la fin de…</div>
            {notes === null ? (
              <div className="px-2 py-3"><Loader2 size={14} className="animate-spin" /></div>
            ) : notes.length === 0 ? (
              <div className="px-2 py-3 text-xs" style={{ color: 'rgba(255,255,255,0.6)' }}>Aucune note. Crée-en une dans Notes.</div>
            ) : (
              notes.map((n) => (
                <button key={n.id} type="button" onClick={() => void mettreDansNote(n)} className="w-full text-left rounded-lg px-2 py-1.5 cursor-pointer hover:bg-white/10 truncate">
                  {n.title || 'Sans titre'}
                </button>
              ))
            )}
          </div>
        )}
      </div>

      {/* ── Pied : légende + tâche, ou la barre d'outils du mode ────── */}
      {mode === 'annoter' ? (
        <div className="flex flex-wrap items-center gap-2 px-4 py-2.5" style={{ background: 'rgba(0,0,0,0.6)', color: '#fff' }}>
          {(
            [
              ['arrow', 'Flèche'],
              ['rect', 'Rectangle'],
              ['ellipse', 'Cercle'],
              ['text', 'Texte'],
              ['highlight', 'Surligneur'],
              ['pen', 'Main levée'],
            ] as Array<[SuccesAnnotationType, string]>
          ).map(([t, nom]) => (
            <button key={t} type="button" onClick={() => setOutil(t)} aria-pressed={outil === t} className="rounded-lg px-2.5 py-1 text-xs cursor-pointer" style={{ background: outil === t ? 'var(--color-accent)' : 'rgba(255,255,255,0.1)' }}>
              {nom}
            </button>
          ))}
          <Separateur />
          {COULEURS_ANNOTATION.map((c) => (
            <button key={c} type="button" onClick={() => setCouleur(c)} aria-label={`Couleur ${c}`} aria-pressed={couleur === c} className="size-5 rounded-full cursor-pointer" style={{ background: c, boxShadow: couleur === c ? '0 0 0 2px #000, 0 0 0 4px #fff' : '0 0 0 1px rgba(255,255,255,0.4)' }} />
          ))}
          <Separateur />
          {EPAISSEURS.map((e) => (
            <button key={e.valeur} type="button" onClick={() => setEpaisseur(e.valeur)} aria-pressed={epaisseur === e.valeur} className="rounded-lg px-2 py-1 text-xs cursor-pointer" style={{ background: epaisseur === e.valeur ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.08)' }}>
              {e.label}
            </button>
          ))}
          <Separateur />
          <button type="button" onClick={() => { changerCalque(calque.slice(0, -1)); setSelection(null); }} disabled={calque.length === 0} className="rounded-lg px-2 py-1 text-xs cursor-pointer disabled:opacity-40 inline-flex items-center gap-1" style={{ background: 'rgba(255,255,255,0.1)' }}>
            <Undo2 size={13} /> Annuler la dernière
          </button>
          <button type="button" onClick={() => { changerCalque(calque.filter((a) => a.id !== selection)); setSelection(null); }} disabled={!selection} className="rounded-lg px-2 py-1 text-xs cursor-pointer disabled:opacity-40" style={{ background: 'rgba(255,255,255,0.1)' }}>
            Supprimer la sélection (⌫)
          </button>
          <span className="flex-1" />
          <button type="button" onClick={() => setMode('vue')} className="rounded-lg px-3 py-1 text-xs cursor-pointer font-medium" style={{ background: 'var(--color-accent)' }}>
            Terminer
          </button>
        </div>
      ) : mode === 'retouche' ? (
        <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-xs" style={{ background: 'rgba(0,0,0,0.6)', color: '#fff' }}>
          <span style={{ color: 'rgba(255,255,255,0.7)' }}>
            {cadreDessine ? 'Cadre prêt — applique-le, ou redessine.' : 'Dessine un rectangle sur la photo pour la recadrer. L’original est toujours gardé.'}
          </span>
          <span className="flex-1" />
          <button type="button" onClick={() => void retablirOriginal()} disabled={occupe || (!photo.rotation && !photo.crop)} className="rounded-lg px-2.5 py-1 cursor-pointer disabled:opacity-40" style={{ background: 'rgba(255,255,255,0.1)' }}>
            Rétablir l’original
          </button>
          <button type="button" onClick={() => { setMode('vue'); setCadreDessine(null); }} className="rounded-lg px-2.5 py-1 cursor-pointer" style={{ background: 'rgba(255,255,255,0.1)' }}>
            Annuler
          </button>
          <button type="button" onClick={() => void appliquerCadre()} disabled={!cadreDessine || occupe} className="rounded-lg px-3 py-1 cursor-pointer font-medium disabled:opacity-40" style={{ background: 'var(--color-accent)' }}>
            Appliquer le cadre
          </button>
        </div>
      ) : (
        <div className="grid gap-2 px-4 py-3 sm:grid-cols-[1fr_auto] items-center" style={{ background: 'rgba(0,0,0,0.5)' }}>
          <input
            value={legende}
            onChange={(e) => setLegende(e.target.value)}
            onBlur={enregistrerLegende}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            }}
            maxLength={500}
            placeholder="Une légende — ce que montre cette photo"
            aria-label="Légende"
            className="rounded-lg px-3 py-2 text-sm bg-transparent outline-none"
            style={{ border: '1px solid rgba(255,255,255,0.2)', color: '#fff' }}
          />
          <label className="flex items-center gap-2 text-xs" style={{ color: 'rgba(255,255,255,0.7)' }}>
            <Link2 size={13} />
            <select
              value={photo.taskId && tachesParId.has(photo.taskId) ? photo.taskId : ''}
              onChange={(e) => void patcher({ taskId: e.target.value }, e.target.value ? 'Photo liée à la tâche' : 'Photo détachée')}
              disabled={occupe}
              aria-label="Lier à une tâche"
              className="rounded-lg px-2 py-2 text-xs outline-none max-w-[280px]"
              style={{ background: 'rgba(255,255,255,0.08)', color: '#fff', border: '1px solid rgba(255,255,255,0.2)' }}
            >
              <option value="" style={{ color: '#000' }}>Aucune tâche liée</option>
              {aplaties.map(({ tache, profondeur }) => (
                <option key={tache.id} value={tache.id} style={{ color: '#000' }}>
                  {'  '.repeat(profondeur)}{tache.title}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
    </div>
  );
}

function Bouton({
  titre,
  onClick,
  disabled,
  actif,
  couleur,
  children,
}: {
  titre: string;
  onClick: () => void;
  disabled?: boolean;
  actif?: boolean;
  couleur?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={titre}
      title={titre}
      aria-pressed={actif}
      className="rounded-lg p-2 cursor-pointer disabled:opacity-40"
      style={{ color: couleur ?? '#fff', background: actif ? 'var(--color-accent)' : undefined }}
    >
      {children}
    </button>
  );
}

function Separateur() {
  return <span className="w-px h-5 mx-1 shrink-0" style={{ background: 'rgba(255,255,255,0.2)' }} />;
}
