// Les piles de photos d'un projet — l'écran.
//
// Une pile fermée montre ses trois dernières photos empilées, légèrement
// tournées, avec son nom et son compte. Un clic l'ouvre : les trois cartes
// glissent vers leur place dans la grille (FLIP), les autres apparaissent
// derrière. Une photo cliquée s'ouvre plein cadre, avec sa légende, sa
// tâche et les flèches pour feuilleter.
//
// La logique pure (inclinaisons, teinte, vérification d'un fichier) vit dans
// `photos.ts` ; la lecture des fichiers dans `photosClient.ts`.

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowLeft,
  Camera,
  CheckSquare,
  FileDown,
  ImagePlus,
  Link2,
  Loader2,
  Pencil,
  Plus,
  Search,
  Square,
  Star,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { toast } from 'sonner';

import { useConfirm } from '../../components/ConfirmDialog';
import {
  addSuccesPhoto,
  createSuccesPhotoPile,
  deleteSuccesPhoto,
  deleteSuccesPhotoPile,
  listSuccesPhotoPiles,
  listSuccesPhotos,
  ocrSuccesPhoto,
  rechercherSuccesPhotos,
  reorderSuccesPhotos,
  updateSuccesPhoto,
  updateSuccesPhotoPile,
} from './api';
import { PhotoPleinCadre } from './PhotoPleinCadre';
import {
  TYPE_GLISSER_PHOTO,
  deplacerVers,
  dispositionPile,
  estGlisserDePhoto,
  nomFichierPdf,
  teinteAvecAlpha,
} from './photos';
import { fichiersImages, preparerPhoto } from './photosClient';
import { exporterPdf } from './photosExport';
import type { SuccesPhoto, SuccesPhotoPile, SuccesTask } from './types';

interface Props {
  projectId: string;
  /** Les tâches du projet, pour relier une photo à l'une d'elles. */
  tasks: SuccesTask[];
  /**
   * Une tâche dont on veut voir les photos (depuis la Ligne). La section
   * ouvre la première pile qui en contient et filtre dessus.
   */
  tacheAOuvrir?: string | null;
  onTacheOuverte?: () => void;
  /** Prévenir le parent quand les comptes par tâche changent. */
  onParTache?: (parTache: Record<string, number>) => void;
}

const CARTE_L = 104;
const CARTE_H = 118;

/**
 * Les photos dont on a déjà tenté la lecture de texte dans cette session.
 * Celles d'avant l'OCR (13 septembre 2026) n'ont pas de texte ; on les lit
 * à l'ouverture de leur pile, une fois — pas à chaque rechargement, et pas
 * en boucle sur une machine sans Vision.
 */
const ocrTentees = new Set<string>();

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

