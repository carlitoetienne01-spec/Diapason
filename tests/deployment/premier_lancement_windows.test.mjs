import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { createHash } from 'node:crypto';
import {
  CONTROLES, ciblePubliee, argumentsNsis, environnementApplication,
  rapportValide, urlCdpValide, origineApplication, verifierNarration,
  residuFermable, ollamaPartageable, erreurDemarragePubliable,
  verifierBackendCourant, preparerAncienneSourceSynthétique,
  CONTROLES_LEGACY, SCHEMA_LEGACY_SQL, SCHEMA_LEGACY_SOURCE,
  preparerDonneesLegacy, verifierDonneesLegacy, empreinteAmorcageLegacy, verifierProfilQa,
  creerAncienServeurSynthétique, verifierBlocageLegacy, verifierRefusServeurLegacy,
} from '../../scripts/tester_installation_windows.mjs';

const version = '1.0.5-beta.20261107.23';
const sha = '8932e416a560c302e1a85c44b24d81598443daaf2151c6c8243c0f29c9c07687';

test('le diagnostic conserve la fin de pile sans publier de chemin ni jeton', () => {
  const pile = 'x'.repeat(1800) + '\nC:\\profil\\runtime\\serve.py\nBearer jeton-factice\nUnicodeDecodeError: cp1252';
  const nettoye = erreurDemarragePubliable(pile);
  assert(nettoye.endsWith('UnicodeDecodeError: cp1252'));
  assert(!nettoye.includes('C:\\profil'));
  assert(!nettoye.includes('jeton-factice'));
  assert.equal(erreurDemarragePubliable('x'.repeat(20000)).length, 12000);
});

test('la cible ne peut sortir de la release officielle et vérifiée', () => {
  const cible = ciblePubliee(version, sha);
  assert.equal(cible.url, `https://github.com/carlitoetienne01-spec/Diapason/releases/download/beta-windows-v${version}/Diapason_${version}_x64-setup.exe`);
  for (const invalide of ['../secrets', `${version}/autre.exe`, 'https://ailleurs.test', '1.0.5', `${version}\n`]) {
    assert.throws(() => ciblePubliee(invalide, sha));
  }
  for (const invalide of ['', sha.toUpperCase(), 'g'.repeat(64), sha.slice(1)]) {
    assert.throws(() => ciblePubliee(version, invalide));
  }
});

test('NSIS reçoit /D en dernier sans une citation qui change son répertoire', () => {
  assert.deepEqual(argumentsNsis('C:\\Essai Windows\\application'), ['/S', '/NS', '/D=C:\\Essai Windows\\application']);
  for (const invalide of ['relative', '/tmp/app', 'C:\\app" /R', 'C:\\app\n/S']) {
    assert.throws(() => argumentsNsis(invalide));
  }
});

test('l’environnement enfant ne reçoit ni clés, ni checkout, ni chemins de modèles du runner', () => {
  const env = environnementApplication({ SystemRoot: 'C:\\Windows',
    PATH: 'C:\\outils\\uv;C:\\outils\\ollama', GITHUB_TOKEN: 'secret',
    DIAPASON_ROOT: 'C:\\checkout', DIAPASON_HOME: 'C:\\donnees',
    HF_TOKEN: 'secret', OLLAMA_MODELS: 'C:\\modeles', PYTHONPATH: 'C:\\checkout',
  }, 'C:\\essai\\profil', 19001);
  assert.equal(env.HOME, 'C:\\essai\\profil');
  assert.equal(env.USERPROFILE, env.HOME);
  assert.equal(env.WEBVIEW2_USER_DATA_FOLDER, 'C:\\essai\\profil\\WebView2');
  assert.equal(env.OLLAMA_MODELS, 'C:\\essai\\profil\\OllamaModels');
  assert(!env.PATH.includes('outils'));
  for (const cle of ['GITHUB_TOKEN', 'HF_TOKEN', 'DIAPASON_ROOT', 'DIAPASON_HOME', 'PYTHONPATH']) {
    assert.equal(env[cle], undefined, `${cle} doit rester hors de l'app testée`);
  }
  assert(env.WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS.includes('127.0.0.1'));
  assert.throws(() => environnementApplication({ SystemRoot: 'C:\\Windows' }, 'C:\\essai', 0));
});

