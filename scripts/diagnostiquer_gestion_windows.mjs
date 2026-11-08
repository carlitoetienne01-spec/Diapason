/** §5/§100 — observer l'installation existante sans lancer son code Python. */
import fs from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const ORIGINE = 'http://127.0.0.1:8000';
export const SONDES = Object.freeze({
  notes: '/v1/vie/notes/resumes', projects: '/v1/vie/projects',
  finances: '/v1/vie/finances/overview', config: '/v1/config',
});
const URLS = new Set(['/health', ...Object.values(SONDES)].map(p => ORIGINE + p));
export const DELAI_HTTP_MS = 6000;
const ISSUES = new Set(['notRequested', 'http', 'timeout', 'connectionRefused',
  'networkError', 'redirectRefused', 'ownerChanged', 'bodyTooLarge', 'invalidTarget']);
const CODES = new Set(['unsupportedPlatform', 'nativeUnavailable', 'ownerNotAttributed',
  'healthUnrecognized', 'keyUnavailable', 'ownerChanged', 'reportWriteFailed', 'invalidArguments']);
const ETAPES_NATIVES = new Set(['initialization', 'registry', 'applications', 'listener', 'backend', 'attestation']);
const ISSUES_NATIVES = new Set(['completed', 'commandFailed', 'launchFailed', 'timeout', 'invalidOutput']);
const ETAPES_ATTRIBUTION = new Set(['rootUnavailable', 'projectUnreadable', 'legacyProject', 'projectUnrecognized', 'venvUnavailable', 'baseUnverified', 'candidatePrepared']);
const nettoyerNatif = n => ({
  outcome: ISSUES_NATIVES.has(n?.outcome) ? n.outcome : 'invalidOutput',
  stage: ETAPES_NATIVES.has(n?.stage) ? n.stage : null,
  line: Number.isInteger(n?.line) && n.line > 0 && n.line <= 1000 ? n.line : null,
});
const INCONNU = () => ({ status: null, outcome: 'notRequested', authenticated: false });
const version = v => typeof v === 'string' && v.length <= 80
  && /^\d{1,4}\.\d{1,4}\.\d{1,4}(?:\.\d{1,9}|-beta\.\d{8}(?:\.\d{1,9})?)?$/.test(v) ? v : null;
const pidValide = n => Number.isInteger(n) && n > 0 && n <= 0xffffffff;
export const urlAutorisee = url => typeof url === 'string' && URLS.has(url);
const cleValide = cle => typeof cle === 'string' && /^diapason_sk_[A-Za-z0-9_-]{32,128}$/.test(cle);

/** Le marqueur « managed » n'est pas une version. Les deux provenances publiques
 * connues doivent s'accorder si elles sont présentes ensemble. */
export function versionPublique({ betaVersion, snapshotBetaVersion } = {}) {
  const valeurs = [betaVersion, snapshotBetaVersion].filter(v => v !== null && v !== undefined);
  return valeurs.length > 0 && valeurs.every(v => version(v) && v === valeurs[0]) ? valeurs[0] : null;
}

const cheminWindows = p => typeof p === 'string' && p.length <= 4096
  && /^[A-Za-z]:\\/.test(p) && !/[\x00-\x1f"<>|?*\/]/.test(p)
  && !p.slice(2).includes(':') && !p.split('\\').some(s => s === '.' || s === '..' || /[. ]$/.test(s))
  ? path.win32.normalize(p).toLowerCase().replace(/\\$/, '') : null;

export function homeVenv(texte) {
  if (typeof texte !== 'string' || Buffer.byteLength(texte) > 8192) return null;
  const valeurs = texte.split(/\r?\n/).flatMap(l => {
    const m = /^\s*home\s*=\s*(.*?)\s*$/.exec(l); return m ? [m[1]] : [];
  });
  return valeurs.length === 1 ? cheminWindows(valeurs[0]) : null;
}

// Sous-ensemble conservateur des lignes Windows : les guillemets imbriqués ou
// échappés sont refusés, plutôt que d'attribuer une commande interprétée autrement.
function argumentsWindows(ligne) {
  if (typeof ligne !== 'string' || ligne.length > 8192 || /[\x00-\x1f]/.test(ligne)) return null;
  const args = []; let restant = ligne.trim();
  while (restant) {
    const m = /^(?:"([^"\r\n]*)"|([^\s"]+))(?:\s+|$)/.exec(restant);
    if (!m || m[1]?.endsWith('\\')) return null;
    args.push(m[1] ?? m[2]); restant = restant.slice(m[0].length);
  }
  return args;
}

