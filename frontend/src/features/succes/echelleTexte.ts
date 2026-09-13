// L'échelle du texte de la Ligne — pur, donc vérifiable sous node.
//
// Demandé le 6 septembre 2026 : « agrandis les caractères pour que je voie
// mieux les lettres ». Les tailles étaient figées dans les classes Tailwind
// (`text-sm` pour un titre de station, `text-[13px]` pour ses notes) : lire
// une station demandait de se pencher sur l'écran, et rien ne permettait d'y
// remédier. Elles deviennent le produit d'une taille de base par une échelle
// que l'on règle et qui se souvient.
//
// L'échelle par défaut est 1,15 et non 1 : la demande était d'agrandir, pas
// d'offrir un réglage qui laisse tout comme avant tant qu'on ne l'a pas
// trouvé.

/** Ce que valent les tailles à l'échelle 1 — les valeurs d'avant le réglage. */
export const TAILLES_BASE = {
  titre: 14,
  note: 13,
  mention: 12,
  badge: 11,
} as const;

export type Tailles = Record<keyof typeof TAILLES_BASE, number>;

export const ECHELLE_MIN = 0.9;
export const ECHELLE_MAX = 2;
export const ECHELLE_DEFAUT = 1.15;
const PAS = 0.15;

/** Arrondi au centième : sinon 1,15 + 0,15 s'écrit 1,2999999999999998. */
const centieme = (valeur: number) => Math.round(valeur * 100) / 100;

/**
 * Une échelle utilisable, quoi qu'on ait lu.
 *
 * La valeur vient de `localStorage`, donc de l'extérieur : une chaîne, un
 * `null`, un `NaN` ou un 40 posé à la main y sont tous possibles, et un
 * `fontSize: NaN` fait disparaître le texte au lieu de l'agrandir.
 */
export function normaliserEchelle(valeur: unknown): number {
  const nombre = typeof valeur === 'string' ? Number(valeur) : valeur;
  if (typeof nombre !== 'number' || !Number.isFinite(nombre)) {
    return ECHELLE_DEFAUT;
  }
  return centieme(Math.min(ECHELLE_MAX, Math.max(ECHELLE_MIN, nombre)));
}

/** L'échelle d'un cran plus grande (`+1`) ou plus petite (`-1`), bornée. */
export function echelleSuivante(valeur: number, sens: 1 | -1): number {
  return normaliserEchelle(centieme(normaliserEchelle(valeur) + sens * PAS));
}

/** Les quatre tailles en pixels, à cette échelle. */
export function taillesDe(echelle: number): Tailles {
  const facteur = normaliserEchelle(echelle);
  return {
    titre: centieme(TAILLES_BASE.titre * facteur),
    note: centieme(TAILLES_BASE.note * facteur),
    mention: centieme(TAILLES_BASE.mention * facteur),
    badge: centieme(TAILLES_BASE.badge * facteur),
  };
}

/** « 115 % » — ce qu'on affiche entre les deux boutons. */
export function libelleEchelle(echelle: number): string {
  return `${Math.round(normaliserEchelle(echelle) * 100)} %`;
}
