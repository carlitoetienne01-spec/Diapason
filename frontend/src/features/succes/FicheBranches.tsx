// La fiche « Branches » d'une tâche du réseau : ce qu'elle attend à gauche,
// ce qu'elle débloque à droite, toute la chaîne indentée sous chaque voisine.
//
// Chantier réseau du 18 septembre 2026. Jusque-là, cliquer une tâche du
// réseau ouvrait l'aside générique bas-droite de SuccesProjectsPage : titre,
// notes, « Ouverte », Terminer, Supprimer — zéro information de réseau, un
// `done` périmé après une coche (l'aside gardait l'OBJET, pas l'id), pas
// d'Échap, et à 340 px il couvrait le graphe qu'il commentait.
//
// Ici, la fiche ne calcule rien : `voisinage`, `chaine`, `voisinSuivant` et
// les comptes viennent de `reseau.ts`, testés sur AgriCulture. Elle relit la
// tâche dans les tâches FRAÎCHES à chaque rendu (motif `etapeLigneId`) :
// après « Terminer », le glyphe et la ligne de comptes viennent de l'état
// rechargé, jamais du clic (§100).

import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { Link2, Loader2, MoreHorizontal, NotebookPen, X } from 'lucide-react';

import { CadreVitre } from '../../components/Glass/CadreVitre';
import { CarnetDeTache } from './CarnetDeTache';
import {
  categories,
  ceQueDebloque,
  chaine,
  construireReseau,
  estOrpheline,
  glypheStatut,
  ligneDeComptes,
  placeSurLeFil,
  statutDe,
  voisinSuivant,
  voisinage,
  type Reseau,
  type Sens,
  type StatutTache,
} from './reseau';
import type { SuccesTask, SuccesTaskEdge } from './types';

interface Props {
  tacheId: string;
  tasks: SuccesTask[];
  edges: SuccesTaskEdge[];
  saving?: boolean;
  onFermer: () => void;
  /** Recentrer la fiche sur une autre tâche — elle ne se ferme jamais pour naviguer. */
  onNaviguer: (id: string) => void;
  onToggle: (task: SuccesTask) => Promise<void>;
  /** Entrer en mode liaison avec cette tâche comme source ; la page ferme la fiche. */
  onRelierDepuis: (task: SuccesTask) => void;
  /** La page confirme, supprime, recharge — et ferme la fiche si ça a marché. */
  onSupprimer: (task: SuccesTask) => Promise<void>;
  /** Doit LEVER si le serveur a refusé : le carnet ne dit « Enregistré » qu'à raison. */
  onEnregistrerCarnet: (taskId: string, journal: string) => Promise<void>;
  /** Le couloir de la tâche ; vide pour l'en retirer. La page enregistre et recharge. */
  onChangerCategorie: (taskId: string, category: string) => Promise<void>;
}

interface Ligne {
  id: string;
  /** 0 = voisine directe ; au-delà, sa chaîne, indentée d'un cran par profondeur. */
  profondeur: number;
}

/** Une colonne = chaque voisine directe suivie de sa propre chaîne transitive. */
function lignesDeColonne(reseau: Reseau, id: string, sens: Sens): Ligne[] {
  const v = voisinage(reseau, id);
  const directes = sens === 'amont' ? v.amont : v.aval;
  const lignes: Ligne[] = [];
  for (const vid of directes) {
    lignes.push({ id: vid, profondeur: 0 });
    for (const maillon of chaine(reseau, vid, sens)) {
      lignes.push({ id: maillon.id, profondeur: maillon.profondeur });
    }
  }
  return lignes;
}

// Le glyphe dit l'état par la FORME (● ○ ◌) ; la teinte n'ajoute que l'accent
// du faisable. Dessiné en SVG : le caractère ◌ (U+25CC) sortait de la police
// en pointillés de 0,5 px, invisibles sur le thème sombre.
function Glyphe({ statut }: { statut: StatutTache }) {
  const couleur = statut === 'faisable' ? 'var(--color-accent)' : 'var(--color-text-secondary)';
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 12 12"
      width={12}
      height={12}
      className="shrink-0 mt-[0.3em]"
      style={{ color: couleur }}
    >
      <circle
        cx={6}
        cy={6}
        r={4.5}
        fill={statut === 'faite' ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth={1.5}
        strokeDasharray={statut === 'bloquee' ? '2 2' : undefined}
      />
    </svg>
  );
}

const FOCUSABLES = 'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

