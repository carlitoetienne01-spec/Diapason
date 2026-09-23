// Les images qu'on joint à un message, avant l'envoi.
//
// 22/09/2026. Le serveur sait recevoir des images depuis ce jour
// (server/pieces_jointes.py) et qwen3.5:9b annonce « vision » ; il manquait
// de quoi en choisir une. Toute la décision vit ici plutôt que dans le
// composant : ce dépôt n'a aucun test de composant React, donc ce qui doit
// être vérifié doit être une fonction pure (CLAUDE.md).
//
// Les bornes sont celles du serveur, recopiées pour refuser AVANT le
// voyage : encoder quatre mégaoctets en base64 pour recevoir un 400 est un
// aller-retour qu'on peut éviter. Si elles divergent un jour, c'est le
// serveur qui tranche — lui seul voit les octets.

export const TAILLE_MAX = 4 * 1024 * 1024;
export const NOMBRE_MAX = 7;

// Ce que les modèles de vision savent lire. Le serveur revérifie dans les
// octets : le type que le navigateur annonce vient du nom du fichier.
export const FORMATS = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'] as const;

export interface PieceJointe {
  id: string;
  nom: string;
  /** Le base64 avec son en-tête `data:`, tel que le rend FileReader. */
  donnees: string;
  octets: number;
}

export type Refus = { fichier: string; raison: string };

export interface Tri {
  acceptees: File[];
  refus: Refus[];
}

/** Sépare ce qui peut être joint de ce qui ne peut pas, et dit pourquoi. */
export function trier(fichiers: File[], dejaJointes: number): Tri {
  const acceptees: File[] = [];
  const refus: Refus[] = [];
  for (const f of fichiers) {
    if (!(FORMATS as readonly string[]).includes(f.type)) {
      refus.push({ fichier: f.name, raison: 'Format non pris en charge (PNG, JPEG, GIF, WebP).' });
      continue;
    }
    if (f.size > TAILLE_MAX) {
      const mo = Math.round((f.size / 1024 / 1024) * 10) / 10;
      refus.push({ fichier: f.name, raison: `Trop lourde : ${mo} Mo, maximum 4 Mo.` });
      continue;
    }
    if (dejaJointes + acceptees.length >= NOMBRE_MAX) {
      refus.push({ fichier: f.name, raison: `Maximum ${NOMBRE_MAX} images par message.` });
      continue;
    }
    acceptees.push(f);
  }
  return { acceptees, refus };
}

/** Lit un fichier en `data:…;base64,…` — la forme que le serveur accepte. */
export function lire(fichier: File): Promise<PieceJointe> {
  return new Promise((resoudre, rejeter) => {
    const lecteur = new FileReader();
    lecteur.onerror = () => rejeter(new Error(`Lecture impossible : ${fichier.name}`));
    lecteur.onload = () =>
      resoudre({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
        nom: fichier.name,
        donnees: String(lecteur.result),
        octets: fichier.size,
      });
    lecteur.readAsDataURL(fichier);
  });
}

/**
 * Les images d'un événement de collage ou de glisser-déposer.
 *
 * Un collage de capture d'écran arrive dans `items` sans nom de fichier —
 * `getAsFile()` rend alors un File nommé « image.png ». Un glisser-déposer
 * arrive dans `files`. Les deux chemins mènent ici.
 */
export function imagesDeLEvenement(donnees: DataTransfer | null): File[] {
  if (!donnees) return [];
  const sortie: File[] = [];
  if (donnees.items && donnees.items.length > 0) {
    for (const item of Array.from(donnees.items)) {
      if (item.kind !== 'file') continue;
      const f = item.getAsFile();
      if (f && f.type.startsWith('image/')) sortie.push(f);
    }
  }
  if (sortie.length === 0 && donnees.files) {
    for (const f of Array.from(donnees.files)) {
      if (f.type.startsWith('image/')) sortie.push(f);
    }
  }
  return sortie;
}

/** Ce qui part sur le fil : le base64, en-tête comprise. */
export function pourLeFil(pieces: PieceJointe[]): string[] | undefined {
  return pieces.length > 0 ? pieces.map((p) => p.donnees) : undefined;
}

/** « 3 images · 1,2 Mo » — ce que l'usager lit sous le champ de saisie. */
export function resume(pieces: PieceJointe[]): string {
  if (pieces.length === 0) return '';
  const octets = pieces.reduce((s, p) => s + p.octets, 0);
  const poids =
    octets >= 1024 * 1024
      ? `${(Math.round((octets / 1024 / 1024) * 10) / 10).toString().replace('.', ',')} Mo`
      : `${Math.round(octets / 1024)} Ko`;
  return `${pieces.length} image${pieces.length > 1 ? 's' : ''} · ${poids}`;
}

/**
 * Les messages tels qu'ils partent sur le fil.
 *
 * Extrait du composant pour être vérifiable : ce dépôt n'a aucun test de
 * composant React (CLAUDE.md), et c'est précisément ici que se joue la
 * jointure entre l'interface et le serveur — le champ `images` doit voyager
 * avec SON message, et n'apparaître que là où il y en a.
 */
export function messagesPourLApi<
  T extends { role: string; content: string; images?: string[] },
>(messages: T[], texteDe: (m: T) => string): Array<{ role: string; content: string; images?: string[] }> {
  return messages.map((m) => ({
    role: m.role,
    content: texteDe(m),
    // Un champ vide sur chaque message de texte gonflerait la requête pour
    // rien, et Ollama n'en veut pas.
    ...(m.images && m.images.length > 0 ? { images: m.images } : {}),
  }));
}
