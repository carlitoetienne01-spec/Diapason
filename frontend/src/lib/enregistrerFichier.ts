// Enregistrer un fichier produit par la page, hors de l'app de bureau.
//
// 26/09/2026 : quatre exports (PDF d'une pile de photos, visuel de la
// Discussion, export JSON de la vie, sauvegarde des conversations)
// fabriquaient un lien `blob:` et cliquaient dessus. Dans la WebView
// d'Android, ce clic ne fait RIEN — aucun fichier, aucune erreur — et trois
// d'entre eux affichaient ensuite « exporté » ou « téléchargé ». Dans le
// téléphone, le fichier part donc à la coquille par le verbe `enregistrer`,
// et on n'annonce un nom qu'une fois la coquille revenue en disant qu'elle
// l'a écrit (§100 : la phrase vient du récepteur).
//
// Le contenu voyage en base64 dans du JSON : un canal JavaScript ne porte
// que du texte, et la WebView de macOS refusait déjà les corps binaires
// (« Load failed », CLAUDE.md §5).

import { octetsEnBase64 } from '../features/vie/pdfPhotos';
import { traduire } from '../i18n/translate';
import { estMobile, pontNatif, type PontNatif, type ReponseNatif } from './natif';

export type Environnement = {
  mobile: boolean;
  demander: (verbe: 'enregistrer', donnees: unknown) => Promise<ReponseNatif>;
  telecharger: (blob: Blob, nom: string) => void;
};

/** Le téléchargement du navigateur : un lien `blob:` cliqué, puis relâché. */
export function telechargerDansLeNavigateur(blob: Blob, nom: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = nom;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Relâcher tout de suite annulait le téléchargement sous Safari : le clic
  // n'a fait que le PROGRAMMER. Dix secondes suffisent à le démarrer.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function environnementCourant(pont: PontNatif | null = pontNatif): Environnement {
  return {
    mobile: estMobile && pont !== null,
    demander: (verbe, donnees) =>
      pont ? pont.demander(verbe, donnees) : Promise.reject(new Error(traduire('natif.absent'))),
    telecharger: telechargerDansLeNavigateur,
  };
}

/**
 * Ce que la coquille a répondu à `enregistrer`, en un nom ou `null`.
 *
 * - `ok` : le nom qu'elle dit avoir écrit (à défaut, celui qu'on a proposé) ;
 * - `annule` : la personne a renoncé dans le sélecteur — `null`, sans erreur ;
 * - tout autre refus : une erreur qui porte la phrase de la coquille.
 */
export function lireReponseEnregistrer(reponse: ReponseNatif, nomPropose: string): string | null {
  if (reponse.ok) {
    const nom = (reponse.donnees as { nom?: unknown } | undefined)?.nom;
    return typeof nom === 'string' && nom.trim() ? nom : nomPropose;
  }
  if (reponse.erreur === 'annule') return null;
  throw new Error(reponse.erreur || traduire('natif.enregistrementEchoue'));
}

/**
 * Enregistrer `blob` sous `nom` : par la coquille dans le téléphone, par un
 * téléchargement ailleurs. Rend le nom écrit, ou `null` si la personne a
 * renoncé. Là où l'app de bureau a son propre chemin (dialogue
 * « Enregistrer sous » puis écriture par le serveur), l'appelant le prend
 * avant d'arriver ici ; ailleurs, la fenêtre de bureau télécharge comme un
 * navigateur, ce qui ne change pas.
 */
export async function enregistrerHorsBureau(
  blob: Blob,
  nom: string,
  env: Environnement = environnementCourant(),
): Promise<string | null> {
  if (!env.mobile) {
    env.telecharger(blob, nom);
    return nom;
  }
  const base64 = octetsEnBase64(new Uint8Array(await blob.arrayBuffer()));
  const reponse = await env.demander('enregistrer', {
    nom,
    mime: blob.type || 'application/octet-stream',
    base64,
  });
  return lireReponseEnregistrer(reponse, nom);
}
