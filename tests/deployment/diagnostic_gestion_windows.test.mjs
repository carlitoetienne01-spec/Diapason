import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import { createHash } from 'node:crypto';
import {
  ORIGINE, SONDES, DELAI_HTTP_MS, urlAutorisee, signatureSante,
  proprietaireAttribuable, nettoyerRapport, creerSondeHttp, collecterNatif, diagnostiquer,
  versionPublique, homeVenv, entreeBackendVerifiee, attribuerInventaire,
} from '../../scripts/diagnostiquer_gestion_windows.mjs';

const CLE = 'diapason_sk_' + 'S'.repeat(43);
const PRIVE = 'C:\\Users\\Personne-privee\\secret';
const natif = () => ({
  installations: [{ productVersion: '1.0.5-beta.20261108.31', fileVersion: '1.0.5.0', running: true }],
  listener: { pid: 1200, sameSid: true, knownEntryPoint: true, processKind: 'python', commandLine: PRIVE },
  backend: { version: '1.0.5-beta.20261108.31', metadataOwned: true, crudExemption: 'patternPresent' },
  private: { identity: '638981234567890000', keyPath: PRIVE, keyOwned: true },
});
const sante = { status: 200, outcome: 'http', signature: 'compatible', authenticated: false };

// Forme confirmée de l'ancien runner, chemins transposés : le redirecteur venv
// donne un PID Python de base hors profil et conserve l'entrée console du venv.
// Ce n'est pas une capture CIM exécutée sur ce Mac.
const redirecteur = () => {
  const root = 'C:\\Users\\Windows Beta\\AppData\\Local\\Diapason\\src';
  const base = 'C:\\hostedtoolcache\\windows\\Python\\3.13.9\\x64';
  const executablePath = base + '\\python.exe';
  return {
    installations: [], private: { identity: '638981234567890000', keyOwned: true, keyPath: PRIVE },
    listener: { pid: 1200, sameSid: true, processKind: 'python', executablePath,
      commandLine: `"${root}\\.venv\\Scripts\\python.exe" "${root}\\.venv\\Scripts\\diapason.exe" serve --port 8000` },
    candidates: [{ root, metadataOwned: true, cfgOwned: true, cfg: `home = ${base}\r\ninclude-system-site-packages = false\r\n`,
      resolvedHome: base, baseVerified: true, entryOwned: true, venvPythonOwned: true, betaOwned: true,
      publicVersions: { betaVersion: null, snapshotBetaVersion: '1.0.5-beta.20261108.31' }, crudExemption: 'patternPresent' }],
  };
};

test('§5 — la version publique vient du manifeste, jamais du marqueur managed', () => {
  assert.equal(versionPublique({ betaVersion: '1.0.5-beta.20261108.31' }), '1.0.5-beta.20261108.31');
  assert.equal(versionPublique({ snapshotBetaVersion: '1.0.5-beta.20261108.31' }), '1.0.5-beta.20261108.31');
  assert.equal(versionPublique({ betaVersion: 'managed' }), null);
  assert.equal(versionPublique({}), null);
  assert.equal(versionPublique({ betaVersion: '1.0.5-beta.20261108.31', snapshotBetaVersion: '1.0.5-beta.20261107.30' }), null);
  assert.equal(versionPublique({ betaVersion: PRIVE + CLE }), null);
  const r = nettoyerRapport(attribuerInventaire(redirecteur()));
  assert.equal(r.backend.version, '1.0.5-beta.20261108.31');
  assert(!JSON.stringify(r).includes(PRIVE));
});

