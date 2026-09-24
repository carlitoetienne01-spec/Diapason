// Le compte chiffré, vu de l'interface (compte-chiffre.md §2.7, §3.8,
// §3.11, §4.11). Aucun test de composant dans ce dépôt : toute décision de
// l'écran d'activation passe par une fonction pure de lib/compte.ts, et
// c'est elle qu'on vérifie ici.
//
// Plusieurs règles vivent deux fois — en Python dans le serveur local, en
// TypeScript ici. Les tests « partagés avec le serveur » lisent la source
// Python et les vecteurs de contrat : si l'un bouge sans l'autre, l'écran
// accepterait ce que le serveur refuse (ou l'inverse), en silence.

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { MESSAGES } from '../i18n/messages';
import {
  ALPHABET_CROCKFORD,
  ETATS_COMPTE,
  LISTE_MOTS_MIN,
  MOT_DE_PASSE_MAX,
  MOT_DE_PASSE_MIN,
  aUnCompte,
  actionEchap,
  actionSection,
  bandeauCompte,
  blocageAdresse,
  courrielValide,
  destinationBloquee,
  doitAfficherAccueil,
  etapeActivation,
  etapeReinitialisation,
  extraitAttendu,
  extraitConcorde,
  formaterHeure,
  formaterJour,
  formaterMoment,
  formeCle,
  genererPhrase,
  groupesDeLaCle,
  iconeEncadre,
  impressionDisponible,
  indiceFocusSuivant,
  indiceUniforme,
  inscriptionExpiree,
  lectureAffichee,
  libelleEtat,
  libelleSynchro,
  lireGroupesDemandes,
  lireListeMots,
  lireStatut,
  listeUtilisable,
  messageErreur,
  mettreEnGroupes,
  motifRefusMemorisation,
  motsNecessaires,
  moyensDeSecours,
  normaliserSaisieCle,
  reglesMotDePasse,
  sortieAccueil,
  texteAucunSecours,
  texteMemorisation,
  type EtapeActivation,
  type EtatVue,
  type StatutCompte,
  type StatutSynchro,
} from './compte';

const ici = dirname(fileURLToPath(import.meta.url));
const racine = resolve(ici, '../../..');
const lire = (chemin: string) => readFileSync(resolve(racine, chemin), 'utf-8');

/** Le statut tel que `ServiceCompte.statut()` le rend à l'étape 8. */
function statutBrut(surcharges: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    state: 'unlocked',
    unlocked: true,
    email: 'carlito@exemple.org',
    remembered: false,
    protector: 'keychain',
    rememberAllowed: true,
    rememberRefusal: null,
    recoveryConfigured: true,
    backupMeans: { recoveryKey: true, rememberedDevices: 0 },
    onboarding: 'done',
    localConversations: 3,
    sync: {
      state: 'disabled',
      serverSeq: null,
      lastConfirmedAt: null,
      pendingCount: null,
      quarantinedCount: null,
      repairedCount: null,
      errorCode: null,
    },
    clockSkewMs: null,
    pendingResetAt: null,
    serverOrigin: 'https://diapason.flashprime.online',
    serverOriginAllowed: true,
    lastKeyChangeAt: null,
    // Ouvert : ces tests exercent les parcours. L'état réel par défaut
    // (fermé) est éprouvé par « les comptes pas encore ouverts » plus bas.
    accountsOpen: true,
    ...surcharges,
  };
}

function statut(surcharges: Record<string, unknown> = {}): StatutCompte {
  const lu = lireStatut(statutBrut(surcharges));
  if (!lu) throw new Error('statut de test illisible');
  return lu;
}

function synchro(surcharges: Partial<StatutSynchro> = {}): StatutSynchro {
  return {
    state: 'disabled',
    serverSeq: null,
    lastConfirmedAt: null,
    pendingCount: null,
    quarantinedCount: null,
    repairedCount: null,
    errorCode: null,
    ...surcharges,
  };
}

// ---------------------------------------------------------------------------

describe('lireStatut — le contrat de GET /v1/account/status (§3.8)', () => {
  it('lit le statut que le serveur local rend à l’étape 8', () => {
    const s = lireStatut(statutBrut());
    expect(s, 'un statut conforme doit se lire').not.toBeNull();
    expect(s?.backupMeans.recoveryKey).toBe(true);
    expect(s?.sync.pendingCount, 'null reste null, jamais 0').toBeNull();
  });

  it('refuse un champ passé en snake_case plutôt que de le lire undefined', () => {
    // Échec évité : `backupMeans.recoveryKey` absent comptait 0 moyen de
    // secours chez quelqu'un qui a une clé (CLAUDE.md §3, champs camelCase).
    const brut = statutBrut();
    delete brut.backupMeans;
    (brut as Record<string, unknown>).backup_means = { recovery_key: true, remembered_devices: 0 };
    expect(lireStatut(brut), 'un champ renommé doit rendre le statut illisible').toBeNull();
  });

  it('refuse un état inconnu au lieu de l’afficher comme un autre', () => {
    expect(lireStatut(statutBrut({ state: 'toutVaBien' }))).toBeNull();
  });

  it('refuse un nombre de synchronisation remplacé par une chaîne', () => {
    const brut = statutBrut();
    (brut.sync as Record<string, unknown>).pendingCount = '0';
    expect(lireStatut(brut), '« 0 » en texte n’est pas une file vide').toBeNull();
  });

  it('refuse ce qui n’est pas un objet', () => {
    expect(lireStatut(null)).toBeNull();
    expect(lireStatut([])).toBeNull();
    expect(lireStatut('unlocked')).toBeNull();
  });

  // Échec évité (contre-épreuve du 24/09/2026) : 9 contrôles sur 11 de
  // lireStatut pouvaient sauter sans qu'un test rougisse. La docstring
  // promet « un champ absent ou mal typé rend null » : chaque champ le prouve.
  const chemins = (brut: Record<string, unknown>): string[][] =>
    Object.entries(brut).flatMap(([k, v]) =>
      v && typeof v === 'object' && !Array.isArray(v)
        ? [[k], ...Object.keys(v).map((n) => [k, n])]
        : [[k]],
    );
  const modifier = (chemin: string[], faire: (parent: Record<string, unknown>, cle: string) => void) => {
    const brut = JSON.parse(JSON.stringify(statutBrut())) as Record<string, unknown>;
    const parent = chemin.length === 1 ? brut : (brut[chemin[0]] as Record<string, unknown>);
    faire(parent, chemin[chemin.length - 1]);
    return brut;
  };

  it('refuse le statut dès qu’UN champ manque, à tous les niveaux', () => {
    for (const chemin of chemins(statutBrut())) {
      const brut = modifier(chemin, (parent, cle) => delete parent[cle]);
      expect(lireStatut(brut), `${chemin.join('.')} absent`).toBeNull();
    }
  });

  it('refuse le statut dès qu’UN champ est mal typé, à tous les niveaux', () => {
    for (const chemin of chemins(statutBrut())) {
      const brut = modifier(chemin, (parent, cle) => {
        parent[cle] = { inattendu: true };
      });
      expect(lireStatut(brut), `${chemin.join('.')} mal typé`).toBeNull();
    }
  });

  it('refuse un protecteur, un onboarding ou un état de synchronisation inconnus', () => {
    expect(lireStatut(statutBrut({ protector: 'coffreFort' }))).toBeNull();
    expect(lireStatut(statutBrut({ onboarding: 'peutEtre' }))).toBeNull();
    const brut = statutBrut();
    (brut.sync as Record<string, unknown>).state = 'toutVaBien';
    expect(lireStatut(brut), 'un état de synchronisation inventé').toBeNull();
  });

  it('refuse un nombre infini ou NaN au lieu de l’afficher', () => {
    expect(lireStatut(statutBrut({ pendingResetAt: Number.NaN }))).toBeNull();
    expect(lireStatut(statutBrut({ lastKeyChangeAt: Number.POSITIVE_INFINITY }))).toBeNull();
  });

  it('rend chaque champ tel quel, sans le confondre avec un voisin', () => {
    const s = lireStatut(
      statutBrut({
        remembered: true,
        rememberAllowed: false,
        rememberRefusal: 'notOnThisPlatform',
        recoveryConfigured: false,
        serverOrigin: 'https://exemple.org',
        serverOriginAllowed: false,
        lastKeyChangeAt: 1234,
        pendingResetAt: 5678,
        clockSkewMs: 9,
        localConversations: 0,
        protector: 'memory',
      }),
    );
    expect(s).toMatchObject({
      remembered: true,
      rememberAllowed: false,
      rememberRefusal: 'notOnThisPlatform',
      recoveryConfigured: false,
      serverOrigin: 'https://exemple.org',
      serverOriginAllowed: false,
      lastKeyChangeAt: 1234,
      pendingResetAt: 5678,
      clockSkewMs: 9,
      localConversations: 0,
      protector: 'memory',
    });
  });
});