/** Les faits disque/SID proviennent de la sonde native ; la décision sur la
 * commande est pure et identique dans le diagnostic et les fixtures. */
export function entreeBackendVerifiee(p, c) {
  if (!pidValide(p?.pid) || p.sameSid !== true || typeof p.identity !== 'string' || !/^\d{1,20}$/.test(p.identity)
    || c?.metadataOwned !== true || c.cfgOwned !== true || c.baseVerified !== true) return false;
  const racine = cheminWindows(c.root), home = homeVenv(c.cfg), resolu = cheminWindows(c.resolvedHome);
  if (!racine || !home || !resolu) return false;
  const aliasUv = path.win32.basename(home) === 'cpython-3.13-windows-x86_64-none'
    && /^cpython-3\.13\.\d+-windows-x86_64-none$/.test(path.win32.basename(resolu))
    && path.win32.dirname(home) === path.win32.dirname(resolu);
  if (home !== resolu && !aliasUv) return false;
  const exe = cheminWindows(p.executablePath), argv = argumentsWindows(p.commandLine);
  if (!exe || !argv?.length) return false;
  const python = racine + '\\.venv\\scripts\\python.exe', entree = racine + '\\.venv\\scripts\\diapason.exe';
  const arg0 = cheminWindows(argv[0]), args = argv.slice(1);
  if (exe === entree && c.entryOwned === true) return arg0 === entree && args[0] === 'serve';
  const interprete = exe === resolu + '\\python.exe' || (exe === python && c.venvPythonOwned === true);
  if (!interprete || (arg0 !== exe && !(arg0 === python && c.venvPythonOwned === true))) return false;
  if (c.entryOwned === true && cheminWindows(args[0]) === entree && args[1] === 'serve') return true;
  // Un « -m diapason » du Python global ne prouve pas quel paquet il importe.
  if (c.venvPythonOwned !== true || (exe !== python && arg0 !== python)) return false;
  while (['-I', '-B', '-u', '-S'].includes(args[0])) args.shift();
  if (args[0] === '-m' && args[1] === 'diapason' && args[2] === 'serve') return true;
  return c.betaOwned === true && cheminWindows(args[0]) === racine + '\\deploy\\windows\\beta_backend.py';
}

export function attribuerInventaire(n) {
  if (!n || typeof n !== 'object') return {};
  const p = { ...n.listener, identity: n.private?.identity };
  const candidats = Array.isArray(n.candidates) ? n.candidates.slice(0, 2).filter(c => entreeBackendVerifiee(p, c)) : [];
  n.listener = { ...n.listener, knownEntryPoint: candidats.length === 1 };
  n.backend = {};
  if (candidats.length === 1) {
    const c = candidats[0];
    n.backend = { version: versionPublique(c.publicVersions), metadataOwned: true, crudExemption: c.crudExemption };
  }
  return n;
}

export function signatureSante(corps) {
  try {
    const o = JSON.parse(corps);
    if (o?.status === 'ok' && o.mode === 'windows-beta-gestion') return 'windowsBetaGestion';
    if (o?.status === 'ok' && o.mode === undefined) return 'compatible';
    if (o?.detail === 'Engine unhealthy') return 'engineUnhealthy';
  } catch { /* Ni corps, ni erreur de parsing dans le rapport. */ }
  return 'unrecognized';
}

export function proprietaireAttribuable(n) {
  return pidValide(n?.listener?.pid) && n.listener.sameSid === true
    && n.listener.knownEntryPoint === true && ['python', 'diapasonLauncher'].includes(n.listener.processKind)
    && n.backend?.metadataOwned === true
    && typeof n.private?.identity === 'string' && /^\d{1,20}$/.test(n.private.identity);
}