export function FicheBranches({
  tacheId,
  tasks,
  edges,
  saving = false,
  onFermer,
  onNaviguer,
  onToggle,
  onRelierDepuis,
  onSupprimer,
  onEnregistrerCarnet,
  onChangerCategorie,
}: Props) {
  const reseau = useMemo(() => construireReseau(tasks, edges), [tasks, edges]);
  const tache = reseau.parId.get(tacheId) ?? null;
  const [historique, setHistorique] = useState<string[]>([]);
  const [curseur, setCurseur] = useState<{ colonne: Sens; index: number } | null>(null);
  const [notesDepliees, setNotesDepliees] = useState(false);
  const [menuOuvert, setMenuOuvert] = useState(false);
  // La catégorie en cours de frappe dans le « ⋯ » ; null = on montre celle
  // de la tâche RECHARGÉE (§100 : un refus du serveur laisse l'ancienne).
  const [categorieSaisie, setCategorieSaisie] = useState<string | null>(null);
  // Le miroir de `categorieSaisie` hors rendu : Entrée pose puis ferme le
  // menu, et le `blur` du champ qui disparaît ne doit pas poser une seconde fois.
  const saisieEnCours = useRef<string | null>(null);
  const [carnetOuvert, setCarnetOuvert] = useState(false);
  const boite = useRef<HTMLDivElement>(null);
  const origine = useRef<Element | null>(null);

  // Le focus est rendu à la carte d'origine à la fermeture : sinon, après
  // Échap, il tombait sur `body` et Tab repartait du haut de la page.
  useEffect(() => {
    origine.current = document.activeElement;
    boite.current?.focus();
    return () => {
      const el = origine.current;
      if (el && typeof (el as HTMLElement).focus === 'function' && el.isConnected) {
        (el as HTMLElement).focus();
      }
    };
  }, []);

  // Recentrer : le curseur, le menu et le repli des notes repartent à zéro,
  // et le focus revient dans la boîte — la ligne cliquée vient de disparaître
  // avec l'ancienne fiche, et le focus tombait sur `body` : les flèches ne
  // répondaient plus après le premier clic.
  useEffect(() => {
    setCurseur(null);
    setMenuOuvert(false);
    setCategorieSaisie(null);
    setNotesDepliees(false);
    boite.current?.focus();
  }, [tacheId]);

  const lignes = useMemo(
    () =>
      tache
        ? { amont: lignesDeColonne(reseau, tache.id, 'amont'), aval: lignesDeColonne(reseau, tache.id, 'aval') }
        : { amont: [], aval: [] },
    [reseau, tache],
  );

  if (!tache) return null;

  const statut = statutDe(reseau, tache.id);
  // Les couloirs déjà employés dans le projet, proposés dans le « ⋯ » ;
  // AgriCulture n'en a aucun : le champ accepte aussi un mot nouveau.
  const couloirs = categories(reseau);
  const fermerMenu = () => {
    setMenuOuvert(false);
    saisieEnCours.current = null;
    setCategorieSaisie(null);
    // Le champ du menu disparaît avec lui : sans ce rappel le focus tombait
    // sur `body` et Échap suivant fermait le mini-panneau entier.
    boite.current?.focus();
  };
  const poserCategorie = () => {
    const saisie = saisieEnCours.current;
    if (saisie === null) return;
    saisieEnCours.current = null;
    setCategorieSaisie(null);
    const valeur = saisie.trim();
    if (valeur === (tache.category ?? '')) return;
    void onChangerCategorie(tache.id, valeur);
  };
  const fil = [...historique, tache.id].slice(-3);
  const place = placeSurLeFil(reseau, tache.id);
  // Ce que terminer la tâche centrale ouvrirait : les successeures dont elle
  // est la dernière attente ouverte. Dit seulement pour une faisable — c'est
  // une invitation, et « Débloque 2 » au-dessus compte déjà les voisines.
  const ouvrirait =
    statut === 'faisable'
      ? ceQueDebloque(reseau, tache.id)
          .map((id) => reseau.parId.get(id)?.title)
          .filter((t): t is string => Boolean(t))
      : [];

  const aller = (id: string) => {
    if (id === tache.id) return;
    setHistorique((h) => [...h, tache.id]);
    onNaviguer(id);
  };

  const retour = () => {
    if (historique.length === 0) return;
    const precedent = historique[historique.length - 1];
    setHistorique((h) => h.slice(0, -1));
    onNaviguer(precedent);
  };

  const revenirA = (indexDansFil: number) => {
    // Le fil montre les trois derniers ; on remonte l'historique jusqu'à celui-là.
    const cible = fil[indexDansFil];
    const pos = historique.lastIndexOf(cible);
    if (pos < 0) return;
    setHistorique((h) => h.slice(0, pos));
    onNaviguer(cible);
  };

  const deplacerCurseur = (delta: 1 | -1) => {
    setCurseur((c) => {
      if (!c) {
        const colonne: Sens = lignes.amont.length > 0 ? 'amont' : 'aval';
        return lignes[colonne].length > 0 ? { colonne, index: 0 } : null;
      }
      const taille = lignes[c.colonne].length;
      if (taille === 0) return null;
      return { colonne: c.colonne, index: Math.min(taille - 1, Math.max(0, c.index + delta)) };
    });
  };

  const surClavier = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const cible = event.target as HTMLElement;
    // Le carnet est un portail sur body : ses frappes remontent l'arbre React
    // sans être dans la boîte. « n » tapé dans le carnet ne doit pas en rouvrir un.
    if (!boite.current?.contains(cible)) return;
    const surBouton = cible.tagName === 'BUTTON';

    if (event.key === 'Escape') {
      // Consommé : le script natif du mini-panneau lit `defaultPrevented`
      // (contrat du 17 sept. 2026, lib.rs) et fermerait le panneau ENTIER.
      event.preventDefault();
      event.stopPropagation();
      if (menuOuvert) fermerMenu();
      else onFermer();
      return;
    }
    // Dans le champ « Catégorie » du « ⋯ », les lettres, Espace, les flèches
    // et Retour arrière sont de la frappe, pas des raccourcis : « l » y
    // entrait en mode liaison et Espace terminait la tâche.
    const dansChamp = cible.tagName === 'INPUT' || cible.tagName === 'TEXTAREA' || cible.tagName === 'SELECT';
    if (dansChamp && event.key !== 'Tab') return;
    if (event.key === 'Tab') {
      const focusables = [...(boite.current?.querySelectorAll<HTMLElement>(FOCUSABLES) ?? [])];
      if (focusables.length === 0) return;
      const premier = focusables[0];
      const dernier = focusables[focusables.length - 1];
      if (event.shiftKey && (cible === premier || cible === boite.current)) {
        event.preventDefault();
        dernier.focus();
      } else if (!event.shiftKey && cible === dernier) {
        event.preventDefault();
        premier.focus();
      }
      return;
    }
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      const suivant = voisinSuivant(reseau, tache.id, event.key === 'ArrowLeft' ? 'amont' : 'aval');
      if (suivant) {
        event.preventDefault();
        aller(suivant);
      }
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      deplacerCurseur(event.key === 'ArrowDown' ? 1 : -1);
      return;
    }
    if (event.key === 'Backspace') {
      event.preventDefault();
      retour();
      return;
    }
    if (surBouton && (event.key === 'Enter' || event.key === ' ')) return;
    if (event.key === 'Enter') {
      if (curseur) {
        event.preventDefault();
        aller(lignes[curseur.colonne][curseur.index].id);
      }
      return;
    }
    if (event.key === ' ') {
      event.preventDefault();
      if (!saving) void onToggle(tache);
      return;
    }
    if (event.key === 'l' || event.key === 'L') {
      event.preventDefault();
      onRelierDepuis(tache);
      return;
    }
    if (event.key === 'n' || event.key === 'N') {
      event.preventDefault();
      setCarnetOuvert(true);
    }
  };

  const rendreColonne = (sens: Sens) => {
    const liste = lignes[sens];
    const titre = sens === 'amont' ? 'Attend' : 'Débloque';
    if (liste.length === 0) {
      return (
        <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {sens === 'amont' ? 'Rien à attendre' : 'Ne débloque rien'}
        </p>
      );
    }
    return (
      <div className="grid gap-1 content-start">
        <p
          className="text-[11px] font-medium tracking-[0.12em] uppercase"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          {titre}
        </p>
        {liste.map((ligne, index) => {
          const t = reseau.parId.get(ligne.id);
          if (!t) return null;
          const st = statutDe(reseau, t.id);
          const sousCurseur = curseur?.colonne === sens && curseur.index === index;
          const transitive = ligne.profondeur > 0;
          return (
            <button
              key={`${ligne.id}-${index}`}
              type="button"
              onClick={() => aller(ligne.id)}
              aria-label={`${glypheStatut(st)} Ouvrir « ${t.title} »`}
              aria-current={sousCurseur ? 'true' : undefined}
              className={`text-left rounded-lg px-2 py-1 flex items-start gap-2 cursor-pointer ${
                transitive ? 'text-xs' : 'text-[13px]'
              }`}
              style={{
                marginLeft: ligne.profondeur * 12,
                color: transitive ? 'var(--color-text-tertiary)' : 'var(--color-text)',
                borderLeft: transitive ? '1px solid var(--color-border)' : '1px solid transparent',
                // Surbrillance par un trait, pas une teinte : lisible en Ardéchine.
                outline: sousCurseur ? '2px solid var(--color-accent)' : 'none',
                outlineOffset: -2,
                textDecoration: t.done ? 'line-through' : undefined,
              }}
            >
              <Glyphe statut={st} />
              <span className="min-w-0 flex-1 whitespace-normal break-words">{t.title}</span>
            </button>
          );
        })}
      </div>
    );
  };

  return createPortal(
    <div
      className="voile-modal z-50 flex items-center justify-center p-4"
      // Léger : le graphe reste visible derrière, c'est lui que la fiche commente.
      style={{ background: 'rgba(0,0,0,0.35)' }}
      onClick={onFermer}
      role="presentation"
    >
      <CadreVitre
        // Le ref passe par `useSurfaceVitree` dans CadreVitre : on retrouve la
        // boîte par son rôle pour le piège de focus et la frappe.
        role="dialog"
        aria-modal="true"
        aria-label={`Branches — ${tache.title}`}
        className="fiche-branches-entree w-full max-w-[520px] rounded-2xl flex flex-col overflow-hidden"
        // Le verre de CadreVitre est fait pour reposer sur le fond de page
        // (3 % de remplissage, 0,18 px de flou) : posé sur le graphe, le
        // titre se lisait à travers les cartes de derrière. Un fond presque
        // plein sous le reflet garde la tranche et l'éclat, et rend le texte.
        style={{
          maxHeight: 'min(80vh, 560px)',
          background: 'color-mix(in srgb, var(--color-bg-secondary) 94%, transparent)',
        }}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={surClavier}
      >
        <div ref={boite} tabIndex={-1} className="flex flex-col flex-1 min-h-0 outline-none">
          <div className="flex items-start gap-3 px-4 pt-4 pb-3 shrink-0">
            <div className="min-w-0 flex-1">
              {fil.length > 1 && (
                <nav aria-label="Fil de navigation" className="flex flex-wrap items-center gap-1 text-[11px] mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                  {fil.map((id, index) => {
                    const t = reseau.parId.get(id);
                    if (!t) return null;
                    const courant = index === fil.length - 1;
                    return (
                      <span key={`${id}-${index}`} className="flex items-center gap-1 min-w-0">
                        {index > 0 && <span aria-hidden="true">›</span>}
                        {courant ? (
                          <span className="truncate max-w-[160px]" style={{ color: 'var(--color-text-secondary)' }}>
                            {t.title}
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => revenirA(index)}
                            className="truncate max-w-[140px] cursor-pointer underline-offset-2 hover:underline"
                          >
                            {t.title}
                          </button>
                        )}
                      </span>
                    );
                  })}
                </nav>
              )}
              <div key={tache.id} className="fiche-branches-glisse">
                <h2 className="text-base font-semibold leading-snug flex items-start gap-2" style={{ color: 'var(--color-text)' }}>
                  <Glyphe statut={statut} />
                  <span className="min-w-0 whitespace-normal break-words" style={{ textDecoration: tache.done ? 'line-through' : undefined }}>
                    {tache.title}
                  </span>
                </h2>
                <p className="text-[11px] mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                  {ligneDeComptes(reseau, tache.id)}
                  {/* « Sur la chaîne la plus longue » ou « Marge : 1 tâche » —
                      en tâches, jamais en jours : aucune durée n'existe. */}
                  {place && <> · {place}</>}
                </p>
                {ouvrirait.length > 0 && (
                  <p className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                    Terminer ceci ouvre : {ouvrirait.join(', ')}
                  </p>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={onFermer}
              aria-label="Fermer la fiche"
              className="size-7 rounded-lg flex items-center justify-center cursor-pointer shrink-0"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <X size={15} />
            </button>
          </div>

          <div key={tache.id} className="fiche-branches-glisse min-h-0 overflow-y-auto px-4 pb-3 grid gap-3">
            {tache.notes && (
              <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                <p className={notesDepliees ? 'whitespace-pre-wrap' : 'line-clamp-2 whitespace-pre-wrap'}>{tache.notes}</p>
                <button
                  type="button"
                  onClick={() => setNotesDepliees((v) => !v)}
                  className="text-[11px] mt-0.5 cursor-pointer underline-offset-2 hover:underline"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  {notesDepliees ? 'Replier' : 'Voir'}
                </button>
              </div>
            )}
            {estOrpheline(reseau, tache.id) && (
              <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                Sans lien dans le réseau — « Relier depuis ici » la rattache à ce qu’elle débloque.
              </p>
            )}
            {/* À 340 px, les deux colonnes s'empilent : Attend, puis Débloque. */}
            <div className="grid gap-3 sm:grid-cols-2">
              {rendreColonne('amont')}
              {rendreColonne('aval')}
            </div>
          </div>

          <div className="relative flex items-center gap-2 px-4 py-3 shrink-0" style={{ borderTop: '1px solid var(--color-border)' }}>
            <button
              type="button"
              disabled={saving}
              onClick={() => void onToggle(tache)}
              className="rounded-xl px-3 py-1.5 text-xs font-medium disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
              style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
            >
              {saving && <Loader2 size={12} className="animate-spin" />}
              {tache.done ? 'Rouvrir' : 'Terminer'}
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => onRelierDepuis(tache)}
              title="Relier depuis ici (L)"
              className="rounded-xl px-3 py-1.5 text-xs disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            >
              <Link2 size={13} />
              <span className="max-sm:hidden">Relier depuis ici</span>
              <span className="sm:hidden">Relier</span>
            </button>
            <button
              type="button"
              onClick={() => setCarnetOuvert(true)}
              title="Carnet (N)"
              className="rounded-xl px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            >
              <NotebookPen size={13} />
              Carnet
            </button>
            <button
              type="button"
              onClick={() => (menuOuvert ? fermerMenu() : setMenuOuvert(true))}
              aria-label="Autres actions"
              aria-expanded={menuOuvert}
              className="ml-auto size-8 rounded-lg flex items-center justify-center cursor-pointer"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <MoreHorizontal size={16} />
            </button>
            {menuOuvert && (
              <div
                role="menu"
                className="absolute right-4 bottom-[calc(100%+4px)] min-w-[180px] rounded-xl p-1 grid gap-0.5 text-xs z-10"
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px solid var(--color-border)',
                  boxShadow: '0 8px 24px -12px rgba(0,0,0,0.4)',
                }}
              >
                {/* Le couloir (18 sept. 2026) : un champ qui propose les
                    catégories déjà employées dans le projet et accepte un mot
                    nouveau ; posé à Entrée ou en quittant le champ, vidé pour
                    le retirer. 100 caractères : la borne du serveur (store.py). */}
                <label className="grid gap-1 px-2 py-1">
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Catégorie (couloir)</span>
                  <input
                    list={`fiche-couloirs-${tache.id}`}
                    value={categorieSaisie ?? tache.category ?? ''}
                    onChange={(event) => {
                      saisieEnCours.current = event.target.value;
                      setCategorieSaisie(event.target.value);
                    }}
                    onBlur={poserCategorie}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        poserCategorie();
                        fermerMenu();
                      }
                    }}
                    placeholder="Aucune"
                    maxLength={100}
                    disabled={saving}
                    className="w-full rounded-lg px-2 py-1 text-xs bg-transparent outline-none disabled:opacity-50"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  />
                  <datalist id={`fiche-couloirs-${tache.id}`}>
                    {couloirs.map((c) => (
                      <option key={c} value={c} />
                    ))}
                  </datalist>
                </label>
                {(tache.date || tache.stage) && (
                  <div className="px-2 py-1" style={{ color: 'var(--color-text-tertiary)' }}>
                    {tache.date && <div>Le {tache.date}</div>}
                    {tache.stage && <div>Étape : {tache.stage}</div>}
                  </div>
                )}
                <button
                  type="button"
                  role="menuitem"
                  disabled={saving}
                  onClick={() => {
                    fermerMenu();
                    void onSupprimer(tache);
                  }}
                  className="text-left rounded-lg px-2 py-1.5 cursor-pointer disabled:opacity-50"
                  style={{ color: 'var(--color-error, var(--color-text))' }}
                >
                  Supprimer…
                </button>
              </div>
            )}
          </div>
        </div>
      </CadreVitre>
      {/* Le carnet est un portail à son tour ; ses clics remontent l'arbre
          REACT jusqu'au voile de la fiche. Sans ce garde-fou, fermer le
          carnet en cliquant à côté fermait aussi la fiche. */}
      {carnetOuvert && (
        <div onClick={(e) => e.stopPropagation()} role="presentation">
          <CarnetDeTache
            tache={tache}
            onFermer={() => {
              setCarnetOuvert(false);
              // Le textarea disparaît avec le carnet : sans ce rappel, le
              // focus tombait sur `body` et « n », les flèches et Échap
              // n'atteignaient plus la fiche.
              boite.current?.focus();
            }}
            onEnregistrer={(journal) => onEnregistrerCarnet(tache.id, journal)}
          />
        </div>
      )}
    </div>,
    document.body,
  );
}