// ---------------------------------------------------------------------------

describe('les règles du mot de passe (D5, §2.4)', () => {
  it('refuse 11 caractères et accepte 12', () => {
    expect(reglesMotDePasse('a'.repeat(11), null).defauts).toContain('tropCourt');
    expect(reglesMotDePasse('a'.repeat(12), null).valide, '12 caractères suffisent (D5)').toBe(true);
  });

  it('compte les caractères comme Python, pas les unités UTF-16', () => {
    // Échec évité : 6 émojis font 12 unités UTF-16 ; les accepter ici
    // renvoyait un `passwordTooShort` du serveur après Argon2id.
    const six = '😀'.repeat(6);
    expect(six.length).toBe(12);
    expect(reglesMotDePasse(six, null).longueur).toBe(6);
    expect(reglesMotDePasse(six, null).defauts, '6 émojis sont 6 caractères').toContain('tropCourt');
  });

  it('normalise en NFKC avant de compter, comme cles.normaliser_mot_de_passe', () => {
    // « ﬁ » (une ligature) devient « fi » : deux caractères après NFKC.
    expect(reglesMotDePasse('ﬁ'.repeat(6), null).longueur).toBe(12);
  });

  it('refuse plus de 1 024 caractères', () => {
    expect(reglesMotDePasse('a'.repeat(1025), null).defauts).toContain('tropLong');
    expect(reglesMotDePasse('a'.repeat(1024), null).valide).toBe(true);
  });

  it('refuse la partie locale de l’adresse, sans égard à la casse', () => {
    const j = reglesMotDePasse('monCARLITOsecret!', 'Carlito@exemple.org');
    expect(j.defauts, 'le début de l’adresse ne doit pas y être').toContain('contientAdresse');
  });

  it('ne refuse pas tout quand la partie locale est vide', () => {
    // Même garde que cles.verifier_mot_de_passe : « @ab » passe le §2.4.
    expect(reglesMotDePasse('un mot de passe long', '@ab').valide).toBe(true);
  });

  it('signale une confirmation différente', () => {
    expect(reglesMotDePasse('cheval-batterie-agrafe', null, 'cheval-batterie-agrafE').defauts).toContain('differents');
    expect(reglesMotDePasse('cheval-batterie-agrafe', null, 'cheval-batterie-agrafe').valide).toBe(true);
  });

  it('valide l’adresse comme le §2.4 : un seul @, pas d’espace, 3 à 254 caractères', () => {
    expect(courrielValide('  Carlito@Exemple.org ')).toBe(true);
    expect(courrielValide('a@b')).toBe(true);
    expect(courrielValide('sans-arobase')).toBe(false);
    expect(courrielValide('a@b@c')).toBe(false);
    expect(courrielValide('car lito@exemple.org')).toBe(false);
    expect(courrielValide('@')).toBe(false);
    // 254 caractères passent, 255 non (§2.4).
    expect(courrielValide(`${'a'.repeat(250)}@b.c`)).toBe(true);
    expect(courrielValide(`${'a'.repeat(251)}@b.c`)).toBe(false);
  });

  it('dit pourquoi l’adresse ne part pas, au lieu d’un bouton grisé muet', () => {
    // Échec évité (24/09/2026) : bouton grisé tant que la case n'était pas
    // cochée — Entrée ne faisait rien, et rien ne disait pourquoi (§82).
    expect(blocageAdresse('pas-une-adresse', true)).toBe('adresse');
    expect(blocageAdresse('carlito@exemple.org', false)).toBe('conditions');
    expect(blocageAdresse('carlito@exemple.org', true)).toBeNull();
  });
});

// ---------------------------------------------------------------------------

describe('la clé de récupération (§2.7)', () => {
  const vecteurs = JSON.parse(lire('tests/contract/vecteurs_compte.json')) as { recovery: { text: string } };
  const cle = vecteurs.recovery.text;

  it('lit la clé des vecteurs de contrat : 8 groupes de 4', () => {
    expect(formeCle(cle)).toBe('complete');
    expect(groupesDeLaCle(cle)).toHaveLength(8);
    expect(groupesDeLaCle(cle).join('-')).toBe(cle);
  });

  it('pardonne ce que Crockford pardonne : O, I, L, casse, tirets, espaces', () => {
    const tapee = cle.toLowerCase().replace(/-/g, ' ').replace(/1/g, 'l').replace(/0/g, 'o');
    expect(normaliserSaisieCle(tapee)).toBe(cle.replace(/-/g, ''));
  });

  it('normalise en NFKC comme recuperation.py : les chiffres pleine chasse passent', () => {
    // « １ » (U+FF11) d'un clavier japonais devient « 1 ».
    expect(normaliserSaisieCle('１ＧＴＪ')).toBe('1GTJ');
  });

  it('ne découpe pas une clé de mauvaise longueur en groupes', () => {
    expect(groupesDeLaCle(cle.slice(0, 20)), 'une clé tronquée n’a pas huit groupes').toEqual([]);
    expect(groupesDeLaCle(`${cle}A`)).toEqual([]);
  });

  it('ne pardonne pas le U, absent de l’alphabet', () => {
    expect(formeCle(`U${cle.slice(1)}`)).toBe('caractereInconnu');
  });

  it('distingue une clé incomplète d’une clé trop longue', () => {
    expect(formeCle('')).toBe('vide');
    expect(formeCle(cle.slice(0, 20))).toBe('incomplete');
    expect(formeCle(`${cle}A`)).toBe('tropLongue');
  });

  it('remet la saisie en groupes pendant la frappe', () => {
    expect(mettreEnGroupes('1gtjk863h')).toBe('1GTJ-K863-H');
  });

  it('l’extrait attendu suit l’ordre de confirmGroups, pas l’ordre des groupes', () => {
    expect(extraitAttendu(cle, [5, 2])).toEqual(['14SJ', 'K863']);
  });

  it('la preuve de sauvegarde accepte une saisie tolérante et refuse un groupe faux', () => {
    expect(extraitConcorde(cle, [1, 7], ['lgtj', 'sj9o']), 'saisie tolérante').toBe(true);
    expect(extraitConcorde(cle, [1, 7], ['1GTJ', 'SJ91']), 'un caractère faux').toBe(false);
    expect(extraitConcorde(cle, [1, 7], ['SJ90', '1GTJ']), 'groupes inversés').toBe(false);
  });

  it('refuse des numéros de groupe hors de 1 à 8, ou deux fois le même', () => {
    // Le serveur les tire ; un « [1, 1] » ferait recopier un seul groupe.
    expect(lireGroupesDemandes([3, 6])).toEqual([3, 6]);
    expect(lireGroupesDemandes([1, 1])).toBeNull();
    expect(lireGroupesDemandes([0, 2])).toBeNull();
    expect(lireGroupesDemandes([2, 9])).toBeNull();
    expect(lireGroupesDemandes([2])).toBeNull();
    expect(lireGroupesDemandes(['1', '2'])).toBeNull();
  });
});