/** Projection fermée : aucun objet natif ou résultat HTTP brut n'est sérialisé. */
export function nettoyerRapport(r = {}) {
  const resultat = o => ({
    status: Number.isInteger(o?.status) && o.status >= 100 && o.status <= 599 ? o.status : null,
    outcome: ISSUES.has(o?.outcome) ? o.outcome : 'networkError',
    authenticated: o?.authenticated === true,
  });
  const liste = Array.isArray(r.installations) ? r.installations.slice(0, 4) : [];
  return {
    schemaVersion: 1, kind: 'windowsGestionReadOnly',
    platform: ['win32', 'windows'].includes(r.platform) ? 'windows' : 'unsupported',
    status: ['completed', 'partial', 'refused'].includes(r.status) ? r.status : 'refused',
    codes: Array.isArray(r.codes) ? [...new Set(r.codes.filter(c => CODES.has(c)))].slice(0, 8) : [],
    native: nettoyerNatif(r.native),
    attribution: {
      processKind: ['python', 'diapasonLauncher', 'other'].includes(r.attribution?.processKind) ? r.attribution.processKind : null,
      candidateStages: Array.isArray(r.attribution?.candidateStages)
        ? r.attribution.candidateStages.slice(0, 2).map(s => ETAPES_ATTRIBUTION.has(s) ? s : 'rootUnavailable') : [],
      matched: r.attribution?.matched === true,
    },
    installations: liste.map(i => ({ productVersion: version(i?.productVersion),
      fileVersion: version(i?.fileVersion), running: i?.running === true })),
    listener: { port: 8000, pid: pidValide(r.listener?.pid) ? r.listener.pid : null,
      ownership: ['diapason', 'unknown', 'absent'].includes(r.listener?.ownership) ? r.listener.ownership : 'unknown',
      sameUser: typeof r.listener?.sameSid === 'boolean' ? r.listener.sameSid
        : typeof r.listener?.sameUser === 'boolean' ? r.listener.sameUser : null },
    backend: { version: version(r.backend?.version), metadataOwned: r.backend?.metadataOwned === true,
      crudExemption: ['patternPresent', 'patternNotFound', 'unreadable'].includes(r.backend?.crudExemption)
        ? r.backend.crudExemption : 'unreadable' },
    credential: ['used', 'unavailable', 'refused', 'notSent'].includes(r.credential) ? r.credential : 'refused',
    health: { ...resultat(r.health), signature: ['compatible', 'windowsBetaGestion', 'engineUnhealthy'].includes(r.health?.signature)
      ? r.health.signature : 'unrecognized' },
    probes: Object.fromEntries(Object.keys(SONDES).map(n => [n, resultat(r.probes?.[n])])),
  };
}

/** La connexion existe AVANT l'attestation et AVANT l'envoi du Bearer. */
export function creerSondeHttp({ connecter = net.createConnection, demander = http.request,
  minuter = setTimeout, demuter = clearTimeout } = {}) {
  return ({ url, key = '', attestSocket, timeoutMs = DELAI_HTTP_MS }) => new Promise(resolve => {
    if (!urlAutorisee(url)) return resolve({ ...INCONNU(), outcome: 'invalidTarget' });
    let fini = false, transmis = false, prise, requete, reponse, agent;
    const terminer = valeur => {
      if (fini) return;
      fini = true; demuter(minuteur);
      reponse?.destroy(); requete?.destroy(); agent?.destroy(); prise?.destroy();
      resolve({ ...valeur, authenticated: transmis });
    };
    const delai = Number.isInteger(timeoutMs) && timeoutMs > 0 ? Math.min(timeoutMs, DELAI_HTTP_MS) : DELAI_HTTP_MS;
    const minuteur = minuter(() => terminer({ status: null, outcome: 'timeout' }), delai);
    try {
      prise = connecter({ host: '127.0.0.1', port: 8000, family: 4 });
      prise.on('error', e => terminer({ status: null,
        outcome: e?.code === 'ECONNREFUSED' ? 'connectionRefused' : 'networkError' }));
      prise.once('connect', async () => {
        try {
          if (prise.remoteAddress !== '127.0.0.1' || prise.remotePort !== 8000) {
            return terminer({ status: null, outcome: 'invalidTarget' });
          }
          if (attestSocket && await attestSocket(prise.localPort) !== true) {
            return terminer({ status: null, outcome: 'ownerChanged' });
          }
          if (fini) return;
          if (key && (!attestSocket || !cleValide(key))) {
            return terminer({ status: null, outcome: 'ownerChanged' });
          }
          // Agent dédié et socket déjà reliée : aucun proxy global ou DNS.
          agent = new http.Agent({ keepAlive: false });
          agent.createConnection = () => prise;
          const headers = { Accept: 'application/json', Connection: 'close' };
          if (key) headers.Authorization = `Bearer ${key}`;
          requete = demander({ protocol: 'http:', hostname: '127.0.0.1', port: 8000,
            method: 'GET', path: new URL(url).pathname, agent, headers }, res => {
            reponse = res;
            const status = res.statusCode;
            if (status >= 300 && status <= 399) return terminer({ status, outcome: 'redirectRefused' });
            if (url !== ORIGINE + '/health') return terminer({ status, outcome: 'http' });
            const morceaux = []; let taille = 0;
            res.on('data', b => {
              taille += b.length;
              if (taille > 2048) terminer({ status, outcome: 'bodyTooLarge' });
              else morceaux.push(b);
            });
            res.on('error', () => terminer({ status, outcome: 'networkError' }));
            res.on('end', () => terminer({ status, outcome: 'http',
              signature: signatureSante(Buffer.concat(morceaux).toString('utf8')) }));
          });
          requete.on('error', () => terminer({ status: null, outcome: 'networkError' }));
          transmis = Boolean(key); requete.end();
        } catch { terminer({ status: null, outcome: 'networkError' }); }
      });
    } catch { terminer({ status: null, outcome: 'networkError' }); }
  });
}