export function PilesPhotos({
  projectId,
  tasks,
  tacheAOuvrir,
  onTacheOuverte,
  onParTache,
}: Props) {
  const confirm = useConfirm();
  const [piles, setPiles] = useState<SuccesPhotoPile[]>([]);
  const [chargement, setChargement] = useState(true);
  const [nouvelleEnCours, setNouvelleEnCours] = useState(false);
  const [nomNouvelle, setNomNouvelle] = useState('');
  /** Les fichiers déposés sur la pile vide, en attente d'un nom. */
  const [fichiersEnAttente, setFichiersEnAttente] = useState<File[]>([]);
  const [survolee, setSurvolee] = useState<string | null>(null);
  /** `{ fait, total }` pendant un envoi ; `null` sinon. */
  const [envoi, setEnvoi] = useState<{ fait: number; total: number } | null>(null);
  const [ouverte, setOuverte] = useState<string | null>(null);
  const [filtreTache, setFiltreTache] = useState<string | null>(null);
  /** Le pop-up des catégories — la fiche ne montre qu'une pile fermée. */
  const [popup, setPopup] = useState(false);
  // La recherche dans les légendes, les noms et le texte lu (idée 8).
  const [requete, setRequete] = useState('');
  const [resultats, setResultats] = useState<Array<SuccesPhoto & { pileName: string }> | null>(null);
  const [rechercheEnVol, setRechercheEnVol] = useState(false);
  const [resultatOuvert, setResultatOuvert] = useState<number>(-1);
  /** Les rectangles des cartes de la pile qu'on vient d'ouvrir, pour le FLIP. */
  const departs = useRef<Map<string, DOMRect>>(new Map());
  const cartes = useRef<Map<string, HTMLElement>>(new Map());
  // Les rappels du parent, lus au moment de l'appel : un parent qui recrée
  // sa fonction à chaque rendu relancerait sinon le chargement — et
  // refermerait la pile ouverte — à chaque frappe dans un autre champ.
  const onParTacheRef = useRef(onParTache);
  onParTacheRef.current = onParTache;
  const onTacheOuverteRef = useRef(onTacheOuverte);
  onTacheOuverteRef.current = onTacheOuverte;
  const rechercheEnCours = useRef(false);

  const tachesParId = useMemo(() => new Map(tasks.map((t) => [t.id, t])), [tasks]);
  const totalPhotos = piles.reduce((n, p) => n + p.count, 0);

  // La recherche part 300 ms après la dernière frappe ; une réponse en
  // retard sur une requête plus courte est jetée.
  useEffect(() => {
    const q = requete.trim();
    if (!q) {
      setResultats(null);
      setRechercheEnVol(false);
      return;
    }
    let annule = false;
    setRechercheEnVol(true);
    const id = window.setTimeout(async () => {
      try {
        const trouvees = await rechercherSuccesPhotos(projectId, q);
        if (!annule) setResultats(trouvees);
      } catch (error) {
        if (!annule) {
          toast.error('La recherche a échoué.', {
            description: error instanceof Error ? error.message : String(error),
          });
        }
      } finally {
        if (!annule) setRechercheEnVol(false);
      }
    }, 300);
    return () => {
      annule = true;
      window.clearTimeout(id);
    };
  }, [requete, projectId]);

  const charger = useCallback(async () => {
    try {
      const resultat = await listSuccesPhotoPiles(projectId);
      setPiles(resultat.piles);
      onParTacheRef.current?.(resultat.parTache);
    } catch (error) {
      toast.error('Les photos ne peuvent pas être chargées.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setChargement(false);
    }
  }, [projectId]);

  useEffect(() => {
    setChargement(true);
    setOuverte(null);
    void charger();
  }, [charger]);

  // Depuis la Ligne : « voir les photos de cette station ».
  useEffect(() => {
    if (!tacheAOuvrir || chargement || rechercheEnCours.current) return;
    rechercheEnCours.current = true;
    let annule = false;
    (async () => {
      for (const pile of piles) {
        if (pile.count === 0) continue;
        try {
          const { photos } = await listSuccesPhotos(pile.id);
          if (annule) return;
          if (photos.some((p) => p.taskId === tacheAOuvrir)) {
            setFiltreTache(tacheAOuvrir);
            setPopup(true);
            setOuverte(pile.id);
            break;
          }
        } catch {
          // Une pile illisible ne bloque pas la recherche dans les autres.
        }
      }
      rechercheEnCours.current = false;
      onTacheOuverteRef.current?.();
    })();
    return () => {
      annule = true;
    };
  }, [tacheAOuvrir, chargement, piles]);

  const envoyer = useCallback(
    async (pileId: string, fichiers: File[], taskId = '') => {
      if (fichiers.length === 0) return;
      setEnvoi({ fait: 0, total: fichiers.length });
      let refusees = 0;
      for (let i = 0; i < fichiers.length; i += 1) {
        try {
          const envoiPhoto = await preparerPhoto(fichiers[i]);
          const ajoutee = await addSuccesPhoto(pileId, { ...envoiPhoto, taskId });
          // La lecture du texte (Vision) suit, sans retenir l'envoi : elle
          // prend une seconde par photo, et son absence n'est pas une erreur
          // — sur une machine sans Vision, la recherche se fera sur les
          // légendes et les noms.
          void ocrSuccesPhoto(ajoutee.id).catch(() => undefined);
        } catch (error) {
          refusees += 1;
          toast.error(`« ${fichiers[i].name} » n'a pas été ajoutée.`, {
            description: error instanceof Error ? error.message : String(error),
          });
        }
        setEnvoi({ fait: i + 1, total: fichiers.length });
      }
      setEnvoi(null);
      const ajoutees = fichiers.length - refusees;
      if (ajoutees > 0) {
        toast.success(ajoutees === 1 ? 'Photo ajoutée' : `${ajoutees} photos ajoutées`, {
          description: 'Enregistrées localement sur ce Mac.',
        });
      }
      await charger();
    },
    [charger],
  );

  const creerPile = async (nom: string, fichiers: File[] = []) => {
    const propre = nom.trim();
    if (!propre) return;
    try {
      const pile = await createSuccesPhotoPile(projectId, propre);
      setNouvelleEnCours(false);
      setNomNouvelle('');
      setFichiersEnAttente([]);
      await charger();
      if (fichiers.length > 0) await envoyer(pile.id, fichiers);
    } catch (error) {
      toast.error("La pile n'a pas été créée.", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const ouvrirPile = (pile: SuccesPhotoPile) => {
    if (fichiersEnAttente.length > 0) {
      const fichiers = fichiersEnAttente;
      setFichiersEnAttente([]);
      setNouvelleEnCours(false);
      void envoyer(pile.id, fichiers);
      return;
    }
    departs.current = new Map();
    for (const apercu of pile.apercus) {
      const el = cartes.current.get(apercu.id);
      if (el) departs.current.set(apercu.id, el.getBoundingClientRect());
    }
    setFiltreTache(null);
    setOuverte(pile.id);
  };

  const deposer = (pileId: string | null) => (e: DragEvent) => {
    e.preventDefault();
    setSurvolee(null);
    const fichiers = fichiersImages(e.dataTransfer);
    if (fichiers.length === 0) {
      toast.info('Rien à ranger : ce n’est pas une image.');
      return;
    }
    if (pileId) {
      void envoyer(pileId, fichiers);
    } else {
      // Déposé sur la pile vide : on demande le nom, puis on range.
      setFichiersEnAttente(fichiers);
      setNouvelleEnCours(true);
    }
  };

  const enSurvol = (cle: string | null) => (e: DragEvent) => {
    e.preventDefault();
    if (survolee !== cle) setSurvolee(cle);
  };

  const pileOuverte = ouverte ? piles.find((p) => p.id === ouverte) ?? null : null;

  const fermerPopup = () => {
    setPopup(false);
    setNouvelleEnCours(false);
    setNomNouvelle('');
    setFichiersEnAttente([]);
    setRequete('');
  };

  // Échap ferme le pop-up quand rien n'est ouvert par-dessus — écouté sur
  // la fenêtre, le focus n'étant pas forcément dans la boîte.
  const fermerPopupRef = useRef(fermerPopup);
  fermerPopupRef.current = fermerPopup;
  useEffect(() => {
    if (!popup || ouverte || resultatOuvert >= 0) return;
    const surTouche = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const cible = e.target as HTMLElement | null;
      if (cible && (cible.tagName === 'INPUT' || cible.tagName === 'TEXTAREA')) return;
      e.stopPropagation();
      fermerPopupRef.current();
    };
    window.addEventListener('keydown', surTouche);
    return () => window.removeEventListener('keydown', surTouche);
  }, [popup, ouverte, resultatOuvert]);

  return (
    <>
      <PileFermee
        piles={piles}
        totalPhotos={totalPhotos}
        chargement={chargement}
        envoi={envoi}
        onOuvrir={() => setPopup(true)}
        onDeposer={(fichiers) => {
          // Déposées sur la pile fermée : le pop-up s'ouvre pour choisir
          // la catégorie — ou en créer une.
          setFichiersEnAttente(fichiers);
          setPopup(true);
          if (piles.length === 0) setNouvelleEnCours(true);
        }}
      />

      {popup &&
        createPortal(
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(0,0,0,0.6)' }}
            onClick={fermerPopup}
            role="presentation"
          >
            <section
              role="dialog"
              aria-modal="true"
              aria-label="Photos du projet"
              className="w-full max-w-4xl rounded-2xl flex flex-col overflow-hidden outline-none"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                maxHeight: 'min(88vh, 860px)',
              }}
              onClick={(e) => e.stopPropagation()}
            >
      <div className="flex items-center justify-between gap-3 px-4 py-3 shrink-0 flex-wrap" style={{ borderBottom: '1px solid var(--color-border)' }}>
        <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          <Camera size={14} style={{ color: 'var(--color-accent)' }} />
          <span className="font-medium tracking-[0.12em] uppercase" style={{ color: 'var(--color-text-secondary)' }}>
            Photos
          </span>
          {!chargement && (
            <span>
              · {piles.length} {piles.length === 1 ? 'pile' : 'piles'} · {totalPhotos}{' '}
              {totalPhotos === 1 ? 'photo' : 'photos'}
            </span>
          )}
          {envoi && (
            <span className="flex items-center gap-1" style={{ color: 'var(--color-accent)' }}>
              <Loader2 size={12} className="animate-spin" />
              {envoi.fait}/{envoi.total}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {totalPhotos > 0 && (
            <label className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}>
              {rechercheEnVol ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
              <input
                value={requete}
                onChange={(e) => setRequete(e.target.value)}
                placeholder="Chercher dans les photos…"
                aria-label="Chercher dans les photos (légendes, noms, texte lu)"
                className="bg-transparent outline-none w-44"
                style={{ color: 'var(--color-text)' }}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setRequete('');
                }}
              />
              {requete && (
                <button type="button" onClick={() => setRequete('')} aria-label="Effacer la recherche" className="cursor-pointer">
                  <X size={12} />
                </button>
              )}
            </label>
          )}
          <button
            type="button"
            onClick={() => setNouvelleEnCours(true)}
            className="flex items-center gap-1 text-xs cursor-pointer rounded-lg px-2 py-1"
            style={{ color: 'var(--color-accent)' }}
            aria-label="Nouvelle pile"
          >
            <Plus size={13} />
            Nouvelle pile
          </button>
          <button type="button" onClick={fermerPopup} aria-label="Fermer" title="Fermer (Échap)" className="rounded-lg p-2 cursor-pointer" style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-surface)' }}>
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
      {fichiersEnAttente.length > 0 && !nouvelleEnCours && (
        <div className="mb-4 flex items-center gap-2 rounded-xl px-3 py-2 text-xs" style={{ border: '1px solid var(--color-accent)', color: 'var(--color-text)' }}>
          <ImagePlus size={14} style={{ color: 'var(--color-accent)' }} />
          <span className="flex-1">
            {fichiersEnAttente.length} {fichiersEnAttente.length === 1 ? 'photo à ranger' : 'photos à ranger'} — clique la pile qui doit les recevoir, ou crée-en une.
          </span>
          <button type="button" onClick={() => setFichiersEnAttente([])} className="cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>
            Annuler
          </button>
        </div>
      )}

      {resultats !== null && (
        <div className="mb-4 rounded-xl p-3" style={{ border: '1px solid var(--color-border)', background: 'var(--color-surface)' }}>
          <div className="text-xs mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            {resultats.length === 0
              ? `Rien pour « ${requete.trim()} » — ni dans les légendes, ni dans les noms, ni dans le texte lu.`
              : `${resultats.length} ${resultats.length === 1 ? 'photo' : 'photos'} pour « ${requete.trim()} »`}
          </div>
          {resultats.length > 0 && (
            <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))' }}>
              {resultats.map((photo, i) => (
                <button
                  key={photo.id}
                  type="button"
                  onClick={() => setResultatOuvert(i)}
                  className="rounded-lg overflow-hidden cursor-pointer text-left"
                  style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}
                  aria-label={`${photo.caption || photo.fileName} — pile ${photo.pileName}`}
                >
                  <img src={photo.thumb} alt="" draggable={false} className="w-full aspect-square object-cover" />
                  <div className="px-1.5 py-1 text-[10px] truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                    {photo.pileName}
                    {photo.caption ? ` · ${photo.caption}` : ''}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div
        className="grid gap-4"
        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))' }}
      >
        {piles.map((pile) => {
          const disposition = dispositionPile(pile.apercus);
          const liseré = teinteAvecAlpha(pile.tint, 0.55);
          const enSurvolDepot = survolee === pile.id;
          return (
            <div
              key={pile.id}
              onDragOver={enSurvol(pile.id)}
              onDragLeave={() => setSurvolee((s) => (s === pile.id ? null : s))}
              onDrop={deposer(pile.id)}
              className="flex flex-col items-center"
            >
              <button
                type="button"
                onClick={() => ouvrirPile(pile)}
                aria-label={`Ouvrir la pile « ${pile.name} » — ${pile.count} photo(s)`}
                className="relative cursor-pointer transition-transform duration-200 hover:-translate-y-1"
                style={{ width: 132, height: 150 }}
              >
                {disposition.length === 0 ? (
                  <div
                    className="absolute rounded-md flex items-center justify-center"
                    style={{
                      left: 14,
                      top: 8,
                      width: CARTE_L,
                      height: CARTE_H,
                      border: `1px dashed ${enSurvolDepot ? 'var(--color-accent)' : 'var(--color-border)'}`,
                      color: 'var(--color-text-tertiary)',
                      background: 'var(--color-surface)',
                    }}
                  >
                    <ImagePlus size={20} />
                  </div>
                ) : (
                  disposition.map((carte) => (
                    <div
                      key={carte.photo.id}
                      ref={(el) => {
                        if (el) cartes.current.set(carte.photo.id, el);
                        else cartes.current.delete(carte.photo.id);
                      }}
                      className="absolute rounded-md overflow-hidden"
                      style={{
                        left: 14,
                        top: 8,
                        width: CARTE_L,
                        height: CARTE_H,
                        zIndex: carte.z,
                        transform: `rotate(${carte.rotation}deg) translate(${carte.dx}px, ${carte.dy}px)`,
                        background: 'var(--color-surface)',
                        border: `1px solid ${enSurvolDepot ? 'var(--color-accent)' : liseré ?? 'var(--color-border)'}`,
                        padding: '5px 5px 18px',
                        boxSizing: 'border-box',
                      }}
                    >
                      <img
                        src={carte.photo.thumb}
                        alt=""
                        draggable={false}
                        className="w-full h-full object-cover rounded-[3px]"
                      />
                    </div>
                  ))
                )}
              </button>
              <p className="mt-1.5 text-sm font-medium text-center truncate max-w-full" style={{ color: 'var(--color-text)' }}>
                {pile.name}
              </p>
              <p className="text-[11px] text-center" style={{ color: 'var(--color-text-tertiary)' }}>
                {pile.count} {pile.count === 1 ? 'photo' : 'photos'}
              </p>
            </div>
          );
        })}

        <div
          onDragOver={enSurvol('nouvelle')}
          onDragLeave={() => setSurvolee((s) => (s === 'nouvelle' ? null : s))}
          onDrop={deposer(null)}
          className="flex flex-col items-center"
        >
          {nouvelleEnCours ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void creerPile(nomNouvelle, fichiersEnAttente);
              }}
              className="flex flex-col items-center gap-2"
              style={{ width: 132, paddingTop: 8 }}
            >
              <input
                autoFocus
                value={nomNouvelle}
                onChange={(e) => setNomNouvelle(e.target.value)}
                maxLength={80}
                placeholder="Nom de la pile"
                aria-label="Nom de la nouvelle pile"
                className="w-full rounded-lg px-2 py-1.5 text-sm bg-transparent outline-none"
                style={{ border: '1px solid var(--color-accent)', color: 'var(--color-text)' }}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') {
                    setNouvelleEnCours(false);
                    setNomNouvelle('');
                    setFichiersEnAttente([]);
                  }
                }}
              />
              {fichiersEnAttente.length > 0 && (
                <span className="text-[11px] text-center" style={{ color: 'var(--color-text-tertiary)' }}>
                  {fichiersEnAttente.length} {fichiersEnAttente.length === 1 ? 'photo à ranger' : 'photos à ranger'}
                </span>
              )}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setNouvelleEnCours(false);
                    setNomNouvelle('');
                    setFichiersEnAttente([]);
                  }}
                  className="text-xs px-2 py-1 cursor-pointer"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  disabled={!nomNouvelle.trim()}
                  className="text-xs px-3 py-1 rounded-lg cursor-pointer disabled:opacity-50"
                  style={{ background: 'var(--color-accent)', color: '#fff' }}
                >
                  Créer
                </button>
              </div>
            </form>
          ) : (
            <>
              <button
                type="button"
                onClick={() => setNouvelleEnCours(true)}
                aria-label="Créer une pile"
                className="relative cursor-pointer"
                style={{ width: 132, height: 150 }}
              >
                <div
                  className="absolute rounded-md flex flex-col items-center justify-center gap-1.5"
                  style={{
                    left: 14,
                    top: 8,
                    width: CARTE_L,
                    height: CARTE_H,
                    border: `1px dashed ${survolee === 'nouvelle' ? 'var(--color-accent)' : 'var(--color-border)'}`,
                    color: survolee === 'nouvelle' ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
                  }}
                >
                  <Plus size={22} />
                  <span className="text-[11px]">Nouvelle pile</span>
                </div>
              </button>
              <p className="mt-1.5 text-[11px] text-center" style={{ color: 'var(--color-text-tertiary)' }}>
                ou glisse des photos ici
              </p>
            </>
          )}
        </div>
      </div>
      </div>
      <div className="px-4 py-2 text-[11px] shrink-0" style={{ borderTop: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}>
        Clique une pile pour voir ses photos · glisse des images sur une pile pour les y ranger · ⌘V colle une capture dans une pile ouverte
      </div>
            </section>
          </div>,
          document.body,
        )}

      {resultats && resultatOuvert >= 0 && resultats[resultatOuvert] && (
        <PhotoPleinCadre
          photos={resultats}
          index={resultatOuvert}
          pile={null}
          tasks={tasks}
          tachesParId={tachesParId}
          onAller={setResultatOuvert}
          onFermer={() => setResultatOuvert(-1)}
          onMisAJour={async () => {
            const q = requete.trim();
            if (q) setResultats(await rechercherSuccesPhotos(projectId, q));
            await charger();
          }}
          onSupprimee={async () => {
            setResultatOuvert(-1);
            const q = requete.trim();
            if (q) setResultats(await rechercherSuccesPhotos(projectId, q));
            await charger();
          }}
          confirm={confirm}
        />
      )}

      {pileOuverte && (
        <PileOuverte
          pile={pileOuverte}
          piles={piles}
          tasks={tasks}
          tachesParId={tachesParId}
          filtreTache={filtreTache}
          departs={departs.current}
          envoi={envoi}
          onFiltre={setFiltreTache}
          onChoisir={(id) => {
            departs.current = new Map();
            setOuverte(id);
          }}
          onFermer={() => {
            setOuverte(null);
            setPopup(false);
          }}
          onRetour={() => setOuverte(null)}
          onEnvoyer={(fichiers) => envoyer(pileOuverte.id, fichiers, filtreTache ?? '')}
          onRenommer={async (nom) => {
            try {
              await updateSuccesPhotoPile(pileOuverte.id, { name: nom });
              await charger();
              toast.success('Pile renommée');
            } catch (error) {
              toast.error("La pile n'a pas été renommée.", {
                description: error instanceof Error ? error.message : String(error),
              });
            }
          }}
          onSupprimerPile={async () => {
            const ok = await confirm({
              title: `Supprimer la pile « ${pileOuverte.name} » ?`,
              description:
                pileOuverte.count > 0
                  ? `Ses ${pileOuverte.count} photo(s) seront effacées du disque. Ça ne se récupère pas.`
                  : 'Elle est vide.',
              confirmLabel: 'Supprimer',
              keepLabel: 'Garder',
              tone: 'danger',
            });
            if (!ok) return;
            try {
              await deleteSuccesPhotoPile(pileOuverte.id);
              setOuverte(null);
              await charger();
              toast.success('Pile supprimée');
            } catch (error) {
              toast.error('La suppression a échoué.', {
                description: error instanceof Error ? error.message : String(error),
              });
            }
          }}
          onChangement={charger}
          confirm={confirm}
        />
      )}
    </>
  );
}