// ---------------------------------------------------------------------------

describe('moyensDeSecours (§3.11, D4)', () => {
  it('compte la clé confirmée et cet appareil mémorisé', () => {
    const m = moyensDeSecours(statut({ backupMeans: { recoveryKey: true, rememberedDevices: 1 } }));
    expect(m).toEqual({ cle: true, cetAppareil: true, total: 2, avertir: false });
  });

  it('avertit à zéro moyen, et l’avertissement reste (D4)', () => {
    const m = moyensDeSecours(statut({ recoveryConfigured: false, backupMeans: { recoveryKey: false, rememberedDevices: 0 } }));
    expect(m?.total).toBe(0);
    expect(m?.avertir, '« 0 moyen de secours » doit rester affiché').toBe(true);
  });

  it('ne compte pas les autres appareils, que celui-ci ne connaît pas', () => {
    // Un appareil « connecté » mais verrouillé ne sauve rien (encadré de
    // l'étape 3) : le compter aurait promis un secours peut-être absent.
    const m = moyensDeSecours(statut({ backupMeans: { recoveryKey: false, rememberedDevices: 0 } }));
    expect(m?.total).toBe(0);
  });

  it('avertit encore quand le nombre d’appareils mémorisés est inconnu (D4)', () => {
    // Échec évité (24/09/2026) : `rememberedDevices` à null chez un compte
    // rendait null — et l'avertissement « 0 moyen de secours » disparaissait.
    const m = moyensDeSecours(statut({ recoveryConfigured: false, backupMeans: { recoveryKey: false, rememberedDevices: null } }));
    expect(m?.avertir, 'ne pas savoir, c’est ne pas pouvoir compter dessus').toBe(true);
  });

  it('ne conseille pas une case grisée (§34)', () => {
    // Échec évité : « cochez Garder cet appareil déverrouillé » là où la
    // mémorisation est refusée (Linux, Windows sans mot de passe…).
    expect(texteAucunSecours(statut({ rememberAllowed: true }))).toBe('compte.secours.aucun');
    expect(texteAucunSecours(statut({ rememberAllowed: false, rememberRefusal: 'notOnThisPlatform' }))).toBe(
      'compte.secours.aucunSansCase',
    );
    expect(MESSAGES.fr['compte.secours.aucunSansCase'], 'le texte sans case ne parle pas de la case').not.toContain('Garder');
  });

  it('rend null sans compte : il n’y a rien à secourir', () => {
    expect(moyensDeSecours(statut({ state: 'none', email: null, backupMeans: { recoveryKey: false, rememberedDevices: null } }))).toBeNull();
    expect(moyensDeSecours(null)).toBeNull();
  });
});

// ---------------------------------------------------------------------------