export async function diagnostiquer({ platform = process.platform, collectNative = collecterNatif,
  attestNative = attesterNatif, readKey = lireCle, probe = creerSondeHttp() } = {}) {
  const r = { platform, status: 'partial', codes: [], credential: 'notSent',
    health: INCONNU(), probes: Object.fromEntries(Object.keys(SONDES).map(n => [n, INCONNU()])) };
  if (platform !== 'win32') {
    r.status = 'refused'; r.codes.push('unsupportedPlatform'); return nettoyerRapport(r);
  }
  let n;
  try { n = await collectNative(); r.native = { outcome: 'completed' }; }
  catch (e) { r.codes.push('nativeUnavailable'); r.native = nettoyerNatif(e?.nativeDiagnostic); }
  r.installations = n?.installations; r.listener = { ...n?.listener, ownership: 'unknown' }; r.backend = n?.backend;
  r.attribution = { processKind: n?.listener?.processKind, candidateStages: n?.candidateStages,
    matched: n?.listener?.knownEntryPoint === true };
  if (n?.listener?.absent === true) r.listener.ownership = 'absent';
  try { r.health = await probe({ url: ORIGINE + '/health' }); } catch { r.health = { outcome: 'networkError' }; }
  if (!proprietaireAttribuable(n)) {
    r.credential = 'refused'; r.codes.push('ownerNotAttributed');
    // Les statuts publics des quatre GET autorisés restent observables sans
    // lire ni transmettre une clé. Leur contenu n'est jamais conservé.
    if (n?.listener?.sameSid === true && r.health.outcome === 'http'
      && ['compatible', 'windowsBetaGestion', 'engineUnhealthy'].includes(r.health.signature)) {
      for (const [nom, route] of Object.entries(SONDES)) {
        try { r.probes[nom] = await probe({ url: ORIGINE + route, key: '' }); }
        catch { r.probes[nom] = { outcome: 'networkError' }; }
      }
    }
    return nettoyerRapport(r);
  }
  r.listener.ownership = 'diapason';
  if (r.health.outcome !== 'http' || !['compatible', 'windowsBetaGestion', 'engineUnhealthy'].includes(r.health.signature)) {
    r.codes.push('healthUnrecognized'); return nettoyerRapport(r);
  }
  let key = '';
  try { const lue = await readKey(n); if (cleValide(lue)) key = lue; } catch { /* Refus fermé. */ }
  r.credential = key ? 'notSent' : 'unavailable';
  if (!key) r.codes.push('keyUnavailable');
  for (const [nom, route] of Object.entries(SONDES)) {
    try {
      r.probes[nom] = await probe({ url: ORIGINE + route, key,
        attestSocket: port => attesterBorne(n, port, attestNative) });
    } catch { r.probes[nom] = { outcome: 'networkError' }; }
    if (r.probes[nom].authenticated === true) r.credential = 'used';
    if (r.probes[nom].outcome === 'ownerChanged') {
      r.codes.push('ownerChanged'); if (r.credential !== 'used') r.credential = 'refused';
      return nettoyerRapport(r);
    }
  }
  key = ''; // Aucune persistance, empreinte ou restitution de la clé.
  r.status = Object.values(r.probes).every(p => p.outcome === 'http') ? 'completed' : 'partial';
  return nettoyerRapport(r);
}