test('aucun contrôle manquant ne devient une installation réussie', () => {
  const r = { installerExecuted: true, scenario: 'fresh', failureCode: null,
    checks: Object.fromEntries(CONTROLES.map(c => [c, true])) };
  assert(rapportValide(r));
  for (const cle of CONTROLES) {
    assert(!rapportValide({ ...r, checks: { ...r.checks, [cle]: false } }), cle);
    const incomplet = { ...r.checks }; delete incomplet[cle];
    assert(!rapportValide({ ...r, checks: incomplet }), cle);
  }
  assert(!rapportValide({ ...r, installerExecuted: false }));
  assert(!rapportValide({ ...r, failureCode: 'notInstalled' }));
  assert(!rapportValide({ ...r, cleanupFailed: true }));
  assert(!rapportValide({ ...r, scenario: 'legacy' }));
  assert(!rapportValide({ ...r, scenario: undefined }));
  const legacy = { ...r, scenario: 'legacy',
    checks: { ...r.checks, ...Object.fromEntries(CONTROLES_LEGACY.map(c => [c, true])) },
    legacyRefusal: { observed: true, ownedServerAlive: true, bootstrapUnchanged: true,
      ownedServerStopped: true, appHealthRequests: 1 },
    legacyPersistence: { seededBeforeLaunch: true, afterStartup: true, afterRestart: true, sameKey: true },
  };
  assert(rapportValide(legacy));
  for (const compte of [0, '1', Infinity, 1.5]) {
    assert(!rapportValide({ ...legacy, legacyRefusal: { ...legacy.legacyRefusal, appHealthRequests: compte } }));
  }
  for (const c of CONTROLES_LEGACY) {
    assert(!rapportValide({ ...legacy, checks: { ...legacy.checks, [c]: false } }), c);
    const checks = { ...legacy.checks }; delete checks[c];
    assert(!rapportValide({ ...legacy, checks }), c);
  }
  for (const groupe of ['legacyRefusal', 'legacyPersistence']) {
    assert(!rapportValide({ ...legacy, [groupe]: undefined }), groupe);
    for (const champ of Object.keys(legacy[groupe])) {
      assert(!rapportValide({ ...legacy, [groupe]: { ...legacy[groupe], [champ]: false } }), champ);
    }
  }
  assert(rapportValide(r), 'fresh reste une preuve valide pour fresh sans exiger legacy');
  assert(!rapportValide({ ...r, scenario: 'autre' }));
});

test('une santé générique ou un ancien backend ne valide pas le nouvel installateur', () => {
  const courant = { status: 'ok', managementApiVersion: 1, backendVersion: version };
  assert.doesNotThrow(() => verifierBackendCourant(courant, version));
  for (const sante of [{ status: 'ok' }, { ...courant, backendVersion: '1.0.0' },
    { ...courant, managementApiVersion: '1' }, { ...courant, managementApiVersion: true },
    { ...courant, backendVersion: version + '.autre' }, { ...courant, status: 'failed' }]) {
    assert.throws(() => verifierBackendCourant(sante, version));
  }
});

test('la source ancienne synthétique reste détectable sans être écrasée par une seconde préparation', () => {
  const profil = fs.mkdtempSync(path.join(os.tmpdir(), 'diapason-ancienne-source-'));
  try {
    const env = { HOME: profil, LOCALAPPDATA: path.join(profil, 'LocalAppData') };
    const preservee = preparerAncienneSourceSynthétique(env);
    assert(preservee());
    assert.throws(() => preparerAncienneSourceSynthétique(env));
    assert(preservee(), 'un second essai ne doit pas écraser la fixture existante');
    fs.writeFileSync(path.join(env.LOCALAPPDATA, 'Diapason', 'src', 'pyproject.toml'), 'modifié');
    assert(!preservee(), 'une ancienne source remplacée doit faire échouer le contrôle');
  } finally { fs.rmSync(profil, { recursive: true, force: true }); }
});

test('le serveur résiduel ne permet pas de fermer une autre fenêtre ou session', () => {
  const app = { processId: 20224, sessionId: 30, hasWindow: false, pathReadable: true, processName: 'diapason' };
  const bureau = { interactive: true, sessionId: 30, existingApplications: [app] };
  assert(residuFermable(bureau, 20224));
  assert(!residuFermable(bureau, 9));
  for (const patch of [{ hasWindow: true }, { sessionId: 0 }, { pathReadable: false }, { processName: 'python' }]) {
    assert(!residuFermable({ ...bureau, existingApplications: [{ ...app, ...patch }] }, 20224));
  }
  assert(!residuFermable({ ...bureau, existingApplications: [app, app] }, 20224));
});