describe('libelleSynchro — la seule fonction qui dit « Synchronisé » (§4.11, §100)', () => {
  const maintenant = new Date(2026, 8, 24, 15, 0).getTime();

  it('dit « Synchronisé » avec un seq du serveur, une confirmation et une file vide', () => {
    const l = libelleSynchro(
      synchro({ state: 'upToDate', serverSeq: 57, lastConfirmedAt: new Date(2026, 8, 24, 14, 2).getTime(), pendingCount: 0 }),
      maintenant,
      'fr',
    );
    expect(l.cle).toBe('compte.synchro.aJour');
    expect(l.vars).toEqual({ moment: '14 h 02', seq: 57 });
  });

  it('refuse « Synchronisé » sans seq, sans confirmation, ou avec une file inconnue', () => {
    // Échec évité : l'étape 8 rend tous ces nombres à null ; un 0 supposé
    // affichait « Synchronisé » chez quelqu'un dont rien n'est parti.
    for (const manque of [
      { serverSeq: null, lastConfirmedAt: 1, pendingCount: 0 },
      { serverSeq: 5, lastConfirmedAt: null, pendingCount: 0 },
      { serverSeq: 5, lastConfirmedAt: 1, pendingCount: null },
      { serverSeq: 5, lastConfirmedAt: 1, pendingCount: 2 },
    ]) {
      const l = libelleSynchro(synchro({ state: 'upToDate', ...manque }), maintenant, 'fr');
      expect(l.cle, JSON.stringify(manque)).not.toBe('compte.synchro.aJour');
    }
  });

  it('aucun autre état ne produit le libellé « Synchronisé »', () => {
    const etats = ['disabled', 'paused', 'needsConsent', 'syncing', 'pending', 'offline', 'quarantined', 'repaired',
      'quotaExceeded', 'serverFull', 'sessionExpired', 'resetPending', 'accountReset', 'accountDeleted',
      'serverRolledBack', 'serverLost'] as const;
    for (const state of etats) {
      const l = libelleSynchro(synchro({ state, serverSeq: 9, lastConfirmedAt: maintenant, pendingCount: 0 }), maintenant, 'fr');
      expect(l.cle, state).not.toBe('compte.synchro.aJour');
    }
  });

  it('à l’étape 8, sans moteur, dit que rien ne part', () => {
    expect(libelleSynchro(synchro({ state: 'disabled' }), maintenant, 'fr').cle).toBe('compte.synchro.inactive');
  });

  it('un compte verrouillé (paused) ne promet aucune reprise (§5)', () => {
    // Échec évité (24/09/2026) : « En pause tant que cet appareil est
    // verrouillé » — `paused` est ce que le service rend pour TOUT compte
    // verrouillé, et aucun moteur ne reprendra quoi que ce soit.
    expect(libelleSynchro(synchro({ state: 'paused' }), maintenant, 'fr').cle).toBe('compte.synchro.inactive');
  });

  it('seul « Synchronisé » a le ton ok', () => {
    const l = libelleSynchro(synchro({ state: 'upToDate', serverSeq: 1, lastConfirmedAt: maintenant, pendingCount: 0 }), maintenant);
    expect(l.ton).toBe('ok');
    expect(libelleSynchro(synchro({ state: 'disabled' }), maintenant).ton).not.toBe('ok');
  });

  it('n’écrit pas « 0 modification en attente » ni une date nulle', () => {
    expect(libelleSynchro(synchro({ state: 'pending', pendingCount: 0 }), maintenant).cle).toBe('compte.synchro.inconnu');
    expect(libelleSynchro(synchro({ state: 'offline', pendingCount: 2, lastConfirmedAt: null }), maintenant).cle).toBe(
      'compte.synchro.horsLigne',
    );
    expect(libelleSynchro(synchro({ state: 'offline', pendingCount: null, lastConfirmedAt: maintenant }), maintenant).cle).toBe(
      'compte.synchro.horsLigne',
    );
  });

  it('ne compte pas zéro élément mis à l’écart ou réparé', () => {
    for (const n of [0, null]) {
      expect(libelleSynchro(synchro({ state: 'quarantined', quarantinedCount: n }), maintenant).cle, `quarantaine ${n}`).toBe(
        'compte.synchro.inconnu',
      );
      expect(libelleSynchro(synchro({ state: 'repaired', repairedCount: n }), maintenant).cle, `réparé ${n}`).toBe(
        'compte.synchro.inconnu',
      );
    }
    expect(libelleSynchro(synchro({ state: 'quarantined', quarantinedCount: 2 }), maintenant).vars).toEqual({ count: 2 });
    expect(libelleSynchro(synchro({ state: 'repaired', repairedCount: 3 }), maintenant).vars).toEqual({ count: 3 });
  });

  it('en attente : le nombre vient du serveur local, jamais d’une supposition', () => {
    expect(libelleSynchro(synchro({ state: 'pending', pendingCount: 3 }), maintenant).vars).toEqual({ count: 3 });
    expect(libelleSynchro(synchro({ state: 'pending', pendingCount: null }), maintenant).cle).toBe('compte.synchro.inconnu');
  });

  it('écrit l’heure en français « 14 h 02 » et en anglais « 2:02 PM »', () => {
    const t = new Date(2026, 8, 24, 14, 2).getTime();
    expect(formaterHeure(t, 'fr')).toBe('14 h 02');
    expect(formaterHeure(t, 'en')).toBe('2:02 PM');
  });

  it('écrit minuit « 12:00 AM » et midi « 12:00 PM » en anglais', () => {
    expect(formaterHeure(new Date(2026, 8, 24, 0, 0).getTime(), 'en')).toBe('12:00 AM');
    expect(formaterHeure(new Date(2026, 8, 24, 12, 0).getTime(), 'en')).toBe('12:00 PM');
    expect(formaterHeure(new Date(2026, 8, 24, 0, 5).getTime(), 'fr')).toBe('0 h 05');
  });

  it('ne donne l’année que si elle diffère', () => {
    const cetteAnnee = formaterMoment(new Date(2026, 2, 3, 9, 0).getTime(), maintenant, 'fr');
    const lAnDernier = formaterMoment(new Date(2025, 2, 3, 9, 0).getTime(), maintenant, 'fr');
    expect(cetteAnnee).not.toContain('2026');
    expect(lAnDernier).toContain('2025');
  });

  it('donne la date quand la confirmation n’est pas du jour', () => {
    const hier = new Date(2026, 8, 23, 9, 5).getTime();
    const l = libelleSynchro(synchro({ state: 'upToDate', serverSeq: 1, lastConfirmedAt: hier, pendingCount: 0 }), maintenant, 'fr');
    expect(String(l.vars?.moment)).toContain('9 h 05');
    expect(String(l.vars?.moment)).toContain('23');
  });

  it('lit un jour du serveur de comptes en UTC, sans inventer d’heure', () => {
    // 20 720 jours après le 1er janvier 1970 = le 24 septembre 2026.
    expect(formaterJour(20720, 'fr')).toContain('24');
    expect(formaterJour(20720, 'fr')).toContain('2026');
  });
});

// ---------------------------------------------------------------------------

describe('messageErreur — une phrase par code, jamais inventée', () => {
  it('donne l’attente d’un 429 quand le serveur la connaît', () => {
    expect(messageErreur({ code: 'tooManyAttempts', attenteS: 30 })).toEqual({
      cle: 'compte.erreur.tooManyAttemptsDelai',
      vars: { secondes: 30 },
    });
    expect(messageErreur({ code: 'tooManyAttempts' }).cle).toBe('compte.erreur.tooManyAttempts');
  });

  it('dit « changé ailleurs » après une révocation, pas « mot de passe incorrect »', () => {
    expect(messageErreur({ code: 'invalidCredentials', raison: 'changedElsewhere' }).cle).toBe('compte.erreur.changedElsewhere');
    expect(messageErreur({ code: 'invalidCredentials' }).cle).toBe('compte.erreur.invalidCredentials');
  });

  it('nomme un code inconnu au lieu de le maquiller', () => {
    expect(messageErreur({ code: 'codeVenuDuFutur' })).toEqual({
      cle: 'compte.erreur.inconnue',
      vars: { code: 'codeVenuDuFutur' },
    });
  });

  it('nomme le champ refusé, jamais la valeur', () => {
    expect(messageErreur({ code: 'invalidRequest', champ: 'password' })).toEqual({
      cle: 'compte.erreur.invalidRequestChamp',
      vars: { champ: 'password' },
    });
  });

  it('dit pourquoi la mémorisation est refusée', () => {
    expect(messageErreur({ code: 'rememberNotAllowed', raison: 'windowsAccountWithoutPassword' }).cle).toBe(
      'compte.memoriser.refus.windowsSansMotDePasse',
    );
    expect(motifRefusMemorisation(null)).toBeNull();
    expect(motifRefusMemorisation('motifInconnu'), 'un motif inconnu reste un refus').toBe('compte.memoriser.refus.aucunProtecteur');
  });

  it('choisit le texte du §2.11 selon le protecteur', () => {
    expect(texteMemorisation('keychain')).toBe('compte.memoriser.aide.trousseau');
    expect(texteMemorisation('dpapi')).toBe('compte.memoriser.aide.windows');
    expect(texteMemorisation('file')).toBe('compte.memoriser.aide.fichier');
    expect(texteMemorisation('memory')).toBe('compte.memoriser.aide.memoire');
  });

  it('dit une réinitialisation que le serveur n’a pas pu confirmer', () => {
    expect(messageErreur({ code: 'resetNeedsKnownAccount', raison: 'incarnationUnconfirmed' }).cle).toBe(
      'compte.erreur.resetIncarnationUnconfirmed',
    );
    expect(messageErreur({ code: 'resetNeedsKnownAccount' }).cle).toBe('compte.erreur.resetNeedsKnownAccount');
  });

  it('nomme le code d’un défaut interne dans sa phrase', () => {
    expect(messageErreur({ code: 'plaintextRefused' })).toEqual({
      cle: 'compte.erreur.defautInterne',
      vars: { code: 'plaintextRefused' },
    });
  });
});

// ---------------------------------------------------------------------------