async function attesterBorne(n, port, attester) {
  if (!proprietaireAttribuable(n) || !Number.isInteger(port) || port < 1 || port > 65535) return false;
  try { return await attester({ pid: n.listener.pid, identity: n.private.identity, port }) === true; }
  catch { return false; }
}

async function lireCle(n) {
  if (!proprietaireAttribuable(n) || n.private.keyOwned !== true || typeof n.private.keyPath !== 'string') return '';
  const f = await fs.open(n.private.keyPath, 'r');
  try {
    const etat = await f.stat(); if (!etat.isFile() || etat.size > 256) return '';
    const b = Buffer.alloc(257); const { bytesRead } = await f.read(b, 0, 257, 0);
    const valeur = b.subarray(0, bytesRead).toString('utf8').trim(); b.fill(0);
    return cleValide(valeur) ? valeur : '';
  } finally { await f.close(); }
}

// Ces informations brutes restent dans le pipe privé du fils, jamais au rapport.
const POWERSHELL = String.raw`
$env:PSModulePath=Join-Path $PSHOME 'Modules'
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$etape='initialization'
try {
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$profil=[Environment]::GetFolderPath('UserProfile')
$local=[Environment]::GetFolderPath('LocalApplicationData')
function Possede([string]$p) {
  try {
    $p=[IO.Path]::GetFullPath($p)
    if (-not $p.StartsWith($profil+'\',[StringComparison]::OrdinalIgnoreCase)) { return $false }
    $courant=$p
    while ($courant) {
      $i=Get-Item -LiteralPath $courant -Force
      if ($i.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
      $courant=[IO.Path]::GetDirectoryName($courant)
    }
    return ((Get-Acl -LiteralPath $p).GetOwner([Security.Principal.SecurityIdentifier]).Value -eq $sid)
  } catch { return $false }
}
function Petit([string]$p,[int]$max) {
  if (-not (Possede $p)) { return $null }
  if ((Get-Item -LiteralPath $p -Force).PSIsContainer) { return $null }
  $s=[IO.File]::OpenRead($p)
  try {
    if ($s.Length -gt $max) { return $null }
    $b=New-Object byte[] ($max+1); $n=0
    while ($n -lt $b.Length) { $lus=$s.Read($b,$n,$b.Length-$n); if ($lus -eq 0) { break }; $n+=$lus }
    if ($n -gt $max) { return $null }
    return (New-Object System.Text.UTF8Encoding($false,$true)).GetString($b,0,$n)
  } finally { $s.Dispose() }
}
function SansReparse([string]$p) {
  try {
    if ($p -notmatch '^[A-Za-z]:\\' -or $p -match '(?:^|\\)\.\.(?:\\|$)') { return $false }
    $courant=[IO.Path]::GetFullPath($p)
    while ($courant) {
      $i=Get-Item -LiteralPath $courant -Force
      if ($i.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
      $courant=[IO.Path]::GetDirectoryName($courant)
    }
    return $true
  } catch { return $false }
}
function BaseVenv([string]$cfg) {
  try {
    $valeursHome=@($cfg -split '\r?\n' | Where-Object { $_ -cmatch '^\s*home\s*=' })
    if ($valeursHome.Count -ne 1) { return $null }
    $baseDeclaree=($valeursHome[0] -split '=',2)[1].Trim()
    if ($baseDeclaree -notmatch '^[A-Za-z]:\\' -or $baseDeclaree -match '(?:^|\\)\.\.(?:\\|$)') { return $null }
    $baseDeclaree=[IO.Path]::GetFullPath($baseDeclaree); $parent=[IO.Path]::GetDirectoryName($baseDeclaree)
    if (-not (SansReparse $parent)) { return $null }
    $i=Get-Item -LiteralPath $baseDeclaree -Force
    if ($i.Attributes -band [IO.FileAttributes]::ReparsePoint) {
      # Même alias uv mineur que l'amorçage : une seule cible patch, sœur directe.
      if ($i.Name -cne 'cpython-3.13-windows-x86_64-none') { return $null }
      $cibles=@($i.Target)
      if ($cibles.Count -ne 1) { return $null }
      $cible=[string]$cibles[0]
      if ($cible -match '(?:^|\\)\.\.(?:\\|$)') { return $null }
      if (-not [IO.Path]::IsPathRooted($cible)) { $cible=Join-Path $parent $cible }
      $cible=[IO.Path]::GetFullPath($cible)
      if ([IO.Path]::GetDirectoryName($cible) -ine $parent -or
        [IO.Path]::GetFileName($cible) -cnotmatch '^cpython-3\.13\.\d+-windows-x86_64-none$') { return $null }
      $baseDeclaree=$cible
    }
    $base=Join-Path $baseDeclaree 'python.exe'
    if (-not (SansReparse $base) -or (Get-Item -LiteralPath $base -Force).PSIsContainer) { return $null }
    if ([IO.File]::Exists((Join-Path $baseDeclaree 'pyvenv.cfg')) -or
      [IO.File]::Exists((Join-Path ([IO.Path]::GetDirectoryName($baseDeclaree)) 'pyvenv.cfg'))) { return $null }
    return $baseDeclaree
  } catch { return $null }
}
function VersionsPubliques([string]$racine) {
  # Windows31 : 793 896 octets. 1 Mio couvre le manifeste observé sans lecture illimitée.
  $texte=Petit (Join-Path $racine 'beta-build.json') 1048576
  if (-not $texte) { return @{} }
  try {
    $meta=ConvertFrom-Json -InputObject $texte
    return @{ betaVersion=$meta.betaVersion; snapshotBetaVersion=$meta.snapshot.betaVersion }
  } catch { return @{} }
}
function MemeSid($p) {
  $o=CimCmdlets\Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid -OperationTimeoutSec 2
  return ($o.ReturnValue -eq 0 -and $o.Sid -eq $sid)
}
function ExecutableInstalle([string]$dir) {
  # Une ancienne valeur InstallLocation invalide ne doit pas annuler l'inventaire.
  try {
    $dir=$dir.Trim()
    if ($dir.Length -ge 2 -and $dir[0] -eq '"' -and $dir[$dir.Length-1] -eq '"') { $dir=$dir.Substring(1,$dir.Length-2) }
    if ($dir -notmatch '^[A-Za-z]:\\' -or $dir -match '[\x00-\x1f"<>|?*]' -or $dir.Substring(2).Contains(':')) { return $null }
    return [IO.Path]::Combine($dir,'Diapason.exe')
  } catch { return $null }
}
function Processus([int]$numero) {
  return CimCmdlets\Get-CimInstance Win32_Process -Filter ('ProcessId='+$numero) -OperationTimeoutSec 2
}
if ($env:DIAG_MODE -eq 'attest') {
  $etape='attestation'
  $numero=[int]$env:DIAG_PID; $portClient=[int]$env:DIAG_CLIENT_PORT
  $p=Processus $numero
  $ok=$p -and (MemeSid $p) -and ($p.CreationDate.ToUniversalTime().Ticks.ToString() -eq $env:DIAG_IDENTITY)
  $liaisons=@(NetTCPIP\Get-NetTCPConnection -State Established -LocalAddress '127.0.0.1' -LocalPort 8000 -RemoteAddress '127.0.0.1' -RemotePort $portClient -ErrorAction Stop)
  $ok=$ok -and $liaisons.Count -eq 1 -and $liaisons[0].OwningProcess -eq $numero
  @{ verified=[bool]$ok } | ConvertTo-Json -Compress
  exit
}
$racines=@((Join-Path $local 'Diapason\src'))
$memo=Petit (Join-Path $profil '.diapason\project_root') 4096
if ($memo) { $racines+= $memo.Trim() }
$installations=@(); $executables=@((Join-Path $local 'Programs\Diapason\Diapason.exe'),(Join-Path $local 'Diapason\Diapason.exe'))
$etape='registry'
$reg=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall',$false)
if ($reg) {
  try {
    foreach ($nom in @($reg.GetSubKeyNames() | Select-Object -First 2048)) {
      $k=$reg.OpenSubKey($nom,$false)
      try {
        if ($k -and ([string]$k.GetValue('DisplayName')) -match '^Diapason(?:\s|$)') {
          $dir=[string]$k.GetValue('InstallLocation')
          $exeInstalle=ExecutableInstalle $dir
          if ($exeInstalle) { $executables+=$exeInstalle }
        }
      } finally { if ($k) { $k.Dispose() } }
    }
  } finally { $reg.Dispose() }
}
$etape='applications'
$apps=@(CimCmdlets\Get-CimInstance Win32_Process -Filter "Name='Diapason.exe' OR Name='diapason-desktop.exe'" -OperationTimeoutSec 2)
$executables=@($apps | Select-Object -ExpandProperty ExecutablePath)+$executables
foreach ($exe in @($executables | Select-Object -Unique | Select-Object -First 8)) {
  if (Possede $exe) {
    $v=[Diagnostics.FileVersionInfo]::GetVersionInfo($exe)
    if ($v.ProductName -match '^Diapason(?:\s|$)') {
      $actifs=@($apps | Where-Object { $_.ExecutablePath -ieq $exe })
      $installations+=@{ productVersion=$v.ProductVersion; fileVersion=$v.FileVersion; running=($actifs.Count -gt 0) }
    }
  }
}
$etape='listener'
$ecoutes=@(NetTCPIP\Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -in @('127.0.0.1','0.0.0.0') })
$ids=@($ecoutes | Select-Object -ExpandProperty OwningProcess -Unique)
$resultat=@{ installations=@($installations | Select-Object -First 4); listener=@{ absent=($ids.Count -eq 0) }; candidates=@(); candidateStages=@(); private=@{} }
if ($ids.Count -eq 1) {
  $etape='backend'
  $p=Processus ([int]$ids[0]); $propre=$p -and (MemeSid $p)
  $genre='other'
  if ($p) {
    $nomExe=[IO.Path]::GetFileName($p.ExecutablePath)
    if ($nomExe -ieq 'python.exe') { $genre='python' }
    if ($nomExe -ieq 'diapason.exe') { $genre='diapasonLauncher' }
  }
  $resultat.listener=@{ pid=[int]$ids[0]; sameSid=[bool]$propre; knownEntryPoint=$false; processKind=$genre }
  if ($propre -and $genre -ne 'other' -and ([string]$p.CommandLine).Length -le 8192) {
    $resultat.listener.executablePath=[string]$p.ExecutablePath
    $resultat.listener.commandLine=[string]$p.CommandLine
    $cle=Join-Path $profil '.diapason\auth\local_api_key'
    $resultat.private=@{ identity=$p.CreationDate.ToUniversalTime().Ticks.ToString(); keyPath=$cle; keyOwned=(Possede $cle) }
    foreach ($racine in @($racines | Select-Object -Unique | Select-Object -First 2)) {
      if (-not (Possede $racine)) { $resultat.candidateStages+='rootUnavailable'; continue }
      $projet=Petit (Join-Path $racine 'pyproject.toml') 65536
      if (-not $projet) { $resultat.candidateStages+='projectUnreadable'; continue }
      if ($projet -match '(?im)^name\s*=\s*["''](?:OpenJarvis|Jarvis)["'']\s*$') { $resultat.candidateStages+='legacyProject'; continue }
      if ($projet -notmatch '(?im)^name\s*=\s*["'']Diapason["'']\s*$') { $resultat.candidateStages+='projectUnrecognized'; continue }
      $entree=Join-Path $racine '.venv\Scripts\diapason.exe'
      $python=Join-Path $racine '.venv\Scripts\python.exe'
      $cfg=Petit (Join-Path $racine '.venv\pyvenv.cfg') 8192
      if (-not $cfg) { $resultat.candidateStages+='venvUnavailable'; continue }
      $baseDeclaree=BaseVenv $cfg
      if (-not $baseDeclaree) { $resultat.candidateStages+='baseUnverified'; continue }
      $resultat.candidateStages+='candidatePrepared'
      $code=Petit (Join-Path $racine 'src\diapason\server\auth_middleware.py') 131072
      $exemption='unreadable'
      if ($code) {
        $present=$code.Contains('"/v1/vie/"') -and $code.Contains('_VIE_SANS_LIMITE = _VIE_PREFIXES') -and
          ($code -match 'if path\.startswith\(_VIE_SANS_LIMITE\) and not path\.startswith\(_VIE_SYNC_LIMITEE\):\s*return await call_next\(request\)')
        $exemption= if ($present) { 'patternPresent' } else { 'patternNotFound' }
      }
      $resultat.candidates+=@{ root=$racine; metadataOwned=$true; cfgOwned=$true; cfg=$cfg;
        resolvedHome=$baseDeclaree; baseVerified=$true; entryOwned=(Possede $entree); venvPythonOwned=(Possede $python);
        betaOwned=(Possede (Join-Path $racine 'deploy\windows\beta_backend.py'));
        publicVersions=(VersionsPubliques $racine); crudExemption=$exemption }
    }
  }
}
$resultat | ConvertTo-Json -Depth 5 -Compress
} catch {
  @{ diagnosticFailure=$true; stage=$etape; line=$_.InvocationInfo.ScriptLineNumber } | ConvertTo-Json -Compress
}
`;

