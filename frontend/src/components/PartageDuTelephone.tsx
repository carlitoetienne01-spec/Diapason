import { useEffect } from 'react';
import { useNavigate } from 'react-router';

import { pontNatif } from '../lib/natif';
import { boiteDuPartage, recevoirUnPartage } from '../lib/partageEntrant';
import { DELAI_AFFICHAGE_MS } from './NavigationDuTelephone';

/**
 * L'autre bout du verbe `partager` : un « Partager vers Diapason » fait
 * depuis une autre app du téléphone arrive à la coquille Flutter, qui le
 * remet ici (26/09/2026, phase 5). Monté seulement quand `estMobile`.
 *
 * La Discussion peut mettre le même temps à monter qu'une page demandée
 * par le maillage : même délai (`DELAI_AFFICHAGE_MS`), et la réponse ne
 * part qu'une fois le compositeur servi (§100).
 */
export function PartageDuTelephone() {
  const navigate = useNavigate();

  useEffect(() => {
    if (!pontNatif) return undefined;
    return pontNatif.surPartager((donnees) =>
      recevoirUnPartage(donnees, {
        naviguer: (chemin) => navigate(chemin),
        boite: boiteDuPartage,
        delaiMs: DELAI_AFFICHAGE_MS,
      }),
    );
  }, [navigate]);

  return null;
}