test('§5 — le Python de base hors profil est attesté par le cfg et l’entrée venv exacte', async () => {
  const brut = redirecteur(), n = attribuerInventaire(brut);
  assert(proprietaireAttribuable(n), 'le redirecteur Windows légitime doit être attribué');
  const readKey = mock.fn(async () => CLE), attestNative = mock.fn(async () => true);
  const probe = mock.fn(async o => {
    if (o.url.endsWith('/health')) return sante;
    assert.equal(await o.attestSocket(19001), true);
    return { status: 200, outcome: 'http', authenticated: true };
  });
  const r = await diagnostiquer({ platform: 'win32', collectNative: async () => n, readKey, attestNative, probe });
  assert.equal(readKey.mock.callCount(), 1); assert.equal(attestNative.mock.callCount(), 4);
  assert.equal(r.listener.ownership, 'diapason'); assert.equal(r.credential, 'used');
  assert(!JSON.stringify(r).includes('hostedtoolcache')); assert(!JSON.stringify(r).includes('Windows Beta'));
});

test('§5 — SID, identité, cfg ou executable ambigus refusent la clé', async () => {
  const mutations = [
    n => { n.listener.sameSid = false; },
    n => { n.private.identity = ''; },
    n => { n.listener.pid = 0; },
    n => { n.listener.executablePath = 'C:\\autre\\python.exe'; },
    n => { n.candidates[0].metadataOwned = false; },
    n => { n.candidates[0].cfgOwned = false; },
    n => { n.candidates[0].baseVerified = false; },
    n => { n.candidates[0].cfg += 'home = C:\\autre\r\n'; },
    n => { n.candidates[0].resolvedHome = 'C:\\autre'; },
    n => { n.candidates.push(structuredClone(n.candidates[0])); },
    n => { n.candidates[0].entryOwned = false; },
  ];
  for (const modifier of mutations) {
    const brut = redirecteur(); modifier(brut); const n = attribuerInventaire(brut);
    assert(!proprietaireAttribuable(n));
    const readKey = mock.fn();
    await diagnostiquer({ platform: 'win32', collectNative: async () => n, readKey, probe: async () => sante });
    assert.equal(readKey.mock.callCount(), 0, 'aucune clé ne doit être lue après une attribution refusée');
  }
});

test('§5 — contenir diapason ou même son chemin dans du code ne suffit pas', () => {
  for (const commande of [
    n => `"${n.listener.executablePath}" -c "print('${n.candidates[0].root}\\.venv\\Scripts\\diapason.exe')" serve`,
    n => `"${n.listener.executablePath}" "${n.candidates[0].root}\\.venv\\Scripts\\diapason.exe.autre" serve`,
    n => `"${n.listener.executablePath}" "${n.candidates[0].root}\\autre\\diapason.exe" serve`,
    n => `"${n.listener.executablePath}" "${n.candidates[0].root}\\.venv\\Scripts\\diapason.exe" observer serve`,
    n => `"${n.listener.executablePath}" -m autre.diapason serve`,
    n => `"${n.listener.executablePath}" -m diapason serve`,
  ]) {
    const n = redirecteur(); n.listener.commandLine = commande(n);
    assert(!proprietaireAttribuable(attribuerInventaire(n)));
  }
});

test('§5 — le redirecteur accepte argv0 venv conservé, sans confondre le Python global', () => {
  const n = redirecteur(), c = n.candidates[0];
  n.listener.commandLine = `"${n.listener.executablePath}" "${c.root}\\.venv\\Scripts\\diapason.exe" serve`;
  assert(proprietaireAttribuable(attribuerInventaire(n)), 'la console exacte reste attribuée avec argv0 de base');
  n.listener.commandLine = `"${c.root}\\.venv\\Scripts\\python.exe" -I -B -m diapason serve`;
  assert(proprietaireAttribuable(attribuerInventaire(n)));
  c.venvPythonOwned = false;
  assert(!proprietaireAttribuable(attribuerInventaire(n)));
});

test('§5 — le cfg borné refuse UNC, traversée et home répété ; seul l’alias uv vérifié est admis', () => {
  for (const texte of ['', 'home = \\\\serveur\\python', 'home = C:\\base\\..\\autre',
    'home = C:\\base\nhome = C:\\base', 'home = C:\\base\n' + 'x'.repeat(8192)]) assert.equal(homeVenv(texte), null);
  const n = redirecteur(), c = n.candidates[0];
  const parent = 'C:\\ProgramData\\uv\\python';
  c.cfg = `home = ${parent}\\cpython-3.13-windows-x86_64-none`;
  c.resolvedHome = parent + '\\cpython-3.13.9-windows-x86_64-none';
  n.listener.executablePath = c.resolvedHome + '\\python.exe';
  n.listener.commandLine = `"${n.listener.executablePath}" "${c.root}\\.venv\\Scripts\\diapason.exe" serve`;
  assert(proprietaireAttribuable(attribuerInventaire(n)));
  c.resolvedHome = 'C:\\autre\\cpython-3.13.9-windows-x86_64-none';
  assert(!proprietaireAttribuable(attribuerInventaire(n)));
});

