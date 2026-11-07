import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  CONTROLES, ciblePubliee, argumentsNsis, environnementApplication,
  rapportValide, urlCdpValide, origineApplication, verifierNarration,
} from '../../scripts/tester_installation_windows.mjs';

const version = '1.0.5-beta.20261107.22';
const sha = '227b5dd1b66f305f16d42a5664df38eca88192f306a339e12afcef0a06266242';

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

test('le premier démarrage ne réutilise ni clés, ni checkout, ni modèles du runner', () => {
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
  const r = { installerExecuted: true, failureCode: null,
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
