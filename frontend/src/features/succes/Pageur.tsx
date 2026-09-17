import { useEffect } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

import { estDansUneZoneDeSaisie } from '../../lib/saisie';
import { ELLIPSE, TAILLES_PAGE, fenetrePages, pageParFleche, type TaillePage } from './pagination';

/**
 * Le pageur des listes de tâches (demande de Carlito, 17 sept. 2026) : la
 * tranche affichée, le choix de la taille, les numéros avec leurs ellipses
 * et les deux flèches. Toute la décision vit dans `pagination.ts` ; ici on
 * peint et on écoute le clavier.
 *
 * Tient à 340 px (mini-panneau) : sept cases de 32 px au plus, chiffres
 * tabulaires pour que « 9 » et « 95 » aient la même colonne, et les deux
 * rangées (tranche + taille, numéros) se replient l'une sous l'autre plutôt
 * que d'écraser les boutons — `flex-wrap`, jamais de largeur fixe.
 *
 * `teinte` : `succes` pour l'onglet Terminées — Carlito a demandé que ses
 * numéros soient « d'une autre couleur ». En Ardéchine, `--color-success`
 * est l'encre elle-même : la classe `teinte-terminees` y ajoute un
 * soulignement (index.css), la forme prend le relais de la couleur.
 */
export interface PageurProps {
  page: number;
  nbPages: number;
  total: number;
  debut: number;
  fin: number;
  parPage: TaillePage;
  onPage: (page: number) => void;
  onParPage: (taille: TaillePage) => void;
  /** Ce qu'on pagine, au pluriel — « tâches ». */
  unite: string;
  teinte?: 'accent' | 'succes';
  /**
   * ← et → changent de page, sauf dans un champ, une modale ou un menu, ou
   * avec un modificateur (§82 : le clavier est un chemin, jamais un piège).
   * Un seul pageur à la fois doit l'écouter.
   */
  clavier?: boolean;
}

/**
 * Une modale, un menu ou un dialogue ouvert : les flèches lui appartiennent.
 * `[role="dialog"]` compris : la grille d'emojis (un portail de boutons, sans
 * aria-modal) laissait passer → au pageur, qui changeait de page et démontait
 * la carte en édition avec son brouillon (revue du 17 sept. 2026).
 */
function uneSurcoucheEstOuverte(): boolean {
  return document.querySelector('[aria-modal="true"], [role="menu"], [role="dialog"]') !== null;
}

export function Pageur({
  page, nbPages, total, debut, fin, parPage, onPage, onParPage, unite, teinte = 'accent', clavier = true,
}: PageurProps) {
  useEffect(() => {
    if (!clavier || nbPages <= 1) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const suivante = pageParFleche(event.key, page, nbPages, {
        modifieur: event.metaKey || event.ctrlKey || event.altKey || event.shiftKey,
        saisie: estDansUneZoneDeSaisie(event.target),
        surcouche: uneSurcoucheEstOuverte(),
      });
      if (suivante === null) return;
      event.preventDefault();
      onPage(suivante);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [clavier, page, nbPages, onPage]);

  // Rien à paginer sous la plus petite taille : un pageur d'une page pour
  // trois tâches serait du chrome pour rien.
  if (total <= TAILLES_PAGE[0]) return null;

  const couleur = teinte === 'succes' ? 'var(--color-success)' : 'var(--color-accent)';
  const classeTeinte = teinte === 'succes' ? 'teinte-terminees' : '';

  return (
    <nav
      aria-label={`Pages des ${unite}`}
      className="mt-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2"
    >
      <div className="flex items-center gap-2 text-xs tabular-nums" style={{ color: 'var(--color-text-tertiary)' }}>
        <span aria-live="polite">{debut}–{fin} sur {total}</span>
        <select
          value={parPage}
          onChange={(event) => onParPage(Number(event.target.value) as TaillePage)}
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none cursor-pointer"
          style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
          aria-label={`${unite} par page`}
        >
          {TAILLES_PAGE.map((taille) => (
            <option key={taille} value={taille}>{taille} par page</option>
          ))}
        </select>
      </div>
      {nbPages > 1 && (
        // Deux fenêtres de numéros : 5 cases sous sm (« 1 … 4 … 95 »), 7 dès
        // sm. À 340 px en peau terminal (html 18 px), la fenêtre de 7 faisait
        // 351 px : le › sortait du panneau et « 95 » était coupé (mesuré en
        // revue le 17 sept. 2026). `flex-wrap` en filet pour data-font-size
        // large.
        <div className="flex flex-wrap items-center gap-1">
          <button
            type="button"
            onClick={() => onPage(page - 1)}
            disabled={page <= 1}
            className="size-8 rounded-lg flex items-center justify-center cursor-pointer disabled:opacity-35 disabled:cursor-default"
            style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            aria-label="Page précédente"
            title="Page précédente (←)"
          >
            <ChevronLeft size={15} />
          </button>
          {[0, 1].map((voisins) => (
            <div
              key={voisins}
              className={`${voisins === 0 ? 'flex sm:hidden' : 'hidden sm:flex'} items-center gap-1`}
            >
          {fenetrePages(page, nbPages, voisins).map((caseDePageur, index) =>
            caseDePageur === ELLIPSE ? (
              <span
                key={`ellipse-${index}`}
                aria-hidden
                className="min-w-6 h-8 flex items-end justify-center pb-1.5 text-xs select-none"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                {ELLIPSE}
              </span>
            ) : (
              <button
                key={caseDePageur}
                type="button"
                onClick={() => onPage(caseDePageur)}
                aria-current={caseDePageur === page ? 'page' : undefined}
                aria-label={`Page ${caseDePageur}`}
                className={`min-w-8 h-8 px-1.5 rounded-lg text-xs tabular-nums cursor-pointer ${classeTeinte} ${
                  caseDePageur === page ? 'font-semibold' : ''
                }`}
                style={
                  caseDePageur === page
                    ? {
                      color: couleur,
                      border: `1px solid ${couleur}`,
                      background: `color-mix(in srgb, ${couleur} 14%, transparent)`,
                    }
                    : {
                      color: teinte === 'succes' ? couleur : 'var(--color-text-secondary)',
                      border: '1px solid transparent',
                    }
                }
              >
                {caseDePageur}
              </button>
            ),
          )}
            </div>
          ))}
          <button
            type="button"
            onClick={() => onPage(page + 1)}
            disabled={page >= nbPages}
            className="size-8 rounded-lg flex items-center justify-center cursor-pointer disabled:opacity-35 disabled:cursor-default"
            style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
            aria-label="Page suivante"
            title="Page suivante (→)"
          >
            <ChevronRight size={15} />
          </button>
        </div>
      )}
    </nav>
  );
}
