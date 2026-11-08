import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { createHash } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import {
  CONTROLES, ciblePubliee, argumentsNsis, environnementApplication,
  rapportValide, urlCdpValide, origineApplication, verifierNarration,
  residuFermable, ollamaPartageable, erreurDemarragePubliable,
  verifierBackendCourant, preparerAncienneSourceSynthétique,
  CONTROLES_LEGACY, SCHEMA_LEGACY_SQL, SCHEMA_LEGACY_SOURCE,
  preparerDonneesLegacy, verifierDonneesLegacy, empreinteAmorcageLegacy, verifierProfilQa,
  creerAncienServeurSynthétique, verifierBlocageLegacy, verifierRefusServeurLegacy,
  autorisationArretAncien, validerArretAncien, arreterAncienBackend, rapportArretAncien,
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

// §100 : chemins factices ; la forme redirecteur correspond au diagnostic du
// runner, sans exécuter PowerShell, toucher un processus ni ouvrir son profil.
const utcObservation = new Date(Date.now() - 60000).toISOString();
const accordAncien = () => autorisationArretAncien({ 'stop-old-backend-pid': '48196',
  'stop-old-backend-observed-utc': utcObservation });
const faitsAncien = () => {
  const root = 'C:\\Users\\Compte Fictif\\AppData\\Local\\Diapason\\src';
  const base = 'C:\\hostedtoolcache\\windows\\Python\\3.13.9\\x64';
  return {
    canonicalRoot: root, interactive: true, runnerSession: 30,
    process: { pid: 48196, sameSid: true, sameSession: true, handleAlive: true,
      identity: '134000000000000000', createdUTC: new Date(Date.now() - 3600000).toISOString(),
      executablePath: base + '\\python.exe', handleImage: base + '\\python.exe',
      commandLine: `"${root}\\.venv\\Scripts\\python.exe" "${root}\\.venv\\Scripts\\diapason.exe" serve --port 8000` },
    source: { root, rootOwned: true, metadataOwned: true, cfgOwned: true, entryOwned: true,
      venvPythonOwned: true, baseVerified: true, aclVerified: true, reparseVerified: true,
      basePythonAclWindowsAncestorVerified: false, basePythonAclWindowsAncestorWriterVerified: false,
      cfg: `home = ${base}\r\ninclude-system-site-packages = false\r\n`, resolvedHome: base,
      projectName: 'Diapason', sourceVersion: '1.0.0', markerState: 'absent', betaAbsent: true, gitAbsent: true },
    listeners: [{ pid: 48196, port: 8000, address: '127.0.0.1' }],
    applications: [{ hasWindow: false, sameSid: true, sameSession: true, createdBeforeObservation: true,
      executablePath: root + '\\.venv\\Scripts\\diapason.exe',
      commandLine: `"${root}\\.venv\\Scripts\\diapason.exe" serve --port 8000` }],
  };
};

test('§100 — aucun arrêt par défaut ; ancien residual-pid toujours refusé', async () => {
  assert.equal(autorisationArretAncien({}), null);
  assert.equal(autorisationArretAncien({ 'stop-old-backend-pid': '', 'stop-old-backend-observed-utc': '' }), null);
  for (const ancien of ['48196', '44676', 48196, true]) {
    assert.throws(() => autorisationArretAncien({ 'residual-pid': ancien }), /personalProcessStopNotAuthorized/);
    assert.throws(() => autorisationArretAncien({ residual_pid: ancien }), /personalProcessStopNotAuthorized/);
  }
  let lances = 0;
  const r = await arreterAncienBackend(null, { platform: 'win32', lancer: () => lances++ });
  assert.equal(lances, 0); assert.equal(r.status, 'notRequested'); assert.equal(r.requested, false);
});

test('§100 — accord limité au PID observé et à un horodatage UTC strict antérieur', () => {
  const now = Date.parse('2026-11-08T15:00:00.000Z');
  const bon = { 'stop-old-backend-pid': '48196', 'stop-old-backend-observed-utc': '2026-11-08T14:59:00Z' };
  assert.deepEqual(autorisationArretAncien(bon, now), { pid: 48196, observedUTC: '2026-11-08T14:59:00.000Z' });
  for (const pid of ['44676', '48197', '048196', '48196\n', '48196;Stop-Process', 48196, true, '']) {
    assert.throws(() => autorisationArretAncien({ ...bon, 'stop-old-backend-pid': pid }, now));
  }
  for (const utc of ['', undefined, '2026-11-08', '2026-11-08T15:00:01Z', '2026-11-07T15:00:00Z',
    '2026-02-30T14:59:00Z', '2026-11-08T14:59:00+00:00', '2026-11-08T14:59:00Z\n']) {
    assert.throws(() => autorisationArretAncien({ ...bon, 'stop-old-backend-observed-utc': utc }, now));
  }
  assert.throws(() => autorisationArretAncien({ 'stop-old-backend-observed-utc': bon['stop-old-backend-observed-utc'] }, now));
});

test('§100 — redirecteur Python de base attesté sans imposer ExecutablePath dans le profil', () => {
  const n = faitsAncien();
  assert(validerArretAncien(n, accordAncien()));
  n.process.executablePath = n.source.root + '\\.venv\\Scripts\\python.exe';
  n.process.handleImage = n.process.executablePath;
  n.process.commandLine = `"${n.process.executablePath}" -I -B -m diapason serve`;
  assert(validerArretAncien(n, accordAncien()));
});

test('§100 — mauvais PID, SID, session, processus réutilisé et port changé refusent avant tout permis', () => {
  const mutations = [
    n => { n.process.pid++; }, n => { n.process.sameSid = false; }, n => { n.process.sameSession = false; },
    n => { n.runnerSession = 0; }, n => { n.interactive = false; }, n => { n.process.handleAlive = false; },
    n => { n.process.identity = ''; }, n => { n.process.createdUTC = new Date().toISOString(); },
    n => { n.process.handleImage = 'C:\\ailleurs\\python.exe'; },
    n => { n.listeners = []; }, n => { n.listeners[0].pid++; },
    n => { n.listeners.push({ ...n.listeners[0], pid: 55555 }); },
    n => { n.listeners[0].port++; }, n => { n.listeners[0].address = '0.0.0.0'; },
  ];
  for (const mutation of mutations) {
    const n = faitsAncien(); mutation(n);
    assert.throws(() => validerArretAncien(n, accordAncien()), /^Error: oldBackend/);
  }
});

test('§100 — metadata, ACL, reparse, version récente ou projet non Diapason empêchent le permis', () => {
  for (const champ of ['rootOwned', 'metadataOwned', 'cfgOwned', 'entryOwned', 'venvPythonOwned',
    'baseVerified', 'aclVerified', 'reparseVerified', 'betaAbsent', 'gitAbsent']) {
    const n = faitsAncien(); n.source[champ] = false;
    assert.throws(() => validerArretAncien(n, accordAncien()), /oldBackend(?:Source|Version)Refused/);
  }
  for (const [champ, valeur] of [['projectName', 'autre'], ['projectName', 'diapason'], ['markerState', 'versioned'],
    ['sourceVersion', '1.0.5-beta.20261108.33'], ['root', 'C:\\ailleurs\\Diapason\\src'],
    ['cfg', 'home = C:\\ailleurs'], ['cfg', 'home = C:\\base\nhome = C:\\base']]) {
    const n = faitsAncien(); n.source[champ] = valeur;
    assert.throws(() => validerArretAncien(n, accordAncien()), /^Error: oldBackend/);
  }
});

test('§100 — aucun simple contains, argument libre ou Python global -m ne suffit', () => {
  const n = faitsAncien(), entree = n.source.root + '\\.venv\\Scripts\\diapason.exe';
  for (const cmd of [
    `"${n.process.executablePath}" -c "print('${entree}')" serve`,
    `"${n.process.executablePath}" "${entree}.autre" serve`,
    `"${n.process.executablePath}" "${entree}" serve --port 8001`,
    `"${n.process.executablePath}" "${entree}" serve --host 0.0.0.0`,
    `"${n.process.executablePath}" "${entree}" serve --config C:\\profil\\secret`,
    `"${n.process.executablePath}" -m diapason serve`,
    n.process.commandLine + ' --port 8000',
  ]) {
    assert.throws(() => validerArretAncien({ ...n, process: { ...n.process, commandLine: cmd } }, accordAncien()), /oldBackendEntryRefused/);
  }
});

test('§100 — fenêtre ouverte, autre desktop ou lanceur ambigu interdisent l’arrêt', () => {
  for (const changer of [
    x => { x.hasWindow = true; }, x => { x.sameSid = false; }, x => { x.sameSession = false; },
    x => { x.createdBeforeObservation = false; },
    x => { x.executablePath = 'C:\\Programs\\Diapason\\diapason-desktop.exe'; },
    x => { x.commandLine += ' --port 8001'; },
  ]) {
    const n = faitsAncien(); changer(n.applications[0]);
    assert.throws(() => validerArretAncien(n, accordAncien()), /oldBackendUiActive/);
  }
  const n = faitsAncien(); n.applications.push({ ...n.applications[0] });
  assert.throws(() => validerArretAncien(n, accordAncien()), /oldBackendUiActive/);
});

function fauxArretNatif({ facts = faitsAncien(), result, refusAvantAttestation, silencieux = false } = {}) {
  let capture, permis = 0, script = '';
  const lancer = (exe, args, options) => {
    capture = { exe, args, options };
    const p = new EventEmitter(); p.stdout = new PassThrough(); p.stderr = new PassThrough();
    p.unref = () => {}; p.stdin = new PassThrough();
    p.stdin.on('data', b => {
      const ligne = b.toString().trim();
      if (!script) {
        script = Buffer.from(ligne, 'base64').toString('utf16le');
        if (!silencieux) queueMicrotask(() => p.stdout.write(JSON.stringify(refusAvantAttestation ?? { stage: 'attestation', facts }) + '\n'));
      } else {
        const autorisation = JSON.parse(ligne); assert.equal(autorisation.permit, true);
        assert.equal(autorisation.identity, facts.process.identity); permis++;
        queueMicrotask(() => p.stdout.write(JSON.stringify(result ?? { stage: 'result', status: 'stopped',
          basePythonAclWindowsAncestorVerified: facts.source.basePythonAclWindowsAncestorVerified,
          basePythonAclWindowsAncestorWriterVerified: facts.source.basePythonAclWindowsAncestorWriterVerified,
          targetStopped: true, portFree: true, launcherExited: true }) + '\n'));
      }
    });
    return p;
  };
  return { lancer, etat: () => ({ capture, permis, script }) };
}

test('§100 — refus de plateforme et mauvais owner ne lancent aucun arrêt natif', async () => {
  let lances = 0;
  const r = await arreterAncienBackend(accordAncien(), { platform: 'darwin', lancer: () => lances++ });
  assert.equal(lances, 0); assert.equal(r.status, 'refused');
  const facts = faitsAncien(); facts.process.sameSid = false;
  const faux = fauxArretNatif({ facts });
  const refus = await arreterAncienBackend(accordAncien(), { platform: 'win32', systeme: { SystemRoot: 'C:\\Windows' }, lancer: faux.lancer });
  assert.equal(refus.code, 'oldBackendOwnerRefused'); assert.equal(faux.etat().permis, 0);
});

test('§100 — les refus PID/SID/entry/version/UI/port bloquent le vrai envoi du permis', async () => {
  for (const changer of [
    n => { n.process.pid = 44676; }, n => { n.process.sameSid = false; },
    n => { n.process.sameSession = false; }, n => { n.process.createdUTC = new Date().toISOString(); },
    n => { n.process.commandLine += ' --port 9000'; },
    n => { n.source.sourceVersion = '1.0.5-beta.20261108.33'; }, n => { n.source.betaAbsent = false; },
    n => { n.applications[0].hasWindow = true; }, n => { n.listeners[0].pid = 12345; },
    n => { n.source.aclVerified = false; }, n => { n.source.reparseVerified = false; },
  ]) {
    const facts = faitsAncien(); changer(facts); const faux = fauxArretNatif({ facts });
    const r = await arreterAncienBackend(accordAncien(), { platform: 'win32', systeme: { SystemRoot: 'C:\\Windows' }, lancer: faux.lancer });
    assert.equal(r.status, 'refused'); assert.equal(r.targetStopped, false);
    assert.equal(faux.etat().permis, 0, 'le fils ne reçoit jamais la commande de terminaison');
  }
});

test('§100 — sonde bornée, environnement sans modules usager ni secrets et arrêt confirmé', async () => {
  const faux = fauxArretNatif();
  const r = await arreterAncienBackend(accordAncien(), { platform: 'win32',
    systeme: { SystemRoot: 'C:\\Windows', PSModulePath: 'C:\\privé\\Modules', TOKEN: 'canari-secret', HOME: 'C:\\privé' }, lancer: faux.lancer });
  assert.deepEqual(r, { requested: true, status: 'stopped', code: null, stage: null, property: null,
    basePythonAclWindowsAncestorVerified: false, basePythonAclWindowsAncestorWriterVerified: false,
    targetStopped: true, portFree: true, launcherExited: true });
  const { capture, permis, script } = faux.etat(); assert.equal(permis, 1);
  assert.equal(capture.options.shell, false);
  assert.equal(capture.options.env.PSModulePath, 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\Modules');
  assert.deepEqual(Object.keys(capture.options.env).sort(), ['SystemRoot', 'WINDIR', 'PATH', 'PSModulePath', 'OLD_PID', 'OLD_OBSERVED_UTC'].sort());
  assert(capture.args.includes('-NoProfile')); assert(capture.args.join(' ').length < 32767);
  assert(script.includes('$env:PSModulePath=Join-Path $PSHOME'));
  assert(!JSON.stringify(capture).includes('canari-secret'));
  assert(script.includes('TerminateProcess(handle,1)') && script.includes('CloseHandle(handle)'));
  assert(!/Stop-Process|taskkill|GetProcessById|\.Kill\(/.test(script.replace(/\/\/[^\n]*/g, '')));
  assert(!/local_api_key|succes\.db|vie\.db|project_root|Get-ChildItem/.test(script));
  assert(script.indexOf('$apres=Faits') < script.indexOf('$lease.StopChecked('));
});

test('§100 — changement final de port/identité, arrêt non confirmé ou lanceur restant restent des refus', async () => {
  for (const code of ['oldBackendFinalCheckChanged', 'oldBackendPortChanged', 'oldBackendStopUnconfirmed', 'oldBackendLauncherStillRunning']) {
    const faux = fauxArretNatif({ result: { stage: 'result', status: 'refused', code, targetStopped: code === 'oldBackendLauncherStillRunning', portFree: false, launcherExited: false } });
    const r = await arreterAncienBackend(accordAncien(), { platform: 'win32', systeme: { SystemRoot: 'C:\\Windows' }, lancer: faux.lancer });
    assert.equal(r.status, 'refused'); assert.equal(r.code, code); assert.equal(faux.etat().permis, 1);
  }
  const faux = fauxArretNatif({ result: { stage: 'result', status: 'stopped', targetStopped: true, portFree: false, launcherExited: true } });
  const r = await arreterAncienBackend(accordAncien(), { platform: 'win32', systeme: { SystemRoot: 'C:\\Windows' }, lancer: faux.lancer });
  assert.equal(r.status, 'refused'); assert.equal(r.code, 'oldBackendProtocolRefused');
});

test('§100 — timeout de sonde sans permis ni Kill de secours', async () => {
  const faux = fauxArretNatif({ silencieux: true }); let expirer, delai, annule = false;
  const attente = arreterAncienBackend(accordAncien(), { platform: 'win32', systeme: { SystemRoot: 'C:\\Windows' }, lancer: faux.lancer,
    minuter: (fn, ms) => { expirer = fn; delai = ms; return 1; }, demuter: () => { annule = true; } });
  expirer(); const r = await attente;
  assert.equal(delai, 40000); assert(annule); assert.equal(r.code, 'oldBackendTimeout'); assert.equal(faux.etat().permis, 0);
});

test('§100 — rapport fermé sans paths, commandes, SID, erreurs ni clé', () => {
  const canari = 'C:\\Users\\Privé\\cle-canari';
  const r = rapportArretAncien({ requested: 'true', status: canari, code: canari,
    path: canari, commandLine: canari, sid: 'S-1-5-21-secret', key: 'canari-secret', error: new Error(canari),
    targetStopped: 'true', portFree: 1, launcherExited: true });
  assert.deepEqual(Object.keys(r), ['requested', 'status', 'code', 'stage', 'property',
    'basePythonAclWindowsAncestorVerified', 'basePythonAclWindowsAncestorWriterVerified',
    'targetStopped', 'portFree', 'launcherExited']);
  assert.equal(r.status, 'refused'); assert.equal(r.code, null); assert.equal(r.targetStopped, false);
  assert(!/Privé|secret|canari|S-1-/.test(JSON.stringify(r)));
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

// Gel35 : tests de décision JS/protocole simulé et contrôles statiques du PS.
// Ni CIM, ni ACL Windows, ni API Win32 ne sont exécutés sur ce Mac.
const faitsSansMarqueur = () => {
  const n = faitsAncien(); delete n.source.managedMarker; n.source.markerState = 'absent'; return n;
};
const jouerMarqueur = async options => {
  const faux = fauxArretNatif(options);
  const r = await arreterAncienBackend(accordAncien(), { platform: 'win32', systeme: { SystemRoot: 'C:\\Windows' }, lancer: faux.lancer });
  return { r, ...faux.etat() };
};
const sourceBancMarqueur = () => fs.readFileSync(new URL('../../scripts/tester_installation_windows.mjs', import.meta.url), 'utf8');

test('gel35 — seul absent exact passe ; toute autre enum refuse sans permis', async () => {
  assert.equal(validerArretAncien(faitsSansMarqueur(), accordAncien()), true);
  const bon = await jouerMarqueur({ facts: faitsSansMarqueur() });
  assert.equal(bon.r.status, 'stopped'); assert.equal(bon.permis, 1);
  for (const etat of [undefined, null, false, true, 'ABSENT', 'absent\n', 'unreadable', 'genericManaged', 'versioned', 'present', {}]) {
    const n = faitsSansMarqueur(); n.source.managedMarker = 'managed';
    if (etat === undefined) delete n.source.markerState; else n.source.markerState = etat;
    assert.throws(() => validerArretAncien(n, accordAncien()), /oldBackendVersionRefused/);
    const refus = await jouerMarqueur({ facts: n });
    assert.equal(refus.r.code, 'oldBackendVersionRefused'); assert.equal(refus.permis, 0);
  }
});

test('gel35 — contrat PS statique : ItemNotFound seul, parents validés et noms de liens contrôlés', () => {
  const code = sourceBancMarqueur();
  const debut = code.indexOf('function Absent([string]$p) {'), fin = code.indexOf('function Processus(', debut);
  assert(debut > 0 && fin > debut);
  const absent = code.slice(debut, fin);
  assert(absent.includes('Get-Item -LiteralPath $p -Force -ErrorAction Stop'));
  assert.equal((absent.match(/catch/g) ?? []).length, 1, 'aucun catch général transformant une erreur en absence');
  const attraper = absent.indexOf('catch [System.Management.Automation.ItemNotFoundException]');
  assert(attraper > 0);
  const avant = absent.slice(0, attraper), apres = absent.slice(attraper);
  for (const bloc of [avant, apres]) {
    assert(bloc.includes('Possede $parent') && bloc.includes('ApplicationSure $parent'), 'parent possédé et ACL/reparse vérifiés');
  }
  assert(apres.includes('[IO.Directory]::EnumerateFileSystemEntries($parent,[IO.Path]::GetFileName($p))'), 'ne pas prendre un lien cassé présent pour une absence');
  assert(apres.indexOf('EnumerateFileSystemEntries') < apres.indexOf('return $true'));
  assert(apres.lastIndexOf('ApplicationSure $parent') < apres.indexOf('return $true'));
  const faits = code.slice(code.indexOf('function Faits {'), code.indexOf('$lease=New-Object -TypeName'));
  assert(faits.indexOf('Possede $racine') < faits.indexOf("Absent (Join-Path $racine '.diapason-backend')"));
  assert(faits.includes("if (-not (Absent (Join-Path $racine '.diapason-backend'))) { throw 'oldBackendVersionRefused' }"));
  assert(faits.includes("markerState='absent'"));
  assert(!/Petit[^\n]*\.diapason-backend|managedMarker/.test(faits), 'aucune lecture nulle ou ancien contenu traité comme absence');
});

test('gel35 — présences simulées managed/versionnée/vide/dossier/lien même cassé refusent', async () => {
  // La sonde PS refuse avant son attestation ; ces fixtures testent le vrai
  // parent JS, sans prétendre exercer Get-Item sur les objets Windows cités.
  for (const presence of ['fichier managed', 'fichier versionné', 'fichier vide', 'dossier', 'lien', 'lien cassé']) {
    const refus = await jouerMarqueur({ refusAvantAttestation: { stage: 'result', status: 'refused', code: 'oldBackendVersionRefused' } });
    assert.equal(refus.r.status, 'refused', presence); assert.equal(refus.r.targetStopped, false, presence);
    assert.equal(refus.permis, 0, presence);
  }
});

test('gel35 — erreurs natives simulées accès refusé et E/S ne deviennent jamais absent', async () => {
  for (const incident of ['accès refusé', 'erreur E/S']) {
    const refus = await jouerMarqueur({ refusAvantAttestation: { stage: 'result', status: 'refused', code: 'oldBackendNativeUnavailable',
      rawError: incident + ' C:\\Users\\Privé\\secret', markerState: 'absent' } });
    assert.equal(refus.r.status, 'refused'); assert.equal(refus.r.code, 'oldBackendNativeUnavailable');
    assert.equal(refus.permis, 0); assert.equal(refus.r.targetStopped, false);
    assert(!JSON.stringify(refus.r).includes('Privé'));
  }
});

test('gel35 — apparition simulée entre attestations refuse ; contrat finally libère le HANDLE', async () => {
  const refus = await jouerMarqueur({ facts: faitsSansMarqueur(), result: { stage: 'result', status: 'refused',
    code: 'oldBackendVersionRefused', targetStopped: false, portFree: false, launcherExited: false } });
  assert.equal(refus.permis, 1, 'le premier accord ne dispense pas de réattester');
  assert.equal(refus.r.status, 'refused'); assert.equal(refus.r.targetStopped, false);
  const code = refus.script;
  const avant = code.indexOf('$avant=Faits'), apres = code.indexOf('$apres=Faits');
  const comparer = code.indexOf("if ($apres -cne $avant) { throw 'oldBackendFinalCheckChanged' }");
  const absenceFinale = code.indexOf("if (-not (Absent (Join-Path $racine '.diapason-backend'))) { throw 'oldBackendVersionRefused' }", apres);
  const terminer = code.indexOf('$stopped=$lease.StopChecked(');
  assert(avant > 0 && apres > avant && comparer > apres && absenceFinale > comparer && terminer > absenceFinale);
  assert(code.includes('} finally { if ($lease) { $lease.Dispose() } }'), 'libération statiquement contrôlée, pas un test Win32');
});

// Gel36 : projection fermée et protocole réel du parent avec réponses natives
// factices. Les ACL/étapes PowerShell restent contrôlées statiquement sur Mac.
const etapesGel36 = ['initialization', 'processHandle', 'processIdentity', 'rootOwnership', 'markerAbsence',
  'projectMetadata', 'venvMetadata', 'basePythonAcl', 'entryFiles', 'betaAbsence', 'gitAbsence',
  'attestation', 'finalCheck', 'stopConfirmation'];
const proprietesGel36 = ['outsideProfile', 'invalidPath', 'reparse', 'itemOwnerNotAllowed', 'ancestorOwnerNotAllowed',
  'itemWriteNotAllowed', 'ancestorWriteNotAllowed', 'inspectionFailed'];

test('gel36 — enums strictes sans chemin, SID, propriétaire, metadata ni erreur brute', () => {
  const canari = 'C:\\Users\\Privé\\metadata-secret';
  const base = { requested: true, status: 'refused', code: 'oldBackendSourceRefused',
    refusalStage: 'basePythonAcl', refusalProperty: 'ancestorOwnerNotAllowed',
    sid: 'S-1-5-21-personne', owner: 'nom-personnel', metadata: canari, commandLine: canari,
    exception: canari, rawError: canari, path: canari };
  const r = rapportArretAncien(base);
  assert.equal(r.stage, 'basePythonAcl'); assert.equal(r.property, 'ancestorOwnerNotAllowed');
  assert.deepEqual(rapportArretAncien(r), r, 'projection réapplicable au seul rapport fermé');
  assert(!/Privé|secret|S-1-|personnel|metadata|exception|commandLine/.test(JSON.stringify(r)));
  for (const etape of [undefined, null, true, false, {}, 'BASEPYTHONACL', 'basePythonAcl\n', canari]) {
    const inconnu = rapportArretAncien({ ...base, refusalStage: etape });
    assert.equal(inconnu.stage, null); assert.equal(inconnu.property, null);
  }
  for (const propriete of [undefined, null, true, {}, 'ancestorOwnerNotAllowed\n', canari]) {
    const inconnu = rapportArretAncien({ ...base, refusalProperty: propriete });
    assert.equal(inconnu.stage, 'basePythonAcl'); assert.equal(inconnu.property, null);
  }
  for (const property of proprietesGel36) {
    assert.equal(rapportArretAncien({ ...base, refusalProperty: property }).property, property);
  }
});

test('gel36 — le refus natif propage seulement étape/propriété fermées, sans permis', async () => {
  for (const refusalStage of etapesGel36) {
    const refus = await jouerMarqueur({ refusAvantAttestation: { stage: 'result', status: 'refused',
      code: 'oldBackendSourceRefused', refusalStage, refusalProperty: 'ancestorOwnerNotAllowed',
      path: 'C:\\Users\\Privé', sid: 'S-1-5-21-canari', rawError: 'canari-secret' } });
    assert.equal(refus.r.code, 'oldBackendSourceRefused'); assert.equal(refus.r.stage, refusalStage);
    assert.equal(refus.r.property, 'ancestorOwnerNotAllowed'); assert.equal(refus.permis, 0);
    assert.equal(refus.r.targetStopped, false);
    assert(!/Privé|canari/.test(JSON.stringify(refus.r)));
  }
  const inconnu = await jouerMarqueur({ refusAvantAttestation: { stage: 'result', status: 'refused',
    code: 'oldBackendSourceRefused', refusalStage: 'C:\\Usager', refusalProperty: 'S-1-5-21-canari' } });
  assert.equal(inconnu.r.stage, null); assert.equal(inconnu.r.property, null); assert.equal(inconnu.permis, 0);
});

test('gel36 — attestation JS et refus final restent fermés et ne deviennent pas des succès', async () => {
  const facts = faitsSansMarqueur(); facts.process.sameSid = false;
  const attestation = await jouerMarqueur({ facts });
  assert.equal(attestation.r.code, 'oldBackendOwnerRefused'); assert.equal(attestation.r.stage, 'attestation');
  assert.equal(attestation.r.property, null); assert.equal(attestation.permis, 0);
  const final = await jouerMarqueur({ facts: faitsSansMarqueur(), result: { stage: 'result', status: 'refused',
    code: 'oldBackendSourceRefused', refusalStage: 'basePythonAcl', refusalProperty: 'ancestorWriteNotAllowed' } });
  assert.equal(final.permis, 1); assert.equal(final.r.status, 'refused'); assert.equal(final.r.targetStopped, false);
  assert.equal(final.r.stage, 'basePythonAcl'); assert.equal(final.r.property, 'ancestorWriteNotAllowed');
});

test('gel36 — défaut sans arrêt et champs diagnostiques incapables d’autoriser une action', async () => {
  let lances = 0;
  const r = await arreterAncienBackend(null, { platform: 'win32', lancer: () => lances++ });
  assert.equal(lances, 0); assert.equal(r.status, 'notRequested'); assert.equal(r.stage, null); assert.equal(r.property, null);
  assert.equal(autorisationArretAncien({ refusalStage: 'finalCheck', refusalProperty: 'inspectionFailed' }), null);
  assert.throws(() => autorisationArretAncien({ 'residual-pid': '48196', refusalStage: 'finalCheck' }), /personalProcessStopNotAuthorized/);
  const ferme = rapportArretAncien({ requested: false, status: 'refused', refusalStage: 'basePythonAcl', refusalProperty: 'reparse' });
  assert.equal(ferme.stage, null); assert.equal(ferme.property, null);
  const succes = rapportArretAncien({ requested: true, status: 'stopped', refusalStage: 'finalCheck', refusalProperty: 'inspectionFailed' });
  assert.equal(succes.stage, null); assert.equal(succes.property, null);
});

test('gel36 — contrat PS statique : étapes et masques/SID historiques identiques, aucun propriétaire publié', () => {
  const code = sourceBancMarqueur();
  const faits = code.slice(code.indexOf('function Faits {'), code.indexOf('$lease=New-Object -TypeName'));
  assert(faits.indexOf("Point 'rootOwnership'") < faits.indexOf('Possede $racine'));
  assert(faits.indexOf("Point 'projectMetadata'") < faits.indexOf('$projet=Petit'));
  assert(faits.indexOf("Point 'venvMetadata'") < faits.indexOf('$cfg=Petit'));
  const acl = code.slice(code.indexOf('function AclBaseSure('), code.indexOf('function Absent('));
  assert(acl.includes("Point 'basePythonAcl'"));
  assert(acl.includes("$fiables=@($sid,'S-1-5-32-544','S-1-5-18')"));
  assert(acl.includes('$masque=if ($premier) { 852310 } else { 852304 }'));
  assert(acl.includes("if ($premier) { $script:refusalProperty='itemOwnerNotAllowed'; return $false }"));
  assert(acl.includes("if (-not $owner.Equals($service)) { $script:refusalProperty='ancestorOwnerNotAllowed'; return $false }"));
  const natif = code.slice(code.indexOf("  $etapePub=if ("), code.indexOf('`;\n\n// 08/11/2026'));
  assert(natif.includes('refusalStage=$etapePub; refusalProperty=$proprietePub;'));
  assert(!/owner=|path=|sid=|metadata=|Exception\s*=|rawError=|CommandLine=/.test(natif));
  for (const etape of etapesGel36) assert(natif.includes("'" + etape + "'"));
  for (const property of proprietesGel36) assert(natif.includes("'" + property + "'"));
  assert(natif.includes('} finally { if ($lease) { $lease.Dispose() } }'));
});

// Gel37 : matrice de la règle PS extraite comme logique booléenne pure,
// protocole simulé et contrôles statiques ; aucune résolution Windows exécutée.
const ownerWindows = 'basePythonAclWindowsAncestorVerified';
const writerWindows = 'basePythonAclWindowsAncestorWriterVerified';
const faitsRoleWindows = (owner = false, writer = false) => {
  const n = faitsSansMarqueur(); n.source[ownerWindows] = owner; n.source[writerWindows] = writer; return n;
};

test('gel37 — la vraie expression PS writer exige ancêtre ET owner service ET writer même service', () => {
  const code = sourceBancMarqueur();
  const debut = code.indexOf('function RegleServiceAncetre('), fin = code.indexOf('function AclBaseSure(', debut);
  assert(debut > 0 && fin > debut);
  const expression = /return \(([^\n]+)\)/.exec(code.slice(debut, fin))?.[1]; assert(expression);
  const residu = expression.replace(/\$premier|\$ownerService|\$writerService|-not|-and|\s|\(|\)/g, '');
  assert.equal(residu, '', 'seul le sous-ensemble booléen extrait est évalué, aucun script natif');
  const js = expression.replace(/\$(premier|ownerService|writerService)/g, '$1').replace(/-not/g, '!').replace(/-and/g, '&&');
  const regle = new Function('premier', 'ownerService', 'writerService', `return (${js});`);
  for (const premier of [false, true]) for (const owner of [false, true]) for (const writer of [false, true]) {
    assert.equal(regle(premier, owner, writer), !premier && owner && writer,
      `fichier=${premier}, ownerService=${owner}, writerService=${writer}`);
  }
});

test('gel37 — résolution Windows exacte, namespace service et aucun élargissement du fichier Python', () => {
  const code = sourceBancMarqueur();
  const acl = code.slice(code.indexOf('function AclBaseSure('), code.indexOf('function Absent('));
  const rejetFichier = acl.indexOf("if ($premier) { $script:refusalProperty='itemOwnerNotAllowed'; return $false }");
  const resolution = acl.indexOf("[Security.Principal.NTAccount]::new('NT SERVICE','TrustedInstaller')");
  assert(rejetFichier > 0 && resolution > rejetFichier, 'le fichier est refusé avant toute exception de rôle');
  assert(acl.includes('$compte.Translate([Security.Principal.SecurityIdentifier])'));
  assert(acl.includes("$service.Value -cnotmatch '^S-1-5-80-(?:[0-9]+-){4}[0-9]+$'"));
  assert(acl.includes("catch { $script:refusalProperty='windowsAncestorLookupFailed'; return $false }"));
  assert(acl.includes('if (-not $owner.Equals($service))'));
  assert(acl.includes('RegleServiceAncetre $premier $ownerService ($r.IdentityReference.Equals($service))'));
  assert(acl.includes("$fiables=@($sid,'S-1-5-32-544','S-1-5-18')"));
  assert(acl.includes('$masque=if ($premier) { 852310 } else { 852304 }'));
  assert(acl.includes('$r.IdentityReference.Value -notin $fiables'));
  assert(!/Set-Acl|takeown|icacls|\.Contains\(|-like|S-1-5-80-\d/.test(acl), 'pas de mutation, SID deviné ou nom fuzzy');
});

test('gel37 — preuves de faits strictement booléennes et writer impossible sans owner', async () => {
  for (const champ of [ownerWindows, writerWindows]) for (const valeur of [undefined, null, 'true', 'false', 0, 1, {}]) {
    const n = faitsRoleWindows();
    if (valeur === undefined) delete n.source[champ]; else n.source[champ] = valeur;
    const r = await jouerMarqueur({ facts: n });
    assert.equal(r.permis, 0); assert.equal(r.r.code, 'oldBackendSourceRefused');
  }
  const impossible = await jouerMarqueur({ facts: faitsRoleWindows(false, true) });
  assert.equal(impossible.permis, 0); assert.equal(impossible.r.code, 'oldBackendSourceRefused');
});

test('gel37 — résultat fermé exige preuves cohérentes avec les premiers faits', async () => {
  for (const [owner, writer] of [[false, false], [true, false], [true, true]]) {
    const r = await jouerMarqueur({ facts: faitsRoleWindows(owner, writer) });
    assert.equal(r.r.status, 'stopped'); assert.equal(r.r[ownerWindows], owner); assert.equal(r.r[writerWindows], writer);
    assert.deepEqual(rapportArretAncien(r.r), r.r, 'preuve publique réappliquée sans contenu natif');
  }
  const base = { stage: 'result', status: 'stopped', targetStopped: true, portFree: true, launcherExited: true,
    [ownerWindows]: true, [writerWindows]: true };
  for (const champ of [ownerWindows, writerWindows]) for (const valeur of [undefined, null, 'true', false]) {
    const result = { ...base };
    if (valeur === undefined) delete result[champ]; else result[champ] = valeur;
    const r = await jouerMarqueur({ facts: faitsRoleWindows(true, true), result });
    assert.equal(r.permis, 1); assert.equal(r.r.status, 'refused'); assert.equal(r.r.code, 'oldBackendProtocolRefused');
    assert.equal(r.r[ownerWindows], false); assert.equal(r.r[writerWindows], false);
  }
});

test('gel37 — défaut, lookup échoué et refus ne présument jamais le rôle rencontré', async () => {
  const defaut = await arreterAncienBackend(null, { lancer: () => { throw new Error('aucun enfant attendu'); } });
  assert.equal(defaut[ownerWindows], false); assert.equal(defaut[writerWindows], false);
  const refus = await jouerMarqueur({ refusAvantAttestation: { stage: 'result', status: 'refused',
    code: 'oldBackendSourceRefused', refusalStage: 'basePythonAcl', refusalProperty: 'windowsAncestorLookupFailed',
    [ownerWindows]: true, [writerWindows]: true, owner: 'S-1-5-80-canari', path: 'C:\\Users\\Privé', rawError: 'secret' } });
  assert.equal(refus.permis, 0); assert.equal(refus.r.property, 'windowsAncestorLookupFailed');
  assert.equal(refus.r[ownerWindows], false); assert.equal(refus.r[writerWindows], false);
  assert(!/Privé|S-1-|secret/.test(JSON.stringify(refus.r)));
  for (const etat of [{ requested: false, status: 'stopped' }, { requested: true, status: 'refused' }]) {
    const r = rapportArretAncien({ ...etat, targetStopped: true, portFree: true, launcherExited: true, [ownerWindows]: true, [writerWindows]: true });
    assert.equal(r[ownerWindows], false); assert.equal(r[writerWindows], false);
  }
});

test('gel37 — contrat natif statique : deux lectures fraîches cohérentes avant terminaison', () => {
  const code = sourceBancMarqueur();
  const acl = code.slice(code.indexOf('function AclBaseSure('), code.indexOf('function Absent('));
  assert(acl.includes('$service=$null; $ownerRencontre=$false; $writerRencontre=$false'), 'cache limité à une seule lecture');
  assert(acl.indexOf('$script:basePythonAclWindowsAncestorVerified=$false') < acl.indexOf('try {'));
  assert(acl.indexOf('$script:basePythonAclWindowsAncestorVerified=$ownerRencontre') > acl.indexOf('$premier=$false;'));
  const faits = code.slice(code.indexOf('function Faits {'), code.indexOf("Point 'processHandle'"));
  assert(faits.includes(ownerWindows + '=[bool]$script:' + ownerWindows));
  assert(faits.includes(writerWindows + '=[bool]$script:' + writerWindows));
  const premiere = code.indexOf('$avant=Faits'), seconde = code.indexOf('$apres=Faits');
  const capture = code.indexOf('$windowsAncestorAvant=$script:'), egalite = code.indexOf('$script:' + ownerWindows + ' -cne $windowsAncestorAvant');
  const arret = code.indexOf('$stopped=$lease.StopChecked(');
  assert(premiere > 0 && capture > premiere && seconde > capture && egalite > seconde && arret > egalite);
  assert(code.includes("if ($apres -cne $avant) { throw 'oldBackendFinalCheckChanged' }"));
  assert(code.includes(ownerWindows + '=$windowsAncestorAvant; ' + writerWindows + '=$windowsWriterAvant'));
  assert(code.includes('} finally { if ($lease) { $lease.Dispose() } }'));
});
