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
import { ChevronLeft, ChevronRight, Pencil, Plus, X } from 'lucide-react';

import type { SuccesTask } from './types';
import {
  construireStations,
  estDoubleClic,
  etapeVoisine,
  linkifier,
  stationCourante,
  type ClicPrecedent,
} from './ligne';

interface Props {
  etape: SuccesTask;
  tasks: SuccesTask[];
  saving: boolean;
  onClose: () => void;
  onNavigate: (etapeId: string) => void;
  onToggle: (task: SuccesTask) => Promise<void>;
  onUpdate: (
    taskId: string,
    patch: { title?: string; notes?: string; date?: string },
  ) => Promise<void>;
  onCreate: (input: { title: string; parentTaskId: string }) => Promise<void>;
}

function Note({ texte }: { texte: string }) {
  return (
    <div
      className="text-[13px] leading-relaxed whitespace-pre-wrap"
      style={{ color: 'var(--color-text-secondary)' }}
    >
      {linkifier(texte).map((seg, i) =>
        seg.type === 'lien' ? (
          <a
            key={i}
            href={seg.valeur}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 break-all"
            style={{ color: 'var(--color-accent)' }}
            onClick={(e) => e.stopPropagation()}
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
              <Note texte={etape.notes} />
            </div>
          ) : null}
          {stations.length === 0 && (
            <div className="py-6 flex flex-col items-center gap-3">
              <p className="text-[13px]" style={{ color: 'var(--color-text-tertiary)' }}>
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
                const ouverte = deplie === tache.id || enEdition === tache.id;
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
                      disabled={saving}
                      onClick={(e) => {
                        e.stopPropagation();
                        void onToggle(tache);
                      }}
                      aria-label={tache.done ? 'Rouvrir' : 'Terminer'}
                      className="relative z-10 mt-[7px] shrink-0 rounded-full cursor-pointer"
                      style={{
                        width: profondeur ? 10 : 14,
                        height: profondeur ? 10 : 14,
                        marginLeft: profondeur ? 0 : 5,
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
                    />
                    {/* le contenu */}
                    <div
                      className="flex-1 min-w-0 rounded-lg px-3 py-1.5 cursor-pointer"
                      style={{
                        background: ouverte ? 'var(--color-bg-tertiary)' : 'transparent',
                      }}
                      onClick={() => {
                        if (enEdition === tache.id) return;
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
                        if (enEdition === tache.id) return;
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
                          <div
                            className="text-sm leading-snug py-0.5"
                            style={{
                              color: tache.done
                                ? 'var(--color-text-tertiary)'
                                : 'var(--color-text)',
                              textDecoration: tache.done ? 'line-through' : 'none',
                              fontWeight: courante ? 600 : 400,
                            }}
                          >
                            {tache.title}
                            {tache.date ? (
                              <span
                                className="ml-2 text-[11px] font-normal"
                                style={{ color: 'var(--color-accent)' }}
                              >
                                {tache.date}
                              </span>
                            ) : null}
                          </div>
                          {ouverte && (
                            <div className="pb-2 flex flex-col gap-2">
                              {tache.notes ? <Note texte={tache.notes} /> : null}
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
    </div>
  );
}