describe('etapeActivation — l’étape suit le serveur local (§3.11)', () => {
  const vue = (v: Partial<EtatVue> = {}): EtatVue => ({ parcours: 'accueil', ...v });
  const sans = statut({ state: 'none', unlocked: false, email: null, backupMeans: { recoveryKey: false, rememberedDevices: null } });

  it('attend le statut, et dit quand il est illisible', () => {
    expect(etapeActivation(null, vue())).toBe('chargement');
    expect(etapeActivation('illisible', vue())).toBe('illisible');
  });

  it('P1 : accueil, puis adresse, code, mot de passe, clé', () => {
    expect(etapeActivation(sans, vue())).toBe('accueil');
    expect(etapeActivation(sans, vue({ parcours: 'inscription' }))).toBe('adresse');
    const enCours = statut({ state: 'signupInProgress', unlocked: false, email: null, backupMeans: { recoveryKey: false, rememberedDevices: null } });
    expect(etapeActivation(enCours, vue({ parcours: 'inscription', inscription: 'code' }))).toBe('code');
    expect(etapeActivation(enCours, vue({ parcours: 'inscription', inscription: 'motDePasse' }))).toBe('motDePasse');
    expect(
      etapeActivation(enCours, vue({ parcours: 'inscription', cle: { cle: 'x', groupes: [1, 2], origine: 'inscription' } })),
    ).toBe('cle');
  });

  it('P2 : une inscription reprise après un rechargement repart du code', () => {
    // La vue a perdu sa sous-étape ; rien n'existe sur le VPS avant la fin.
    const enCours = statut({ state: 'signupInProgress', unlocked: false, email: null, backupMeans: { recoveryKey: false, rememberedDevices: null } });
    expect(etapeActivation(enCours, vue())).toBe('accueil');
    expect(etapeActivation(enCours, vue({ parcours: 'inscription' }))).toBe('code');
  });

  it('une fois ouvert : le consentement d’abord si des conversations attendent (P3)', () => {
    const consentement = statut({ sync: { ...synchro({ state: 'needsConsent' }) } });
    expect(etapeActivation(consentement, vue({ parcours: 'connexion' }))).toBe('consentement');
    expect(etapeActivation(statut(), vue({ parcours: 'inscription' }))).toBe('synchro');
    expect(etapeActivation(statut(), vue({ parcours: 'inscription', synchroVue: true }))).toBe('termine');
  });

  it('une clé montrée n’est jamais quittée pour une autre étape', () => {
    // Elle n'est gardée nulle part ailleurs : la quitter, c'est la perdre.
    const cle = { cle: 'x', groupes: [1, 2] as [number, number], origine: 'remplacement' as const };
    expect(etapeActivation(statut(), vue({ parcours: 'recuperation', cle }))).toBe('nouvelleCle');
  });

  it('suit un état posé par le serveur, quoi que la vue ait choisi', () => {
    const expiree = statut({ state: 'sessionExpired', unlocked: false });
    expect(etapeActivation(expiree, vue({ parcours: 'inscription' }))).toBe('connexion');
    expect(etapeActivation(statut({ state: 'locked', unlocked: false }), vue())).toBe('deverrouillage');
    expect(etapeActivation(statut({ state: 'resetPending' }), vue({ parcours: 'connexion' }))).toBe('reinitPrevue');
    expect(etapeActivation(statut({ state: 'serverRolledBack', unlocked: false }), vue())).toBe('retourArriere');
    expect(etapeActivation(statut({ state: 'serverLost', unlocked: false }), vue())).toBe('serveurPerdu');
    expect(etapeActivation(statut({ state: 'accountReset', unlocked: false }), vue())).toBe('compteReinitialise');
  });

  it('P4 : les trois chemins de l’oubli restent atteignables d’un appareil verrouillé', () => {
    const verrouille = statut({ state: 'locked', unlocked: false });
    expect(etapeActivation(verrouille, vue({ parcours: 'oubli' }))).toBe('oubli');
    expect(etapeActivation(verrouille, vue({ parcours: 'recuperation' }))).toBe('recuperation');
    expect(etapeActivation(verrouille, vue({ parcours: 'reinitialisation' }))).toBe('reinitialisation');
  });

  it('sans compte ici, la réinitialisation ramène à l’écran d’oubli qui l’explique', () => {
    // Écart de l'étape 8 : `reset/*` répond `resetNeedsKnownAccount` depuis
    // un appareil neuf ; ouvrir le parcours aurait mené à une impasse (§34).
    expect(etapeActivation(sans, vue({ parcours: 'reinitialisation' }))).toBe('oubli');
  });

  it('serveur perdu : « Recréer le compte » passe par l’inscription', () => {
    const perdu = statut({ state: 'serverLost', unlocked: false });
    expect(etapeActivation(perdu, vue({ parcours: 'inscription', inscription: 'adresse' }))).toBe('adresse');
  });

  const cleInscription = { cle: 'x', groupes: [1, 2] as [number, number], origine: 'inscription' as const };
  const cleRemplacement = { cle: 'x', groupes: [1, 2] as [number, number], origine: 'remplacement' as const };

  it('une inscription oubliée par le serveur local revient à l’adresse, et le dit', () => {
    // Échec évité (24/09/2026) : inscription expirée (30 min) ou serveur
    // local redémarré → état `none` ; l'étape de la clé restait affichée,
    // chaque bouton répondait `noPendingSignup`, sans Retour ni croix — et
    // l'écran d'accueil plein écran bloquait toute l'app.
    expect(etapeActivation(sans, vue({ parcours: 'inscription', inscription: 'motDePasse', cle: cleInscription }))).toBe('adresse');
    expect(etapeActivation(sans, vue({ parcours: 'inscription', inscription: 'motDePasse' }))).toBe('adresse');
    expect(etapeActivation(sans, vue({ parcours: 'inscription', inscription: 'code' }))).toBe('adresse');
    expect(inscriptionExpiree(sans, vue({ parcours: 'inscription', inscription: 'motDePasse' })), 'l’écran doit le dire').toBe(true);
    expect(inscriptionExpiree(sans, vue({ parcours: 'inscription', inscription: 'adresse' })), 'pas à l’adresse').toBe(false);
    expect(inscriptionExpiree(sans, vue({ parcours: 'inscription' }))).toBe(false);
  });

  it('une clé d’inscription reste à l’écran tant que le serveur local la garde', () => {
    const enCours = statut({ state: 'signupInProgress', unlocked: false, email: null, backupMeans: { recoveryKey: false, rememberedDevices: null } });
    expect(etapeActivation(enCours, vue({ parcours: 'accueil', cle: cleInscription }))).toBe('cle');
    const perdu = statut({ state: 'serverLost', unlocked: false });
    expect(etapeActivation(perdu, vue({ parcours: 'inscription', cle: cleInscription }))).toBe('cle');
    expect(inscriptionExpiree(enCours, vue({ parcours: 'inscription', cle: cleInscription }))).toBe(false);
  });

  it('une clé de remplacement ne se montre que sur un appareil ouvert', () => {
    const verrouille = statut({ state: 'locked', unlocked: false });
    expect(etapeActivation(verrouille, vue({ cle: cleRemplacement }))).toBe('deverrouillage');
  });

  it('P4 chemin 2 : un appareil verrouillé peut se connecter avec le NOUVEAU mot de passe', () => {
    // Échec évité (24/09/2026) : `locked` ignorait le parcours connexion ;
    // le déverrouillage, hors ligne, refuse le mot de passe changé ailleurs,
    // et rien ne menait à /login — l'impasse du §34.
    const verrouille = statut({ state: 'locked', unlocked: false });
    expect(etapeActivation(verrouille, vue({ parcours: 'connexion' }))).toBe('connexion');
  });

  it('oubli, récupération et connexion restent atteignables depuis chaque état', () => {
    expect(etapeActivation(sans, vue({ parcours: 'oubli' }))).toBe('oubli');
    expect(etapeActivation(sans, vue({ parcours: 'recuperation' }))).toBe('recuperation');
    const enCours = statut({ state: 'signupInProgress', unlocked: false, email: null, backupMeans: { recoveryKey: false, rememberedDevices: null } });
    expect(etapeActivation(enCours, vue({ parcours: 'connexion' }))).toBe('connexion');
    for (const state of ['sessionExpired', 'accountReset', 'accountDeleted']) {
      const s = statut({ state, unlocked: false });
      expect(etapeActivation(s, vue({ parcours: 'oubli' })), `${state} oubli`).toBe('oubli');
      expect(etapeActivation(s, vue({ parcours: 'recuperation' })), `${state} récupération`).toBe('recuperation');
    }
    const arriere = statut({ state: 'serverRolledBack', unlocked: false });
    expect(etapeActivation(arriere, vue({ parcours: 'recuperation' }))).toBe('recuperation');
  });
});