test('§5 — Python venv, module et script beta gardent une entrée complète vérifiée', () => {
  for (const mode of ['console', 'module', 'beta']) {
    const n = redirecteur(), c = n.candidates[0];
    n.listener.executablePath = c.root + '\\.venv\\Scripts\\python.exe';
    const suite = mode === 'console' ? `"${c.root}\\.venv\\Scripts\\diapason.exe" serve`
      : mode === 'module' ? '-I -B -u -m diapason serve' : `"${c.root}\\deploy\\windows\\beta_backend.py"`;
    n.listener.commandLine = `"${n.listener.executablePath}" ${suite}`;
    assert(entreeBackendVerifiee({ ...n.listener, identity: n.private.identity }, c));
    c.venvPythonOwned = false;
    assert(!proprietaireAttribuable(attribuerInventaire(n)));
  }
});

test('§5 — spawn PowerShell reçoit seulement les modules système et aucune variable usager', async () => {
  const anciens = { SystemRoot: process.env.SystemRoot, PSModulePath: process.env.PSModulePath, TOKEN: process.env.TOKEN };
  process.env.SystemRoot = 'C:\\Windows'; process.env.PSModulePath = PRIVE + '\\Modules'; process.env.TOKEN = CLE;
  let code;
  const lancer = mock.fn((_exe, argv) => {
    assert(Buffer.from(argv.at(-1), 'base64').toString('utf16le').includes('FromBase64String'));
    const enfant = new EventEmitter(); enfant.stdin = new EventEmitter(); enfant.stdout = new EventEmitter(); enfant.stderr = new EventEmitter();
    enfant.stdin.destroy = mock.fn(); enfant.stdout.destroy = mock.fn(); enfant.stderr.destroy = mock.fn(); enfant.unref = mock.fn();
    enfant.stdin.end = payload => {
      code = Buffer.from(payload, 'base64').toString('utf16le');
      queueMicrotask(() => { enfant.stdout.emit('data', Buffer.from(JSON.stringify(redirecteur()))); enfant.emit('close', 0); });
    };
    return enfant;
  });
  try {
    const n = await collecterNatif({ platform: 'win32', lancer });
    assert(proprietaireAttribuable(n)); assert.equal(n.backend.version, '1.0.5-beta.20261108.31');
    const [exe, argv, options] = lancer.mock.calls[0].arguments;
    assert.equal(exe, 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe');
    assert(argv.includes('-NoProfile')); assert.equal(options.shell, false);
    assert([exe, ...argv].map(a => `"${a}"`).join(' ').length < 32767,
      'la commande encodée doit tenir dans CreateProcessW, avec marge de guillemets');
    assert.equal(options.env.PSModulePath, 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\Modules');
    assert(!JSON.stringify(options.env).includes(PRIVE)); assert(!JSON.stringify(options.env).includes(CLE));
    assert.deepEqual(Object.keys(options.env).sort(), ['DIAG_MODE', 'PATH', 'PSModulePath', 'SystemRoot', 'WINDIR'].sort());
    assert.deepEqual(options.stdio, ['pipe', 'pipe', 'pipe']);
    assert(code.startsWith("\n$env:PSModulePath=Join-Path $PSHOME 'Modules'"));
    assert(code.includes("Petit (Join-Path $racine 'beta-build.json') 1048576"));
    assert(code.includes('snapshotBetaVersion=$meta.snapshot.betaVersion'));
    assert(!code.includes('.diapason-backend')); assert(!code.includes('Possede $p.ExecutablePath'));
  } finally {
    for (const [nom, ancien] of Object.entries(anciens)) {
      if (ancien === undefined) delete process.env[nom]; else process.env[nom] = ancien;
    }
  }
});

function transport({ status = 200, body = '{}', remote = '127.0.0.1', silence = false,
  timeout = false, manualTimeout = false } = {}) {
  const prise = new EventEmitter(); prise.remoteAddress = remote; prise.remotePort = 8000; prise.localPort = 19001;
  prise.destroy = mock.fn();
  const reponse = new EventEmitter(); reponse.statusCode = status;
  reponse.headers = { location: 'https://exterieur.example/' + CLE };
  reponse.destroy = mock.fn();
  const requete = new EventEmitter(); requete.destroy = mock.fn();
  requete.end = mock.fn(() => queueMicrotask(() => {
    callback(reponse);
    if (reponse.listenerCount('data')) {
      reponse.emit('data', Buffer.from(body)); reponse.emit('end');
    }
  }));
  let callback;
  const connecter = mock.fn(() => { if (!silence) queueMicrotask(() => prise.emit('connect')); return prise; });
  const demander = mock.fn((_options, cb) => { callback = cb; return requete; });
  const options = { connecter, demander };
  let expirer;
  if (timeout) { options.minuter = f => { queueMicrotask(f); return 1; }; options.demuter = () => {}; }
  if (manualTimeout) { options.minuter = f => { expirer = f; return 1; }; options.demuter = () => {}; }
  return { probe: creerSondeHttp(options), connecter, demander, prise, reponse, expire: () => expirer() };
}

test('§78 — importer et refuser une plateforme non Windows ne lance aucune sonde native', async () => {
  const lancer = mock.fn();
  await assert.rejects(collecterNatif({ platform: 'linux', lancer }), /unsupportedPlatform/);
  assert.equal(lancer.mock.callCount(), 0);
  const collectNative = mock.fn(), probe = mock.fn(), readKey = mock.fn();
  const r = await diagnostiquer({ platform: 'darwin', collectNative, probe, readKey });
  assert.equal(r.platform, 'unsupported'); assert.equal(r.status, 'refused');
  for (const f of [collectNative, probe, readKey]) assert.equal(f.mock.callCount(), 0);
});

test('§5 — seules les URL canoniques des deux familles de routes sont admises', () => {
  for (const p of ['/health', ...Object.values(SONDES)]) assert(urlAutorisee(ORIGINE + p));
  for (const u of ['https://127.0.0.1:8000/health', 'http://localhost:8000/health',
    'http://[::1]:8000/health', 'http://127.0.0.1:8001/health', 'http://127.0.0.1:8000.evil/health',
    'http://2130706433:8000/health', 'http://127.0.0.1:8000/health?secret=' + CLE,
    'http://127.0.0.1:8000/health#secret', 'http://secret@127.0.0.1:8000/health',
    'http://127.0.0.1:8000/api/v1/vie/notes', 'http://exterieur.example/health']) {
    assert.equal(urlAutorisee(u), false);
  }
  assert(DELAI_HTTP_MS < 8000);
});

test('§100 — un nom Diapason seul ne suffit pas à attribuer le listener', () => {
  assert(proprietaireAttribuable(natif()));
  for (const patch of [{ sameSid: false }, { knownEntryPoint: false }, { pid: -1 }, { processKind: 'other' }]) {
    const n = natif(); Object.assign(n.listener, patch); assert(!proprietaireAttribuable(n));
  }
  const n = natif(); n.backend.metadataOwned = false; assert(!proprietaireAttribuable(n));
});

test('§5 — propriétaire inconnu : santé sans clé, aucune lecture de clé ni donnée métier', async () => {
  const n = natif(); n.listener.sameSid = false;
  const readKey = mock.fn(() => CLE), attestNative = mock.fn(), probe = mock.fn(async () => sante);
  const r = await diagnostiquer({ platform: 'win32', collectNative: async () => n, readKey, attestNative, probe });
  assert.equal(r.credential, 'refused'); assert.equal(r.listener.ownership, 'unknown');
  assert.equal(readKey.mock.callCount(), 0); assert.equal(attestNative.mock.callCount(), 0);
  assert.equal(probe.mock.callCount(), 1); assert.deepEqual(probe.mock.calls[0].arguments, [{ url: ORIGINE + '/health' }]);
});

test('§100 — les quatre GET finaux rendent uniquement les statuts, même en 429', async () => {
  const attestNative = mock.fn(async () => true);
  const probe = mock.fn(async o => {
    if (o.url.endsWith('/health')) return sante;
    assert.equal(o.key, CLE); assert.equal(await o.attestSocket(19001), true);
    return { status: o.url.endsWith('/config') ? 429 : 200, outcome: 'http', authenticated: true,
      body: { notes: PRIVE, finances: CLE }, error: PRIVE };
  });
  const r = await diagnostiquer({ platform: 'win32', collectNative: async () => natif(), readKey: async () => CLE, attestNative, probe });
  assert.equal(probe.mock.callCount(), 5); assert.equal(attestNative.mock.callCount(), 4);
  assert.deepEqual(probe.mock.calls.map(c => c.arguments[0].url),
    ['/health', ...Object.values(SONDES)].map(p => ORIGINE + p));
  assert.equal(r.probes.config.status, 429); assert.equal(r.credential, 'used');
  assert.equal(r.status, 'completed'); assert.equal(r.installations[0].productVersion, '1.0.5-beta.20261108.31');
  assert(!JSON.stringify(r).includes(CLE)); assert(!JSON.stringify(r).includes(PRIVE));
});

test('§5 — serveur du même usager non attribué : quatre statuts sans jamais lire de clé', async () => {
  const n = natif(); n.listener.knownEntryPoint = false;
  const readKey = mock.fn(() => CLE);
  const probe = mock.fn(async o => {
    if (o.url.endsWith('/health')) return sante;
    assert.equal(o.key, ''); assert.equal(o.attestSocket, undefined);
    return { status: o.url.endsWith('/config') ? 401 : 429, outcome: 'http', authenticated: false, body: CLE + PRIVE };
  });
  const r = await diagnostiquer({ platform: 'win32', collectNative: async () => n, readKey, probe });
  assert.equal(r.status, 'partial'); assert.equal(r.credential, 'refused');
  assert.equal(readKey.mock.callCount(), 0); assert.equal(probe.mock.callCount(), 5);
  assert.equal(r.probes.notes.status, 429); assert.equal(r.probes.config.status, 401);
  assert(!JSON.stringify(r).includes(CLE)); assert(!JSON.stringify(r).includes(PRIVE));
});

test('§100 — le profil historique reste cinq GET canoniques sans corps conservé', async () => {
  const urls = [];
  const probe = async o => {
    urls.push(o.url); assert(urlAutorisee(o.url));
    if (o.url.endsWith('/health')) return sante;
    assert(!o.url.includes('/v1/vie/'));
    assert.equal(await o.attestSocket(19001), true);
    return { status: 200, outcome: 'http', authenticated: true };
  };
  const r = await diagnostiquer({ platform: 'win32', legacy: true, collectNative: async () => natif(),
    readKey: async () => CLE, attestNative: async () => true, probe });
  assert.equal(r.routeFamily, 'succes'); assert.equal(urls.length, 5);
  assert(urls.includes(ORIGINE + '/v1/succes/notes/resumes'));
  assert(urls.includes(ORIGINE + '/v1/succes/finances/overview'));
  assert.equal(r.status, 'completed');
});

test('§5 — changement de PID/SID sur la connexion : aucun Bearer envoyé', async () => {
  const t = transport(); const attestSocket = mock.fn(async () => false);
  const r = await t.probe({ url: ORIGINE + SONDES.projects, key: CLE, attestSocket });
  assert.equal(r.outcome, 'ownerChanged'); assert.equal(r.authenticated, false);
  assert.equal(t.demander.mock.callCount(), 0); assert.equal(attestSocket.mock.callCount(), 1);
});

test('§5 — une clé sans attestation ne peut jamais devenir un en-tête', async () => {
  const t = transport();
  const r = await t.probe({ url: ORIGINE + SONDES.notes, key: CLE });
  assert.equal(r.outcome, 'ownerChanged'); assert.equal(t.demander.mock.callCount(), 0);
});

test('§5 — HTTP direct GET, socket déjà attestée, clé hors URL et corps métier ignoré', async () => {
  const t = transport({ body: CLE + PRIVE });
  const r = await t.probe({ url: ORIGINE + SONDES.finances, key: CLE, attestSocket: async () => true });
  const options = t.demander.mock.calls[0].arguments[0];
  assert.equal(options.method, 'GET'); assert.equal(options.hostname, '127.0.0.1'); assert.equal(options.port, 8000);
  assert.equal(options.agent.createConnection(), t.prise); assert.equal(options.headers.Authorization, `Bearer ${CLE}`);
  assert.equal(options.path, SONDES.finances); assert.equal(t.reponse.listenerCount('data'), 0);
  assert.equal(r.status, 200); assert.equal(r.authenticated, true); assert(!JSON.stringify(r).includes(CLE));
});

test('§5 — une redirection ne déclenche ni seconde requête ni lecture du corps', async () => {
  const t = transport({ status: 302, body: CLE });
  const r = await t.probe({ url: ORIGINE + '/health' });
  assert.equal(r.outcome, 'redirectRefused'); assert.equal(t.demander.mock.callCount(), 1);
  assert.equal(t.reponse.listenerCount('data'), 0); assert(!JSON.stringify(r).includes(CLE));
  const readKey = mock.fn(() => CLE);
  await diagnostiquer({ platform: 'win32', collectNative: async () => natif(), readKey, probe: async () => r });
  assert.equal(readKey.mock.callCount(), 0);
});

test('§78 — expiration absolue avant attestation : connexion abandonnée sans requête', async () => {
  const t = transport({ silence: true, timeout: true });
  const r = await t.probe({ url: ORIGINE + '/health', timeoutMs: 7000 });
  assert.equal(r.outcome, 'timeout'); assert.equal(t.demander.mock.callCount(), 0);
  assert.equal(t.prise.destroy.mock.callCount(), 1);
});

test('§78 — une attestation arrivée après le timeout ne peut envoyer une clé', async () => {
  const t = transport({ manualTimeout: true }); let confirmer;
  const attente = t.probe({ url: ORIGINE + SONDES.notes, key: CLE,
    attestSocket: () => new Promise(resolve => { confirmer = resolve; }) });
  await new Promise(resolve => queueMicrotask(resolve));
  t.expire(); confirmer(true);
  assert.equal((await attente).outcome, 'timeout');
  await new Promise(resolve => queueMicrotask(resolve));
  assert.equal(t.demander.mock.callCount(), 0);
});

test('§5 — même avec un proxy hérité, le transport reçoit seulement la socket IPv4 littérale', async () => {
  const ancien = process.env.HTTP_PROXY;
  process.env.HTTP_PROXY = 'http://exterieur.example:8080';
  try {
    const t = transport(); await t.probe({ url: ORIGINE + '/health' });
    assert.deepEqual(t.connecter.mock.calls[0].arguments, [{ host: '127.0.0.1', port: 8000, family: 4 }]);
    assert.equal(t.demander.mock.calls[0].arguments[0].agent.createConnection(), t.prise);
  } finally {
    if (ancien === undefined) delete process.env.HTTP_PROXY; else process.env.HTTP_PROXY = ancien;
  }
});

test('§5 — cible invalide ou mauvaise socket : rien ne sort vers un autre hôte', async () => {
  const t = transport();
  assert.equal((await t.probe({ url: 'http://exterieur.example/health', key: CLE })).outcome, 'invalidTarget');
  assert.equal(t.connecter.mock.callCount(), 0);
  const autre = transport({ remote: '192.0.2.1' });
  assert.equal((await autre.probe({ url: ORIGINE + '/health' })).outcome, 'invalidTarget');
  assert.equal(autre.demander.mock.callCount(), 0);
});

test('§5 — santé bornée, signature par valeurs connues et jamais par texte brut', async () => {
  assert.equal(signatureSante('{"status":"ok","mode":"windows-beta-gestion","secret":"' + CLE + '"}'), 'windowsBetaGestion');
  assert.equal(signatureSante('{"detail":"Engine unhealthy"}'), 'engineUnhealthy');
  assert.equal(signatureSante(CLE + PRIVE), 'unrecognized');
  const t = transport({ body: 'x'.repeat(2049) + CLE });
  const r = await t.probe({ url: ORIGINE + '/health' });
  assert.equal(r.outcome, 'bodyTooLarge'); assert(!JSON.stringify(r).includes(CLE));
});

test('§5 — projection fermée et bornée : ni secrets, SID, chemins, cmdline, SQL ou environnement', () => {
  const mal = { ...natif(), platform: 'win32', status: 'completed', codes: [CLE, PRIVE, 'ownerChanged'],
    installations: Array.from({ length: 100 }, () => ({ productVersion: PRIVE, fileVersion: CLE, running: true, path: PRIVE })),
    secret: CLE, sql: 'SELECT notes', sid: 'S-1-5-21-secret', env: { TOKEN: CLE }, commandLine: PRIVE,
    health: { status: PRIVE, outcome: CLE, body: CLE, signature: PRIVE },
    probes: { notes: { status: 200, outcome: 'http', body: PRIVE, image: CLE } } };
  const r = nettoyerRapport(mal), texte = JSON.stringify(r);
  for (const interdit of [CLE, PRIVE, 'S-1-5-21-secret', 'SELECT notes', 'commandLine', 'TOKEN', 'image']) assert(!texte.includes(interdit));
  assert.equal(r.installations.length, 4); assert.equal(r.installations[0].productVersion, null);
  assert(texte.length < 8192); assert.deepEqual(Object.keys(r.probes), Object.keys(SONDES));
  assert.deepEqual(nettoyerRapport(r), r, 'une seconde projection avant écriture ne perd aucune preuve');
});

test('§5 — une fausse clé ou une erreur de lecture ne sont jamais transmises ou publiées', async () => {
  for (const lue of [PRIVE + CLE, CLE + '\nsecret', '', null]) {
    const probe = mock.fn(async o => o.url.endsWith('/health') ? sante
      : (assert.equal(o.key, ''), { status: 401, outcome: 'http', authenticated: false }));
    const r = await diagnostiquer({ platform: 'win32', collectNative: async () => natif(), readKey: async () => lue, probe });
    assert.equal(r.credential, 'unavailable'); assert.equal(probe.mock.callCount(), 5);
    assert(!JSON.stringify(r).includes(PRIVE)); assert(!JSON.stringify(r).includes(CLE));
  }
});

test('§5 — exceptions natives/réseau brutes remplacées par des codes fermés', async () => {
  const mauvais = async () => { throw new Error(PRIVE + ' Bearer ' + CLE); };
  const r = await diagnostiquer({ platform: 'win32', collectNative: mauvais, probe: mauvais, readKey: mauvais });
  assert(r.codes.includes('nativeUnavailable')); assert(r.codes.includes('ownerNotAttributed'));
  assert(!JSON.stringify(r).includes(CLE)); assert(!JSON.stringify(r).includes(PRIVE));
});

test('§5 — un échec PowerShell garde seulement son étape et sa ligne statique', async () => {
  const ancien = process.env.SystemRoot; process.env.SystemRoot = 'C:\\Windows';
  const lancer = (_exe, argv) => {
    assert(Buffer.from(argv.at(-1), 'base64').toString('utf16le').includes('ReadToEnd'));
    const enfant = new EventEmitter(); enfant.stdin = new EventEmitter(); enfant.stdout = new EventEmitter(); enfant.stderr = new EventEmitter();
    enfant.stdin.destroy = mock.fn(); enfant.stdout.destroy = mock.fn(); enfant.stderr.destroy = mock.fn(); enfant.unref = mock.fn();
    enfant.stdin.end = payload => queueMicrotask(() => {
      const code = Buffer.from(payload, 'base64').toString('utf16le');
      const ligne = code.split('\n').findIndex(l => l.startsWith('$apps=@(')) + 1;
      assert(ligne > 0); assert(code.includes('} catch {'));
      enfant.stderr.emit('data', Buffer.from(PRIVE + CLE));
      enfant.stdout.emit('data', Buffer.from(JSON.stringify({ diagnosticFailure: true,
        stage: 'applications', line: ligne, message: PRIVE + CLE })));
      enfant.emit('close', 0);
    });
    return enfant;
  };
  try {
    const r = await diagnostiquer({ platform: 'win32',
      collectNative: () => collecterNatif({ platform: 'win32', lancer }), probe: async () => sante });
    assert.deepEqual(r.native, { outcome: 'commandFailed', stage: 'applications', line: r.native.line });
    assert(r.native.line > 0); assert(r.codes.includes('nativeUnavailable'));
    assert(!JSON.stringify(r).includes(CLE)); assert(!JSON.stringify(r).includes(PRIVE));
    assert.deepEqual(nettoyerRapport(r), r);
  } finally {
    if (ancien === undefined) delete process.env.SystemRoot; else process.env.SystemRoot = ancien;
  }
});

test('§5 — le diagnostic natif refuse une étape ou une ligne reçue en texte privé', () => {
  const r = nettoyerRapport({ native: { outcome: CLE, stage: PRIVE, line: 1001, secret: CLE },
    attribution: { processKind: PRIVE, candidateStages: [CLE], projectFiles: [{ ownerClass: PRIVE, exists: true, path: CLE }] } });
  assert.deepEqual(r.native, { outcome: 'invalidOutput', stage: null, line: null });
  assert.deepEqual(r.attribution.projectFiles, [{ ownerClass: 'unknown', exists: true, withinLimit: false }]);
  assert(!JSON.stringify(r).includes(CLE)); assert(!JSON.stringify(r).includes(PRIVE));
});

test('§100 — la perte d’attribution arrête les GET suivants', async () => {
  const probe = mock.fn(async o => o.url.endsWith('/health') ? sante
    : { status: null, outcome: 'ownerChanged', authenticated: false });
  const r = await diagnostiquer({ platform: 'win32', collectNative: async () => natif(), readKey: async () => CLE, probe });
  assert.equal(probe.mock.callCount(), 2); assert(r.codes.includes('ownerChanged'));
  assert.equal(r.probes.finances.outcome, 'notRequested');
});

const workflow = new URL('../../.github/workflows/diagnostic-gestion-windows.yml', import.meta.url);
test('§5 — le workflow ne reçoit que deux fichiers épinglés et ne publie que rapport.json',
  { skip: fs.existsSync(workflow) ? false : 'Le banc distant ne reçoit que les deux fichiers épinglés.' }, () => {
  const yml = fs.readFileSync(new URL('../../.github/workflows/diagnostic-gestion-windows.yml', import.meta.url), 'utf8');
  for (const [variable, nom] of [['DIAGNOSTIC_SCRIPT_SHA256', '../../scripts/diagnostiquer_gestion_windows.mjs'],
    ['DIAGNOSTIC_TEST_SHA256', './diagnostic_gestion_windows.test.mjs']]) {
    const attendu = createHash('sha256').update(fs.readFileSync(new URL(nom, import.meta.url))).digest('hex');
    assert(yml.includes(`${variable}: ${attendu}`));
  }
  assert(yml.includes('workflow_dispatch:')); assert(yml.includes('contents: read'));
  assert(yml.includes("node-version: '22'")); assert(yml.includes('DIAGNOSTIC_COMMIT: ${{ github.sha }}'));
  assert(yml.includes('/rapport.json')); assert(!/actions\/checkout|workflow_call|schedule:|contents: write/.test(yml));
  assert(!/taskkill|Stop-Process|diapason serve|uv sync|install-desktop|npm install|uninstall\.exe/.test(yml));
});
