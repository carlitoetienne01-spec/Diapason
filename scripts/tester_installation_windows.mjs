/** Premier lancement du véritable installateur publié, sans amorçage simulé. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const CONTROLES = Object.freeze([
  'preflightPassed', 'installerHashVerified', 'installerExecuted',
  'installedExecutablePresent', 'versionMatches', 'firstLaunchReady',
  'newManagedBackendPrepared', 'twoTurnUiConversation',
  'notePersistedAfterRestart', 'narrationWithWordTimings',
  'updateButtonVisible', 'updateCatalogueMatches',
  'uninstallSucceeded', 'registryRestored', 'processesStopped',
]);
const DEPOT = 'https://github.com/carlitoetienne01-spec/Diapason/releases/download/';

export function ciblePubliee(version, sha256) {
  assert.match(version, /^\d+\.\d+\.\d+-beta\.\d{8}\.\d+$/);
  assert.match(sha256, /^[a-f0-9]{64}$/);
  const nom = `Diapason_${version}_x64-setup.exe`;
  return { version, sha256, nom, url: `${DEPOT}beta-windows-v${version}/${nom}` };
}

export function argumentsNsis(dossier) {
  // 07/11/2026 : /D doit être le dernier argument et rester sans guillemets.
  // Pas de shell : même un espace dans le chemin ne devient pas du code.
  assert.match(dossier, /^[A-Za-z]:\\/);
  assert(!/["\r\n]/.test(dossier));
  return ['/S', '/NS', `/D=${dossier}`];
}

export function environnementApplication(systeme, profil, port) {
  assert(Number.isInteger(port) && port > 1024 && port < 65536);
  const w = path.win32;
  const env = {};
  for (const cle of ['SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SystemDrive',
    'SYSTEMDRIVE', 'PATHEXT', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE',
    'PROCESSOR_IDENTIFIER', 'USERNAME', 'USERDOMAIN']) {
    if (systeme[cle]) env[cle] = systeme[cle];
  }
  const windows = systeme.SystemRoot || systeme.SYSTEMROOT || systeme.WINDIR;
  assert(windows, 'SystemRoot requis');
  env.PATH = [w.join(windows, 'System32'), windows,
    w.join(windows, 'System32', 'Wbem'),
    w.join(windows, 'System32', 'WindowsPowerShell', 'v1.0')].join(';');
  env.HOME = profil;
  env.USERPROFILE = profil;
  env.APPDATA = w.join(profil, 'AppData', 'Roaming');
  env.LOCALAPPDATA = w.join(profil, 'AppData', 'Local');
  env.TEMP = w.join(profil, 'Temp');
  env.TMP = env.TEMP;
  env.WEBVIEW2_USER_DATA_FOLDER = w.join(profil, 'WebView2');
  env.UV_CACHE_DIR = w.join(profil, 'CacheUv');
  env.UV_PYTHON_INSTALL_DIR = w.join(profil, 'Python');
  env.OLLAMA_MODELS = w.join(profil, 'OllamaModels');
  env.HF_HOME = w.join(profil, 'HuggingFace');
  env.WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS =
    `--remote-debugging-address=127.0.0.1 --remote-debugging-port=${port}`;
  // Aucun code source, modèle, clé d'API, profil Diapason ou outil du runner
  // n'entre dans PATH. Le vrai amorçage doit les installer lui-même.
  return env;
}

export function rapportValide(rapport) {
  return rapport.installerExecuted === true
    && CONTROLES.every(c => rapport.checks[c] === true)
    && rapport.failureCode === null && !rapport.cleanupFailed;
}

export function urlCdpValide(texte, port) {
  try {
    const u = new URL(texte);
    return u.protocol === 'ws:' && u.hostname === '127.0.0.1'
      && u.port === String(port) && !u.username && !u.password
      && /^\/devtools\/page\/[\w-]+$/.test(u.pathname);
  } catch { return false; }
}

export function origineApplication(texte) {
  try {
    const u = new URL(texte);
    return (u.protocol === 'tauri:' && u.hostname === 'localhost')
      || (['http:', 'https:'].includes(u.protocol) && u.hostname === 'tauri.localhost');
  } catch { return false; }
}

export function verifierNarration(corps) {
  assert.equal(corps.mimeType, 'audio/wav');
  assert.equal(corps.sampleRate, 24000);
  assert.equal(corps.timingStatus, 'aligned');
  assert(Array.isArray(corps.words) && corps.words.length >= 5);
  const wav = Buffer.from(corps.dataBase64, 'base64');
  assert.equal(wav.toString('ascii', 0, 4), 'RIFF');
  assert.equal(wav.toString('ascii', 8, 12), 'WAVE');
  let donnees; let format;
  for (let i = 12; i + 8 <= wav.length;) {
    const taille = wav.readUInt32LE(i + 4);
    assert(i + 8 + taille <= wav.length);
    if (wav.toString('ascii', i, i + 4) === 'fmt ') format = wav.subarray(i + 8, i + 8 + taille);
    if (wav.toString('ascii', i, i + 4) === 'data') donnees = wav.subarray(i + 8, i + 8 + taille);
    i += 8 + taille + (taille % 2);
  }
  assert(format && format.length >= 16);
  assert.equal(format.readUInt16LE(0), 1, 'PCM requis');
  assert.equal(format.readUInt16LE(2), 1, 'Mono requis');
  assert.equal(format.readUInt32LE(4), 24000);
  assert.equal(format.readUInt16LE(14), 16, 'PCM 16 bits requis');
  assert(donnees && donnees.length >= 24000);
  assert(donnees.some(o => o !== 0), 'Le son ne doit pas être silencieux');
  const duree = donnees.length / 48000;
  let fin = 0;
  for (const mot of corps.words) {
    assert(Number.isFinite(mot.start) && Number.isFinite(mot.end));
    assert(mot.start >= fin - 0.02 && mot.end > mot.start && mot.end <= duree + 0.15);
    fin = mot.end;
  }
  return { durationSeconds: duree, wordCount: corps.words.length,
    sha256: createHash('sha256').update(wav).digest('hex'), wav };
}

function verifier(ok, code) { if (!ok) throw new Error(code); }
const pause = ms => new Promise(r => setTimeout(r, ms));
async function attendre(action, delai, code, intervalle = 1000) {
  const limite = Date.now() + delai;
  while (Date.now() < limite) {
    const valeur = await action();
    if (valeur) return valeur;
    await pause(intervalle);
  }
  throw new Error(code);
}

async function executer(exe, args, options = {}) {
  const { timeoutMs = 600000, ...autres } = options;
  const enfant = spawn(exe, args, { windowsHide: true, shell: false, ...autres });
  let stdout = '';
  let stderr = '';
  enfant.stdout?.on('data', b => { stdout = (stdout + b).slice(-32768); });
  enfant.stderr?.on('data', b => { stderr = (stderr + b).slice(-32768); });
  const code = await new Promise((resolve, reject) => {
    const delai = setTimeout(() => {
      const kill = spawn(path.join(process.env.SystemRoot, 'System32', 'taskkill.exe'),
        ['/PID', String(enfant.pid), '/T', '/F'], { shell: false, windowsHide: true, stdio: 'ignore' });
      kill.once('error', () => {});
      reject(new Error('childProcessTimeout'));
    }, timeoutMs);
    enfant.once('error', e => { clearTimeout(delai); reject(e); });
    enfant.once('exit', code => { clearTimeout(delai); resolve(code); });
  });
  return { code, stdout, stderr };
}

async function powershell(programme, env = process.env) {
  const exe = path.win32.join(process.env.SystemRoot || process.env.SYSTEMROOT,
    'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  const r = await executer(exe, ['-NoProfile', '-NonInteractive', '-EncodedCommand',
    Buffer.from(`$ErrorActionPreference='Stop'\n${programme}`, 'utf16le').toString('base64')], { env });
  verifier(r.code === 0, 'windowsPreflightOrMetadataFailed');
  return JSON.parse(r.stdout.replace(/^\uFEFF/, '').trim());
}

const SONDE_REGISTRE = String.raw`
# Une ancienne MSI porte une clé GUID, pas une clé nommée Diapason.
# NSIS pourrait la désinstaller : lire aussi les DisplayName, sans les publier.
$present = 0
foreach ($ruche in @([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryHive]::LocalMachine)) {
  foreach ($vue in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($ruche, $vue)
    try {
      $uninstall = $base.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall')
      if ($uninstall) {
        try {
          foreach ($nom in $uninstall.GetSubKeyNames()) {
            $cle = $uninstall.OpenSubKey($nom)
            try {
              if ($cle -and ($nom -ieq 'Diapason' -or ([string]$cle.GetValue('DisplayName')) -match '^Diapason(?:\s|$)')) { $present++ }
            } finally { if ($cle) { $cle.Dispose() } }
          }
        } finally { $uninstall.Dispose() }
      }
      $protocole = $base.OpenSubKey('Software\Classes\diapason')
      if ($protocole) { $present++; $protocole.Dispose() }
      if ($ruche -eq [Microsoft.Win32.RegistryHive]::CurrentUser) {
        $software = $base.OpenSubKey('Software')
        if ($software) {
          try {
            foreach ($societe in $software.GetSubKeyNames()) {
              $editeur = $software.OpenSubKey($societe)
              try { if ($editeur -and $editeur.GetSubKeyNames() -icontains 'Diapason') { $present++ } }
              finally { if ($editeur) { $editeur.Dispose() } }
            }
          } finally { $software.Dispose() }
        }
      }
    } finally { $base.Dispose() }
  }
}
@{ existingKeys=$present } | ConvertTo-Json -Compress
`;

class Cdp {
  constructor(ws) {
    this.ws = ws; this.compteur = 0; this.attentes = new Map();
    ws.addEventListener('message', e => {
      const m = JSON.parse(String(e.data));
      if (!m.id) return;
      const attente = this.attentes.get(m.id);
      if (!attente) return;
      clearTimeout(attente.minuteur); this.attentes.delete(m.id);
      if (m.error) attente.reject(new Error('cdpCommandFailed'));
      else attente.resolve(m.result);
    });
    ws.addEventListener('close', () => {
      for (const a of this.attentes.values()) {
        clearTimeout(a.minuteur); a.reject(new Error('cdpClosed'));
      }
      this.attentes.clear();
    });
  }
  static async connecter(url) {
    const ws = new WebSocket(url);
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true });
      ws.addEventListener('error', () => reject(new Error('cdpConnectionFailed')), { once: true });
    });
    return new Cdp(ws);
  }
  appel(method, params = {}, delai = 30000) {
    const id = ++this.compteur;
    return new Promise((resolve, reject) => {
      const minuteur = setTimeout(() => {
        this.attentes.delete(id); reject(new Error('cdpCommandTimeout'));
      }, delai);
      this.attentes.set(id, { resolve, reject, minuteur });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluer(expression) {
    const r = await this.appel('Runtime.evaluate', { expression,
      awaitPromise: true, returnByValue: true });
    verifier(!r.exceptionDetails, 'applicationEvaluationFailed');
    return r.result?.value;
  }
  async invoquer(nom) {
    return this.evaluer(`window.__TAURI_INTERNALS__.invoke(${JSON.stringify(nom)})`);
  }
  fermer() { this.ws.close(); }
}

async function portLibre() {
  const serveur = net.createServer();
  await new Promise((resolve, reject) => {
    serveur.once('error', reject); serveur.listen(0, '127.0.0.1', resolve);
  });
  const port = serveur.address().port;
  await new Promise(r => serveur.close(r));
  return port;
}

async function portOccupe(port) {
  return new Promise(resolve => {
    const socket = net.connect({ host: '127.0.0.1', port });
    const terminer = valeur => { socket.destroy(); resolve(valeur); };
    socket.once('connect', () => terminer(true));
    socket.once('error', () => terminer(false));
    socket.setTimeout(1000, () => terminer(true));
  });
}

async function connecterApplication(port, appPid, profilWebview) {
  const cible = await attendre(async () => {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(2000) });
      const pages = await r.json();
      return pages.find(p => p.type === 'page' && origineApplication(p.url)
        && urlCdpValide(p.webSocketDebuggerUrl, port));
    } catch { return false; }
  }, 90000, 'webviewNotReachable');
  // Ne jamais remettre le jeton local à un autre navigateur déjà sur le port.
  const origine = await powershell(String.raw`
$port = [int]$env:DIAPASON_E2E_PORT
$racine = [int]$env:DIAPASON_E2E_PID
$connexions = @(Get-NetTCPConnection -State Listen -LocalPort $port)
$valide = $false
$profilValide = $false
foreach ($c in $connexions) {
  if ($c.LocalAddress -ne '127.0.0.1') { continue }
  $courant = [int]$c.OwningProcess
  $navigateur = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $courant)
  $chemin = [regex]::Escape($env:DIAPASON_E2E_WEBVIEW)
  $motif = '--user-data-dir=(?:"' + $chemin + '"|' + $chemin + '(?=\s|$))'
  if ($navigateur.CommandLine -match $motif) { $profilValide = $true }
  for ($i=0; $i -lt 12 -and $courant -gt 0; $i++) {
    if ($courant -eq $racine) { $valide=$true; break }
    $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $courant)
    if (-not $p) { break }
    $courant = [int]$p.ParentProcessId
  }
}
@{ owned=$valide; privateProfile=$profilValide } | ConvertTo-Json -Compress
`, { ...process.env, DIAPASON_E2E_PORT: String(port), DIAPASON_E2E_PID: String(appPid),
    DIAPASON_E2E_WEBVIEW: profilWebview });
  verifier(origine.owned === true, 'debugPortNotOwnedByTestApp');
  verifier(origine.privateProfile === true, 'webviewProfileNotIsolated');
  return Cdp.connecter(cible.webSocketDebuggerUrl);
}

async function capture(cdp, fichier) {
  const image = await cdp.appel('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(fichier, Buffer.from(image.data, 'base64'));
}

async function dialogue(cdp, question, attendu) {
  await attendre(async () => {
    const cible = await cdp.evaluer(`(() => {
    function visible(e, kind) {
      if (!e || e.disabled) return null;
      const r = e.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return null;
      const x = r.x + r.width / 2, y = r.y + r.height / 2;
      if (!e.contains(document.elementFromPoint(x, y))) return null;
      return { x, y, kind };
    }
    const champ = document.querySelector('textarea.composer-glass-input');
    const saisie = visible(champ, 'composer');
    if (saisie) return saisie;
    const plusTard = [...document.querySelectorAll('button')].find(b =>
      ['Plus tard — tout reste sur cet appareil', 'Later — everything stays on this device'].includes(b.innerText.trim()));
    const accueil = visible(plusTard, 'localOnboarding');
    if (accueil) return accueil;
    const bouton = [...document.querySelectorAll('nav[aria-label] button')]
      .find(b => ['Discussion','Chat'].includes(b.getAttribute('aria-label')));
    return visible(bouton, 'navigation');
  })()`);
    if (!cible) return false;
    await cdp.appel('Input.dispatchMouseEvent', { type: 'mousePressed', x: cible.x, y: cible.y,
      button: 'left', clickCount: 1 });
    await cdp.appel('Input.dispatchMouseEvent', { type: 'mouseReleased', x: cible.x, y: cible.y,
      button: 'left', clickCount: 1 });
    return cible.kind === 'composer';
  }, 45000, 'composerNotReady');
  const nombre = await cdp.evaluer(`document.querySelectorAll('[data-message-id].mb-6').length`);
  await cdp.appel('Input.insertText', { text: question });
  await cdp.appel('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  await cdp.appel('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  let dernier = ''; let stable = 0;
  return attendre(async () => {
    const r = await cdp.evaluer(`(() => {
      const messages = [...document.querySelectorAll('[data-message-id].mb-6')];
      return { count: messages.length, text: messages.at(-1)?.innerText || '',
        generating: !!document.querySelector('button[aria-label="Stop generating"],button[aria-label="Arrêter la génération"]') };
    })()`);
    if (r.count <= nombre || r.generating || !r.text.trim()) return false;
    stable = r.text === dernier ? stable + 1 : 0; dernier = r.text;
    if (stable < 2) return false;
    verifier(attendu.test(r.text), 'conversationAnswerIncorrect');
    return { complete: true, expectedResultFound: true };
  }, 300000, 'conversationIncomplete');
}

export async function premierLancement(options) {
  verifier(process.platform === 'win32', 'windowsRequired');
  const cible = ciblePubliee(options.version, options.sha256);
  const travail = path.resolve(options.workdir);
  verifier(!fs.existsSync(travail), 'workdirAlreadyExists');
  fs.mkdirSync(travail, { recursive: false });
  const sortie = path.join(travail, 'rapport'); fs.mkdirSync(sortie);
  const rapport = { schemaVersion: 1, kind: 'publishedInstallerFirstLaunch',
    version: cible.version, installerSha256: cible.sha256, installerExecuted: false,
    status: 'running', passed: false, failureCode: null,
    personalDocumentsOpened: false, microphoneActivated: false,
    checks: Object.fromEntries(CONTROLES.map(c => [c, false])) };
  const noter = phase => {
    console.log(JSON.stringify({ phase }));
    fs.writeFileSync(path.join(sortie, 'resultat.json'), JSON.stringify(rapport, null, 2));
  };
  let enfant; let cdp; let installe = false;
  let envApp; let exe; let port;
  async function verifierAucuneApp() {
    const actif = await powershell(String.raw`
@{ count=@(Get-Process -Name 'diapason-desktop','Diapason' -ErrorAction SilentlyContinue).Count } | ConvertTo-Json -Compress
`);
    verifier(actif.count === 0, 'applicationRunningBeforeUninstall');
  }
  async function arreter() {
    if (!enfant && !cdp) return;
    if (cdp) {
      try { await cdp.invoquer('stop_backend'); } catch { /* récolte par PID ensuite */ }
      cdp.fermer(); cdp = null;
    }
    if (enfant && enfant.exitCode === null) {
      await executer(path.join(process.env.SystemRoot, 'System32', 'taskkill.exe'),
        ['/PID', String(enfant.pid), '/T', '/F']);
    }
    enfant = null;
    await attendre(async () => !(await portOccupe(8000)) && !(await portOccupe(11434)),
      30000, 'testProcessesNotStopped');
  }
  async function lancer() {
    const debut = Date.now();
    port = await portLibre();
    envApp = environnementApplication(process.env, path.join(travail, 'profil'), port);
    for (const cle of ['HOME', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'WEBVIEW2_USER_DATA_FOLDER']) {
      fs.mkdirSync(envApp[cle], { recursive: true });
    }
    const log = fs.openSync(path.join(travail, 'application-prive.log'), 'a');
    enfant = spawn(exe, [], { cwd: path.dirname(exe), env: envApp, shell: false,
      stdio: ['ignore', log, log], windowsHide: false });
    enfant.once('error', () => {});
    fs.closeSync(log);
    cdp = await connecterApplication(port, enfant.pid, envApp.WEBVIEW2_USER_DATA_FOLDER);
    verifier(await cdp.invoquer('plugin:app|version') === cible.version, 'installedVersionMismatch');
    rapport.checks.versionMatches = true;
    let phase = '';
    await attendre(async () => {
      verifier(enfant.exitCode === null, 'appExitedDuringStartup');
      const etat = await cdp.invoquer('get_setup_status');
      if (etat.phase !== phase) {
        phase = etat.phase; noter(/^[a-z_]+$/.test(phase) ? `startup:${phase}` : 'startup');
      }
      if (etat.error) {
        // Uniquement le profil neuf, sans conserver de clé ou d'environnement.
        rapport.startupError = String(etat.error).replace(/[A-Za-z]:[\\/][^\s"']+/g, '<qa-path>')
          .replace(/Bearer\s+\S+/gi, 'Bearer <redacted>').slice(0, 1500);
        throw new Error('firstLaunchStartupError');
      }
      return etat.backend_ready && etat.ollama_ready && etat.model_ready && etat.server_ready;
    }, options.startupTimeoutMs || 7200000, 'firstLaunchTimeout', 2000);
    rapport.startupDurationsSeconds ??= [];
    rapport.startupDurationsSeconds.push(Math.round((Date.now() - debut) / 1000));
    return cdp;
  }
  try {
    noter('preflight');
    const bureau = await powershell(String.raw`
$apps = @(Get-Process -Name 'diapason-desktop','Diapason' -ErrorAction SilentlyContinue | ForEach-Object {
  $chemin = [string]$_.Path
  if (-not $chemin) { $chemin = [string](Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_.Id)).ExecutablePath }
  $temporaire = [regex]::Match($chemin, '[\\/]diapason-beta-(\d+)-(\d+)[\\/]', 'IgnoreCase')
  @{ processId=$_.Id; temporaryRunId=$(if ($temporaire.Success) {$temporaire.Groups[1].Value} else {$null});
     sessionId=$_.SessionId; hasWindow=($_.MainWindowHandle -ne 0); pathReadable=($chemin.Length -gt 0);
     processName=$_.ProcessName;
     runnerTemporaryPath=($chemin.StartsWith($env:RUNNER_TEMP + '\', [StringComparison]::OrdinalIgnoreCase)) }
})
@{ sessionId=[Diagnostics.Process]::GetCurrentProcess().SessionId;
   interactive=[Environment]::UserInteractive;
   appRunning=($apps.Count -gt 0); existingApplications=$apps;
   windowsSandboxAvailable=(Test-Path -LiteralPath (Join-Path $env:SystemRoot 'System32\WindowsSandbox.exe'))
} | ConvertTo-Json -Compress
`);
    rapport.preflight = bureau;
    rapport.preflight.existingInstallationKeys = (await powershell(SONDE_REGISTRE)).existingKeys;
    verifier(bureau.sessionId > 0 && bureau.interactive, 'interactiveRunnerRequired');
    verifier(!bureau.appRunning, 'preexistingAppRunning');
    verifier(!(await portOccupe(8000)) && !(await portOccupe(11434)), 'preexistingServerPort');
    noter('downloadInstaller');
    const r = await fetch(cible.url, { signal: AbortSignal.timeout(300000) });
    verifier(r.ok, 'installerDownloadFailed');
    const octets = Buffer.from(await r.arrayBuffer());
    verifier(createHash('sha256').update(octets).digest('hex') === cible.sha256, 'installerHashMismatch');
    verifier(octets.toString('ascii', 0, 2) === 'MZ', 'installerNotExecutable');
    const installateur = path.join(travail, cible.nom); fs.writeFileSync(installateur, octets);
    rapport.checks.installerHashVerified = true;
    const avant = await powershell(SONDE_REGISTRE);
    verifier(avant.existingKeys === 0, 'preexistingInstallationOrProtocol');
    rapport.checks.preflightPassed = true;
    const dossierApp = path.join(travail, 'application');
    exe = path.join(dossierApp, 'diapason-desktop.exe');
    installe = true;
    noter('installingPublishedExe');
    const installation = await executer(installateur, argumentsNsis(dossierApp),
      { windowsVerbatimArguments: true, cwd: travail });
    rapport.installerExecuted = true; rapport.installerExitCode = installation.code;
    verifier(installation.code === 0, 'installerFailed');
    rapport.checks.installerExecuted = true;
    verifier(fs.existsSync(exe) && fs.existsSync(path.join(dossierApp, 'uninstall.exe')), 'installedFilesMissing');
    rapport.checks.installedExecutablePresent = true;
    verifier(!fs.existsSync(path.join(travail, 'profil')), 'firstLaunchProfileNotEmpty');
    noter('firstLaunch'); await lancer(); rapport.checks.firstLaunchReady = true;
    const gere = path.join(envApp.LOCALAPPDATA, 'Diapason');
    const marqueurs = [path.join(gere, 'src', '.diapason-backend'), path.join(gere, '.diapason-backend')];
    verifier(marqueurs.some(p => fs.existsSync(p) && fs.readFileSync(p, 'utf8').trim() === cible.version),
      'downloadedBackendMarkerMissing');
    rapport.checks.newManagedBackendPrepared = true;
    await capture(cdp, path.join(sortie, '01-premier-demarrage.png'));
    const base = await cdp.invoquer('get_api_base');
    verifier(base === 'http://127.0.0.1:8000', 'unexpectedApiOrigin');
    let cle = await cdp.invoquer('get_local_api_key'); verifier(!!cle, 'localAuthenticationMissing');
    const api = async (chemin, methode = 'GET', corps) => {
      const res = await fetch(base + chemin, { method: methode,
        headers: { Authorization: `Bearer ${cle}`, ...(corps ? { 'Content-Type': 'application/json' } : {}) },
        ...(corps ? { body: JSON.stringify(corps) } : {}), signal: AbortSignal.timeout(600000) });
      verifier(res.ok, `apiFailed:${methode}:${chemin.replace(/[a-f0-9-]{20,}/gi, '<id>')}:${res.status}`);
      return res.json();
    };
    noter('twoTurnConversation');
    await dialogue(cdp, 'Combien font 12 plus 25 ? Réponds en une phrase.', /37|trente[ -]sept/i);
    await dialogue(cdp, 'Ajoute un au résultat précédent. Réponds en une phrase.', /38|trente[ -]huit/i);
    rapport.checks.twoTurnUiConversation = true;
    await capture(cdp, path.join(sortie, '02-discussion-reelle.png'));
    noter('saveSyntheticNote');
    const projet = (await api('/v1/vie/projects', 'POST', { name: 'Essai installation Windows' })).project;
    const contenu = 'Note créée dans le profil d’essai. Trente-sept pages sont prêtes.';
    const note = (await api('/v1/vie/notes', 'POST', {
      title: 'Note de contrôle', content: contenu, projectId: projet.id,
    })).note;
    verifier(note.content === contenu, 'noteSaveFailed');
    noter('narrationAndWordTimings');
    const parole = await api('/v1/speech/narrate', 'POST', {
      text: 'Bonjour, nous avons lu 37 pages. Tout va bien.', format: 'json', language: 'fr', wordTimings: true,
    });
    rapport.narrationDiagnostic = { timingStatus: parole.timingStatus,
      wordCount: Array.isArray(parole.words) ? parole.words.length : 0 };
    const son = verifierNarration(parole);
    fs.writeFileSync(path.join(sortie, 'narration-publique.wav'), son.wav);
    const { wav: _wav, ...mesures } = son; rapport.narration = mesures;
    rapport.checks.narrationWithWordTimings = true;
    const maj = await cdp.evaluer(`!![...document.querySelectorAll('button')].find(b =>
      /^(Mise à jour|Update|Updates|Check for updates)$/i.test(b.getAttribute('aria-label') || b.title || b.innerText.trim()))`);
    verifier(maj, 'updateButtonMissing'); rapport.checks.updateButtonVisible = true;
    const catalogue = await cdp.invoquer('verifier_telechargements');
    verifier(catalogue.platform === 'windows' && catalogue.currentVersion === cible.version
      && catalogue.catalog?.platforms?.windows?.version === cible.version, 'updateCatalogueMismatch');
    rapport.checks.updateCatalogueMatches = true;
    noter('restartInstalledApplication');
    await arreter(); await lancer();
    cle = await cdp.invoquer('get_local_api_key');
    const relue = (await api(`/v1/vie/notes/${encodeURIComponent(note.id)}`)).note;
    verifier(relue.content === contenu && relue.projectId === projet.id, 'noteLostAfterRestart');
    rapport.checks.notePersistedAfterRestart = true;
    await capture(cdp, path.join(sortie, '03-apres-relance.png'));
    await arreter(); rapport.checks.processesStopped = true;
    noter('uninstallTestCopy');
    await verifierAucuneApp();
    const desinstallation = await executer(path.join(dossierApp, 'uninstall.exe'), ['/S'], { cwd: travail });
    verifier(desinstallation.code === 0, 'uninstallerFailed');
    await attendre(() => !fs.existsSync(exe), 30000, 'uninstallerLeftApplication');
    rapport.checks.uninstallSucceeded = true; installe = false;
    await attendre(async () => (await powershell(SONDE_REGISTRE)).existingKeys === 0,
      30000, 'registryNotRestored');
    rapport.checks.registryRestored = true;
  } catch (e) {
    rapport.failureCode = /^[A-Za-z0-9_:<>/-]{1,180}$/.test(e.message) ? e.message : 'unexpectedTestFailure';
    try { if (cdp) await capture(cdp, path.join(sortie, 'echec-application.png')); } catch { /* facultatif */ }
  } finally {
    try { await arreter(); } catch { rapport.cleanupFailed = true; }
    if (installe && exe && fs.existsSync(path.join(path.dirname(exe), 'uninstall.exe'))) {
      try {
        await verifierAucuneApp();
        const u = await executer(path.join(path.dirname(exe), 'uninstall.exe'), ['/S'], { cwd: travail });
        rapport.cleanupUninstallerExitCode = u.code;
        verifier(u.code === 0, 'cleanupUninstallFailed');
        await attendre(() => !fs.existsSync(exe), 30000, 'cleanupLeftApplication');
      } catch { rapport.cleanupFailed = true; }
    }
    if (installe) {
      try {
        await attendre(async () => (await powershell(SONDE_REGISTRE)).existingKeys === 0,
          30000, 'cleanupLeftRegistry');
      } catch { rapport.cleanupFailed = true; }
    }
    rapport.passed = rapportValide(rapport) && !rapport.cleanupFailed;
    rapport.status = rapport.passed ? 'passed' : 'failed';
    noter(rapport.status);
  }
  return rapport;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const valeurs = {};
  for (let i = 2; i < process.argv.length; i += 2) valeurs[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
  premierLancement(valeurs).then(r => { process.exitCode = r.passed ? 0 : 1; }).catch(() => {
    console.error('Préparation de l’essai refusée. Aucun succès déclaré.'); process.exitCode = 1;
  });
}
