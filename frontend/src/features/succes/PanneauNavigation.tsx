import { useEffect, useMemo, useRef, useState } from 'react';
import { FileText, List, X } from 'lucide-react';

import {
  construireSommaire,
  debutsDePage,
  type EntreeDeSommaire,
} from './noteNavigation';
import { OVERFLOW_GAP_CLASS } from './notePages';

type Props = {
  editeur: HTMLElement | null;
  bureau: HTMLElement | null;
  /** Le zoom courant : les mesures d'écran doivent y être ramenées. */
  zoom: number;
  pageCourante: number;
  onFermer: () => void;
  /** Change à chaque pagination, pour relire le document. */
  cle: string;
};

/**
 * Le volet de navigation, comme celui de Word.
 *
 * Deux onglets : les PAGES en miniature, pour aller exactement où l'on veut,
 * et les TITRES, pour se déplacer par chapitre. Sans lui, un document de
 * quarante-sept pages ne se parcourt qu'à la molette.
 *
 * Les miniatures sont construites en clonant, pour chaque page, LES SEULS
 * blocs de cette page. Cloner le document entier dans chaque vignette ferait
 * quarante-sept copies d'un document de soixante mille pixels ; ici la somme
 * des vignettes vaut un document, et chacune n'est construite que lorsqu'elle
 * entre dans le champ (`IntersectionObserver`).
 */
