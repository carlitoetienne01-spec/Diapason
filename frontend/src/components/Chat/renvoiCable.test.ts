import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';


/**
 * Le câblage de « Renvoyer » (28/09/2026), lu comme du texte — à la manière
 * de telephoneSeulement.test.ts, faute de tests de composants dans ce dépôt.
 *
 * Contre-épreuve de la revue du même jour : huit mutations d'InputArea.tsx et
 * de MessageBubble.tsx laissaient les 1 803 tests verts — la question
 * réécrite dans le fil à chaque renvoi (et propagée au Mac), le fil complet
 * relu, le brouillon vidé, la recherche perdue, `connectionLost` jamais
 * transmis au store, l'avis jamais monté, le bouton à 32 px au doigt ou
 * caché jusqu'au survol. Les décisions vivent dans `planifierLeTour`
 * (lib/coupureDuFlux.ts, testé) ; ce fichier tient les fils qui les relient.
 */
const lire = (chemin: string) => readFileSync(join(__dirname, chemin), 'utf8');
const sansCommentaires = (code: string) =>
  code.replace(/\{\/\*[\s\S]*?\*\/\}/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');

/** Ce qui suit `tete` jusqu'à son délimiteur fermant (accolade ou parenthèse). */
function bloc(code: string, tete: string): string {
  const debut = code.indexOf(tete);
  if (debut < 0) return '';
  const ouvrant = tete[tete.length - 1];
  const fermant = ouvrant === '{' ? '}' : ')';
  let profondeur = 0;
  for (let i = debut + tete.length - 1; i < code.length; i += 1) {
    if (code[i] === ouvrant) profondeur += 1;
    else if (code[i] === fermant && (profondeur -= 1) === 0) return code.slice(debut, i + 1);
  }
  return '';
}

/** Tous les appels `nom(…)` du code, parenthèses équilibrées. */
function appels(code: string, nom: string): string[] {
  const sortie: string[] = [];
  for (let i = code.indexOf(nom); i >= 0; i = code.indexOf(nom, i + 1)) {
    sortie.push(bloc(code.slice(i), nom));
  }
  return sortie;
}

const saisie = sansCommentaires(lire('InputArea.tsx'));
const bulle = sansCommentaires(lire('MessageBubble.tsx'));

describe('InputArea : un renvoi ne recopie rien', () => {
  it('la question n’est écrite dans le fil que si le plan le demande', () => {
    expect(saisie.split('addMessage(convId, userMsg)').length - 1, 'un seul endroit écrit la question').toBe(1);
    const ecrire = bloc(saisie, 'if (plan.ecrireLaQuestion) {');
    expect(ecrire, 'sinon chaque « Renvoyer » double la question, et la synchro la propage au Mac')
      .toContain('addMessage(convId, userMsg)');
    expect(ecrire, 'les images en attente ne partent pas avec un renvoi').toContain('setPieces([])');
    expect(ecrire).toContain('setDocuments([])');
  });

  it('le brouillon ne s’efface que si le plan le demande', () => {
    expect(saisie.split("setInput('')").length - 1).toBe(1);
    expect(bloc(saisie, '} else if (plan.viderLeBrouillon) {'), 'un renvoi garde le brouillon en cours')
      .toContain("setInput('')");
  });

  it('le texte, le mode et le fil relu viennent du plan', () => {
    expect(bloc(saisie, 'planifierLeTour({'), 'le plan doit connaître le renvoi préparé').toMatch(/\brenvoi,/);
    expect(saisie).toMatch(/const \{ contenu: content, recherche \} = plan;/);
    expect(saisie, 'un renvoi relit le fil jusqu’à sa question, sans la réponse coupée')
      .toContain('const currentMessages = plan.historique ?? useAppStore.getState().messages;');
    expect(saisie).toContain('interactiveQuestions: plan.questionsInteractives,');
  });

  it('la fin du flux écrit la coupure dans la bulle', () => {
    const finale = appels(saisie, 'updateLastAssistant(').filter((a) => a.includes('telemetry,'));
    expect(finale.length, 'un seul appel final, celui qui porte la télémétrie du tour').toBe(1);
    expect(finale[0], 'sans elle, ni phrase ni bouton ne s’affichent').toMatch(/coupure \?\? undefined,?\s*\)$/);
    expect(saisie).toContain('issueDuFlux(err, accumulatedContent, serviParLeTailnet(), t)');
    expect(saisie).toContain('texteFinal(accumulatedContent, coupure, t)');
  });

  it('le bouton demande le renvoi de CE message, sans relance automatique', () => {
    const ecoute = bloc(saisie, 'const renvoyer = (event: Event) => {');
    expect(ecoute).toContain('actuel.streamState.isStreaming');
    expect(ecoute).toContain('sendMessage(undefined, undefined, { renvoi: demande.messageId, garderBrouillon: true })');
    expect(saisie.split('renvoi: ').length - 1, 'seul le bouton déclenche un renvoi').toBe(1);
  });
});

describe('MessageBubble : l’avis de coupure', () => {
  const avis = bloc(bulle, 'function AvisDeCoupure({ message }: { message: ChatMessage }) {');
  const bouton = avis.slice(avis.indexOf('<button'), avis.indexOf('</button>'));

  it('est monté sous toute réponse coupée terminée', () => {
    expect(bulle).toContain('{!isLive && message.connectionLost && <AvisDeCoupure message={message} />}');
    expect(avis, 'la phrase vient de la coupure, choisie par cleDeCoupure').toContain('t(cleDeCoupure(coupure))');
    expect(avis, 'le nom brut, en petit').toContain('{coupure.detail}');
  });

  it('le bouton fait 40 px au doigt et ne se cache jamais derrière le survol', () => {
    expect(bouton, 'renvoyer est la seule issue proposée').toContain('onClick={renvoyer}');
    expect(bouton, 'cible de 40 px au téléphone (règles du téléphone)').toMatch(/\bmobile:min-h-10\b/);
    expect(bouton, 'rien qui n’existe qu’au survol').not.toMatch(/opacity-0|\binvisible\b|\bhidden\b|hover:/);
    expect(avis, 'il n’existe que si le renvoi a un sens').toMatch(/\{renvoyable && \(\s*<button/);
  });
});
