import { createElement, type HTMLAttributes } from 'react';
import { useSurfaceVitree } from '../Chat/useSurfaceVitree';
import { styleCadreVitre } from './styleCadreVitre';
import '../Chat/ComposerGlass.css';
import './CarteVitree.css';
import './CadreVitre.css';

type CadreVitreProps = HTMLAttributes<HTMLElement> & {
  as?: 'div' | 'section' | 'article' | 'button';
  compact?: boolean;
  actif?: boolean;
  type?: 'button';
  disabled?: boolean;
};

/** La même balise et les mêmes événements : pas de conteneur intermédiaire
 * qui changerait la grille, le glisser-déposer ou la sémantique du bouton. */
export function CadreVitre({
  as = 'div', compact = false, actif = true, className = '', style, children, ...attributs
}: CadreVitreProps) {
  const surface = useSurfaceVitree<HTMLElement>(true, actif);
  // TaskCard sert aussi dans Projets, hors du périmètre de cette demande.
  // Son appelant choisit la matière ; aucun habillage implicite ailleurs.
  if (!actif) return createElement(as, { ...attributs, className, style }, children);
  return createElement(as, {
    ...attributs,
    ref: surface,
    className: `composer-glass carte-vitree cadre-vitre ${className}`,
    style: styleCadreVitre(style),
    'data-verre-densite': compact ? 'compact' : 'normal',
  }, children);
}