// ── La pile fermée, sur la fiche ───────────────────────────────────────
//
// Une carte par catégorie, empilées derrière la première — l'option
// « Empilées derrière » de la démonstration du 13 septembre 2026. Elle
// tient sous le dossier du projet ; tout le reste vit dans le pop-up.

function PileFermee({
  piles,
  totalPhotos,
  chargement,
  envoi,
  onOuvrir,
  onDeposer,
}: {
  piles: SuccesPhotoPile[];
  totalPhotos: number;
  chargement: boolean;
  envoi: { fait: number; total: number } | null;
  onOuvrir: () => void;
  onDeposer: (fichiers: File[]) => void;
}) {
  const [survol, setSurvol] = useState(false);
  // Devant : la catégorie la plus récemment touchée qui a des photos ; les
  // vides derrière. Une pile vide devant montrait une case en pointillé à
  // la place des photos (constaté à la première ouverture).
  const cartes = [...piles]
    .sort((a, b) => {
      const va = a.apercus.length > 0 ? 1 : 0;
      const vb = b.apercus.length > 0 ? 1 : 0;
      return vb - va || b.updatedAtMs - a.updatedAtMs;
    })
    .slice(0, 4);
  const legende = chargement
    ? '…'
    : piles.length === 0
      ? 'Aucune photo'
      : `${piles.length} ${piles.length === 1 ? 'pile' : 'piles'} · ${totalPhotos} ${totalPhotos === 1 ? 'photo' : 'photos'}`;
  return (
    <div
      className="flex flex-col items-center mt-3"
      onDragOver={(e) => {
        if (estGlisserDePhoto(e.dataTransfer.types)) return;
        e.preventDefault();
        if (!survol) setSurvol(true);
      }}
      onDragLeave={() => setSurvol(false)}
      onDrop={(e) => {
        e.preventDefault();
        setSurvol(false);
        const fichiers = fichiersImages(e.dataTransfer);
        if (fichiers.length === 0) {
          toast.info('Rien à ranger : ce n’est pas une image.');
          return;
        }
        onDeposer(fichiers);
      }}
    >
      <button
        type="button"
        onClick={onOuvrir}
        aria-label={`Photos du projet — ${legende}`}
        className="relative cursor-pointer transition-transform duration-200 hover:-translate-y-1 group"
        style={{ width: 160, height: 176 }}
      >
        {cartes.length === 0 ? (
          <div
            className="absolute rounded-md flex flex-col items-center justify-center gap-1.5"
            style={{
              left: 28,
              top: 40,
              width: CARTE_L,
              height: CARTE_H,
              border: `1px dashed ${survol ? 'var(--color-accent)' : 'var(--color-border)'}`,
              color: survol ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
              background: 'var(--color-surface)',
            }}
          >
            <Camera size={20} />
            <span className="text-[11px]">Photos</span>
          </div>
        ) : (
          cartes.map((pile, i) => {
            // i = 0 devant. Les suivantes reculent : plus haut, plus petites,
            // plus pâles — on devine la profondeur sans lire.
            const profondeur = i;
            const apercu = pile.apercus[0];
            const liseré = teinteAvecAlpha(pile.tint, 0.55);
            return (
              <div
                key={pile.id}
                className="absolute rounded-md overflow-hidden flex items-center justify-center"
                style={{
                  left: 28,
                  top: 40,
                  width: CARTE_L,
                  height: CARTE_H,
                  zIndex: 10 - profondeur,
                  // Chaque carte derrière dépasse de 12 px au-dessus de la
                  // précédente, un peu plus étroite et plus pâle.
                  transform: `translateY(${-profondeur * 12}px) scale(${1 - profondeur * 0.06})`,
                  opacity: 1 - profondeur * 0.2,
                  background: 'var(--color-surface)',
                  border: `1px solid ${survol ? 'var(--color-accent)' : liseré ?? 'var(--color-border)'}`,
                  padding: '5px 5px 18px',
                  boxSizing: 'border-box',
                  transition: 'transform 200ms ease',
                }}
              >
                {apercu ? (
                  <img src={apercu.thumb} alt="" draggable={false} className="w-full h-full object-cover rounded-[3px]" />
                ) : (
                  <ImagePlus size={18} style={{ color: 'var(--color-text-tertiary)' }} />
                )}
                {profondeur === 0 && (
                  <span
                    className="absolute left-0 right-0 bottom-0 px-1.5 text-[10px] truncate text-left"
                    style={{ color: 'var(--color-text-secondary)', lineHeight: '18px' }}
                  >
                    {pile.name}
                  </span>
                )}
              </div>
            );
          })
        )}
      </button>
      <p className="mt-1 text-[11px] text-center flex items-center gap-1" style={{ color: 'var(--color-text-tertiary)' }}>
        <Camera size={11} style={{ color: 'var(--color-accent)' }} />
        {legende}
        {envoi && (
          <span className="flex items-center gap-1" style={{ color: 'var(--color-accent)' }}>
            <Loader2 size={11} className="animate-spin" />
            {envoi.fait}/{envoi.total}
          </span>
        )}
      </p>
    </div>
  );
}