test('un service partagé est forcément Ollama en boucle locale dans la même session', () => {
  const p = { port: 11434, processId: 9, sessionId: 30, loopback: true, processName: 'ollama', executableIsOllama: true };
  assert(ollamaPartageable([p], 30));
  for (const patch of [{ port: 8000 }, { processName: 'python' }, { sessionId: 0 }, { loopback: false }, { executableIsOllama: false }]) {
    assert(!ollamaPartageable([{ ...p, ...patch }], 30));
  }
  assert(!ollamaPartageable([], 30));
  assert(!ollamaPartageable([p, { ...p, processId: 10 }], 30));
});

test('le canal de test refuse un navigateur externe ou un autre port', () => {
  assert(urlCdpValide('ws://127.0.0.1:19001/devtools/page/abc-123', 19001));
  for (const url of ['ws://ailleurs.test:19001/devtools/page/abc',
    'ws://127.0.0.1:19002/devtools/page/abc', 'ws://secret@127.0.0.1:19001/devtools/page/abc',
    'wss://127.0.0.1:19001/devtools/page/abc', 'ws://127.0.0.1:19001/autre']) {
    assert(!urlCdpValide(url, 19001), url);
  }
  assert(origineApplication('http://tauri.localhost/'));
  assert(origineApplication('tauri://localhost/'));
  for (const url of ['https://github.com/', 'http://127.0.0.1:8000/', 'about:blank']) {
    assert(!origineApplication(url));
  }
});

function audio() {
  const pcm = Buffer.alloc(48000); pcm.writeInt16LE(100, 100);
  const wav = Buffer.alloc(44 + pcm.length);
  wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVE', 8);
  wav.write('fmt ', 12); wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22); wav.writeUInt32LE(24000, 24); wav.writeUInt32LE(48000, 28);
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36);
  wav.writeUInt32LE(pcm.length, 40); pcm.copy(wav, 44);
  return { mimeType: 'audio/wav', sampleRate: 24000, timingStatus: 'aligned',
    dataBase64: wav.toString('base64'),
    words: Array.from({ length: 5 }, (_, i) => ({ word: 'mot', start: i / 10, end: (i + 1) / 10 })) };
}

test('un WAV valide ne suffit pas sans vrais repères cohérents', () => {
  assert.equal(verifierNarration(audio()).durationSeconds, 1);
  assert.throws(() => verifierNarration({ ...audio(), timingStatus: 'unavailable' }));
  assert.throws(() => verifierNarration({ ...audio(), words: [] }));
  const r = audio(); r.words[4].end = 20;
  assert.throws(() => verifierNarration(r));
  const inverse = audio(); inverse.words[3] = { word: 'mot', start: 0, end: 0.1 };
  assert.throws(() => verifierNarration(inverse));
});

function contexteQa(t) {
  const travail = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'diapason-reprise-')));
  const profil = path.join(travail, 'profil');
  const env = { HOME: profil, USERPROFILE: profil,
    LOCALAPPDATA: path.join(profil, 'AppData', 'Local'), APPDATA: path.join(profil, 'AppData', 'Roaming'),
    UV_CACHE_DIR: path.join(profil, 'CacheUv'), UV_PYTHON_INSTALL_DIR: path.join(profil, 'Python'),
    OLLAMA_MODELS: path.join(profil, 'OllamaModels'), HF_HOME: path.join(profil, 'HuggingFace') };
  fs.mkdirSync(env.LOCALAPPDATA, { recursive: true }); fs.mkdirSync(env.APPDATA, { recursive: true });
  t.after(() => fs.rmSync(travail, { recursive: true, force: true }));
  return { travail, env };
}

function apiFixture(f) {
  return async route => {
    if (route === '/v1/vie/projects') return { projects: [{ ...f.project }] };
    if (route.startsWith('/v1/vie/notes/')) return { note: { ...f.note, projectId: f.project.id } };
    if (route === '/v1/vie/finances/accounts') return { accounts: [{ ...f.account, currency: 'CAD',
      openingBalance: f.account.openingCents / 100, balance: (f.account.openingCents - f.transaction.amountCents) / 100 }] };
    if (route.startsWith('/v1/vie/finances/transactions?')) return { transactions: [{ ...f.transaction,
      accountId: f.account.id, categoryId: f.categoryId, type: 'expense', currency: 'CAD', amount: f.transaction.amountCents / 100 }] };
    if (route.startsWith('/v1/vie/finances/overview?')) return { transactionCount: 1, expense: f.transaction.amountCents / 100 };
    throw new Error('unexpectedFixtureRoute');
  };
}