describe('les sorties de l’écran du compte (D13, §82)', () => {
  it('l’écran d’accueil plein écran garde « Plus tard » hors de l’étape de la clé', () => {
    // Échec évité (24/09/2026) : au mot de passe, sans Retour, croix ni
    // Échap, un /signup/prepare en échec enfermait l'app plein écran.
    for (const etape of ['chargement', 'adresse', 'code', 'motDePasse', 'consentement', 'synchro', 'connexion', 'oubli',
      'recuperation', 'deverrouillage'] as EtapeActivation[]) {
      expect(sortieAccueil(etape), etape).toBe(true);
    }
    for (const etape of ['cle', 'nouvelleCle'] as EtapeActivation[]) {
      expect(sortieAccueil(etape), `${etape} : la clé n’est gardée nulle part ailleurs`).toBe(false);
    }
  });

  const base = { contexte: 'reglages' as const, cleAffichee: false, autreModale: false, dejaConsomme: false, etape: 'adresse' as EtapeActivation };

  it('Échap ferme le voile des Réglages, et vaut « Plus tard » en plein écran', () => {
    expect(actionEchap(base)).toBe('fermer');
    expect(actionEchap({ ...base, contexte: 'accueil' }), 'sans elle, aucune sortie au clavier dans WKWebView').toBe('plusTard');
  });

  it('Échap laisse la confirmation ouverte au-dessus décider seule', () => {
    // Échec évité (24/09/2026) : l'écouteur du voile, inscrit avant celui
    // de ConfirmModal, fermait aussi le voile sur l'Échap qui voulait dire
    // « Garder » — le code de réinitialisation saisi était perdu.
    expect(actionEchap({ ...base, autreModale: true })).toBeNull();
    expect(actionEchap({ ...base, contexte: 'accueil', autreModale: true })).toBeNull();
  });

  it('Échap ne ferme jamais une clé à l’écran, ni un Échap déjà consommé', () => {
    expect(actionEchap({ ...base, cleAffichee: true })).toBeNull();
    expect(actionEchap({ ...base, contexte: 'accueil', cleAffichee: true })).toBeNull();
    expect(actionEchap({ ...base, dejaConsomme: true })).toBeNull();
  });

  it('Tab boucle dans la carte, dans les deux sens', () => {
    expect(indiceFocusSuivant(3, 2, false)).toBe(0);
    expect(indiceFocusSuivant(3, 0, true)).toBe(2);
    expect(indiceFocusSuivant(3, 1, false)).toBe(2);
    expect(indiceFocusSuivant(3, -1, false), 'focus hors de la carte : le premier').toBe(0);
    expect(indiceFocusSuivant(3, -1, true), 'focus hors de la carte, Maj+Tab : le dernier').toBe(2);
    expect(indiceFocusSuivant(0, -1, false)).toBe(-1);
  });
});

describe('les Réglages rouvrent ce qui attend une réponse (§34)', () => {
  it('propose de répondre au consentement une fois le voile fermé', () => {
    // Échec évité (24/09/2026) : « En attente de votre accord… » sans aucun
    // bouton pour le donner.
    expect(actionSection(statut({ sync: synchro({ state: 'needsConsent' }) }))).toBe('consentir');
    expect(actionSection(statut())).toBeNull();
    expect(actionSection(statut({ state: 'locked', unlocked: false }))).toBeNull();
  });

  it('propose de résoudre chaque état d’alerte', () => {
    for (const state of ['sessionExpired', 'accountReset', 'accountDeleted', 'serverRolledBack', 'serverLost']) {
      expect(actionSection(statut({ state, unlocked: false })), state).toBe('resoudre');
    }
  });

  it('dit un statut périmé au lieu de l’afficher comme frais', () => {
    // Échec évité (24/09/2026) : serveur local arrêté, la section restait
    // « Déverrouillé », pastille verte, sans l'avis compte.statutPerime.
    expect(lectureAffichee(statut(), true, new Error('injoignable'))).toBe('perime');
    expect(lectureAffichee(statut(), true, null)).toBe('frais');
    expect(lectureAffichee(null, true, new Error('injoignable'))).toBe('erreur');
    expect(lectureAffichee(null, false, null)).toBe('chargement');
  });

  it('grise tout geste vers une destination que local_only refuse (§3.12)', () => {
    // Échec évité (24/09/2026) : l'adresse, la récupération et la
    // réinitialisation partaient, et le refus arrivait après le geste.
    expect(destinationBloquee(statut({ serverOriginAllowed: false }))).toBe(true);
    expect(destinationBloquee(statut())).toBe(false);
  });

  it('ne propose « Imprimer » que là où l’impression est vérifiée', () => {
    // Échec évité (24/09/2026) : sous Tauri macOS, window.print devient un
    // invoke refusé (core:webview:allow-print absent) — le bouton ne
    // faisait rien, sans un mot.
    expect(impressionDisponible(true)).toBe(false);
    expect(impressionDisponible(false)).toBe(true);
  });

  it('porte l’icône d’un encadré grave même sans titre', () => {
    // Échec évité (24/09/2026) : en ardéchine, danger et attente ont la même
    // encre ; seule l'icône les distingue, et elle n'était posée qu'avec un titre.
    expect(iconeEncadre('danger')).toBe('alerte');
    expect(iconeEncadre('alerte')).toBe('alerte');
    expect(iconeEncadre('ok')).toBe('ok');
    expect(iconeEncadre('attente')).toBeNull();
  });
});

describe('doitAfficherAccueil — une fois, dans la fenêtre (D13)', () => {
  const sans = statut({ state: 'none', unlocked: false, email: null, onboarding: 'pending', backupMeans: { recoveryKey: false, rememberedDevices: null } });

  it('s’affiche dans la fenêtre tant que le drapeau dit pending', () => {
    expect(doitAfficherAccueil(sans, true)).toBe(true);
    expect(doitAfficherAccueil({ ...sans, state: 'signupInProgress' }, true), 'une inscription commencée reprend').toBe(true);
  });

  it('ne s’affiche pas une fois « Plus tard » ou terminé', () => {
    expect(doitAfficherAccueil({ ...sans, onboarding: 'done' }, true)).toBe(false);
  });

  it('ne s’affiche jamais hors de la fenêtre (mini-panneau, navigateur)', () => {
    expect(doitAfficherAccueil(sans, false)).toBe(false);
  });

  it('ne bloque pas l’app sur un statut illisible ni sur un compte déjà là', () => {
    expect(doitAfficherAccueil(null, true)).toBe(false);
    expect(doitAfficherAccueil({ ...sans, state: 'locked' }, true)).toBe(false);
  });
});