// ── La pile ouverte ────────────────────────────────────────────────────

interface PileOuverteProps {
  pile: SuccesPhotoPile;
  piles: SuccesPhotoPile[];
  tasks: SuccesTask[];
  tachesParId: Map<string, SuccesTask>;
  filtreTache: string | null;
  departs: Map<string, DOMRect>;
  envoi: { fait: number; total: number } | null;
  onFiltre: (taskId: string | null) => void;
  onChoisir: (pileId: string) => void;
  onFermer: () => void;
  /** Revenir aux piles du pop-up, sans tout refermer. */
  onRetour: () => void;
  onEnvoyer: (fichiers: File[]) => Promise<void>;
  onRenommer: (nom: string) => Promise<void>;
  onSupprimerPile: () => Promise<void>;
  onChangement: () => Promise<void>;
  confirm: ReturnType<typeof useConfirm>;
}

function PileOuverte({
  pile,
  piles,
  tasks,
  tachesParId,
  filtreTache,
  departs,
  envoi,
  onFiltre,
  onChoisir,
  onFermer,
  onRetour,
  onEnvoyer,
  onRenommer,
  onSupprimerPile,
  onChangement,
  confirm,
}: PileOuverteProps) {
  const [photos, setPhotos] = useState<SuccesPhoto[] | null>(null);
  const [renommage, setRenommage] = useState<string | null>(null);
  /** La photo qu'on tient au curseur, et celle dont elle prendra la place. */
  const [tenue, setTenue] = useState<string | null>(null);
  const [cible, setCible] = useState<string | null>(null);
  /** Les rectangles d'avant un rangement, pour faire glisser les cases. */
  const rectsAvant = useRef<Map<string, DOMRect> | null>(null);
  const [courante, setCourante] = useState<number>(-1);
  const [survol, setSurvol] = useState(false);
  /** Les photos cochées (⇧-clic, ⌘-clic ou la case), pour agir sur plusieurs. */
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [action, setAction] = useState<{ nom: string; fait: number; total: number } | null>(null);
  const cellules = useRef<Map<string, HTMLElement>>(new Map());
  const entree = useRef<HTMLInputElement>(null);
  const boite = useRef<HTMLDivElement>(null);
  // Les rappels du parent sont recréés à chacun de ses rendus. Les mettre
  // dans les dépendances de `recharger` faisait relire la pile à chaque
  // rendu de la fiche — neuf requêtes en cinq secondes, puis des 429 du
  // limiteur (constaté le 13 septembre 2026).
  const onFermerRef = useRef(onFermer);
  onFermerRef.current = onFermer;
  const onEnvoyerRef = useRef(onEnvoyer);
  onEnvoyerRef.current = onEnvoyer;
  const selectionRef = useRef<Set<string>>(new Set());
  selectionRef.current = selection;

  const recharger = useCallback(async () => {
    try {
      const { photos: liste } = await listSuccesPhotos(pile.id);
      setPhotos(liste);
      const aLire = liste.filter((p) => !p.ocrText && !ocrTentees.has(p.id));
      if (aLire.length > 0) {
        for (const p of aLire) ocrTentees.add(p.id);
        let lues = 0;
        for (const p of aLire) {
          try {
            const photo = await ocrSuccesPhoto(p.id);
            if (photo.ocrText) lues += 1;
          } catch {
            // Vision absente ou photo sans texte : on n'insiste pas.
            break;
          }
        }
        if (lues > 0) {
          const { photos: relue } = await listSuccesPhotos(pile.id);
          setPhotos(relue);
        }
      }
    } catch (error) {
      toast.error('Cette pile ne peut pas être ouverte.', {
        description: error instanceof Error ? error.message : String(error),
      });
      onFermerRef.current();
    }
  }, [pile.id]);

  useEffect(() => {
    setPhotos(null);
    setCourante(-1);
  }, [pile.id]);

  useEffect(() => {
    void recharger();
  }, [recharger, pile.updatedAtMs]);

  /** La pile dont la grille a déjà fait son entrée. */
  const derniereAnimee = useRef<string>('');

  // Le focus entre dans la boîte : Échap et les flèches y arrivent sans
  // qu'on ait à cliquer dedans d'abord.
  useEffect(() => {
    boite.current?.focus();
  }, []);

  // FLIP : chaque carte de la pile fermée part de son rectangle d'origine
  // et rejoint sa case dans la grille. Les autres cases s'estompent en
  // entrant. `useLayoutEffect` : avant la peinture, sinon la grille clignote
  // à sa place finale une image avant de partir de la pile.
  useLayoutEffect(() => {
    if (!photos || derniereAnimee.current === pile.id) return;
    derniereAnimee.current = pile.id;
    for (const [id, cellule] of cellules.current) {
      const depart = departs.get(id);
      const arrivee = cellule.getBoundingClientRect();
      if (depart && arrivee.width > 0) {
        const dx = depart.left - arrivee.left;
        const dy = depart.top - arrivee.top;
        const sx = depart.width / arrivee.width;
        const sy = depart.height / arrivee.height;
        cellule.animate(
          [
            { transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})`, opacity: 1 },
            { transform: 'translate(0, 0) scale(1, 1)', opacity: 1 },
          ],
          { duration: 380, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)', fill: 'backwards' },
        );
      } else {
        cellule.animate(
          [{ opacity: 0, transform: 'scale(0.96)' }, { opacity: 1, transform: 'scale(1)' }],
          { duration: 260, delay: 120, easing: 'ease-out', fill: 'backwards' },
        );
      }
    }
    // Une seule fois par ouverture : les rechargements suivants (légende,
    // suppression) ne doivent pas refaire voler la grille.
    departs.clear();
  }, [photos, departs, pile.id]);

  const visibles = useMemo(
    () => (photos ?? []).filter((p) => !filtreTache || p.taskId === filtreTache),
    [photos, filtreTache],
  );

  const ranger = async (source: string, cibleId: string) => {
    if (!photos) return;
    const avant = photos.map((p) => p.id);
    const apres = deplacerVers(avant, source, cibleId);
    if (apres === avant) return;
    // Les positions d'avant, pour que les cases glissent au lieu de sauter.
    const rects = new Map<string, DOMRect>();
    for (const [id, el] of cellules.current) rects.set(id, el.getBoundingClientRect());
    rectsAvant.current = rects;
    const parId = new Map(photos.map((p) => [p.id, p]));
    // Optimiste : la grille se range tout de suite ; le serveur confirme.
    setPhotos(apres.map((id) => parId.get(id)!));
    try {
      await reorderSuccesPhotos(pile.id, apres);
      await onChangement();
    } catch (error) {
      toast.error("L'ordre n'a pas été enregistré.", {
        description: error instanceof Error ? error.message : String(error),
      });
      await recharger();
    }
  };

  useLayoutEffect(() => {
    const rects = rectsAvant.current;
    if (!rects) return;
    rectsAvant.current = null;
    for (const [id, el] of cellules.current) {
      const depart = rects.get(id);
      if (!depart) continue;
      const arrivee = el.getBoundingClientRect();
      const dx = depart.left - arrivee.left;
      const dy = depart.top - arrivee.top;
      const sx = arrivee.width ? depart.width / arrivee.width : 1;
      const sy = arrivee.height ? depart.height / arrivee.height : 1;
      if (!dx && !dy && sx === 1 && sy === 1) continue;
      el.animate(
        [
          { transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})` },
          { transform: 'translate(0, 0) scale(1, 1)' },
        ],
        { duration: 300, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' },
      );
    }
  }, [photos]);

  // Coller une capture (⌘V) pendant que la pile est ouverte la range dedans.
  useEffect(() => {
    const surCollage = (e: ClipboardEvent) => {
      if (courante >= 0) return;
      const cible = e.target as HTMLElement | null;
      if (cible && (cible.tagName === 'INPUT' || cible.tagName === 'TEXTAREA')) return;
      const fichiers = fichiersImages(e.clipboardData);
      if (fichiers.length === 0) return;
      e.preventDefault();
      void onEnvoyerRef.current(fichiers);
    };
    window.addEventListener('paste', surCollage);
    return () => window.removeEventListener('paste', surCollage);
  }, [courante]);

  useEffect(() => {
    if (courante >= 0) return;
    const surTouche = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const cible = e.target as HTMLElement | null;
      // Un champ ouvert (renommage) se ferme par son propre Échap.
      if (cible && (cible.tagName === 'INPUT' || cible.tagName === 'TEXTAREA' || cible.tagName === 'SELECT')) return;
      e.stopPropagation();
      if (selectionRef.current.size > 0) {
        setSelection(new Set());
        return;
      }
      onFermerRef.current();
    };
    window.addEventListener('keydown', surTouche);
    return () => window.removeEventListener('keydown', surTouche);
  }, [courante]);

  const tacheFiltre = filtreTache ? tachesParId.get(filtreTache) : null;

  // La sélection ne survit ni à un changement de pile, ni à un rechargement
  // qui a fait disparaître des photos.
  useEffect(() => {
    setSelection(new Set());
  }, [pile.id]);
  useEffect(() => {
    if (!photos) return;
    const ids = new Set(photos.map((p) => p.id));
    setSelection((s) => {
      const suite = new Set([...s].filter((id) => ids.has(id)));
      return suite.size === s.size ? s : suite;
    });
  }, [photos]);

  const basculer = (id: string) => {
    setSelection((s) => {
      const suite = new Set(s);
      if (suite.has(id)) suite.delete(id);
      else suite.add(id);
      return suite;
    });
  };
  const selectionnees = (photos ?? []).filter((p) => selection.has(p.id));

  const surChacune = async (
    nom: string,
    cibles: SuccesPhoto[],
    faire: (p: SuccesPhoto) => Promise<unknown>,
    succes: string,
  ) => {
    setAction({ nom, fait: 0, total: cibles.length });
    let echecs = 0;
    for (let i = 0; i < cibles.length; i += 1) {
      try {
        await faire(cibles[i]);
      } catch {
        echecs += 1;
      }
      setAction({ nom, fait: i + 1, total: cibles.length });
    }
    setAction(null);
    setSelection(new Set());
    await recharger();
    await onChangement();
    if (echecs) toast.error(`${echecs} sur ${cibles.length} n'ont pas pu être traitées.`);
    else toast.success(succes);
  };

  const supprimerSelection = async () => {
    const ok = await confirm({
      title: `Supprimer ${selectionnees.length} photo(s) ?`,
      description: 'Elles seront effacées du disque. Ça ne se récupère pas.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!ok) return;
    await surChacune('Suppression', selectionnees, (p) => deleteSuccesPhoto(p.id), 'Photos supprimées');
  };

  const deplacerSelection = async (pileId: string) => {
    const cible = piles.find((p) => p.id === pileId);
    await surChacune(
      'Déplacement',
      selectionnees,
      (p) => updateSuccesPhoto(p.id, { pileId }),
      `Déplacées vers « ${cible?.name ?? 'la pile'} »`,
    );
  };

  const lierSelection = async (taskId: string) => {
    await surChacune(
      'Lien',
      selectionnees,
      (p) => updateSuccesPhoto(p.id, { taskId }),
      taskId ? 'Photos liées à la tâche' : 'Photos détachées',
    );
  };

  const exporter = async (cibles: SuccesPhoto[], titre: string) => {
    if (cibles.length === 0) return;
    setAction({ nom: 'Export PDF', fait: 0, total: cibles.length });
    try {
      const chemin = await exporterPdf(cibles, titre, nomFichierPdf(titre), (fait, total) =>
        setAction({ nom: 'Export PDF', fait, total }),
      );
      if (chemin) toast.success('PDF exporté', { description: chemin });
    } catch (error) {
      toast.error("L'export a échoué.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setAction(null);
    }
  };

  const tachesAplaties = useMemo(() => {
    const parParent = new Map<string, SuccesTask[]>();
    for (const t of tasks) {
      const liste = parParent.get(t.parentTaskId || '') ?? [];
      liste.push(t);
      parParent.set(t.parentTaskId || '', liste);
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
  }, [tasks]);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.6)' }}
      onClick={onFermer}
      role="presentation"
    >
      <div
        ref={boite}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={`Pile « ${pile.name} »`}
        className="w-full max-w-4xl rounded-2xl flex flex-col overflow-hidden outline-none"
        style={{
          background: 'var(--color-bg-secondary)',
          border: `1px solid ${survol ? 'var(--color-accent)' : 'var(--color-border)'}`,
          maxHeight: 'min(88vh, 860px)',
        }}
        onClick={(e) => e.stopPropagation()}
        onDragOver={(e) => {
          // Une photo de la grille qu'on range n'est pas un dépôt de fichiers.
          if (estGlisserDePhoto(e.dataTransfer.types)) return;
          e.preventDefault();
          if (!survol) setSurvol(true);
        }}
        onDragLeave={() => setSurvol(false)}
        onDrop={(e) => {
          if (estGlisserDePhoto(e.dataTransfer.types)) return;
          e.preventDefault();
          setSurvol(false);
          const fichiers = fichiersImages(e.dataTransfer);
          if (fichiers.length > 0) void onEnvoyer(fichiers);
        }}
      >
        <div
          className="flex items-center gap-2 px-4 py-3 shrink-0 flex-wrap"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center gap-1.5 flex-wrap flex-1 min-w-0">
            <button
              type="button"
              onClick={onRetour}
              aria-label="Revenir aux piles"
              title="Revenir aux piles"
              className="rounded-lg p-1.5 cursor-pointer mr-1"
              style={{ color: 'var(--color-text-secondary)', background: 'var(--color-surface)' }}
            >
              <ArrowLeft size={15} />
            </button>
            {piles.map((p) => {
              const active = p.id === pile.id;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    if (!active) onChoisir(p.id);
                  }}
                  className="text-xs rounded-full px-3 py-1 cursor-pointer max-w-[200px] truncate"
                  style={{
                    background: active ? 'var(--color-accent)' : 'var(--color-surface)',
                    color: active ? '#fff' : 'var(--color-text-secondary)',
                    border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-border)'}`,
                  }}
                  aria-pressed={active}
                >
                  {p.name} · {p.count}
                </button>
              );
            })}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {envoi && (
              <span className="flex items-center gap-1 text-xs mr-1" style={{ color: 'var(--color-accent)' }}>
                <Loader2 size={12} className="animate-spin" />
                {envoi.fait}/{envoi.total}
              </span>
            )}
            <input
              ref={entree}
              type="file"
              accept="image/*,.heic,.heif"
              multiple
              className="hidden"
              onChange={(e) => {
                const fichiers = Array.from(e.target.files ?? []);
                e.target.value = '';
                if (fichiers.length > 0) void onEnvoyer(fichiers);
              }}
            />
            <IconeBouton titre="Ajouter des photos" onClick={() => entree.current?.click()}>
              <Upload size={15} />
            </IconeBouton>
            <IconeBouton titre="Exporter la pile en PDF" onClick={() => void exporter(photos ?? [], pile.name)}>
              <FileDown size={15} />
            </IconeBouton>
            <IconeBouton titre="Renommer la pile" onClick={() => setRenommage(pile.name)}>
              <Pencil size={15} />
            </IconeBouton>
            <IconeBouton titre="Supprimer la pile" onClick={() => void onSupprimerPile()} danger>
              <Trash2 size={15} />
            </IconeBouton>
            <IconeBouton titre="Fermer" onClick={onFermer}>
              <X size={16} />
            </IconeBouton>
          </div>
        </div>

        {renommage !== null && (
          <form
            className="flex items-center gap-2 px-4 py-2"
            style={{ borderBottom: '1px solid var(--color-border)' }}
            onSubmit={(e) => {
              e.preventDefault();
              const nom = renommage.trim();
              setRenommage(null);
              if (nom && nom !== pile.name) void onRenommer(nom);
            }}
          >
            <input
              autoFocus
              value={renommage}
              onChange={(e) => setRenommage(e.target.value)}
              maxLength={80}
              aria-label="Nouveau nom de la pile"
              className="flex-1 rounded-lg px-2 py-1.5 text-sm bg-transparent outline-none"
              style={{ border: '1px solid var(--color-accent)', color: 'var(--color-text)' }}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.stopPropagation();
                  setRenommage(null);
                }
              }}
            />
            <button type="submit" className="text-xs px-3 py-1.5 rounded-lg cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>
              Renommer
            </button>
            <button type="button" onClick={() => setRenommage(null)} className="text-xs px-2 py-1.5 cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>
              Annuler
            </button>
          </form>
        )}

        {(selection.size > 0 || action) && (
          <div className="flex flex-wrap items-center gap-2 px-4 py-2 text-xs" style={{ borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)', color: 'var(--color-text-secondary)' }}>
            {action ? (
              <span className="flex items-center gap-1.5" style={{ color: 'var(--color-accent)' }}>
                <Loader2 size={12} className="animate-spin" />
                {action.nom} · {action.fait}/{action.total}
              </span>
            ) : (
              <>
                <CheckSquare size={13} style={{ color: 'var(--color-accent)' }} />
                <span className="font-medium" style={{ color: 'var(--color-text)' }}>
                  {selection.size} {selection.size === 1 ? 'sélectionnée' : 'sélectionnées'}
                </span>
                <span className="w-px h-4" style={{ background: 'var(--color-border)' }} />
                <label className="flex items-center gap-1">
                  Déplacer vers
                  <select
                    value=""
                    onChange={(e) => {
                      if (e.target.value) void deplacerSelection(e.target.value);
                    }}
                    aria-label="Déplacer la sélection vers une pile"
                    className="rounded-md px-1.5 py-1 bg-transparent outline-none"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  >
                    <option value="">une pile…</option>
                    {piles.filter((p) => p.id !== pile.id).map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-1">
                  <Link2 size={12} />
                  <select
                    value=""
                    onChange={(e) => {
                      if (e.target.value === '__detacher') void lierSelection('');
                      else if (e.target.value) void lierSelection(e.target.value);
                    }}
                    aria-label="Lier la sélection à une tâche"
                    className="rounded-md px-1.5 py-1 bg-transparent outline-none max-w-[220px]"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  >
                    <option value="">Lier à une tâche…</option>
                    <option value="__detacher">Détacher</option>
                    {tachesAplaties.map(({ tache, profondeur }) => (
                      <option key={tache.id} value={tache.id}>{'  '.repeat(profondeur)}{tache.title}</option>
                    ))}
                  </select>
                </label>
                <button type="button" onClick={() => void exporter(selectionnees, `${pile.name} — sélection`)} className="flex items-center gap-1 rounded-md px-2 py-1 cursor-pointer" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  <FileDown size={12} /> PDF
                </button>
                <button type="button" onClick={() => void supprimerSelection()} className="flex items-center gap-1 rounded-md px-2 py-1 cursor-pointer" style={{ border: '1px solid var(--color-border)', color: '#e5484d' }}>
                  <Trash2 size={12} /> Supprimer
                </button>
                <span className="flex-1" />
                <button type="button" onClick={() => setSelection(new Set(visibles.map((p) => p.id)))} className="cursor-pointer underline-offset-2 hover:underline">
                  Tout
                </button>
                <button type="button" onClick={() => setSelection(new Set())} className="cursor-pointer underline-offset-2 hover:underline">
                  Aucune (Échap)
                </button>
              </>
            )}
          </div>
        )}

        {tacheFiltre && (
          <div className="flex items-center gap-2 px-4 py-2 text-xs" style={{ borderBottom: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
            <Link2 size={13} style={{ color: 'var(--color-accent)' }} />
            <span className="truncate">Photos de « {tacheFiltre.title} »</span>
            <button type="button" onClick={() => onFiltre(null)} className="cursor-pointer underline-offset-2 hover:underline" style={{ color: 'var(--color-accent)' }}>
              Tout voir
            </button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4">
          {photos === null ? (
            <div className="flex items-center justify-center py-16" style={{ color: 'var(--color-text-tertiary)' }}>
              <Loader2 size={18} className="animate-spin" />
            </div>
          ) : visibles.length === 0 ? (
            <div
              className="flex flex-col items-center justify-center gap-2 py-14 rounded-xl text-sm"
              style={{ border: '1px dashed var(--color-border)', color: 'var(--color-text-tertiary)' }}
            >
              <ImagePlus size={22} />
              <span>{filtreTache ? 'Aucune photo pour cette tâche.' : 'Cette pile est vide.'}</span>
              <span className="text-[11px]">Glisse des photos ici, colle une capture (⌘V), ou utilise le bouton d’envoi.</span>
            </div>
          ) : (
            <div
              className="grid gap-2.5"
              style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}
            >
              {visibles.map((photo, index) => {
                // Toutes les cases ont la même taille, carrées : demandé le
                // 13 septembre 2026 contre la première en 2×2.
                const couverture = photo.id === pile.coverPhotoId;
                const estTenue = tenue === photo.id;
                const estCible = cible === photo.id && tenue !== photo.id;
                const cochee = selection.has(photo.id);
                return (
                  <button
                    key={photo.id}
                    type="button"
                    ref={(el) => {
                      if (el) cellules.current.set(photo.id, el);
                      else cellules.current.delete(photo.id);
                    }}
                    onClick={(e) => {
                      // ⇧ ou ⌘ : on coche au lieu d'ouvrir ; une sélection
                      // en cours se poursuit au simple clic.
                      if (e.shiftKey || e.metaKey || e.ctrlKey || selection.size > 0) basculer(photo.id);
                      else setCourante(index);
                    }}
                    aria-pressed={cochee}
                    aria-label={photo.caption || photo.fileName}
                    // Le rangement au curseur : on prend une photo, on la
                    // lâche sur celle dont elle prendra la place. Pas quand
                    // la grille est filtrée : l'ordre des absentes serait
                    // deviné.
                    draggable={!filtreTache}
                    onDragStart={(e) => {
                      if (filtreTache) return;
                      e.dataTransfer.setData(TYPE_GLISSER_PHOTO, photo.id);
                      e.dataTransfer.effectAllowed = 'move';
                      setTenue(photo.id);
                    }}
                    onDragEnd={() => {
                      setTenue(null);
                      setCible(null);
                    }}
                    onDragOver={(e) => {
                      if (!estGlisserDePhoto(e.dataTransfer.types)) return;
                      e.preventDefault();
                      e.stopPropagation();
                      e.dataTransfer.dropEffect = 'move';
                      if (cible !== photo.id) setCible(photo.id);
                    }}
                    onDrop={(e) => {
                      if (!estGlisserDePhoto(e.dataTransfer.types)) return;
                      e.preventDefault();
                      e.stopPropagation();
                      const source = e.dataTransfer.getData(TYPE_GLISSER_PHOTO) || tenue;
                      setTenue(null);
                      setCible(null);
                      if (source) void ranger(source, photo.id);
                    }}
                    className="relative rounded-lg overflow-hidden cursor-pointer group"
                    style={{
                      aspectRatio: '1',
                      background: 'var(--color-surface)',
                      border: `2px solid ${estCible || cochee ? 'var(--color-accent)' : 'var(--color-border)'}`,
                      opacity: estTenue ? 0.35 : 1,
                      transform: estCible ? 'scale(0.96)' : cochee ? 'scale(0.97)' : undefined,
                      transition: 'transform 120ms ease, opacity 120ms ease, border-color 120ms ease',
                    }}
                  >
                    <img src={photo.thumb} alt="" draggable={false} className="w-full h-full object-cover" />
                    <span
                      role="checkbox"
                      aria-checked={cochee}
                      aria-label={cochee ? 'Décocher' : 'Cocher'}
                      onClick={(e) => {
                        e.stopPropagation();
                        basculer(photo.id);
                      }}
                      className={`absolute bottom-1.5 left-1.5 rounded-md p-0.5 transition-opacity ${cochee || selection.size > 0 ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
                      style={{ background: cochee ? 'var(--color-accent)' : 'rgba(0,0,0,0.55)', color: '#fff' }}
                    >
                      {cochee ? <CheckSquare size={14} /> : <Square size={14} />}
                    </span>
                    {couverture && (
                      <span className="absolute top-1.5 left-1.5 rounded-full p-1" style={{ background: 'rgba(0,0,0,0.55)', color: '#fff' }} title="Couverture de la pile">
                        <Star size={11} />
                      </span>
                    )}
                    {photo.taskId && tachesParId.has(photo.taskId) && (
                      <span className="absolute top-1.5 right-1.5 rounded-full p-1" style={{ background: 'rgba(0,0,0,0.55)', color: '#fff' }} title={`Liée à « ${tachesParId.get(photo.taskId)?.title} »`}>
                        <Link2 size={11} />
                      </span>
                    )}
                    {photo.caption && (
                      <span
                        className="absolute inset-x-0 bottom-0 px-2 py-1 text-[11px] text-left truncate opacity-0 group-hover:opacity-100 transition-opacity"
                        style={{ background: 'rgba(0,0,0,0.6)', color: '#fff' }}
                      >
                        {photo.caption}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between px-4 py-2 text-[11px] shrink-0" style={{ borderTop: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}>
          <span>
            {visibles.length} {visibles.length === 1 ? 'photo' : 'photos'}
            {pile.count !== visibles.length ? ` sur ${pile.count}` : ''}
          </span>
          <span>
            {filtreTache ? 'Clic pour agrandir' : 'Clic pour agrandir · glisse pour ranger · ⇧-clic pour sélectionner'} · Échap
          </span>
        </div>
      </div>

      {courante >= 0 && visibles[courante] && (
        <PhotoPleinCadre
          photos={visibles}
          index={courante}
          pile={pile}
          tasks={tasks}
          tachesParId={tachesParId}
          onAller={setCourante}
          onFermer={() => setCourante(-1)}
          onMisAJour={async () => {
            await recharger();
            await onChangement();
          }}
          onSupprimee={async () => {
            setCourante(-1);
            await recharger();
            await onChangement();
          }}
          confirm={confirm}
        />
      )}
    </div>,
    document.body,
  );
}

function IconeBouton({
  titre,
  onClick,
  danger,
  children,
}: {
  titre: string;
  onClick: () => void;
  danger?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={titre}
      title={titre}
      className="rounded-lg p-2 cursor-pointer"
      style={{ color: danger ? '#e5484d' : 'var(--color-text-tertiary)', background: 'var(--color-surface)' }}
    >
      {children}
    </button>
  );
}
