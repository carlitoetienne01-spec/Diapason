import type { ReactNode } from 'react';
import { useSurfaceVitree } from '../Chat/useSurfaceVitree';
import '../Chat/ComposerGlass.css';
import './CarteVitree.css';

interface CarteVitreeProps {
  as?: 'div' | 'section' | 'article';
  /** Position dans la page : marges et taille, hors de la vitre. */
  className?: string;
  /** Disposition du contenu, protégée des reflets. */
  contenuClassName?: string;
  children: ReactNode;
}

export function CarteVitree({
  as: Balise = 'div', className = '', contenuClassName = '', children,
}: CarteVitreeProps) {
  const surface = useSurfaceVitree(true);
  return (
    <Balise className={`carte-vitree-support ${className}`}>
      <div ref={surface} className={`composer-glass carte-vitree ${contenuClassName}`}>
        {children}
      </div>
    </Balise>
  );
}
