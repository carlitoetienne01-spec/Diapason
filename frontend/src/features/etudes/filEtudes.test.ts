import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '../../types';
import type { Etude } from './etudes';
import { actualiserEtudes, apercuEtude, intercalerEtudes } from './filEtudes';

const message = (id: string, timestamp: number): ChatMessage => ({ id, timestamp, role: 'user', content: id });
const etude = (id: string, createdAt: number, apres?: string | null): Etude => ({
  id, createdAt, updatedAt: createdAt, version: 1, title: id, objectives: ['Comprendre le sujet'],
  ...(apres === undefined ? {} : { placement: { afterMessageId: apres, openedAt: createdAt } }),
} as Etude);
const cles = (elements: ReturnType<typeof intercalerEtudes>) => elements.map(e => e.type === 'message' ? e.message.id : e.type === 'etude' ? e.etude.id : 'preparation');

describe('Les études restent à leur place dans la discussion', () => {
  it('entrelace les messages, deux études et la suite du dialogue', () => {
    const messages = [message('avant', 10), message('entre', 30), message('apres', 50)];
    const premiere = etude('cours-1', 20, 'avant');
    const seconde = etude('cours-2', 40, 'entre');
    expect(cles(intercalerEtudes(messages, [seconde, premiere]))).toEqual(['avant', 'cours-1', 'entre', 'cours-2', 'apres']);
    expect(cles(intercalerEtudes(messages, [{ ...premiere, updatedAt: 1000, version: 8 }, seconde]))).toEqual(['avant', 'cours-1', 'entre', 'cours-2', 'apres']);
  });
  it('garde le formulaire puis son cours au même endroit pendant la préparation', () => {
    const emplacement = { afterMessageId: 'avant', openedAt: 20 };
    const messages = [message('avant', 10), message('pendant', 30)];
    expect(cles(intercalerEtudes(messages, [], emplacement))).toEqual(['avant', 'preparation', 'pendant']);
    expect(cles(intercalerEtudes(messages, [{ ...etude('cours', 90), placement: emplacement }]))).toEqual(['avant', 'cours', 'pendant']);
  });
  it('une étude ouverte dans un fil vide précède les premiers messages', () => {
    expect(cles(intercalerEtudes([message('apres', 1)], [etude('cours', 20, null)]))).toEqual(['cours', 'apres']);
  });
  it('replie plusieurs études au même endroit sans dépendre de leur ordre de mise à jour', () => {
    expect(cles(intercalerEtudes([message('avant', 1)], [etude('deux', 30, 'avant'), etude('un', 20, 'avant')]))).toEqual(['avant', 'un', 'deux']);
  });
  it('retrouve une place par la date si le message ancre a été supprimé', () => {
    expect(cles(intercalerEtudes([message('avant', 10), message('apres', 40)], [etude('cours', 30, 'supprime')]))).toEqual(['avant', 'cours', 'apres']);
  });
  it('place une préparation orale selon son début et non sa dernière correction', () => {
    expect(cles(intercalerEtudes([message('demande', 10), message('suite', 40)], [{ ...etude('oral', 20), updatedAt: 900 }]))).toEqual(['demande', 'oral', 'suite']);
  });
  it('relit encore les anciennes études sans métadonnées nouvelles', () => {
    const ancienne = etude('ancien', 20); delete ancienne.createdAt;
    expect(cles(intercalerEtudes([message('avant', 10), message('apres', 40)], [ancienne]))).toEqual(['avant', 'ancien', 'apres']);
  });
});

describe('La relève et l’aperçu ne remplacent pas le travail de l’étudiant', () => {
  it('une relève ancienne ne remplace pas une réponse qui vient d’être enregistrée', () => {
    const recente = { ...etude('cours', 20), version: 3 };
    expect(actualiserEtudes([recente], [etude('cours', 20)])[0]).toBe(recente);
    expect(actualiserEtudes([recente], [])).toEqual([]);
  });
  it('conserve simultanément les études avec leurs propres révisions', () => {
    const un = etude('un', 20); const deux = etude('deux', 40);
    const retour = actualiserEtudes([un, deux], [{ ...deux, version: 2 }, un]);
    expect(retour.map(e => [e.id, e.version])).toEqual([['deux', 2], ['un', 1]]);
    expect(retour[1]).toBe(un);
  });
  it('l’aperçu reste court et ne révèle ni corrigé ni réponse', () => {
    const e = { ...etude('Fractions', 20), lesson: 'CORRIGE SECRET', responses: { q1: { text: 'REPONSE' } } };
    expect(apercuEtude(e)).toBe('Fractions — Comprendre le sujet');
    expect(apercuEtude({ title: 'A'.repeat(200), objectives: ['B'.repeat(300)] }).length).toBeLessThanOrEqual(220);
  });
});
