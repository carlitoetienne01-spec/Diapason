import { useEffect } from 'react';
import { useNavigate } from 'react-router';

import { readShellNavigation } from '../features/mesh/routes';
import { traduire } from '../i18n/translate';
import { pontNatif } from '../lib/natif';
import { pagesAffichees } from '../lib/pagesAffichees';
import { useAppStore } from '../lib/store';

/**
 * Combien le bundle attend qu'une page demandée par la coquille soit montée.
 *
 * Huit secondes : le morceau d'une page de vie pèse quelques dizaines de ko,
 * servis par le Mac à travers le tailnet — une seconde en Wi-Fi, plusieurs
 * en données mobiles faibles. Au-delà, l'appareil qui a demandé doit lire un
 * échec plutôt que « ouvert ». Moins que les dix secondes de la coquille
 * (`delaiNaviguer`, mesh_executor.dart), pour que ce soit la phrase d'ici qui
 * arrive, pas son délai.
 */
export const DELAI_AFFICHAGE_MS = 8_000;

/**
 * L'autre bout du verbe `naviguer` : au téléphone, une commande du maillage
 * arrive à la coquille Flutter, qui traduit la route et demande l'écran ici
 * (26/09/2026, phase 3 étape 9). Monté seulement quand `estMobile` — la
 * fenêtre du Mac a `MeshHost`, qui lit la boîte du maillage.
 *
 * La réponse n'arrive qu'une fois la page MONTÉE (`pagesAffichees`) : c'est
 * elle que la coquille acquitte SUCCESS à l'appareil qui a demandé (§100).
 */
export function NavigationDuTelephone() {
  const navigate = useNavigate();
  const setPendingMeshSelection = useAppStore((s) => s.setPendingMeshSelection);

  useEffect(() => {
    if (!pontNatif) return undefined;
    return pontNatif.surNaviguer(async (donnees) => {
      const cible = readShellNavigation(donnees);
      if (!cible) throw new Error(traduire('natif.naviguer.inconnu'));
      // Posée avant de naviguer : la page lit la sélection à sa montée, et la
      // montée a lieu pendant navigate() (même règle que MeshHost).
      if (cible.selection) setPendingMeshSelection(cible.selection);
      const affichee = pagesAffichees.attendre(cible.path, DELAI_AFFICHAGE_MS);
      navigate(cible.path);
      if (!(await affichee)) throw new Error(traduire('natif.naviguer.pasAffichee'));
      return { path: cible.path, selection: cible.selection ?? null };
    });
  }, [navigate, setPendingMeshSelection]);

  return null;
}