export function PanneauNavigation({
  editeur,
  bureau,
  zoom,
  pageCourante,
  onFermer,
  cle,
}: Props) {
  const [onglet, setOnglet] = useState<'pages' | 'titres'>('pages');
  const liste = useRef<HTMLDivElement>(null);

  /** Les bornes de page, en unités de layout, relues à chaque pagination. */
  const mesure = useMemo(() => {
    if (!editeur) return { bornes: [] as number[], titres: [] as EntreeDeSommaire[] };
    const haut = editeur.getBoundingClientRect().top;
    const enLayout = (v: number) => (v - haut) / zoom;
    const bornes = Array.from(
      editeur.querySelectorAll<HTMLElement>(`.${OVERFLOW_GAP_CLASS}`),
    )
      .map((c) => enLayout(c.getBoundingClientRect().bottom))
      .sort((a, b) => a - b)
      // Une ligne de tableau fractionnée pose une cale par CELLULE, à la même
      // hauteur : ce sont des doublons, pas des pages.
      .filter((v, i, tab) => i === 0 || v - tab[i - 1] > 2);
    const titres = construireSommaire(
      Array.from(editeur.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6')).map(
        (h) => ({
          balise: h.tagName,
          texte: h.textContent || '',
          haut: enLayout(h.getBoundingClientRect().top),
        }),
      ),
      bornes,
    );
    return { bornes, titres };
  }, [editeur, zoom, cle]);

  const debuts = useMemo(() => debutsDePage(mesure.bornes), [mesure.bornes]);

  // Le titre en cours de lecture : le dernier dont la page est atteinte.
  // Sans lui, le plan d'un document de soixante et une pages ne dit jamais
  // où l'on se trouve dedans.
  const titreCourant = useMemo(() => {
    let vu = -1;
    for (const t of mesure.titres) {
      if (t.page > pageCourante) break;
      vu = t.index;
    }
    return vu;
  }, [mesure.titres, pageCourante]);

  // Suivre la lecture : quand le défilement change de page, amener l'entrée
  // active sous les yeux — mais SEULEMENT si elle en est sortie, sinon le
  // volet se recadrerait sous la main de celui qui le parcourt.
  useEffect(() => {
    const boite = liste.current;
    if (!boite) return;
    const actif = boite.querySelector<HTMLElement>('[data-actif="oui"]');
    if (!actif) return;
    const b = boite.getBoundingClientRect();
    const a = actif.getBoundingClientRect();
    if (a.top >= b.top && a.bottom <= b.bottom) return;
    boite.scrollTo({
      top: boite.scrollTop + (a.top - b.top) - (b.height - a.height) / 2,
      behavior: 'smooth',
    });
  }, [pageCourante, onglet, titreCourant]);

  const allerA = (hautEnLayout: number) => {
    if (!bureau || !editeur) return;
    const dejaVu = editeur.getBoundingClientRect().top - bureau.getBoundingClientRect().top;
    bureau.scrollTo({ top: bureau.scrollTop + dejaVu + hautEnLayout * zoom, behavior: 'smooth' });
  };

  return (
    <aside
      // En miniature (sous sm), le volet passerait côte à côte et confisquerait
      // la moitié du panneau : il se superpose à la feuille, refermable au ✕.
      className="succes-note-nav shrink-0 flex flex-col min-h-0 w-56 rounded-xl overflow-hidden max-sm:absolute max-sm:inset-y-0 max-sm:left-0 max-sm:z-40 max-sm:shadow-2xl"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      aria-label="Navigation dans le document"
    >
      <div
        className="flex items-center gap-1 p-1.5 shrink-0"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        <button
          type="button"
          title="Pages"
          aria-pressed={onglet === 'pages'}
          onClick={() => setOnglet('pages')}
          className="h-7 flex-1 rounded-lg flex items-center justify-center gap-1 text-[11px] cursor-pointer"
          style={
            onglet === 'pages'
              ? { background: 'var(--color-accent)', color: 'var(--color-bg)' }
              : { color: 'var(--color-text-secondary)' }
          }
        >
          <FileText size={13} /> Pages
        </button>
        <button
          type="button"
          title="Titres"
          aria-pressed={onglet === 'titres'}
          onClick={() => setOnglet('titres')}
          className="h-7 flex-1 rounded-lg flex items-center justify-center gap-1 text-[11px] cursor-pointer"
          style={
            onglet === 'titres'
              ? { background: 'var(--color-accent)', color: 'var(--color-bg)' }
              : { color: 'var(--color-text-secondary)' }
          }
        >
          <List size={13} /> Titres
        </button>
        <button
          type="button"
          aria-label="Fermer la navigation"
          onClick={onFermer}
          className="size-7 rounded-lg flex items-center justify-center cursor-pointer"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          <X size={13} />
        </button>
      </div>

      <div ref={liste} className="min-h-0 flex-1 overflow-auto p-2">
        {onglet === 'pages' ? (
          <ol className="flex flex-col gap-2 m-0 p-0 list-none">
            {debuts.map((debut, i) => (
              <Miniature
                key={`${cle}-${i}`}
                editeur={editeur}
                debut={debut}
                fin={mesure.bornes[i] ?? Number.POSITIVE_INFINITY}
                numero={i + 1}
                courante={i + 1 === pageCourante}
                onAller={() => allerA(debut)}
              />
            ))}
          </ol>
        ) : mesure.titres.length === 0 ? (
          <p className="text-[11px] m-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Cette note n’a pas encore de titres. Les boutons H1, H2 et H3 de la barre
            en créent.
          </p>
        ) : (
          <ul className="flex flex-col m-0 p-0 list-none">
            {mesure.titres.map((t) => (
              <li key={t.index} data-actif={t.index === titreCourant ? 'oui' : 'non'}>
                <button
                  type="button"
                  onClick={() => {
                    const h = editeur?.querySelectorAll('h1,h2,h3,h4,h5,h6')[t.index];
                    if (h && editeur) {
                      const haut =
                        (h.getBoundingClientRect().top -
                          editeur.getBoundingClientRect().top) /
                        zoom;
                      allerA(haut);
                    }
                  }}
                  className="w-full text-left text-[11px] py-1 px-1.5 rounded cursor-pointer truncate"
                  style={{
                    paddingLeft: `${6 + (t.niveau - 1) * 12}px`,
                    color:
                      t.index === titreCourant
                        ? 'var(--color-accent)'
                        : t.niveau === 1
                          ? 'var(--color-text)'
                          : 'var(--color-text-secondary)',
                    fontWeight: t.niveau === 1 || t.index === titreCourant ? 600 : 400,
                    background:
                      t.index === titreCourant ? 'var(--color-bg-tertiary)' : undefined,
                  }}
                  title={`${t.titre} — page ${t.page}`}
                >
                  {t.titre}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

/**
 * Une vignette de page : les blocs de CETTE page, clonés et réduits.
 *
 * Construite seulement quand elle entre dans le champ. Sans cela, ouvrir le
 * volet sur un document de cinquante pages clonerait cinquante fois son
 * contenu d'un coup.
 */
function Miniature({
  editeur,
  debut,
  fin,
  numero,
  courante,
  onAller,
}: {
  editeur: HTMLElement | null;
  debut: number;
  fin: number;
  numero: number;
  courante: boolean;
  onAller: () => void;
}) {
  const boite = useRef<HTMLDivElement>(null);
  const [vue, setVue] = useState(false);

  useEffect(() => {
    const el = boite.current;
    if (!el || vue || typeof IntersectionObserver === 'undefined') return;
    const o = new IntersectionObserver((entrees) => {
      if (entrees.some((e) => e.isIntersecting)) setVue(true);
    });
    o.observe(el);
    return () => o.disconnect();
  }, [vue]);

  useEffect(() => {
    const el = boite.current;
    if (!el || !vue || !editeur) return;
    el.replaceChildren();
    const cadre = editeur.closest<HTMLElement>('.succes-note-frame');
    if (!cadre) return;
    const styleCadre = getComputedStyle(cadre);
    // Les variables de page sont en POUCES (`8.5in`) : les lire avec
    // `parseFloat` rendait 8.5, et la vignette se réduisait au format d'un
    // timbre de huit pixels. On les fait résoudre par le moteur, en posant
    // une sonde de la taille d'une page dans le cadre lui-même.
    const sonde = document.createElement('div');
    sonde.style.cssText =
      'position:absolute;visibility:hidden;pointer-events:none;' +
      'width:var(--note-page-width);height:var(--note-page-height)';
    cadre.appendChild(sonde);
    const pageL = sonde.offsetWidth;
    const pageH = sonde.offsetHeight;
    sonde.remove();
    if (!pageL || !pageH) return;

    // Le zoom de l'écran ne doit pas entrer dans la mesure : la vignette
    // travaille en unités de mise en page, celles où sont exprimées les
    // bornes de page.
    const zoomEditeur =
      editeur.getBoundingClientRect().width / (editeur.offsetWidth || 1) || 1;
    const haut = editeur.getBoundingClientRect().top;

    // La vignette est la PAGE, pas la zone de texte : mêmes marges, même
    // papier, même encre. Une vignette blanche sous un papier sombre
    // montrerait une page qui n'existe pas.
    const stylePapier = getComputedStyle(editeur);
    const page = document.createElement('div');
    page.className = 'succes-note-mini';
    page.style.width = `${pageL}px`;
    page.style.height = `${pageH}px`;
    page.style.paddingTop = styleCadre.getPropertyValue('--note-m-t');
    page.style.paddingRight = styleCadre.getPropertyValue('--note-m-r');
    page.style.paddingBottom = styleCadre.getPropertyValue('--note-m-b');
    page.style.paddingLeft = styleCadre.getPropertyValue('--note-m-l');
    page.style.color = stylePapier.color;
    page.style.fontFamily = stylePapier.fontFamily;
    page.style.lineHeight = stylePapier.lineHeight;

    const encart = document.createElement('div');
    encart.style.overflow = 'hidden';
    encart.style.height = '100%';
    for (const bloc of Array.from(editeur.children)) {
      if (bloc.classList.contains(OVERFLOW_GAP_CLASS)) continue;
      const t = (bloc.getBoundingClientRect().top - haut) / zoomEditeur;
      // Un bloc à cheval sur une coupure (une ligne de tableau fractionnée)
      // est rangé tout entier dans la page où commence son sommet. Une
      // vignette sert à choisir une page, pas à la relire.
      if (t < debut - 2 || t >= fin - 2) continue;
      encart.appendChild(bloc.cloneNode(true));
    }
    page.appendChild(encart);

    const reduction = (el.clientWidth || 1) / pageL;
    page.style.transform = `scale(${reduction})`;
    el.style.aspectRatio = `${pageL} / ${pageH}`;
    el.style.background = getComputedStyle(
      editeur.closest<HTMLElement>('.succes-note-page') ?? editeur,
    ).backgroundColor;
    el.appendChild(page);
  }, [vue, editeur, debut, fin]);

  return (
    <li data-actif={courante ? 'oui' : 'non'}>
      <button
        type="button"
        onClick={onAller}
        className="w-full flex flex-col items-center gap-1 cursor-pointer"
        title={`Aller à la page ${numero}`}
      >
        <div
          ref={boite}
          className="succes-note-miniature w-full"
          style={{
            outline: courante
              ? '2px solid var(--color-accent)'
              : '1px solid var(--color-border)',
          }}
        />
        <span
          className="text-[10px] tabular-nums"
          style={{ color: courante ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }}
        >
          {numero}
        </span>
      </button>
    </li>
  );
}
