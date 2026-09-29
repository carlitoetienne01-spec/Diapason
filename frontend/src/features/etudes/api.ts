import { apiFetch } from '../../lib/api';
import type { DemandeEtude, Etude, SourceEtude } from './etudes';

async function requete<T>(chemin: string, methode = 'GET', donnees?: unknown): Promise<T> {
  const reponse = await apiFetch(`/v1/study${chemin}`, {
    method: methode,
    ...(donnees === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(donnees) }),
  });
  const contenu = await reponse.json().catch(() => null);
  if (!reponse.ok) {
    const detail = contenu?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map((d: { msg?: string }) => d.msg ?? 'Paramètre invalide').join(' · ')
      : 'Impossible de joindre le mode Étudier. Tes réponses enregistrées sont conservées.');
  }
  return contenu as T;
}
export const listerEtudes = (conversationId: string) => requete<{ sessions: Etude[] }>(`/sessions?conversationId=${encodeURIComponent(conversationId)}`);
export const lireMateriel = (conversationId: string) => requete<{ sources: SourceEtude[] }>(`/materials?conversationId=${encodeURIComponent(conversationId)}`);
export const garderMateriel = (conversationId: string, sources: SourceEtude[]) => requete('/materials', 'PUT', { conversationId, sources });
export const creerEtude = (demande: DemandeEtude) => requete<Etude>('/sessions', 'POST', demande);
export const lireEtude = (id: string) => requete<Etude>(`/sessions/${encodeURIComponent(id)}`);
export const supprimerEtude = (id: string) => requete(`/sessions/${encodeURIComponent(id)}`, 'DELETE');
export const agirEtude = (etude: Etude, action: string, donnees: { questionId?: string; text?: string } = {}) =>
  requete<Etude>(`/sessions/${encodeURIComponent(etude.id)}/actions`, 'POST', { version: etude.version, action, ...donnees });
