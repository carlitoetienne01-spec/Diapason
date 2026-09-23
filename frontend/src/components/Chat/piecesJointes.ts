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

// Les documents (22/09/2026) suivent le même chemin que les images, mais
// sont lus par le SERVEUR — pdfplumber et python-docx n'ont pas d'équivalent
// dans un navigateur. Deux suffisent pour comparer ; trois remplissent la
// fenêtre du modèle.
export const DOCUMENT_TAILLE_MAX = 10 * 1024 * 1024;
export const DOCUMENTS_MAX = 2;
export const EXTENSIONS_DOCUMENT = ['.txt', '.md', '.csv', '.pdf', '.docx'] as const;

export interface DocumentJoint {
  id: string;
  nom: string;
  /** Le texte extrait par le serveur — c'est lui qui part au modèle. */
  texte: string;
  pages?: number;
  caracteres: number;
  tronque: boolean;
}

/** Un fichier est-il un document plutôt qu'une image ? */
export function estUnDocument(fichier: File): boolean {
  const nom = fichier.name.toLowerCase();
  return (EXTENSIONS_DOCUMENT as readonly string[]).some((e) => nom.endsWith(e));
}

/** Sépare un lot mêlé : les images d'un côté, les documents de l'autre. */
export function separer(fichiers: File[]): { images: File[]; documents: File[] } {
  const images: File[] = [];
  const documents: File[] = [];
  for (const f of fichiers) {
    if (f.type.startsWith('image/')) images.push(f);
    else if (estUnDocument(f)) documents.push(f);
    else images.push(f); // refusé plus loin, avec sa raison
  }
  return { images, documents };
}

/** Ce qu'on peut joindre comme document, et pourquoi pas le reste. */
export function trierDocuments(fichiers: File[], dejaJoints: number): Tri {
  const acceptees: File[] = [];
  const refus: Refus[] = [];
  for (const f of fichiers) {
    if (!estUnDocument(f)) {
      refus.push({
        fichier: f.name,
        raison: 'Format non pris en charge (.txt, .md, .csv, .pdf, .docx).',
      });
      continue;
    }
    if (f.size > DOCUMENT_TAILLE_MAX) {
      const mo = Math.round((f.size / 1024 / 1024) * 10) / 10;
      refus.push({ fichier: f.name, raison: `Trop lourd : ${mo} Mo, maximum 10 Mo.` });
      continue;
    }
    if (dejaJoints + acceptees.length >= DOCUMENTS_MAX) {
      refus.push({ fichier: f.name, raison: `Maximum ${DOCUMENTS_MAX} documents par message.` });
      continue;
    }
    acceptees.push(f);
  }
  return { acceptees, refus };
}

/** Ce qui part sur le fil : le texte extrait, pas le fichier. */
export function documentsPourLeFil(
  documents: DocumentJoint[],
): Array<{ nom: string; texte: string; pages?: number; tronque?: boolean }> | undefined {
  if (documents.length === 0) return undefined;
  return documents.map((d) => ({
    nom: d.nom,
    texte: d.texte,
    ...(d.pages ? { pages: d.pages } : {}),
    ...(d.tronque ? { tronque: true } : {}),
  }));
}

/** « bail.pdf · 12 pages » ou « note.docx · 3 200 caractères ». */
export function resumeDocument(d: DocumentJoint): string {
  const detail = d.pages
    ? `${d.pages} page${d.pages > 1 ? 's' : ''}`
    : `${d.caracteres.toLocaleString('fr-CA')} caractères`;
  // La coupure se dit ici aussi : l'usager doit savoir que sa question porte
  // sur un extrait avant de la poser, pas après avoir lu la réponse.
  return d.tronque ? `${d.nom} · ${detail} · extrait seulement` : `${d.nom} · ${detail}`;
}

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
      // Le composeur accepte DEUX familles. Ne nommer que les images faisait
      // répondre à un .zip — et à un .pptx — que seuls PNG, JPEG, GIF et
      // WebP passent, ce qui est faux : constaté au navigateur le
      // 22/09/2026, un .zip déposé s'entendait refuser au nom d'une liste
      // qui omettait .pdf et .docx.
      refus.push({
        fichier: f.name,
        raison: 'Format non pris en charge. Images : PNG, JPEG, GIF, WebP. Documents : .txt, .md, .csv, .pdf, .docx.',
      });
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
  T extends {
    role: string;
    content: string;
    images?: string[];
    documents?: Array<{ nom: string; texte: string; pages?: number; tronque?: boolean }>;
  },
>(
  messages: T[],
  texteDe: (m: T) => string,
): Array<{
  role: string;
  content: string;
  images?: string[];
  documents?: Array<{ nom: string; texte: string; pages?: number; tronque?: boolean }>;
}> {
  return messages.map((m) => ({
    role: m.role,
    content: texteDe(m),
    // Un champ vide sur chaque message de texte gonflerait la requête pour
    // rien, et Ollama n'en veut pas.
    ...(m.images && m.images.length > 0 ? { images: m.images } : {}),
    ...(m.documents && m.documents.length > 0 ? { documents: m.documents } : {}),
  }));
}

/**
 * Fait lire un document par le serveur, et rend ce qu'il en a tiré.
 *
 * L'extraction est faite UNE fois, ici, quand l'usager joint le fichier :
 * le message ne porte ensuite que le texte. Relire un PDF de cent pages à
 * chaque tour de la conversation coûterait une seconde par tour pour un
 * résultat identique.
 *
 * pdfplumber et python-docx n'ont pas d'équivalent dans un navigateur — le
 * serveur est le seul à pouvoir lire ces formats.
 */
export async function lireDocument(
  fichier: File,
  poster: (chemin: string, init: RequestInit) => Promise<Response>,
): Promise<DocumentJoint> {
  const donnees = await lire(fichier); // le base64, avec son en-tête data:
  const reponse = await poster('/v1/chat/documents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nom: fichier.name, contenu: donnees.donnees }),
  });
  if (!reponse.ok) {
    // Le serveur dit CE QUI est refusé — « scan.pdf : aucun texte lisible ».
    // L'afficher tel quel vaut mieux qu'un « erreur 400 » qui n'apprend rien.
    const detail = await reponse
      .json()
      .then((d) => d?.detail)
      .catch(() => null);
    throw new Error(detail || `${fichier.name} : lecture impossible.`);
  }
  const lu = await reponse.json();
  return {
    id: donnees.id,
    nom: String(lu.nom ?? fichier.name),
    texte: String(lu.texte ?? ''),
    pages: typeof lu.pages === 'number' ? lu.pages : undefined,
    caracteres: Number(lu.characters ?? 0),
    tronque: Boolean(lu.truncated),
  };
}