describe('bandeauCompte et la réinitialisation (§3.6, §3.11)', () => {
  it('se tait sans compte et sur un appareil ouvert', () => {
    expect(bandeauCompte(statut({ state: 'none', unlocked: false }), 'fr')).toBeNull();
    expect(bandeauCompte(statut(), 'fr')).toBeNull();
    expect(bandeauCompte(null, 'fr')).toBeNull();
  });

  it('signale les six états du §3.11', () => {
    for (const state of ['locked', 'sessionExpired', 'resetPending', 'accountReset', 'serverRolledBack', 'serverLost']) {
      expect(bandeauCompte(statut({ state, unlocked: false, pendingResetAt: 1_790_000_000_000 }), 'fr'), state).not.toBeNull();
    }
  });

  it('propose de déverrouiller un appareil verrouillé, et d’annuler une réinitialisation', () => {
    expect(bandeauCompte(statut({ state: 'locked', unlocked: false }), 'fr')?.action).toBe('deverrouiller');
    expect(bandeauCompte(statut({ state: 'resetPending', pendingResetAt: 1_790_000_000_000 }), 'fr')?.action).toBe('annulerReinit');
  });

  it('donne à chaque état d’alerte son geste, compte supprimé compris (§4.11)', () => {
    const actions: Record<string, string> = {
      sessionExpired: 'reconnecter',
      accountReset: 'reconnecter',
      accountDeleted: 'reconnecter',
      serverRolledBack: 'reconnecter',
      serverLost: 'ouvrir',
    };
    for (const [state, action] of Object.entries(actions)) {
      expect(bandeauCompte(statut({ state, unlocked: false }), 'fr')?.action, state).toBe(action);
    }
  });

  it('dit une réinitialisation sans date comme une contradiction', () => {
    expect(bandeauCompte(statut({ state: 'resetPending', pendingResetAt: null }), 'fr')?.cle).toBe('compte.bandeau.reinitPrevueSansDate');
  });

  it('a un libellé, en deux langues, pour chaque état du compte', () => {
    for (const state of ETATS_COMPTE) {
      const cle = libelleEtat(state);
      expect(cle, state).toBe(`compte.etat.${state}`);
      expect(MESSAGES.fr[cle], `${cle} en français`).toBeTruthy();
    }
  });

  it('ne compte pas une inscription en cours comme un compte', () => {
    expect(aUnCompte(statut({ state: 'signupInProgress', unlocked: false }))).toBe(false);
    expect(aUnCompte(statut({ state: 'none', unlocked: false }))).toBe(false);
    expect(aUnCompte(statut({ state: 'locked', unlocked: false }))).toBe(true);
    expect(aUnCompte(null)).toBe(false);
  });

  it('distingue programmer, attendre et terminer une réinitialisation', () => {
    expect(etapeReinitialisation(null, 1000)).toBe('programmer');
    expect(etapeReinitialisation(2000, 1000)).toBe('attente');
    expect(etapeReinitialisation(1000, 1000)).toBe('terminer');
  });
});

// ---------------------------------------------------------------------------

describe('la phrase de passe (D5, D6)', () => {
  const PETITE_LISTE = ['abricot', 'baleine', 'cactus', 'dauphin', 'erable', 'falaise', 'girafe', 'hibou'];

  it('lit le format EFF et le format « un mot par ligne », sans doublon ni tiret', () => {
    expect(lireListeMots('11111\tabacus\n11112\tabdomen\n11113\tt-shirt\n11114\tabacus\n')).toEqual(['abacus', 'abdomen']);
    expect(lireListeMots('Cheval\nbatterie\n\n')).toEqual(['cheval', 'batterie']);
  });

  it('une petite liste n’est pas utilisable en production', () => {
    // D6 n'est pas tranchée : tant que la vraie liste manque, la suggestion
    // est masquée plutôt que tirée d'une liste trop courte.
    expect(listeUtilisable(PETITE_LISTE)).toBe(false);
    expect(listeUtilisable(Array.from({ length: LISTE_MOTS_MIN }, (_, i) => `m${i}`))).toBe(true);
  });

  it('tire assez de mots pour atteindre l’entropie visée', () => {
    expect(motsNecessaires(7776)).toBe(6); // la grande liste EFF : 6 × 12,9 bits
    expect(motsNecessaires(8)).toBe(24); // 3 bits par mot
  });

  it('tire uniformément par rejet, sans le biais du modulo', () => {
    // 2^32 n'est pas un multiple de 3 : 0xFFFFFFFF doit être rejeté.
    const tirages = [0xffffffff, 7];
    expect(indiceUniforme(3, () => tirages.shift() ?? 0)).toBe(1);
  });

  it('assemble des mots de la liste, séparés par des tirets', () => {
    let n = 0;
    const phrase = genererPhrase(PETITE_LISTE, () => n++, 9);
    expect(phrase?.texte).toBe('abricot-baleine-cactus');
    expect(phrase?.mots).toBe(3);
    expect(phrase?.bits).toBe(9);
  });

  it('ne propose rien sans liste : rien d’inventé (D6)', () => {
    expect(genererPhrase([])).toBeNull();
    expect(genererPhrase(['seul']), 'un seul mot ne porte aucune entropie').toBeNull();
  });

  it('arrondit les bits annoncés vers le bas, jamais au-dessus', () => {
    // 7 776 mots : 12,92 bits par mot ; six mots font 77,5 — on annonce 77.
    const mots = Array.from({ length: 7776 }, (_, i) => `m${i}`);
    expect(genererPhrase(mots, () => 0)?.bits).toBe(77);
  });

  it('refuse de tirer dans un intervalle invalide', () => {
    for (const n of [0, -1, 1.5, 2 ** 32 + 1, Number.NaN]) {
      expect(() => indiceUniforme(n, () => 0), String(n)).toThrow(RangeError);
    }
  });

  it('une phrase tirée respecte les règles du mot de passe', () => {
    const phrase = genererPhrase(PETITE_LISTE);
    expect(phrase && reglesMotDePasse(phrase.texte, 'carlito@exemple.org').valide).toBe(true);
  });
});

// ---------------------------------------------------------------------------

