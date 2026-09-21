// 20/09/2026 : une recherche rend des sources numérotées [N]. Les pastilles
// dans le texte n'apparaissent que si le modèle cite ; la ligne sous la bulle
// les montre toutes, pour que Carlito vérifie d'un clic ce qu'on lui affirme.
import type { ResearchSource } from '../../types';

export interface LigneDeSource {
  ref: number;
  url: string;
  domaine: string;
  titre: string;
  date: string;
  /** Page officielle lue par le code : dite telle quelle sous la bulle. */
  officielle: boolean;
}

const MOIS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];

export function dateCourte(iso: string | undefined): string {
  if (!iso) return '';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso.trim());
  if (!m) return iso.trim().slice(0, 16);
  const mois = MOIS[Number(m[2]) - 1];
  return mois ? `${Number(m[3])} ${mois} ${m[1]}` : m[0];
}

export function domaineDe(url: string | undefined): string {
  if (!url) return '';
  try {
    const hote = new URL(url).hostname.toLowerCase();
    return hote.startsWith('www.') ? hote.slice(4) : hote;
  } catch {
    return '';
  }
}

/** Les sources d'une réponse, une fois chacune, dans l'ordre de leurs numéros. */
export function lignesDeSources(sources: ResearchSource[] | undefined): LigneDeSource[] {
  const vues = new Set<number>();
  const lignes: LigneDeSource[] = [];
  for (const s of sources ?? []) {
    if (!s || typeof s.ref !== 'number' || !s.url || vues.has(s.ref)) continue;
    vues.add(s.ref);
    lignes.push({
      ref: s.ref,
      url: s.url,
      domaine: s.sender && !s.sender.includes('/') ? s.sender : domaineDe(s.url),
      titre: (s.title || '').trim(),
      date: dateCourte(s.date),
      officielle: s.official === true,
    });
  }
  return lignes.sort((a, b) => a.ref - b.ref);
}
