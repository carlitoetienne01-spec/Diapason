// La Ligne — une étape déroulée en stations, comme une ligne de métro.
//
// Demandé le 23 août 2026 : « quand je clique sur une étape, ça m'affiche en
// fil tous ses enfants et petits-enfants ; je défile pour voir quelle étape
// suivre ; double-clic pour éditer et ajouter ce qui compte. »
//
// Le vocabulaire visuel tient en trois états de station : COCHÉE (pleine),
// COURANTE (halo pulsant — c'est là qu'on en est), À VENIR (creuse). Un clic
// déplie la station ; un double-clic l'édite SUR PLACE — titre, notes, date —
// sans changer d'écran. Échap annule l'édition, puis ferme la ligne.

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Camera,
  Check,
  ChevronLeft,
  ChevronRight,
  Lock,
  NotebookPen,
  Pencil,
  Plus,
  X,
} from 'lucide-react';

import { ouvrirLienExterne } from '../../lib/lienExterne';
import { CarnetDeTache, carnetRempli } from './CarnetDeTache';
import {
  ECHELLE_MAX,
  ECHELLE_MIN,
  echelleSuivante,
  libelleEchelle,
  taillesDe,
} from './echelleTexte';
import { loadLigneEchelle, saveLigneEchelle } from './uiPrefs';

import type { SuccesTask } from './types';
import {
  construireStations,
  estDoubleClic,
  etapeVoisine,
  linkifier,
  stationCourante,
  type ClicPrecedent,
} from './ligne';
import type { Verrous } from './verrou';

interface Props {
  etape: SuccesTask;
  tasks: SuccesTask[];
  saving: boolean;
  /**
   * Les stations encore fermées, chacune avec le titre de celle qui les
   * débloque. Vide quand le projet n'a pas la progression séquentielle.
   * Le magasin refuse aussi de les cocher : ceci ne fait que le dire avant
   * le clic, au lieu de laisser partir une requête qui sera rejetée.
   */
  verrous?: Verrous;
  /** Combien de photos du projet pointent vers chaque tâche. */
  photosParTache?: Record<string, number>;
  /** Ouvrir la pile de photos filtrée sur cette tâche. */
  onVoirPhotos?: (taskId: string) => void;
  onClose: () => void;
  onNavigate: (etapeId: string) => void;
  onToggle: (task: SuccesTask) => Promise<void>;
  onUpdate: (
    taskId: string,
    patch: { title?: string; notes?: string; date?: string; journal?: string },
    /** `silencieux` : enregistrer sans le dire. Le carnet sauvegarde tout seul. */
    options?: { silencieux?: boolean },
  ) => Promise<void>;
  onCreate: (input: { title: string; parentTaskId: string }) => Promise<void>;
}

function Note({ texte, taille }: { texte: string; taille: number }) {
  return (
    <div
      className="leading-relaxed whitespace-pre-wrap"
      style={{ color: 'var(--color-text-secondary)', fontSize: taille }}
    >
      {linkifier(texte).map((seg, i) =>
        seg.type === 'lien' ? (
          <a
            key={i}
            href={seg.valeur}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 break-all cursor-pointer"
            style={{ color: 'var(--color-accent)' }}
            onClick={(e) => {
              // `target="_blank"` ne fait RIEN dans la fenêtre de bureau :
              // WKWebView n'ouvre pas de seconde fenêtre, et le clic tombe
              // dans le vide sans un message. Le lien était souligné, en
              // couleur d'accent, et mort. On passe par le greffon.
              e.preventDefault();
              e.stopPropagation();
              void ouvrirLienExterne(seg.valeur);
            }}
          >
            {seg.valeur}
          </a>
        ) : (
          <span key={i}>{seg.valeur}</span>
        ),
      )}
    </div>
  );
}