describe('partagé avec le serveur local : la source Python fait foi', () => {
  it('connaît chaque état que ServiceCompte peut rendre', () => {
    const service = lire('src/diapason/compte/service.py');
    const bloc = service.match(/^ETATS = \(([\s\S]*?)\n\)/m)?.[1] ?? '';
    const etats = [...bloc.matchAll(/"(\w+)"/g)].map((m) => m[1]);
    expect(etats.length, 'ETATS introuvable dans service.py').toBeGreaterThan(5);
    for (const e of etats) expect(ETATS_COMPTE as readonly string[], e).toContain(e);
  });

  it('a le même alphabet de clé que recuperation.py', () => {
    const source = lire('src/diapason/compte/recuperation.py');
    expect(source.match(/ALPHABET_CROCKFORD = "([0-9A-Z]+)"/)?.[1]).toBe(ALPHABET_CROCKFORD);
  });

  it('a les mêmes bornes de mot de passe que cles.py (D5)', () => {
    const source = lire('src/diapason/compte/cles.py');
    expect(Number(source.match(/^MOT_DE_PASSE_MIN = (\d+)/m)?.[1])).toBe(MOT_DE_PASSE_MIN);
    expect(Number(source.match(/^MOT_DE_PASSE_MAX = (\d+)/m)?.[1])).toBe(MOT_DE_PASSE_MAX);
  });

  it('lit exactement les champs que ServiceCompte.statut() rend (§3.8)', () => {
    // Échec évité (24/09/2026) : statutBrut() était écrit à la main ; un
    // champ renommé en Python (lastKeyChangeAt, rememberRefusal…) laissait
    // tous les tests verts, et en production lireStatut rendait null — la
    // section « illisible », le bandeau muet, l'accueil sauté sans un mot.
    const service = lire('src/diapason/compte/service.py');
    const corps = service.match(/\n {4}def statut\(self\)[\s\S]*?\n {8}return \{([\s\S]*?)\n {8}\}\n/)?.[1] ?? '';
    const python = new Set([...corps.matchAll(/"(\w+)":/g)].map((m) => m[1]));
    expect(python.size, 'le dict rendu par statut() introuvable dans service.py').toBeGreaterThan(10);
    const brut = statutBrut();
    const ici = new Set(
      Object.entries(brut).flatMap(([k, v]) => (v && typeof v === 'object' ? [k, ...Object.keys(v)] : [k])),
    );
    expect([...python].filter((k) => !ici.has(k)), 'champs rendus par Python que ce contrat ignore').toEqual([]);
    expect([...ici].filter((k) => !python.has(k)), 'champs attendus ici que Python ne rend pas').toEqual([]);
    expect(lireStatut(brut), 'le statut du contrat doit se lire').not.toBeNull();
  });

  it('a une phrase pour chaque code que le serveur local ou le serveur de comptes peut émettre', () => {
    // Échec évité (24/09/2026) : dpapiUnavailable, protectedFileCorrupt,
    // keyringInvalid, notFound, payloadTooLarge… s'affichaient « Refus
    // inattendu » ; seul `_STATUTS` était relu.
    const dossier = (d: string) =>
      readdirSync(resolve(racine, d))
        .filter((f) => f.endsWith('.py'))
        .map((f) => lire(`${d}/${f}`))
        .join('\n');
    const local = dossier('src/diapason/compte');
    const vps = dossier('src/diapason_comptes');
    const codes = new Set<string>();
    const cueillir = (source: string, motif: RegExp) => {
      for (const m of source.matchAll(motif)) codes.add(m[1]);
    };
    cueillir(local, /\bcode(?::\s*str)?\s*=\s*"(\w+)"/g);
    cueillir(local, /EtatRefuse\(\s*"(\w+)"/g);
    cueillir(local, /ErreurServeur\(\s*\w+,\s*"(\w+)"/g);
    cueillir(vps, /(?:ErreurRequete|refus_avec_meta)\([^()]*?\b\d{3},\s*"(\w+)"/g);
    cueillir(vps, /SessionRefusee\(\s*"(\w+)"/g);
    cueillir(vps, /_refus\(\s*"(\w+)"/g);
    cueillir(vps.match(/_CODES_HTTP = \{([^}]*)\}/)?.[1] ?? '', /"(\w+)"/g);
    expect(codes.size, 'aucun code cueilli : les motifs ne lisent plus la source').toBeGreaterThan(30);
    for (const code of ['dpapiUnavailable', 'keyringInvalid', 'notFound', 'payloadTooLarge', 'internal']) {
      expect(codes.has(code), `${code} doit être cueilli`).toBe(true);
    }
    const sansPhrase = [...codes].filter((code) => messageErreur({ code }).cle === 'compte.erreur.inconnue');
    expect(sansPhrase, 'codes sans phrase').toEqual([]);
    for (const code of codes) {
      const { cle } = messageErreur({ code });
      expect(MESSAGES.en[cle], `${cle} en anglais`).toBeTruthy();
      expect(MESSAGES.fr[cle], `${cle} en français`).toBeTruthy();
    }
  });

  it('a une phrase, en anglais et en français, pour chaque code que les routes connaissent', () => {
    // Échec évité : un code ajouté côté Python s'affichait « Refus
    // inattendu », alors que le serveur savait très bien ce qu'il refusait.
    const routes = lire('src/diapason/server/compte_routes.py');
    const bloc = routes.match(/_STATUTS: dict\[str, int\] = \{([\s\S]*?)\n\}/)?.[1] ?? '';
    const codes = [...bloc.matchAll(/"(\w+)":/g)].map((m) => m[1]);
    expect(codes.length, '_STATUTS introuvable dans compte_routes.py').toBeGreaterThan(10);
    for (const code of codes) {
      const { cle } = messageErreur({ code });
      expect(cle, code).not.toBe('compte.erreur.inconnue');
      expect(MESSAGES.en[cle], `${cle} en anglais`).toBeTruthy();
      expect(MESSAGES.fr[cle], `${cle} en français`).toBeTruthy();
    }
  });
});

describe('les comptes pas encore ouverts (service.COMPTES_OUVERTS, 24/09/2026)', () => {
  // Échec évité : le service de comptes n'est déployé nulle part, et l'app se
  // reconstruit depuis main. L'écran d'accueil proposait un compte qu'aucun
  // serveur ne pouvait créer ; l'inscription échouait au premier appel (§5).
  it('un serveur local plus ancien, qui ne dit rien, rend un statut illisible — et donc aucun accueil', () => {
    const brut = statutBrut({ state: 'none', unlocked: false, email: null, onboarding: 'pending' });
    delete brut.accountsOpen;
    const s = lireStatut(brut);
    expect(s, 'un champ absent se voit, comme les autres').toBeNull();
    expect(doitAfficherAccueil(s, true), 'pas d’écran d’accueil sur un statut illisible').toBe(false);
  });

  it('refuse un accountsOpen qui n’est pas un booléen', () => {
    expect(lireStatut(statutBrut({ accountsOpen: 'true' })), 'une chaîne n’est pas un oui').toBeNull();
  });

  it('sans compte ici, l’écran dit « pas encore ouverts » au lieu de proposer un parcours', () => {
    const ferme = statut({ state: 'none', unlocked: false, email: null, accountsOpen: false, onboarding: 'pending' });
    for (const parcours of [undefined, 'inscription', 'connexion', 'oubli', 'recuperation', 'reinitialisation'] as const) {
      const vue = { parcours } as Parameters<typeof etapeActivation>[1];
      expect(etapeActivation(ferme, vue), `le parcours ${parcours ?? 'par défaut'} ne doit pas s’ouvrir`).toBe('fermee');
    }
  });

  it('l’écran d’accueil ne s’affiche pas tant que les comptes sont fermés', () => {
    const ferme = statut({ state: 'none', unlocked: false, email: null, accountsOpen: false, onboarding: 'pending' });
    expect(doitAfficherAccueil(ferme, true), 'rien à accueillir quand rien n’est ouvert').toBe(false);
    const ouvert = statut({ state: 'none', unlocked: false, email: null, accountsOpen: true, onboarding: 'pending' });
    expect(doitAfficherAccueil(ouvert, true), 'ouvert, l’accueil revient comme avant').toBe(true);
  });

  it('le refus du serveur local a sa phrase', () => {
    expect(messageErreur({ code: 'accountsNotOpen' } as Parameters<typeof messageErreur>[0]).cle).toBe(
      'compte.erreur.accountsNotOpen',
    );
  });
});
