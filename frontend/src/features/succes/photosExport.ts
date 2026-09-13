// Sortir une photo de sa pile : vers un PDF, vers une note.
//
// Les deux passent par le même rendu — l'original tourné, cadré, avec ses
// annotations gravées — pour que ce qu'on exporte soit ce qu'on voit.

import { isTauri } from '../../lib/api';
import { exporterSuccesFichier, getSuccesPhotoContenu, listSuccesNotes, updateSuccesNote } from './api';
import { construirePdf, octetsEnBase64, type PagePhoto } from './pdfPhotos';
import { canvasEnJpeg, chargerImage, rendrePhoto } from './photosClient';
import type { SuccesNote, SuccesPhoto } from './types';

/** Le grand côté d'une page de PDF : assez pour lire du code, pas un scan. */
const COTE_PDF = 1800;
/** Le grand côté d'une image insérée dans une note : les notes sont bornées à 1 Mo. */
const COTE_NOTE = 1200;
const NOTE_OCTETS_MAX = 1_000_000;

/** L'original d'une photo, décodé. */
export async function chargerOriginal(photo: SuccesPhoto): Promise<HTMLImageElement> {
  const contenu = await getSuccesPhotoContenu(photo.id);
  return chargerImage(`data:${contenu.mime};base64,${contenu.dataBase64}`);
}

/** Une page de PDF pour cette photo, annotations comprises. */
export async function pagePour(photo: SuccesPhoto): Promise<PagePhoto> {
  const image = await chargerOriginal(photo);
  const rendu = rendrePhoto(image, photo.rotation, photo.crop, {
    annotations: photo.annotations,
    maxCote: COTE_PDF,
  });
  return {
    jpeg: canvasEnJpeg(rendu.canvas, 0.85).octets,
    largeur: rendu.largeur,
    hauteur: rendu.hauteur,
    legende: photo.caption || photo.fileName,
  };
}

/**
 * Le PDF d'une liste de photos, enregistré là où l'utilisateur le choisit.
 *
 * Dans l'app de bureau : le dialogue « Enregistrer sous » de macOS, puis le
 * serveur écrit le fichier (la fenêtre n'a pas de droit d'écriture directe).
 * Dans un navigateur : un téléchargement. Rend le chemin ou le nom écrit,
 * ou `null` si l'utilisateur a annulé.
 */
export async function exporterPdf(
  photos: SuccesPhoto[],
  titre: string,
  nomFichier: string,
  surProgres?: (fait: number, total: number) => void,
): Promise<string | null> {
  const pages: PagePhoto[] = [];
  for (let i = 0; i < photos.length; i += 1) {
    pages.push(await pagePour(photos[i]));
    surProgres?.(i + 1, photos.length);
  }
  const pdf = construirePdf(pages, titre);

  if (isTauri()) {
    const { save } = await import('@tauri-apps/plugin-dialog');
    const chemin = await save({
      defaultPath: nomFichier,
      filters: [{ name: 'PDF', extensions: ['pdf'] }],
      title: `Exporter « ${titre} » en PDF`,
    });
    if (!chemin) return null;
    const resultat = await exporterSuccesFichier(chemin, octetsEnBase64(pdf));
    return resultat.path;
  }

  const blob = new Blob([pdf], { type: 'application/pdf' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = nomFichier;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return nomFichier;
}

/** Les notes où l'on peut mettre une photo, les plus récentes d'abord. */
export async function notesDisponibles(): Promise<SuccesNote[]> {
  const notes = await listSuccesNotes();
  return [...notes].sort((a, b) => b.updatedAtMs - a.updatedAtMs);
}

/**
 * Ajouter la photo à la fin d'une note, en JPEG réduit, avec sa légende.
 * Refuse si la note dépasserait sa taille maximale.
 */
export async function insererDansNote(photo: SuccesPhoto, note: SuccesNote): Promise<void> {
  const image = await chargerOriginal(photo);
  const rendu = rendrePhoto(image, photo.rotation, photo.crop, {
    annotations: photo.annotations,
    maxCote: COTE_NOTE,
  });
  const { base64 } = canvasEnJpeg(rendu.canvas, 0.8);
  const legende = (photo.caption || '').replace(/[<>&"]/g, (c) =>
    c === '<' ? '&lt;' : c === '>' ? '&gt;' : c === '&' ? '&amp;' : '&quot;',
  );
  const html =
    `<p><img src="data:image/jpeg;base64,${base64}" alt="${legende}" ` +
    `width="${rendu.largeur}" height="${rendu.hauteur}"></p>` +
    (legende ? `<p><em>${legende}</em></p>` : '');
  const contenu = (note.content || '') + html;
  if (contenu.length > NOTE_OCTETS_MAX) {
    throw new Error(
      'Cette note est presque pleine : la photo ne tient plus dedans. Choisis une autre note.',
    );
  }
  await updateSuccesNote(note.id, { content: contenu });
}