async function sondeNative(mode, valeurs = {}, { platform = process.platform, lancer = spawn } = {}) {
  if (platform !== 'win32') throw new Error('unsupportedPlatform');
  const windows = process.env.SystemRoot;
  if (!windows || !/^[A-Za-z]:\\[^\r\n]+$/.test(windows)) throw new Error('nativeUnavailable');
  const executable = path.win32.join(windows, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  return new Promise((resolve, reject) => {
    let fini = false, taille = 0; const blocs = [];
    const enfant = lancer(executable, ['-NoProfile', '-NonInteractive', '-EncodedCommand',
      Buffer.from(POWERSHELL, 'utf16le').toString('base64')], { shell: false, windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'], env: { SystemRoot: windows, WINDIR: windows,
        PATH: path.win32.join(windows, 'System32'),
        PSModulePath: path.win32.join(windows, 'System32', 'WindowsPowerShell', 'v1.0', 'Modules'),
        DIAG_MODE: mode, ...valeurs } });
    const finir = (valeur, erreur = false, detail = {}) => {
      if (fini) return; fini = true; clearTimeout(minuteur);
      enfant.stdout?.destroy(); enfant.stderr?.destroy(); enfant.unref();
      if (erreur) {
        const e = new Error('nativeUnavailable'); e.nativeDiagnostic = nettoyerNatif(detail); reject(e);
      } else resolve(valeur);
    };
    // Aucun taskkill/Stop-Process : seul le pipe de notre sonde est abandonné.
    const minuteur = setTimeout(() => finir(null, true, { outcome: 'timeout' }), 6500);
    enfant.stdout.on('data', b => { taille += b.length; if (taille > 32768) finir(null, true); else blocs.push(b); });
    enfant.stderr.on('data', () => {});
    enfant.on('error', () => finir(null, true, { outcome: 'launchFailed' }));
    enfant.on('close', code => {
      if (code !== 0) return finir(null, true, { outcome: 'commandFailed' });
      try {
        const r = JSON.parse(Buffer.concat(blocs).toString('utf8').replace(/^\uFEFF/, '').trim());
        if (r?.diagnosticFailure === true) finir(null, true, { outcome: 'commandFailed', stage: r.stage, line: r.line });
        else finir(r);
      }
      catch { finir(null, true); }
    });
  });
}