test('legacy sème la clé et les vraies tables héritées avant tout lancement', async t => {
  const { travail, env } = contexteQa(t);
  const preservee = preparerAncienneSourceSynthétique(env);
  const f = await preparerDonneesLegacy(env, travail);
  const { DatabaseSync } = await import('node:sqlite');
  const db = new DatabaseSync(f.base, { readOnly: true });
  try {
    assert.equal(db.prepare('PRAGMA integrity_check').get().integrity_check, 'ok');
    assert.equal(db.prepare('PRAGMA user_version').get().user_version, 5);
    assert.equal(db.prepare('SELECT content,project_id FROM succes_notes WHERE id=?').get(f.note.id).content, f.note.content);
    assert.equal(db.prepare('SELECT project_id FROM succes_notes WHERE id=?').get(f.note.id).project_id, f.project.id);
    assert.equal(db.prepare('SELECT name FROM succes_projects WHERE id=?').get(f.project.id).name, f.project.name);
    assert.equal(db.prepare('SELECT amount_cents FROM succes_transactions WHERE id=?').get(f.transaction.id).amount_cents, 3537);
    assert.equal(db.prepare('SELECT value FROM succes_meta WHERE key=?').get('device_id').value, f.deviceId);
  } finally { db.close(); }
  assert.equal(fs.existsSync(path.join(f.home, 'vie.db')), false, 'aucune base vide neuve à côté de la base héritée');
  assert(fs.readFileSync(f.clePath, 'utf8').trim() === f.cle, 'clé synthétique conservée sans la publier');
  assert(preservee());
  assert.equal(createHash('sha256').update(SCHEMA_LEGACY_SQL).digest('hex'), SCHEMA_LEGACY_SOURCE.sha256);
  assert.equal(Object.keys(SCHEMA_LEGACY_SOURCE.files).length, 3, 'origine des six tables gelées');
  await assert.rejects(preparerDonneesLegacy(env, travail), /legacyDataAlreadyExists/);
  assert(preservee());
});

test('la fixture et ses empreintes refusent de sortir du profil QA ou de suivre un lien', async t => {
  const { travail, env } = contexteQa(t);
  const dehors = path.join(travail, 'dehors'); fs.mkdirSync(dehors);
  assert.throws(() => verifierProfilQa({ ...env, HOME: dehors }, travail), /qaProfileOutsideWorkdir/);
  assert.throws(() => verifierProfilQa({ ...env, HF_HOME: path.dirname(travail) }, travail), /qaPathOutsideWorkdir/);
  fs.symlinkSync(dehors, env.HF_HOME, process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => empreinteAmorcageLegacy(env, travail), /qaPathLinked/);
  await assert.rejects(preparerDonneesLegacy(env, travail), /qaPathLinked/);
  assert.deepEqual(fs.readdirSync(dehors), [], 'aucune donnée écrite par le lien');
});

test('les anciennes note, projet, finance et clé doivent rester identiques aux deux lectures', async t => {
  const { travail, env } = contexteQa(t); const f = await preparerDonneesLegacy(env, travail);
  const api = apiFixture(f);
  assert.deepEqual(await verifierDonneesLegacy(f, api, f.cle), { matches: true, sameKey: true });
  assert.deepEqual(await verifierDonneesLegacy(f, api, f.cle), { matches: true, sameKey: true });
  for (const corruption of ['note', 'project', 'account', 'transaction', 'overview']) {
    const alterer = async route => {
      const r = await api(route);
      if (corruption === 'note' && r.note) r.note.projectId = 'autre-projet';
      if (corruption === 'project' && r.projects) r.projects[0].name = 'nouveau projet';
      if (corruption === 'account' && r.accounts) r.accounts[0].balance += 0.01;
      if (corruption === 'transaction' && r.transactions) r.transactions[0].amount += 0.01;
      if (corruption === 'overview' && r.transactionCount) r.transactionCount = 0;
      return r;
    };
    await assert.rejects(verifierDonneesLegacy(f, alterer, f.cle), /legacy.*Changed/, corruption);
  }
  await assert.rejects(verifierDonneesLegacy(f, api, 'autre-cle'), /legacyKeyChanged/);
});