export function LigneEtape({
  etape,
  tasks,
  saving,
  verrous,
  photosParTache,
  onVoirPhotos,
  onClose,
  onNavigate,
  onToggle,
  onUpdate,
  onCreate,
}: Props) {
  const stations = useMemo(
    () => construireStations(etape.id, tasks),
    [etape.id, tasks],
  );
  const couranteId = useMemo(() => stationCourante(stations), [stations]);
  const faites = stations.filter((s) => s.tache.done).length;

  const [deplie, setDeplie] = useState<string | null>(couranteId);
  const [enEdition, setEnEdition] = useState<string | null>(null);
  /** La tâche dont le carnet est ouvert. */
  const [carnetDe, setCarnetDe] = useState<string | null>(null);
  // L'échelle du texte : réglée ici, retenue d'une ouverture à l'autre.
  // Lue paresseusement — `localStorage` ne doit pas être touché à chaque
  // rendu, et un accès qui lève (navigation privée) est déjà avalé par
  // `uiPrefs`.
  const [echelle, setEchelle] = useState<number>(() => loadLigneEchelle());
  const tailles = taillesDe(echelle);
  const changerEchelle = (sens: 1 | -1) => {
    const suivant = echelleSuivante(echelle, sens);
    setEchelle(suivant);
    saveLigneEchelle(suivant);
  };
  const [brouillon, setBrouillon] = useState({ title: '', notes: '', date: '' });
  const [ajoutSous, setAjoutSous] = useState<string | null>(null);
  const [titreSous, setTitreSous] = useState('');

  // Le simple clic attend 220 ms avant de plier/déplier : sinon le premier
  // clic d'un double-clic replie la carte ouverte au-dessus, tout remonte,
  // et le second clic édite LA MAUVAISE station (vu au banc d'essai).
  // Le double-clic est détecté MAISON (deux clics < 450 ms) : le dblclick
  // natif n'arrivait jamais dans le WebView de l'app de bureau.
  const clicEnAttente = useRef<number | null>(null);
  const clicPrecedent = useRef<ClicPrecedent>({ id: '', a: 0 });
  useEffect(
    () => () => {
      if (clicEnAttente.current) window.clearTimeout(clicEnAttente.current);
    },
    [],
  );

  const precedente = etapeVoisine(etape.id, tasks, -1);
  const suivante = etapeVoisine(etape.id, tasks, 1);

  // La station courante arrive À L'ÉCRAN d'elle-même : on ouvre la ligne
  // pour savoir où l'on en est, pas pour le chercher en défilant.
  const couranteRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    couranteRef.current?.scrollIntoView({ block: 'center' });
  }, [etape.id]);

  useEffect(() => {
    const surTouche = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (enEdition) setEnEdition(null);
        else if (ajoutSous) setAjoutSous(null);
        else onClose();
      } else if (!enEdition && !ajoutSous && e.key === 'ArrowLeft' && precedente) {
        onNavigate(precedente);
      } else if (!enEdition && !ajoutSous && e.key === 'ArrowRight' && suivante) {
        onNavigate(suivante);
      }
    };
    window.addEventListener('keydown', surTouche);
    return () => window.removeEventListener('keydown', surTouche);
  }, [enEdition, ajoutSous, precedente, suivante, onClose, onNavigate]);

  const commencerEdition = (t: SuccesTask) => {
    setBrouillon({ title: t.title, notes: t.notes || '', date: t.date || '' });
    setEnEdition(t.id);
  };
  const enregistrer = async (t: SuccesTask) => {
    const patch: { title?: string; notes?: string; date?: string } = {};
    if (brouillon.title.trim() && brouillon.title !== t.title)
      patch.title = brouillon.title.trim();
    if (brouillon.notes !== (t.notes || '')) patch.notes = brouillon.notes;
    if (brouillon.date !== (t.date || '')) patch.date = brouillon.date;
    if (Object.keys(patch).length) await onUpdate(t.id, patch);
    setEnEdition(null);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(3px)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="w-full max-w-xl mx-4 rounded-2xl flex flex-col max-h-[88vh] overflow-hidden"
        style={{
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
        }}
      >
        {/* ── en-tête : où l'on est, où aller ── */}
        <div
          className="flex items-center gap-3 px-5 py-4 shrink-0"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <button
            type="button"
            disabled={!precedente}
            onClick={() => precedente && onNavigate(precedente)}
            className="p-1 rounded-md disabled:opacity-25 cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
            aria-label="Étape précédente"
          >
            <ChevronLeft size={18} />
          </button>
          <div className="flex-1 min-w-0 text-center">
            <div
              className="text-sm font-medium truncate"
              style={{ color: 'var(--color-text)' }}
            >
              {etape.emoji ? `${etape.emoji} ` : ''}
              {etape.title}
            </div>
            <div
              className="text-[11px] tracking-wide"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              {faites}/{stations.length} · cliquer déplie · double-clic édite
              {/* Les photos liées à l'étape elle-même, pas à une station. */}
              {onVoirPhotos && (photosParTache?.[etape.id] ?? 0) > 0 ? (
                <>
                  {' · '}
                  <button
                    type="button"
                    onClick={() => onVoirPhotos(etape.id)}
                    className="inline-flex items-center gap-0.5 cursor-pointer align-middle"
                    style={{ color: 'var(--color-accent)' }}
                    aria-label={`${photosParTache?.[etape.id]} photo(s) liée(s) à cette étape`}
                  >
                    <Camera size={11} />
                    {photosParTache?.[etape.id]} photo(s)
                  </button>
                </>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            disabled={!suivante}
            onClick={() => suivante && onNavigate(suivante)}
            className="p-1 rounded-md disabled:opacity-25 cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
            aria-label="Étape suivante"
          >
            <ChevronRight size={18} />
          </button>
          {/* Agrandir les lettres. Demandé le 6 septembre 2026 : les tailles
              étaient figées dans les classes, et rien ne permettait de les
              changer. Le réglage se souvient d'une ouverture à l'autre. */}
          <div
            className="flex items-center gap-0.5 rounded-lg px-1 py-0.5 shrink-0"
            style={{ border: '1px solid var(--color-border)' }}
          >
            <button
              type="button"
              disabled={echelle <= ECHELLE_MIN}
              onClick={() => changerEchelle(-1)}
              className="px-1.5 leading-none cursor-pointer disabled:opacity-30 disabled:cursor-default"
              style={{ color: 'var(--color-text-secondary)', fontSize: 12 }}
              aria-label="Réduire la taille du texte"
              title="Réduire la taille du texte"
            >
              A
            </button>
            <span
              className="tabular-nums select-none"
              style={{ color: 'var(--color-text-tertiary)', fontSize: 10 }}
              aria-live="polite"
            >
              {libelleEchelle(echelle)}
            </span>
            <button
              type="button"
              disabled={echelle >= ECHELLE_MAX}
              onClick={() => changerEchelle(1)}
              className="px-1.5 leading-none cursor-pointer disabled:opacity-30 disabled:cursor-default"
              style={{ color: 'var(--color-text-secondary)', fontSize: 18 }}
              aria-label="Agrandir la taille du texte"
              title="Agrandir la taille du texte"
            >
              A
            </button>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-md cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)' }}
            aria-label="Fermer"
          >
            <X size={16} />
          </button>
        </div>

        {/* ── la ligne ── */}
        <div className="flex-1 min-h-0 overflow-y-auto px-5 py-5">
          {etape.notes ? (
            <div className="mb-5 pl-9">
              <Note texte={etape.notes} taille={tailles.note} />
            </div>
          ) : null}
          {stations.length === 0 && (
            <div className="py-6 flex flex-col items-center gap-3">
              <p
                style={{
                  color: 'var(--color-text-tertiary)',
                  fontSize: tailles.note,
                }}
              >
                Cette étape n'a pas encore de stations.
              </p>
              <input
                value={titreSous}
                onChange={(e) => setTitreSous(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && titreSous.trim()) {
                    void onCreate({
                      title: titreSous.trim(),
                      parentTaskId: etape.id,
                    }).then(() => setTitreSous(''));
                  }
                }}
                placeholder="Première station, Entrée pour la poser"
                className="w-72 max-w-full text-[13px] rounded-md px-3 py-2"
                style={{
                  background: 'var(--color-bg-tertiary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </div>
          )}
          <div className="relative">
            {/* le rail */}
            <div
              className="absolute top-1 bottom-1 w-[2px] rounded"
              style={{ left: 11, background: 'var(--color-border)' }}
            />
            <div className="flex flex-col gap-1">
              {stations.map(({ tache, profondeur }) => {
                const courante = tache.id === couranteId;
                const verrouille = verrous?.get(tache.id);
                // Une station fermée ne se déplie pas : son contenu EST ce
                // qu'on vient chercher trop tôt.
                const ouverte =
                  !verrouille && (deplie === tache.id || enEdition === tache.id);
                return (
                  <div
                    key={tache.id}
                    ref={courante ? couranteRef : undefined}
                    className="relative flex gap-3"
                    style={{ paddingLeft: profondeur ? 26 : 0 }}
                  >
                    {/* la station */}
                    <button
                      type="button"
                      disabled={saving || !!verrouille}
                      onClick={(e) => {
                        e.stopPropagation();
                        void onToggle(tache);
                      }}
                      aria-label={
                        verrouille
                          ? `Verrouillée — termine d'abord « ${verrouille} »`
                          : tache.done
                            ? 'Rouvrir'
                            : 'Terminer'
                      }
                      title={
                        verrouille
                          ? `Termine d'abord « ${verrouille} »`
                          : undefined
                      }
                      className="relative z-10 mt-[5px] shrink-0 rounded-full cursor-pointer flex items-center justify-center"
                      style={{
                        // Élargies de 14 à 18 px pour loger le crochet. Les
                        // marges compensent au pixel près : le centre reste à
                        // 12 px (racine) et 5 px (sous-étape), sinon la station
                        // sortirait du rail qui la traverse.
                        width: profondeur ? 14 : 18,
                        height: profondeur ? 14 : 18,
                        marginLeft: profondeur ? -2 : 3,
                        background: tache.done
                          ? 'var(--color-accent)'
                          : 'var(--color-bg-secondary)',
                        border: `2px solid ${
                          tache.done || courante
                            ? 'var(--color-accent)'
                            : 'var(--color-border)'
                        }`,
                        boxShadow: courante
                          ? '0 0 0 4px color-mix(in srgb, var(--color-accent) 25%, transparent)'
                          : 'none',
                        animation: courante ? 'pulse 2s infinite' : undefined,
                      }}
                    >
                      {/* LE CROCHET, au milieu de la station.
                          Une station pleine et une station courante se
                          ressemblaient à un halo près : il fallait comparer
                          deux points pour savoir lequel était fait. Un crochet
                          se lit sans comparer. Trait épais : à neuf pixels, un
                          trait fin disparaît. */}
                      {tache.done ? (
                        <Check
                          size={profondeur ? 9 : 12}
                          strokeWidth={3.5}
                          style={{ color: 'var(--color-bg)' }}
                        />
                      ) : verrouille ? (
                        <Lock
                          size={profondeur ? 8 : 10}
                          strokeWidth={2.5}
                          style={{ color: 'var(--color-text-tertiary)' }}
                        />
                      ) : null}
                    </button>
                    {/* le contenu */}
                    <div
                      className="flex-1 min-w-0 rounded-lg px-3 py-1.5 cursor-pointer"
                      style={{
                        background: ouverte ? 'var(--color-bg-tertiary)' : 'transparent',
                      }}
                      onClick={() => {
                        if (verrouille || enEdition === tache.id) return;
                        if (clicEnAttente.current)
                          window.clearTimeout(clicEnAttente.current);
                        const maintenant = performance.now();
                        if (
                          estDoubleClic(clicPrecedent.current, tache.id, maintenant)
                        ) {
                          clicPrecedent.current = { id: '', a: 0 };
                          clicEnAttente.current = null;
                          commencerEdition(tache);
                          return;
                        }
                        clicPrecedent.current = { id: tache.id, a: maintenant };
                        clicEnAttente.current = window.setTimeout(() => {
                          clicEnAttente.current = null;
                          setDeplie((d) => (d === tache.id ? null : tache.id));
                        }, 220);
                      }}
                      onDoubleClick={() => {
                        // Filet natif — quand le moteur veut bien l'envoyer.
                        if (verrouille || enEdition === tache.id) return;
                        if (clicEnAttente.current) {
                          window.clearTimeout(clicEnAttente.current);
                          clicEnAttente.current = null;
                        }
                        commencerEdition(tache);
                      }}
                    >
                      {enEdition === tache.id ? (
                        <div
                          className="flex flex-col gap-2 py-1"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            value={brouillon.title}
                            onChange={(e) =>
                              setBrouillon({ ...brouillon, title: e.target.value })
                            }
                            autoFocus
                            className="text-sm rounded-md px-2 py-1.5 w-full"
                            style={{
                              background: 'var(--color-bg-secondary)',
                              color: 'var(--color-text)',
                              border: '1px solid var(--color-accent)',
                            }}
                          />
                          <textarea
                            value={brouillon.notes}
                            onChange={(e) =>
                              setBrouillon({ ...brouillon, notes: e.target.value })
                            }
                            rows={4}
                            placeholder="Notes, liens, ressources — tout ce qui compte pour cette étape…"
                            className="text-[13px] rounded-md px-2 py-1.5 w-full resize-y"
                            style={{
                              background: 'var(--color-bg-secondary)',
                              color: 'var(--color-text)',
                              border: '1px solid var(--color-border)',
                            }}
                          />
                          <div className="flex items-center gap-2 flex-wrap">
                            <input
                              type="date"
                              value={brouillon.date}
                              onChange={(e) =>
                                setBrouillon({ ...brouillon, date: e.target.value })
                              }
                              className="text-[12px] rounded-md px-2 py-1"
                              style={{
                                background: 'var(--color-bg-secondary)',
                                color: 'var(--color-text)',
                                border: '1px solid var(--color-border)',
                              }}
                              title="Datée, l'étape entre dans le briefing du matin"
                            />
                            <div className="flex-1" />
                            <button
                              type="button"
                              onClick={() => setEnEdition(null)}
                              className="text-[12px] px-2.5 py-1 rounded-md cursor-pointer"
                              style={{ color: 'var(--color-text-secondary)' }}
                            >
                              Annuler
                            </button>
                            <button
                              type="button"
                              disabled={saving}
                              onClick={() => void enregistrer(tache)}
                              className="text-[12px] px-3 py-1 rounded-md cursor-pointer disabled:opacity-50"
                              style={{ background: 'var(--color-accent)', color: '#fff' }}
                            >
                              Enregistrer
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          {/* LE CARNET, DANS la carte, en haut à DROITE.
                              Il a d'abord été posé à côté de la carte : on le
                              cherchait au bout d'une ligne dont la longueur
                              change à chaque station. Puis à gauche du titre,
                              où il repoussait chaque titre de vingt-huit
                              pixels. À droite de la carte, il est aligné à la
                              verticale sur toutes les stations ET les titres
                              repartent du même bord qu'avant.
                              Sur chaque station, dépliée ou non : écrire une
                              note ne doit pas coûter deux clics. */}
                          <div className="flex items-start gap-2 py-0.5">
                            <div
                              className="leading-snug flex-1 min-w-0"
                              style={{
                                fontSize: tailles.titre,
                                color:
                                  tache.done || verrouille
                                    ? 'var(--color-text-tertiary)'
                                    : 'var(--color-text)',
                                textDecoration: tache.done ? 'line-through' : 'none',
                                fontWeight: courante ? 600 : 400,
                              }}
                            >
                              {tache.title}
                              {tache.date ? (
                                <span
                                  className="ml-2 font-normal"
                                  style={{
                                    color: 'var(--color-accent)',
                                    fontSize: tailles.badge,
                                  }}
                                >
                                  {tache.date}
                                </span>
                              ) : null}
                            </div>
                            {/* SEULEMENT SUR LA CARTE DÉPLIÉE.
                                Trois états essayés : partout (onze icônes en
                                colonne le long du bord droit — « pourquoi je
                                les vois quand la carte est fermée ? »), puis
                                au survol (l'icône d'un carnet vide
                                n'apparaissait qu'en passant dessus). Ici :
                                elle n'existe que quand on a ouvert la carte
                                pour en voir le détail.
                                Conséquence assumée : sur une ligne fermée,
                                rien ne dit plus qu'un carnet est écrit. Le
                                repère se paie d'un dépliage.
                                Rien n'est rendu du tout — pas un bouton
                                transparent : une cible invisible reste
                                atteignable au clavier, et l'on tabulerait sur
                                ce qu'on ne voit pas. */}
                            {ouverte ? (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setCarnetDe(tache.id);
                                }}
                                aria-label={
                                  carnetRempli(tache.journal)
                                    ? `Carnet de « ${tache.title} » — écrit`
                                    : `Carnet de « ${tache.title} » — vide`
                                }
                                title={
                                  carnetRempli(tache.journal)
                                    ? 'Carnet — des notes vous attendent'
                                    : 'Carnet — prendre des notes sur cette tâche'
                                }
                                className="mt-[1px] size-5 shrink-0 rounded-md flex items-center justify-center cursor-pointer"
                                style={{
                                  // La couleur dit encore s'il y a quelque
                                  // chose dedans, une fois la carte ouverte.
                                  color: carnetRempli(tache.journal)
                                    ? 'var(--color-accent)'
                                    : 'var(--color-text-tertiary)',
                                }}
                              >
                                <NotebookPen size={13} />
                              </button>
                            ) : null}
                            {/* Le repère des photos, aux mêmes conditions
                                que le carnet : carte ouverte seulement, et
                                seulement s'il y en a — un appareil photo
                                gris sur chaque station n'aurait rien dit. */}
                            {ouverte && onVoirPhotos && (photosParTache?.[tache.id] ?? 0) > 0 ? (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onVoirPhotos(tache.id);
                                }}
                                aria-label={`${photosParTache?.[tache.id]} photo(s) liée(s) à « ${tache.title} »`}
                                title={`${photosParTache?.[tache.id]} photo(s) — voir la pile`}
                                className="mt-[1px] h-5 shrink-0 rounded-md flex items-center gap-0.5 px-1 cursor-pointer text-[10px]"
                                style={{ color: 'var(--color-accent)' }}
                              >
                                <Camera size={13} />
                                {photosParTache?.[tache.id]}
                              </button>
                            ) : null}
                          </div>
                          {/* Le contenu d'une station fermée n'est pas rendu
                              du tout — ni notes, ni liens, ni carnet. Le
                              masquer en CSS le laisserait dans le HTML, donc
                              lisible par qui sait ouvrir l'inspecteur : ce
                              serait un rideau, pas un verrou. */}
                          {verrouille ? (
                            <div
                              className="pb-1.5 flex items-center gap-1.5"
                              style={{
                                color: 'var(--color-text-tertiary)',
                                fontSize: tailles.mention,
                              }}
                            >
                              <Lock size={11} />
                              <span>Termine d'abord « {verrouille} »</span>
                            </div>
                          ) : null}
                          {ouverte && (
                            <div className="pb-2 flex flex-col gap-2">
                              {tache.notes ? (
                                <Note texte={tache.notes} taille={tailles.note} />
                              ) : null}
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (clicEnAttente.current) {
                                    window.clearTimeout(clicEnAttente.current);
                                    clicEnAttente.current = null;
                                  }
                                  commencerEdition(tache);
                                }}
                                className="self-start flex items-center gap-1 text-[12px] cursor-pointer"
                                style={{ color: 'var(--color-text-tertiary)' }}
                              >
                                <Pencil size={12} /> modifier
                              </button>
                              {ajoutSous === tache.id ? (
                                <div
                                  className="flex gap-2"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <input
                                    value={titreSous}
                                    onChange={(e) => setTitreSous(e.target.value)}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter' && titreSous.trim()) {
                                        void onCreate({
                                          title: titreSous.trim(),
                                          parentTaskId: tache.id,
                                        }).then(() => setTitreSous(''));
                                      }
                                    }}
                                    autoFocus
                                    placeholder="Nouvelle sous-étape, Entrée pour créer"
                                    className="flex-1 text-[13px] rounded-md px-2 py-1"
                                    style={{
                                      background: 'var(--color-bg-secondary)',
                                      color: 'var(--color-text)',
                                      border: '1px solid var(--color-border)',
                                    }}
                                  />
                                </div>
                              ) : (
                                profondeur === 0 && (
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setAjoutSous(tache.id);
                                      setTitreSous('');
                                    }}
                                    className="self-start flex items-center gap-1 text-[12px] cursor-pointer"
                                    style={{ color: 'var(--color-text-tertiary)' }}
                                  >
                                    <Plus size={12} /> sous-étape
                                  </button>
                                )
                              )}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
      {/* Le carnet, par-dessus la Ligne. Monté seulement quand il est ouvert :
          onze carnets montés en permanence garderaient onze textes en mémoire
          pour un seul qu'on regarde. */}
      {carnetDe
        ? (() => {
            const cible = stations.find((st) => st.tache.id === carnetDe)?.tache;
            if (!cible) return null;
            return (
              <CarnetDeTache
                tache={cible}
                onFermer={() => setCarnetDe(null)}
                onEnregistrer={(journal) =>
                  onUpdate(cible.id, { journal }, { silencieux: true })
                }
              />
            );
          })()
        : null}
    </div>
  );
}
