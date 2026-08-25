/**
 * Dire au serveur ce que l'écran affiche.
 *
 * Spatial Mesh, handoff — 25 août 2026. « Continue ce projet sur mon
 * téléphone » suppose que « ce projet » ait un référent, et il n'en avait
 * aucun : les routes sont statiques, la sélection vit en état local de
 * composant, et le serveur ne savait rien de tout cela.
 *
 * Le cliché est VOLATILE côté serveur (trois minutes) et n'est jamais
 * persisté : ceci n'est pas de la télémétrie, c'est un référent pour le mot
 * « ça ». Aucun contenu ne part — un chemin d'écran, un type, un
 * identifiant, un titre.
 */

import { apiFetch } from '../../lib/api';

export type RessourceVue = {
  type: 'project' | 'note' | 'task';
  id: string;
  title?: string;
};

let dernierEnvoi = '';

/** Publier l'écran courant. Silencieux : un cliché raté n'est pas une panne. */
export async function publierLaVue(
  path: string,
  ressource?: RessourceVue | null,
): Promise<void> {
  const corps = {
    path,
    resourceType: ressource?.type ?? '',
    resourceId: ressource?.id ?? '',
    resourceTitle: ressource?.title ?? '',
  };
  // Ne pas répéter le même cliché : la sélection se recalcule à chaque
  // rendu, et le serveur n'a rien à apprendre d'un état inchangé.
  const empreinte = JSON.stringify(corps);
  if (empreinte === dernierEnvoi) return;
  dernierEnvoi = empreinte;
  try {
    await apiFetch('/v1/context/view', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: empreinte,
    });
  } catch {
    // Le référent est un bonus : son absence rend l'assistant ignorant,
    // jamais l'interface cassée.
  }
}