test('l’empreinte constate les créations vides, le venv et les données changés', async t => {
  const { travail, env } = contexteQa(t); const f = await preparerDonneesLegacy(env, travail);
  const avant = empreinteAmorcageLegacy(env, travail);
  const runtime = path.join(env.LOCALAPPDATA, 'Diapason', 'runtime-complet');
  fs.mkdirSync(runtime, { recursive: true });
  assert.notEqual(empreinteAmorcageLegacy(env, travail), avant, 'même un dossier de bootstrap vide est une mutation');
  fs.writeFileSync(path.join(runtime, 'venv-temoin'), 'création interdite');
  assert.notEqual(empreinteAmorcageLegacy(env, travail), avant);
  fs.writeFileSync(f.clePath, 'cle changee');
  assert.notEqual(empreinteAmorcageLegacy(env, travail), avant);
});

test('seul le serveur synthétique de ce banc est fermé, pas un autre listener', async t => {
  const autre = http.createServer((req, res) => res.end('service distinct'));
  await new Promise(resolve => autre.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => autre.close(resolve)));
  const stub = await creerAncienServeurSynthétique(0);
  const url = `http://127.0.0.1:${stub.port}/health`;
  assert(await stub.verifierVivant());
  assert.equal(stub.mesures().appHealthRequests, 0, 'la sonde de propriété ne simule pas une requête de l’EXE');
  const r = await fetch(url); assert.deepEqual(await r.json(), { status: 'ok' });
  assert.equal(stub.mesures().appHealthRequests, 1);
  await assert.rejects(creerAncienServeurSynthétique(stub.port), /EADDRINUSE/);
  assert(await stub.verifierVivant(), 'le refus de prendre le port ne ferme pas son propriétaire');
  await stub.fermer(); await stub.fermer();
  await assert.rejects(stub.verifierVivant(), /legacyStubStoppedUnexpectedly/);
  assert(autre.listening, 'le listener distinct est toujours vivant');
});

const etatRefuse = () => ({ error: 'service incompatible', server_ready: false,
  backend_ready: false, ollama_ready: false, model_ready: false });

test('un état prêt, une erreur sans preuve ou une mutation ne deviennent pas un refus validé', () => {
  const log = 'DIAPASON_WINDOWS_BACKEND_MISMATCH expectedVersion=' + version;
  const faits = { ownedServerAlive: true, appHealthRequests: 1, bootstrapUnchanged: true };
  assert(verifierRefusServeurLegacy(etatRefuse(), log, version, faits));
  for (const champ of ['server_ready', 'backend_ready', 'ollama_ready', 'model_ready']) {
    assert.throws(() => verifierRefusServeurLegacy({ ...etatRefuse(), [champ]: true }, log, version, faits));
  }
  assert.throws(() => verifierRefusServeurLegacy(etatRefuse(), '', version, faits));
  assert.throws(() => verifierRefusServeurLegacy(etatRefuse(), log + '.autre', version, faits));
  assert.throws(() => verifierRefusServeurLegacy(etatRefuse(), log, version,
    { ...faits, appHealthRequests: 0 }));
  assert.throws(() => verifierRefusServeurLegacy(etatRefuse(), log, version,
    { ...faits, bootstrapUnchanged: false }));
});

test('le cycle garde le stub vivant jusqu’à l’arrêt de la fenêtre puis libère seulement son port', async () => {
  let stub, fermeApp = false;
  const preuve = await verifierBlocageLegacy({ version, empreinte: () => 'identique',
    creerStub: async () => { stub = await creerAncienServeurSynthétique(0); return stub; },
    lancer: async s => { await (await fetch(`http://127.0.0.1:${s.port}/health`)).json(); return etatRefuse(); },
    lireLog: () => 'DIAPASON_WINDOWS_BACKEND_MISMATCH expectedVersion=' + version,
    arreter: async s => { assert(await s.verifierVivant()); fermeApp = true; },
  });
  assert(fermeApp && preuve.observed && preuve.ownedServerAlive && preuve.ownedServerStopped);
  assert.equal(stub.mesures().listening, false);
});

