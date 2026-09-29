import type { ChatMessage } from '../../types';
import type { EmplacementEtude, Etude } from './etudes';

export type ElementEtudes =
  | { type: 'message'; message: ChatMessage }
  | { type: 'etude'; etude: Etude }
  | { type: 'preparation'; emplacement: EmplacementEtude };

/** Une modification du corrigé ne change jamais la place du cours dans le fil. */
export function intercalerEtudes(messages: ChatMessage[], etudes: Etude[], preparation?: EmplacementEtude | null): ElementEtudes[] {
  const groupes = new Map<number, Array<{ date: number; cle: string; element: ElementEtudes }>>();
  const ajouter = (element: ElementEtudes, cle: string, date: number, emplacement?: EmplacementEtude | null) => {
    let position: number;
    const ancre = emplacement?.afterMessageId;
    if (emplacement && ancre === null) position = 0;
    else {
      const index = ancre ? messages.findIndex(m => m.id === ancre) : -1;
      const apres = messages.findIndex(m => m.timestamp > date);
      position = index >= 0 ? index + 1 : apres >= 0 ? apres : messages.length;
    }
    const groupe = groupes.get(position) ?? [];
    groupe.push({ date, cle, element }); groupes.set(position, groupe);
  };
  for (const etude of etudes) ajouter({ type: 'etude', etude }, etude.id, etude.placement?.openedAt ?? etude.createdAt ?? etude.updatedAt, etude.placement);
  if (preparation) ajouter({ type: 'preparation', emplacement: preparation }, '~preparation', preparation.openedAt, preparation);
  const resultat: ElementEtudes[] = [];
  for (let i = 0; i <= messages.length; i++) {
    const groupe = groupes.get(i) ?? [];
    groupe.sort((a, b) => a.date - b.date || a.cle.localeCompare(b.cle));
    resultat.push(...groupe.map(g => g.element));
    if (i < messages.length) resultat.push({ type: 'message', message: messages[i] });
  }
  return resultat;
}

export function apercuEtude(etude: Pick<Etude, 'title' | 'objectives'>): string {
  // L'aperçu ne prend ni le cours ni une réponse : il reste utilisable en examen.
  const contexte = [etude.title, etude.objectives[0]].filter(Boolean).join(' — ').replace(/\s+/g, ' ').trim();
  return contexte.length > 220 ? `${contexte.slice(0, 219).trimEnd()}…` : contexte;
}

export function actualiserEtudes(avant: Etude[], reçues: Etude[]): Etude[] {
  const existantes = new Map(avant.map(e => [e.id, e]));
  return reçues.map(e => {
    const connue = existantes.get(e.id);
    return connue && connue.version >= e.version ? connue : e;
  });
}