export const collecterNatif = async options => attribuerInventaire(await sondeNative('inventory', {}, options));
async function attesterNatif({ pid, identity, port }) {
  if (!pidValide(pid) || !/^\d{1,20}$/.test(identity) || !Number.isInteger(port) || port < 1 || port > 65535) return false;
  const r = await sondeNative('attest', { DIAG_PID: String(pid), DIAG_IDENTITY: identity, DIAG_CLIENT_PORT: String(port) });
  return r?.verified === true;
}

async function main() {
  let rapport;
  try {
    if (process.argv.length !== 4 || process.argv[2] !== '--output' || !path.isAbsolute(process.argv[3])) {
      throw new Error('invalidArguments');
    }
    rapport = await diagnostiquer();
    const texte = JSON.stringify(nettoyerRapport(rapport), null, 2) + '\n';
    if (Buffer.byteLength(texte) > 8192) throw new Error('reportWriteFailed');
    await fs.writeFile(process.argv[3], texte, { flag: 'wx', mode: 0o600 });
    process.stdout.write(JSON.stringify({ schemaVersion: 1, reportWritten: true, status: rapport.status }) + '\n');
  } catch (e) {
    const code = e?.message === 'invalidArguments' ? 'invalidArguments' : 'reportWriteFailed';
    process.stdout.write(JSON.stringify({ schemaVersion: 1, reportWritten: false, code }) + '\n');
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  void main();
}