test('une erreur de démarrage ou une mutation nettoie le stub sans autoriser la reprise', async () => {
  for (const cas of ['startupError', 'mutation']) {
    let stub, mutations = false, arrets = 0;
    await assert.rejects(verifierBlocageLegacy({ version, empreinte: () => mutations ? 'modifie' : 'avant',
      creerStub: async () => { stub = await creerAncienServeurSynthétique(0); return stub; },
      lancer: async s => {
        await (await fetch(`http://127.0.0.1:${s.port}/health`)).json();
        if (cas === 'startupError') throw new Error('injectedStartupFailure');
        mutations = true; return etatRefuse();
      },
      lireLog: () => 'DIAPASON_WINDOWS_BACKEND_MISMATCH expectedVersion=' + version,
      arreter: async s => { assert(await s.verifierVivant()); arrets++; },
    }));
    assert.equal(arrets, 1, 'arrêter la fenêtre possédée avant le stub, même en échec');
    assert.equal(stub.mesures().listening, false, 'aucun stub restant après échec');
  }
});

test('un arrêt de fenêtre non confirmé ne libère pas le port du stub', async t => {
  let stub, arrets = 0;
  await assert.rejects(verifierBlocageLegacy({ version, empreinte: () => 'avant',
    creerStub: async () => {
      stub = await creerAncienServeurSynthétique(0);
      t.after(() => stub.fermer());
      return stub;
    },
    lancer: async s => { await (await fetch(`http://127.0.0.1:${s.port}/health`)).json(); return etatRefuse(); },
    lireLog: () => 'DIAPASON_WINDOWS_BACKEND_MISMATCH expectedVersion=' + version,
    arreter: async s => { assert(await s.verifierVivant()); arrets++; throw new Error('ownedAppStillAlive'); },
  }), /ownedAppStillAlive/);
  assert.equal(arrets, 2, 'un second essai de fermeture de la seule fenêtre possédée');
  assert(await stub.verifierVivant(), 'port encore protégé tant que la fenêtre peut repartir');
});

test('le vrai arrêt interne réessaie les services sans oublier l’enfant ni fermer le stub', async () => {
  const texte = fs.readFileSync(new URL('../../scripts/tester_installation_windows.mjs', import.meta.url), 'utf8');
  const debut = texte.indexOf('  async function arreter({ garderStub = false } = {}) {');
  const fin = texte.indexOf('  async function preparerEnvironnement()', debut);
  assert(debut > 0 && fin > debut, 'extraire le corps interne exact, pas un double de son état');
  const fonctionExacte = texte.slice(debut, fin);
  let ferme = false, controlesArret = 0;
  const enfantInitial = { exitCode: 0, signalCode: null };
  const stub = {
    verifierVivant: async () => !ferme,
    mesures: () => ({ appHealthRequests: 1 }),
    fermer: async () => { ferme = true; },
  };
  // Aucun processus/socket : fenêtre déjà sortie, service QA encore vivant.
  const fabrique = new Function('dep', `
    let enfant = dep.enfantInitial;
    let cdp = { invoquer: async () => {}, fermer: () => {} };
    const ollamaExistant = null;
    const { attendre, path } = dep;
    const portOccupe = async () => true;
    const inferenceOriginalePreservee = async () => false;
    const verifier = (ok, code) => { if (!ok) throw new Error(code); };
    const executer = async () => { throw new Error('aucun processus autorisé'); };
    ${fonctionExacte}
    return { arreter, etat: () => ({ enfant, cdp }) };
  `);
  const controle = fabrique({ path, enfantInitial, attendre: async (action, delai, code) => {
    controlesArret++;
    assert.equal(delai, 30000);
    assert.equal(code, 'testProcessesNotStopped');
    assert.equal(await action(), false, 'le service QA empêche la confirmation');
    throw new Error(code);
  } });
  const versionLegacy = '1.0.5-beta.20261108.33';
  await assert.rejects(verifierBlocageLegacy({
    version: versionLegacy, empreinte: () => 'identique', creerStub: async () => stub,
    lancer: async () => etatRefuse(),
    lireLog: () => 'DIAPASON_WINDOWS_BACKEND_MISMATCH expectedVersion=' + versionLegacy,
    arreter: s => controle.arreter({ garderStub: s }),
  }), erreur => erreur.message === 'testProcessesNotStopped');
  assert.equal(controlesArret, 2, 'le second arrêt doit refaire la confirmation des services');
  assert.equal(controle.etat().enfant, enfantInitial, 'ne pas oublier l’enfant avant confirmation complète');
  assert.equal(controle.etat().cdp, null, 'la fenêtre a été fermée');
  assert.equal(ferme, false, 'le port du stub reste protégé après les deux échecs');
});
