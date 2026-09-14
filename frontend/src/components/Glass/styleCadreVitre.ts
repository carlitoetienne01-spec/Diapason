import type { CSSProperties } from 'react';

/** Retirer seulement les aplats neutres hérités. Les couleurs d'alerte,
 * de sélection et de dépôt restent prioritaires sur le matériau. */
export function styleCadreVitre(style: CSSProperties = {}): CSSProperties {
  const resultat = { ...style };
  if (style.background === 'var(--color-surface)' || style.background === 'var(--color-bg-secondary)') {
    delete resultat.background;
  }
  if (style.border === '1px solid var(--color-border)' || style.border === '1px solid transparent') {
    delete resultat.border;
  }
  return resultat;
}
