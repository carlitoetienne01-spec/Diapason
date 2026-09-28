// La page Appareils dit les sessions d'un appareil (plan mobile, phase 2,
// étape 9 — 26/09/2026). Chaque cas nomme ce que la page aurait dit de faux.

import { describe, expect, it } from 'vitest';

import { translate } from '../../i18n/translate';
import type { MeshDeviceSessions, MeshPairingInvitation } from './types';
import {
  adresseDInvitation,
  depuis,
  phraseDeFermeture,
  resumeDesSessions,
  type Traduire,
} from './sessions';

const fr: Traduire = (cle, vars) => translate('fr', cle, vars);
const en: Traduire = (cle, vars) => translate('en', cle, vars);

const MAINTENANT = Date.UTC(2026, 8, 26, 18, 0, 0);

function lecture(partiel: Partial<MeshDeviceSessions>): MeshDeviceSessions {
  return { deviceId: 'dev_tel', sessions: [], count: 0, lastUsedAtMs: null, ...partiel };
}

function invitation(extra: Record<string, unknown> = {}): MeshPairingInvitation {
  return {
    pairingToken: 'jeton-de-test',
    deviceName: 'Téléphone',
    expiresAtMs: MAINTENANT + 600_000,
    expiresInSeconds: 600,
    ...extra,
  } as MeshPairingInvitation;
}

describe('depuis — la dernière activité, à la minute près', () => {
  it('ne prétend pas une précision à la seconde que le serveur n’a pas', () => {
    expect(depuis(MAINTENANT - 12_000, MAINTENANT, fr, 'fr'), 'le serveur ne touche la session qu’une fois par minute').toBe(
      'à l’instant',
    );
  });

  it('compte les minutes, puis les heures', () => {
    expect(depuis(MAINTENANT - 3 * 60_000 - 5_000, MAINTENANT, fr, 'fr')).toBe('il y a 3 min');
    expect(depuis(MAINTENANT - 2 * 3_600_000, MAINTENANT, fr, 'fr')).toBe('il y a 2 h');
    expect(depuis(MAINTENANT - 3 * 60_000, MAINTENANT, en, 'en')).toBe('3 min ago');
  });

  it('lit une date du futur (horloges décalées) comme « à l’instant », jamais « il y a -1 min »', () => {
    expect(depuis(MAINTENANT + 90_000, MAINTENANT, fr, 'fr')).toBe('à l’instant');
  });

  it('passe à une date au-delà d’un jour', () => {
    const texte = depuis(MAINTENANT - 3 * 86_400_000, MAINTENANT, fr, 'fr');
    expect(texte.startsWith('le '), `une vieille session se date, elle ne se compte pas en heures : ${texte}`).toBe(true);
  });
});

describe('resumeDesSessions — la ligne de chaque appareil', () => {
  it('dit le nombre et la dernière activité rendus par le serveur', () => {
    const r = resumeDesSessions(
      { etat: 'lu', lecture: lecture({ count: 2, lastUsedAtMs: MAINTENANT - 5 * 60_000 }) },
      MAINTENANT,
      fr,
      'fr',
    );
    expect(r.texte).toBe('2 sessions ouvertes · dernière activité il y a 5 min');
    expect(r.fermable, 'deux sessions ouvertes : le bouton doit être offert').toBe(true);
  });

  it('accorde le singulier', () => {
    const r = resumeDesSessions(
      { etat: 'lu', lecture: lecture({ count: 1, lastUsedAtMs: MAINTENANT }) },
      MAINTENANT,
      en,
      'en',
    );
    expect(r.texte).toBe('1 open session · last activity just now');
  });

  it('suit le compte du SERVEUR, pas la longueur de la liste', () => {
    // Une liste vide avec count 1 : la page ne recompte pas. C'est le serveur
    // qui sait ce que la passerelle acceptera.
    const r = resumeDesSessions(
      { etat: 'lu', lecture: lecture({ count: 1, sessions: [], lastUsedAtMs: null }) },
      MAINTENANT,
      fr,
      'fr',
    );
    expect(r.texte).toBe('1 session ouverte');
    expect(r.fermable).toBe(true);
  });

  it('n’offre pas « Fermer ses sessions » quand il n’y en a aucune (§5)', () => {
    const r = resumeDesSessions({ etat: 'lu', lecture: lecture({ count: 0 }) }, MAINTENANT, fr, 'fr');
    expect(r).toEqual({ texte: 'Aucune session ouverte.', fermable: false, ton: 'neutre' });
  });

  it('dit un échec de lecture comme un échec, jamais comme « aucune session »', () => {
    const r = resumeDesSessions({ etat: 'erreur', message: 'Erreur appareils (500)' }, MAINTENANT, fr, 'fr');
    expect(r.ton).toBe('erreur');
    expect(r.fermable, 'un bouton sur un état inconnu fermerait à l’aveugle').toBe(false);
    expect(r.texte).toContain('Erreur appareils (500)');
    expect(r.texte).not.toContain('Aucune session');
  });

  it('ne promet rien pendant la lecture', () => {
    const r = resumeDesSessions({ etat: 'chargement' }, MAINTENANT, fr, 'fr');
    expect(r.fermable).toBe(false);
  });
});

describe('phraseDeFermeture — le résultat rendu par le serveur (§100)', () => {
  it('dit le nombre que le serveur a fermé', () => {
    expect(phraseDeFermeture(2, 'Téléphone', fr)).toBe('2 sessions fermées : Téléphone devra se reconnecter.');
    expect(phraseDeFermeture(1, 'Phone', en)).toBe('1 session closed: Phone will have to reconnect.');
  });

  it('dit « aucune » quand le serveur n’en a fermé aucune, même si la page en affichait', () => {
    expect(phraseDeFermeture(0, 'Téléphone', fr)).toBe('Aucune session n’était ouverte pour Téléphone.');
  });

  it('ne fabrique pas de nombre à partir d’une réponse illisible', () => {
    expect(phraseDeFermeture(undefined, 'Téléphone', fr)).toBe('Aucune session n’était ouverte pour Téléphone.');
    expect(phraseDeFermeture('3', 'Téléphone', fr), 'une chaîne n’est pas un compte').toBe(
      'Aucune session n’était ouverte pour Téléphone.',
    );
  });
});

describe('adresseDInvitation — l’adresse à saisir, jamais devinée', () => {
  it('rend l’adresse https lue dans [tailnet] adresse', () => {
    expect(adresseDInvitation(invitation({ tailnetAddress: 'https://mac.tail0000.ts.net' }))).toEqual({
      type: 'adresse',
      adresse: 'https://mac.tail0000.ts.net',
    });
  });

  it('distingue la clé non posée (null) du serveur qui ne connaît pas le champ', () => {
    expect(adresseDInvitation(invitation({ tailnetAddress: null }))).toEqual({ type: 'nonPosee' });
    expect(
      adresseDInvitation(invitation()),
      'un serveur d’avant l’étape 9 : dire « posez la clé » serait faux si elle l’est déjà',
    ).toEqual({ type: 'serveurAncien' });
  });

  it('n’affiche pas une adresse en clair ou mal formée', () => {
    expect(adresseDInvitation(invitation({ tailnetAddress: 'http://mac.ts.net' }))).toEqual({ type: 'nonPosee' });
    expect(adresseDInvitation(invitation({ tailnetAddress: 'https://a b' }))).toEqual({ type: 'nonPosee' });
  });
});
