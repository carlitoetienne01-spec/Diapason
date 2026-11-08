/** Premier lancement du véritable installateur publié, sans amorçage simulé. */
import assert from 'node:assert/strict';
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const CONTROLES = Object.freeze([
  'preflightPassed', 'installerHashVerified', 'installerExecuted',
  'installedExecutablePresent', 'versionMatches', 'firstLaunchReady',
  'newManagedBackendPrepared', 'twoTurnUiConversation',
  'backendVersionMatches',
  'managementCrudAfterQuota', 'navigationScrollbarHidden',
  'initialModelMatchesValidatedPlan',
  'notePersistedAfterRestart', 'narrationWithWordTimings',
  'updateButtonVisible', 'updateCatalogueMatches',
  'uninstallSucceeded', 'registryRestored', 'processesStopped',
  'originalInstallationPreserved',
  'originalInferenceServerPreserved',
]);
export const CONTROLES_LEGACY = Object.freeze([
  'legacySourcePreserved', 'legacyFixtureSeeded', 'legacyOldServerRejected',
  'legacyOldServerPreserved', 'legacyBootstrapUnmodified', 'legacyOwnedServerStopped',
  'legacyDataAfterStartup', 'legacyDataAfterRestart', 'legacyKeyPreserved',
]);
const ARRET_ANCIEN_POWERSHELL = String.raw`
$env:PSModulePath=Join-Path $PSHOME 'Modules'
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$lease=$null; $stopped=$false; $portFree=$false; $launcherExited=$false
$chrono=[Diagnostics.Stopwatch]::StartNew()
try {
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$session=[Diagnostics.Process]::GetCurrentProcess().SessionId
$profil=[Environment]::GetFolderPath('UserProfile')
$local=[Environment]::GetFolderPath('LocalApplicationData')
$racine=Join-Path $local 'Diapason\src'
$numero=[int]$env:OLD_PID
if ($numero -ne 48196 -or $session -le 0 -or -not [Environment]::UserInteractive) { throw 'oldBackendOwnerRefused' }
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Security.Principal;
public sealed class DiapasonOldServerLease : IDisposable {
  IntPtr handle;
  [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr h);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetProcessTimes(IntPtr h, out long c, out long e, out long k, out long u);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool QueryFullProcessImageName(IntPtr h, uint flags, StringBuilder s, ref uint size);
  [DllImport("kernel32.dll", SetLastError=true)] static extern uint GetProcessId(IntPtr h);
  [DllImport("kernel32.dll", SetLastError=true)] static extern uint WaitForSingleObject(IntPtr h, uint ms);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr h, uint code);
  [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr h, uint access, out IntPtr t);
  [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetTokenInformation(IntPtr t, int type, out int session, int size, out int needed);
  public DiapasonOldServerLease(uint pid) {
    // PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE.
    handle=OpenProcess(0x101001, false, pid);
    if (handle==IntPtr.Zero || GetProcessId(handle)!=pid) { Dispose(); throw new Exception("oldBackendIdentityChanged"); }
  }
  public long Creation { get { long c,e,k,u; if (!GetProcessTimes(handle,out c,out e,out k,out u)) throw new Exception("oldBackendIdentityChanged"); return c; } }
  public bool MatchesCimCreation(DateTime cim) {
    // DMTF/CIM a six décimales ; FILETIME en a sept. Division entière, sans double.
    return Creation/10==cim.ToUniversalTime().ToFileTimeUtc()/10;
  }
  public bool Alive { get { return WaitForSingleObject(handle,0)==258; } }
  public string Image { get { var s=new StringBuilder(4096); uint n=4096; if (!QueryFullProcessImageName(handle,0,s,ref n)) throw new Exception("oldBackendIdentityChanged"); return s.ToString(); } }
  public string Sid { get { IntPtr t; if (!OpenProcessToken(handle,8,out t)) throw new Exception("oldBackendOwnerRefused"); try { using (var i=new WindowsIdentity(t)) return i.User.Value; } finally { CloseHandle(t); } } }
  public int Session { get { IntPtr t; int s,n; if (!OpenProcessToken(handle,8,out t)) throw new Exception("oldBackendOwnerRefused"); try { if (!GetTokenInformation(t,12,out s,4,out n)) throw new Exception("oldBackendOwnerRefused"); return s; } finally { CloseHandle(t); } } }
  public bool StopChecked(long creation, string sid, int session, System.Diagnostics.Stopwatch clock) {
    // Dernière identité issue du HANDLE conservé, jamais un Kill/GetProcessById.
    if (!Alive || Creation!=creation || Sid!=sid || Session!=session || clock.ElapsedMilliseconds>=25000)
      throw new Exception("oldBackendFinalCheckChanged");
    if (!TerminateProcess(handle,1)) throw new Exception("oldBackendStopUnconfirmed");
    return WaitForSingleObject(handle,5000)==0;
  }
  public static string ReadPermit() {
    var read=System.Threading.Tasks.Task.Factory.StartNew(() => Console.ReadLine());
    if (!read.Wait(5000)) throw new Exception("oldBackendTimeout");
    return read.Result;
  }
  public void Dispose() { if (handle!=IntPtr.Zero) { CloseHandle(handle); handle=IntPtr.Zero; } }
}
'@
# Possede/ApplicationSure/Petit/SansReparse/BaseVenv : diagnostic f0321e3,
# SHA256 50ee6e29315718d11d2dc42669cd855b0977d90524b9343061e512192eec7d99.
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
function ApplicationSure([string]$p) {
  # Les fichiers extraits par le runner élevé appartiennent aux Administrateurs.
  # Accepter ce propriétaire exige aussi la chaîne des ACL, jamais le nom seul.
  try {
    $p=[IO.Path]::GetFullPath($p)
    if (-not $p.StartsWith($profil+'\',[StringComparison]::OrdinalIgnoreCase)) { return $false }
    $courant=$p; $fiables=@($sid,'S-1-5-32-544','S-1-5-18')
    while ($courant -and ($courant -ieq $profil -or $courant.StartsWith($profil+'\',[StringComparison]::OrdinalIgnoreCase))) {
      $i=Get-Item -LiteralPath $courant -Force
      if ($i.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
      $acl=Get-Acl -LiteralPath $courant
      if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $fiables) { return $false }
      foreach ($regle in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($regle.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
          ($regle.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly)) { continue }
        # WriteData/AppendData/WriteEA/DeleteChild/WriteAttributes/Delete/WriteDac/WriteOwner.
        if (([int64]$regle.FileSystemRights -band 852310) -ne 0 -and $regle.IdentityReference.Value -notin $fiables) { return $false }
      }
      if ($courant -ieq $profil) { return $true }
      $courant=[IO.Path]::GetDirectoryName($courant)
    }
    return $false
  } catch { return $false }
}
function Petit([string]$p,[int]$max) {
  if (-not (ApplicationSure $p)) { return $null }
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

function AclBaseSure([string]$p) {
  # Hors profil, vérifier aussi les ACL du Python pointé par pyvenv.cfg.
  try {
    if (-not (SansReparse $p)) { return $false }
    $courant=[IO.Path]::GetFullPath($p); $premier=$true
    $fiables=@($sid,'S-1-5-32-544','S-1-5-18')
    while ($courant) {
      $acl=Get-Acl -LiteralPath $courant
      if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $fiables) { return $false }
      foreach ($r in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($r.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
          ($r.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly)) { continue }
        # Les ancêtres ne doivent pas permettre de remplacer un enfant existant.
        $masque=if ($premier) { 852310 } else { 852304 }
        if (([int64]$r.FileSystemRights -band $masque) -ne 0 -and $r.IdentityReference.Value -notin $fiables) { return $false }
      }
      $premier=$false; $courant=[IO.Path]::GetDirectoryName($courant)
    }
    return $true
  } catch { return $false }
}
function Absent([string]$p) {
  $parent=[IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($p))
  if ($parent -ine $racine -or -not (Possede $parent) -or -not (ApplicationSure $parent)) { throw 'oldBackendSourceRefused' }
  try { $null=Get-Item -LiteralPath $p -Force -ErrorAction Stop; return $false }
  catch [System.Management.Automation.ItemNotFoundException] {
    if (-not (Possede $parent) -or -not (ApplicationSure $parent)) { throw 'oldBackendSourceRefused' }
    # Un lien cassé reste une entrée présente, même si Get-Item ne le résout pas.
    if (@([IO.Directory]::EnumerateFileSystemEntries($parent,[IO.Path]::GetFileName($p))).Count -ne 0) { return $false }
    if (-not (Possede $parent) -or -not (ApplicationSure $parent)) { throw 'oldBackendSourceRefused' }
    return $true
  }
}
function Processus([int]$n) { return CimCmdlets\Get-CimInstance Win32_Process -Filter ('ProcessId='+$n) -OperationTimeoutSec 2 }
function MemeSid($p) {
  $o=CimCmdlets\Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid -OperationTimeoutSec 2
  return ($o.ReturnValue -eq 0 -and $o.Sid -ceq $sid)
}
function Ecoutes {
  return @(CimCmdlets\Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection -Filter 'LocalPort=8000 AND State=2' -OperationTimeoutSec 2 |
    Sort-Object LocalAddress,OwningProcess | ForEach-Object { [ordered]@{ pid=[int]$_.OwningProcess; port=[int]$_.LocalPort; address=[string]$_.LocalAddress } })
}
function Applications {
  $apps=@(Get-Process -Name 'diapason-desktop','Diapason' -ErrorAction SilentlyContinue | Sort-Object Id)
  if ($apps.Count -gt 1) { throw 'oldBackendUiActive' }
  return @($apps | ForEach-Object {
    $p=Processus $_.Id
    if (-not $p) { throw 'oldBackendUiActive' }
    [ordered]@{ pid=[int]$p.ProcessId; identity=$p.CreationDate.ToUniversalTime().ToFileTimeUtc().ToString();
      hasWindow=($_.MainWindowHandle -ne 0); sameSid=[bool](MemeSid $p);
      sameSession=([int]$p.SessionId -eq $session); executablePath=[string]$p.ExecutablePath;
      commandLine=[string]$p.CommandLine;
      createdBeforeObservation=($p.CreationDate.ToUniversalTime() -lt [DateTime]::Parse($env:OLD_OBSERVED_UTC).ToUniversalTime()) }
  })
}
function Empreinte([string]$s) {
  $h=[Security.Cryptography.SHA256]::Create()
  try { return [Convert]::ToBase64String($h.ComputeHash([Text.Encoding]::UTF8.GetBytes($s))) } finally { $h.Dispose() }
}
function Faits {
  if ($chrono.ElapsedMilliseconds -ge 25000) { throw 'oldBackendTimeout' }
  $p=Processus $numero
  if (-not $p -or -not $lease.MatchesCimCreation($p.CreationDate)) { throw 'oldBackendIdentityChanged' }
  if (-not (Possede $racine) -or -not (ApplicationSure $racine)) { throw 'oldBackendSourceRefused' }
  # 08/11/2026, diagnostic 42505534195 : l'ancien PID n'a aucun marqueur.
  # Un contenu « managed », une version ou une erreur ne prouvent pas l'absence.
  if (-not (Absent (Join-Path $racine '.diapason-backend'))) { throw 'oldBackendVersionRefused' }
  $projet=Petit (Join-Path $racine 'pyproject.toml') 65536
  $cfg=Petit (Join-Path $racine '.venv\pyvenv.cfg') 8192
  if (-not $projet -or -not $cfg) { throw 'oldBackendSourceRefused' }
  # Métadonnées [project] seulement : pas un name/version d'un autre tableau TOML.
  $sections=[regex]::Matches($projet,'(?ms)^\[project\]\s*\r?\n(.*?)(?=^\[|\z)')
  if ($sections.Count -ne 1) { throw 'oldBackendVersionRefused' }
  $texte=$sections[0].Groups[1].Value
  $noms=[regex]::Matches($texte,'(?m)^name\s*=\s*["'']([^"'']+)["'']\s*$')
  $versions=[regex]::Matches($texte,'(?m)^version\s*=\s*["'']([^"'']+)["'']\s*$')
  if ($noms.Count -ne 1 -or $versions.Count -ne 1) { throw 'oldBackendVersionRefused' }
  $base=BaseVenv $cfg
  if (-not $base -or -not (AclBaseSure (Join-Path $base 'python.exe'))) { throw 'oldBackendSourceRefused' }
  $entree=Join-Path $racine '.venv\Scripts\diapason.exe'; $python=Join-Path $racine '.venv\Scripts\python.exe'
  if ((Get-Item -LiteralPath $entree -Force).PSIsContainer -or (Get-Item -LiteralPath $python -Force).PSIsContainer) { throw 'oldBackendSourceRefused' }
  $sansBeta=Absent (Join-Path $racine 'beta-build.json'); $sansGit=Absent (Join-Path $racine '.git')
  [ordered]@{
    canonicalRoot=$racine; interactive=[Environment]::UserInteractive; runnerSession=$session
    process=[ordered]@{ pid=$numero; sameSid=((MemeSid $p) -and $lease.Sid -ceq $sid);
      sameSession=([int]$p.SessionId -eq $session -and $lease.Session -eq $session);
      handleAlive=$lease.Alive; identity=$lease.Creation.ToString();
      createdUTC=[DateTime]::FromFileTimeUtc($lease.Creation).ToString('o');
      executablePath=[string]$p.ExecutablePath; commandLine=[string]$p.CommandLine; handleImage=$lease.Image }
    source=[ordered]@{ root=$racine; rootOwned=$true; metadataOwned=$true; cfgOwned=$true;
      entryOwned=(ApplicationSure $entree); venvPythonOwned=(ApplicationSure $python);
      cfg=$cfg; resolvedHome=$base; baseVerified=$true; aclVerified=$true; reparseVerified=$true;
      projectName=$noms[0].Groups[1].Value; sourceVersion=$versions[0].Groups[1].Value;
      markerState='absent'; betaAbsent=[bool]$sansBeta; gitAbsent=[bool]$sansGit;
      metadataDigest=(Empreinte ($projet+'|absent|'+$cfg)) }
    listeners=@(Ecoutes); applications=@(Applications)
  }
}
$lease=New-Object -TypeName DiapasonOldServerLease -ArgumentList ([uint32]$numero)
$avant=Faits | ConvertTo-Json -Depth 6 -Compress
'{"stage":"attestation","facts":'+$avant+'}' | Write-Output
[Console]::Out.Flush()
$accord=ConvertFrom-Json -InputObject ([DiapasonOldServerLease]::ReadPermit())
if ($accord.permit -isnot [bool] -or $accord.permit -ne $true -or $accord.identity -cne $lease.Creation.ToString()) { throw 'oldBackendProtocolRefused' }
# Relire source/ACL/reparse/commande/SID/UI/socket sous le HANDLE ouvert initialement.
$apres=Faits | ConvertTo-Json -Depth 6 -Compress
if ($apres -cne $avant) { throw 'oldBackendFinalCheckChanged' }
if (-not (Absent (Join-Path $racine '.diapason-backend'))) { throw 'oldBackendVersionRefused' }
$stopped=$lease.StopChecked($lease.Creation,$sid,$session,$chrono)
if (-not $stopped) { throw 'oldBackendStopUnconfirmed' }
$fin=[Diagnostics.Stopwatch]::StartNew()
do {
  $portFree=@(Ecoutes).Count -eq 0
  $launcherExited=@(Get-Process -Name 'diapason-desktop','Diapason' -ErrorAction SilentlyContinue).Count -eq 0
  if ($portFree -and $launcherExited) { break }
  Start-Sleep -Milliseconds 200
} while ($fin.ElapsedMilliseconds -lt 5000)
if (-not $portFree) { throw 'oldBackendPortChanged' }
if (-not $launcherExited) { throw 'oldBackendLauncherStillRunning' }
@{ stage='result'; status='stopped'; targetStopped=$true; portFree=$true; launcherExited=$true } | ConvertTo-Json -Compress
} catch {
  $code='oldBackendNativeUnavailable'
  if ($_.Exception.Message -cmatch '^oldBackend(?:PidChanged|OwnerRefused|IdentityChanged|SourceRefused|VersionRefused|EntryRefused|PortChanged|UiActive|Timeout|ProtocolRefused|FinalCheckChanged|StopUnconfirmed|LauncherStillRunning)$') { $code=$_.Exception.Message }
  @{ stage='result'; status='refused'; code=$code; targetStopped=[bool]$stopped; portFree=[bool]$portFree; launcherExited=[bool]$launcherExited } | ConvertTo-Json -Compress
} finally { if ($lease) { $lease.Dispose() } }
`;

// 08/11/2026 : fermer l'UI laisse le Python 1.0.0 sur 8000. L'ancien
// residual-pid reste interdit ; cette autorisation désigne ce seul incident.
export function autorisationArretAncien(options, maintenant = Date.now()) {
  verifier(['residual-pid', 'residual_pid'].every(c => [undefined, '0', 0].includes(options[c])), 'personalProcessStopNotAuthorized');
  const pid = options['stop-old-backend-pid'], utc = options['stop-old-backend-observed-utc'];
  if ((pid === undefined || pid === '') && (utc === undefined || utc === '')) return null;
  verifier(pid === '48196', 'oldBackendPidNotAuthorized');
  verifier(typeof utc === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z$/.test(utc), 'oldBackendObservationInvalid');
  const ms = Date.parse(utc);
  verifier(Number.isFinite(ms) && new Date(ms).toISOString() === utc.replace(/(?<!\.\d{3})Z$/, '.000Z')
    // Une autorisation reste liée au diagnostic de cet incident, au plus 24 h.
    && maintenant >= ms && maintenant - ms < 86400000, 'oldBackendObservationInvalid');
  return Object.freeze({ pid: 48196, observedUTC: new Date(ms).toISOString() });
}

const cheminAncien = p => typeof p === 'string' && p.length <= 4096
  && /^[A-Za-z]:\\/.test(p) && !/[\x00-\x1f"<>|?*\/]/.test(p)
  && !p.slice(2).includes(':') && !p.split('\\').some(x => x === '.' || x === '..' || /[. ]$/.test(x))
  ? path.win32.normalize(p).toLowerCase().replace(/\\$/, '') : null;

function argvAncien(ligne) {
  if (typeof ligne !== 'string' || ligne.length > 8192 || /[\x00-\x1f]/.test(ligne)) return null;
  const args = []; let reste = ligne.trim();
  while (reste) {
    const m = /^(?:"([^"\r\n]*)"|([^\s"]+))(?:\s+|$)/.exec(reste);
    if (!m || m[1]?.endsWith('\\')) return null;
    args.push(m[1] ?? m[2]); reste = reste.slice(m[0].length);
  }
  return args;
}

function commandeAncienne(p, c, lanceur = false) {
  const root = cheminAncien(c.root), base = cheminAncien(c.resolvedHome);
  const exe = cheminAncien(p.executablePath), argv = argvAncien(p.commandLine);
  if (!root || !base || !exe || !argv?.length) return false;
  const entree = root + '\\.venv\\scripts\\diapason.exe', python = root + '\\.venv\\scripts\\python.exe';
  const arg0 = cheminAncien(argv.shift());
  if (lanceur) {
    if (exe !== entree || arg0 !== entree) return false;
  } else {
    if (![python, base + '\\python.exe'].includes(exe) || ![exe, python].includes(arg0)) return false;
    if (cheminAncien(argv[0]) === entree) argv.shift();
    else {
      if (exe !== python && arg0 !== python) return false;
      while (['-I', '-B', '-u', '-S'].includes(argv[0])) argv.shift();
      if (argv.shift() !== '-m' || argv.shift() !== 'diapason') return false;
    }
  }
  if (argv.shift() !== 'serve') return false;
  const vus = new Set();
  while (argv.length) {
    const cle = argv.shift(), valeur = argv.shift();
    if (vus.has(cle) || !['--port', '--host'].includes(cle)
      || (cle === '--port' ? valeur !== '8000' : valeur !== '127.0.0.1')) return false;
    vus.add(cle);
  }
  return true;
}

/** Faits privés lus sous un HANDLE conservé : aucune clé/config de profil. */
export function validerArretAncien(n, a) {
  const p = n?.process, c = n?.source;
  verifier(a?.pid === 48196 && p?.pid === a.pid, 'oldBackendPidChanged');
  verifier(n.interactive === true && p.sameSid === true && p.sameSession === true
    && Number.isInteger(n.runnerSession) && n.runnerSession > 0, 'oldBackendOwnerRefused');
  verifier(p.handleAlive === true && typeof p.identity === 'string' && /^\d{1,20}$/.test(p.identity)
    && typeof p.createdUTC === 'string' && Number.isFinite(Date.parse(p.createdUTC))
    && Date.parse(p.createdUTC) < Date.parse(a.observedUTC), 'oldBackendIdentityChanged');
  const root = cheminAncien(c?.root), attendu = cheminAncien(n.canonicalRoot);
  verifier(root && root === attendu && c.rootOwned === true && c.metadataOwned === true
    && c.cfgOwned === true && c.entryOwned === true && c.venvPythonOwned === true
    && c.baseVerified === true && c.aclVerified === true && c.reparseVerified === true,
  'oldBackendSourceRefused');
  verifier(c.projectName === 'Diapason' && c.sourceVersion === '1.0.0'
    && c.markerState === 'absent' && c.betaAbsent === true && c.gitAbsent === true,
  'oldBackendVersionRefused');
  const homes = typeof c.cfg === 'string' && Buffer.byteLength(c.cfg) <= 8192
    ? c.cfg.split(/\r?\n/).flatMap(l => { const m = /^\s*home\s*=\s*(.*?)\s*$/.exec(l); return m ? [cheminAncien(m[1])] : []; }) : [];
  const home = homes[0], base = cheminAncien(c.resolvedHome);
  const aliasUv = home && base && path.win32.basename(home) === 'cpython-3.13-windows-x86_64-none'
    && /^cpython-3\.13\.\d+-windows-x86_64-none$/.test(path.win32.basename(base))
    && path.win32.dirname(home) === path.win32.dirname(base);
  verifier(homes.length === 1 && home && base && (home === base || aliasUv)
    && cheminAncien(p.executablePath) === cheminAncien(p.handleImage)
    && commandeAncienne(p, c), 'oldBackendEntryRefused');
  verifier(Array.isArray(n.listeners) && n.listeners.length > 0 && n.listeners.length <= 4
    && n.listeners.every(l => l.pid === a.pid && l.port === 8000
      && ['127.0.0.1', '::1'].includes(l.address)), 'oldBackendPortChanged');
  verifier(Array.isArray(n.applications) && n.applications.length <= 1
    && n.applications.every(x => x.hasWindow === false && x.sameSid === true && x.sameSession === true
      && x.createdBeforeObservation === true && commandeAncienne(x, c, true)), 'oldBackendUiActive');
  return true;
}

const CODES_ARRET_ANCIEN = new Set(['oldBackendPidChanged', 'oldBackendOwnerRefused',
  'oldBackendIdentityChanged', 'oldBackendSourceRefused', 'oldBackendVersionRefused',
  'oldBackendEntryRefused', 'oldBackendPortChanged', 'oldBackendUiActive',
  'oldBackendNativeUnavailable', 'oldBackendTimeout', 'oldBackendProtocolRefused',
  'oldBackendFinalCheckChanged', 'oldBackendStopUnconfirmed', 'oldBackendLauncherStillRunning']);
export function rapportArretAncien(r = {}) {
  return { requested: r.requested === true, status: ['notRequested', 'refused', 'stopped'].includes(r.status) ? r.status : 'refused',
    code: CODES_ARRET_ANCIEN.has(r.code) ? r.code : null,
    targetStopped: r.targetStopped === true, portFree: r.portFree === true,
    launcherExited: r.launcherExited === true };
}

export async function arreterAncienBackend(a, { platform = process.platform, systeme = process.env,
  lancer = spawn, minuter = setTimeout, demuter = clearTimeout } = {}) {
  if (!a) return rapportArretAncien({ status: 'notRequested' });
  // Valider aussi les appels programmatiques ; seul le couple CLI validé est admis.
  autorisationArretAncien({ 'stop-old-backend-pid': String(a.pid), 'stop-old-backend-observed-utc': a.observedUTC });
  if (platform !== 'win32') return rapportArretAncien({ requested: true, status: 'refused', code: 'oldBackendNativeUnavailable' });
  const windows = systeme.SystemRoot;
  if (!cheminAncien(windows)) return rapportArretAncien({ requested: true, status: 'refused', code: 'oldBackendNativeUnavailable' });
  return new Promise(resolve => {
    let fini = false, enfant, taille = 0, tampon = '', autorise = false;
    const finir = r => {
      if (fini) return; fini = true; demuter(delai);
      enfant?.stdin?.destroy(); enfant?.stdout?.destroy(); enfant?.stderr?.destroy(); enfant?.unref();
      resolve(rapportArretAncien({ status: 'refused', ...r, requested: true }));
    };
    // La sonde ne peut plus envoyer TerminateProcess après 25 s. Dix secondes
    // restent pour confirmer la sortie/port ; le parent abandonne à 40 s.
    const delai = minuter(() => finir({ code: 'oldBackendTimeout' }), 40000);
    try {
      const bootstrap = "[Console]::InputEncoding=[Text.Encoding]::ASCII; $s=[Console]::In.ReadLine(); & ([ScriptBlock]::Create([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($s))))";
      enfant = lancer(path.win32.join(windows, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'),
        ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(bootstrap, 'utf16le').toString('base64')],
        { shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], env: {
          SystemRoot: windows, WINDIR: windows, PATH: path.win32.join(windows, 'System32'),
          PSModulePath: path.win32.join(windows, 'System32', 'WindowsPowerShell', 'v1.0', 'Modules'),
          OLD_PID: String(a.pid), OLD_OBSERVED_UTC: a.observedUTC,
        } });
      enfant.stdout.on('data', b => {
        if (fini) return;
        taille += b.length;
        if (taille > 32768) return finir({ code: 'oldBackendProtocolRefused' });
        tampon += b.toString('utf8');
        while (tampon.includes('\n') && !fini) {
          const i = tampon.indexOf('\n'), ligne = tampon.slice(0, i).replace(/^\uFEFF/, '').trim(); tampon = tampon.slice(i + 1);
          try {
            const n = JSON.parse(ligne);
            if (n.stage === 'attestation' && !autorise) {
              validerArretAncien(n.facts, a); autorise = true;
              // Le fils compare de nouveau TOUS les faits sous le même HANDLE.
              enfant.stdin.write(JSON.stringify({ permit: true, identity: n.facts.process.identity }) + '\n');
            } else if (n.stage === 'result' && n.status === 'stopped' && autorise
              && n.targetStopped === true && n.portFree === true && n.launcherExited === true) finir(n);
            else if (n.stage === 'result' && n.status === 'refused' && CODES_ARRET_ANCIEN.has(n.code)) finir(n);
            else finir({ code: 'oldBackendProtocolRefused' });
          } catch (e) { finir({ code: CODES_ARRET_ANCIEN.has(e.message) ? e.message : 'oldBackendProtocolRefused' }); }
        }
      });
      enfant.stderr.on('data', () => {});
      enfant.on('error', () => finir({ code: 'oldBackendNativeUnavailable' }));
      enfant.on('close', () => finir({ code: 'oldBackendProtocolRefused' }));
      enfant.stdin.on('error', () => finir({ code: 'oldBackendProtocolRefused' }));
      enfant.stdin.write(Buffer.from(ARRET_ANCIEN_POWERSHELL, 'utf16le').toString('base64') + '\n');
    } catch { finir({ code: 'oldBackendNativeUnavailable' }); }
  });
}

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
  return rapport?.installerExecuted === true
    && CONTROLES.every(c => rapport.checks?.[c] === true)
    && ['fresh', 'legacy'].includes(rapport.scenario)
    && (rapport.scenario !== 'legacy' || (
      CONTROLES_LEGACY.every(c => rapport.checks?.[c] === true)
      && rapport.legacyRefusal?.observed === true
      && rapport.legacyRefusal?.ownedServerAlive === true
      && rapport.legacyRefusal?.bootstrapUnchanged === true
      && rapport.legacyRefusal?.ownedServerStopped === true
      && Number.isSafeInteger(rapport.legacyRefusal?.appHealthRequests)
      && rapport.legacyRefusal?.appHealthRequests > 0
      && rapport.legacyPersistence?.seededBeforeLaunch === true
      && rapport.legacyPersistence?.afterStartup === true
      && rapport.legacyPersistence?.afterRestart === true
      && rapport.legacyPersistence?.sameKey === true))
    && rapport.failureCode === null && !rapport.cleanupFailed;
}

export function verifierBackendCourant(sante, version) {
  assert.equal(sante?.status, 'ok');
  assert.equal(sante.managementApiVersion, 1);
  assert.equal(sante.backendVersion, version);
}

export function preparerAncienneSourceSynthétique(env) {
  const racine = path.join(env.LOCALAPPDATA, 'Diapason', 'src');
  const fichiers = [
    [path.join(racine, 'pyproject.toml'), '[project]\nname = "Diapason"\nversion = "1.0.0"\n'],
    [path.join(racine, 'temoin-ancienne-source.txt'), 'Corpus synthétique : ancienne source à conserver.\n'],
  ];
  for (const [fichier, contenu] of fichiers) {
    fs.mkdirSync(path.dirname(fichier), { recursive: true });
    fs.writeFileSync(fichier, contenu, { flag: 'wx' });
  }
  const memoire = path.join(env.HOME, '.diapason', 'project_root');
  fs.mkdirSync(path.dirname(memoire), { recursive: true });
  fs.writeFileSync(memoire, racine, { flag: 'wx' });
  return () => fichiers.every(([fichier, contenu]) => fs.existsSync(fichier)
    && fs.readFileSync(fichier, 'utf8') === contenu);
}

// Six tables extraites des constantes SQL de la source33 gelée ; seul le
// préfixe vie_ devient succes_ pour exercer la migration du véritable serveur.
export const SCHEMA_LEGACY_SOURCE = {"sha256": "ffd46e8b0fe31b207bfef318dde80c2a8c9d9e9be611ad2746b20e95cf65b359", "snapshotSha256": "3c96b465994b1b7482a1859a830634c66d02703a8b3cad190b8e439720bb89b8", "files": {"src/diapason/vie/store.py": "26428951291e05445f5fb831d959852be61d99622cc22dd012e6b982c6a4092c", "src/diapason/vie/workspace.py": "9b90b2ab665fc1a7e4708ae000ec88439fd36be97953ca23691ea53b19bb9d78", "src/diapason/vie/finances.py": "cf2954512efdca434925f994056d681fa50996ab0d28a36e47d073c6c0e9c051"}};
export const SCHEMA_LEGACY_SQL = "CREATE TABLE IF NOT EXISTS succes_meta (\n    key TEXT PRIMARY KEY,\n    value TEXT NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS succes_projects (\n    id TEXT PRIMARY KEY,\n    name TEXT NOT NULL,\n    description TEXT NOT NULL DEFAULT '',\n    color TEXT NOT NULL DEFAULT '#6366f1',\n    icon TEXT NOT NULL DEFAULT '',\n    start_date TEXT NOT NULL DEFAULT '',\n    end_date TEXT NOT NULL DEFAULT '',\n    created_date TEXT NOT NULL DEFAULT '',\n    updated_at_ms INTEGER NOT NULL,\n    deleted_at_ms INTEGER,\n    order_index INTEGER NOT NULL DEFAULT 0\n);\n\nCREATE TABLE IF NOT EXISTS succes_notes (\n    id TEXT PRIMARY KEY,\n    title TEXT NOT NULL,\n    content TEXT NOT NULL DEFAULT '',\n    created_at TEXT NOT NULL,\n    updated_at TEXT NOT NULL,\n    updated_at_ms INTEGER NOT NULL,\n    deleted_at_ms INTEGER,\n    page_format TEXT NOT NULL DEFAULT 'a4',\n    page_size TEXT NOT NULL DEFAULT 'a4',\n    page_orientation TEXT NOT NULL DEFAULT 'portrait',\n    page_margins TEXT NOT NULL DEFAULT 'normales',\n    page_background TEXT NOT NULL DEFAULT 'default',\n    font_family TEXT NOT NULL DEFAULT 'Special Elite',\n    doc_lang TEXT NOT NULL DEFAULT 'fr',\n    color TEXT NOT NULL DEFAULT '#6366f1',\n    reading_mark INTEGER NOT NULL DEFAULT 0,\n    category TEXT NOT NULL DEFAULT '',\n    project_id TEXT NOT NULL DEFAULT '',\n    order_index INTEGER NOT NULL DEFAULT 0\n);\n\nCREATE TABLE IF NOT EXISTS succes_accounts (\n    id TEXT PRIMARY KEY,\n    name TEXT NOT NULL,\n    account_type TEXT NOT NULL DEFAULT 'checking',\n    currency TEXT NOT NULL DEFAULT 'CAD',\n    opening_balance_cents INTEGER NOT NULL DEFAULT 0,\n    color TEXT NOT NULL DEFAULT '#6366f1',\n    icon TEXT NOT NULL DEFAULT '🏦',\n    archived INTEGER NOT NULL DEFAULT 0,\n    updated_at_ms INTEGER NOT NULL,\n    deleted_at_ms INTEGER\n);\n\nCREATE TABLE IF NOT EXISTS succes_finance_categories (\n    id TEXT PRIMARY KEY,\n    name TEXT NOT NULL,\n    kind TEXT NOT NULL DEFAULT 'expense',\n    color TEXT NOT NULL DEFAULT '#6366f1',\n    icon TEXT NOT NULL DEFAULT '📦',\n    system INTEGER NOT NULL DEFAULT 0,\n    updated_at_ms INTEGER NOT NULL,\n    deleted_at_ms INTEGER\n);\n\nCREATE TABLE IF NOT EXISTS succes_transactions (\n    id TEXT PRIMARY KEY,\n    account_id TEXT NOT NULL,\n    category_id TEXT NOT NULL DEFAULT '',\n    txn_type TEXT NOT NULL DEFAULT 'expense',\n    amount_cents INTEGER NOT NULL,\n    currency TEXT NOT NULL DEFAULT 'CAD',\n    txn_date TEXT NOT NULL,\n    payee TEXT NOT NULL DEFAULT '',\n    notes TEXT NOT NULL DEFAULT '',\n    transfer_account_id TEXT NOT NULL DEFAULT '',\n    subscription_id TEXT NOT NULL DEFAULT '',\n    import_hash TEXT NOT NULL DEFAULT '',\n    updated_at_ms INTEGER NOT NULL,\n    deleted_at_ms INTEGER\n);\n";

export function verifierProfilQa(env, travail) {
  const racine = fs.realpathSync(travail);
  verifier(!fs.lstatSync(travail).isSymbolicLink(), 'qaWorkdirLinked');
  verifier(path.relative(racine, path.resolve(env.HOME)) === 'profil'
    && path.resolve(env.USERPROFILE) === path.resolve(env.HOME), 'qaProfileOutsideWorkdir');
  for (const valeur of [env.HOME, env.LOCALAPPDATA, env.APPDATA, env.UV_CACHE_DIR,
    env.UV_PYTHON_INSTALL_DIR, env.OLLAMA_MODELS, env.HF_HOME]) {
    const relatif = path.relative(racine, path.resolve(valeur));
    verifier(relatif && !relatif.startsWith('..') && !path.isAbsolute(relatif), 'qaPathOutsideWorkdir');
    let courant = path.resolve(valeur);
    while (path.relative(racine, courant) !== '') {
      try {
        verifier(!fs.lstatSync(courant).isSymbolicLink(), 'qaPathLinked');
      } catch (e) { if (e.code !== 'ENOENT') throw e; }
      courant = path.dirname(courant);
    }
  }
  verifier(!env.DIAPASON_HOME && !env.DIAPASON_ROOT && !env.DIAPASON_API_KEY, 'qaEnvironmentOverride');
  return racine;
}

export async function preparerDonneesLegacy(env, travail) {
  verifierProfilQa(env, travail);
  const home = path.join(env.HOME, '.diapason');
  const base = path.join(home, 'succes.db'), clePath = path.join(home, 'auth', 'local_api_key');
  verifier(!fs.existsSync(base) && !fs.existsSync(path.join(home, 'vie.db'))
    && !fs.existsSync(clePath), 'legacyDataAlreadyExists');
  const { DatabaseSync } = await import('node:sqlite');
  fs.mkdirSync(path.dirname(clePath), { recursive: true });
  const cle = 'diapason_sk_' + randomBytes(32).toString('base64url');
  fs.writeFileSync(clePath, cle + '\n', { flag: 'wx', mode: 0o600 });
  fs.closeSync(fs.openSync(base, 'wx', 0o600));
  const id = 'qa-' + randomUUID();
  const date = new Date().toISOString().slice(0, 10), stamp = Date.now() - 1000;
  const fixture = {
    home, base, clePath, cle,
    deviceId: id + '-device',
    project: { id: id + '-project', name: 'Projet antérieur synthétique', description: 'Créé avant le premier EXE33' },
    note: { id: id + '-note', title: 'Note antérieure synthétique', content: 'Ce texte existait avant la réparation et doit rester identique.' },
    account: { id: id + '-account', name: 'Compte synthétique antérieur', openingCents: 100000 },
    categoryId: id + '-category',
    transaction: { id: id + '-transaction', amountCents: 3537, date, payee: 'Commerce synthétique antérieur' },
  };
  const db = new DatabaseSync(base);
  try {
    db.exec('PRAGMA journal_mode=DELETE; PRAGMA user_version=5; BEGIN IMMEDIATE;');
    db.exec(SCHEMA_LEGACY_SQL);
    db.prepare('INSERT INTO succes_meta(key,value) VALUES (?,?)').run('device_id', fixture.deviceId);
    db.prepare('INSERT INTO succes_projects(id,name,description,created_date,updated_at_ms) VALUES (?,?,?,?,?)')
      .run(fixture.project.id, fixture.project.name, fixture.project.description, date, stamp);
    db.prepare('INSERT INTO succes_notes(id,title,content,created_at,updated_at,updated_at_ms,project_id) VALUES (?,?,?,?,?,?,?)')
      .run(fixture.note.id, fixture.note.title, fixture.note.content, new Date(stamp).toISOString(), new Date(stamp).toISOString(), stamp, fixture.project.id);
    db.prepare('INSERT INTO succes_accounts(id,name,opening_balance_cents,updated_at_ms) VALUES (?,?,?,?)')
      .run(fixture.account.id, fixture.account.name, fixture.account.openingCents, stamp);
    db.prepare('INSERT INTO succes_finance_categories(id,name,kind,updated_at_ms) VALUES (?,?,?,?)')
      .run(fixture.categoryId, 'Dépense synthétique', 'expense', stamp);
    db.prepare('INSERT INTO succes_transactions(id,account_id,category_id,txn_type,amount_cents,txn_date,payee,updated_at_ms) VALUES (?,?,?,?,?,?,?,?)')
      .run(fixture.transaction.id, fixture.account.id, fixture.categoryId, 'expense', fixture.transaction.amountCents, date, fixture.transaction.payee, stamp);
    db.exec('COMMIT;');
    verifier(db.prepare('PRAGMA integrity_check').get().integrity_check === 'ok', 'legacyFixtureInvalid');
  } finally { db.close(); }
  return fixture;
}

export async function verifierDonneesLegacy(fixture, api, cle) {
  verifier(cle === fixture.cle && fs.readFileSync(fixture.clePath, 'utf8').trim() === fixture.cle, 'legacyKeyChanged');
  const projets = await api('/v1/vie/projects');
  const projet = projets.projects?.find(p => p.id === fixture.project.id);
  verifier(projet?.name === fixture.project.name && projet.description === fixture.project.description, 'legacyProjectChanged');
  const note = (await api('/v1/vie/notes/' + encodeURIComponent(fixture.note.id))).note;
  verifier(note?.title === fixture.note.title && note.content === fixture.note.content
    && note.projectId === fixture.project.id, 'legacyNoteChanged');
  const comptes = await api('/v1/vie/finances/accounts');
  const compte = comptes.accounts?.find(c => c.id === fixture.account.id);
  verifier(compte?.name === fixture.account.name && compte.currency === 'CAD'
    && Math.round(compte.openingBalance * 100) === fixture.account.openingCents
    && Math.round(compte.balance * 100) === fixture.account.openingCents - fixture.transaction.amountCents, 'legacyAccountChanged');
  const transactions = await api('/v1/vie/finances/transactions?accountId=' + encodeURIComponent(fixture.account.id));
  const txn = transactions.transactions?.find(t => t.id === fixture.transaction.id);
  verifier(txn?.accountId === fixture.account.id && txn.categoryId === fixture.categoryId
    && txn.type === 'expense' && txn.currency === 'CAD' && txn.date === fixture.transaction.date
    && txn.payee === fixture.transaction.payee
    && Math.round(txn.amount * 100) === fixture.transaction.amountCents, 'legacyTransactionChanged');
  const finances = await api('/v1/vie/finances/overview?period=month&anchor=' + fixture.transaction.date);
  verifier(finances.transactionCount === 1 && Math.round(finances.expense * 100) === fixture.transaction.amountCents,
    'legacyFinanceOverviewChanged');
  return { matches: true, sameKey: true };
}

export function empreinteAmorcageLegacy(env, travail) {
  verifierProfilQa(env, travail);
  const resultat = [];
  const racines = [path.join(env.LOCALAPPDATA, 'Diapason'), path.join(env.HOME, '.diapason'),
    env.UV_CACHE_DIR, env.UV_PYTHON_INSTALL_DIR, env.OLLAMA_MODELS, env.HF_HOME];
  const visiter = (racine, relatif = '') => {
    const fichier = path.join(racine, relatif);
    if (!fs.existsSync(fichier)) return;
    const stat = fs.lstatSync(fichier);
    verifier(!stat.isSymbolicLink(), 'legacySnapshotLinked');
    verifier(resultat.length < 20000, 'legacySnapshotTooLarge');
    if (stat.isDirectory()) {
      resultat.push([racines.indexOf(racine), relatif, 'directory']);
      for (const nom of fs.readdirSync(fichier).sort()) visiter(racine, path.join(relatif, nom));
    } else {
      verifier(stat.isFile(), 'legacySnapshotNotRegular');
      // Un mauvais amorçage pourrait déjà télécharger des Go : constater
      // leur apparition suffit, sans charger ces fichiers dans le banc.
      const hash = stat.size <= 64 * 1024 * 1024
        ? createHash('sha256').update(fs.readFileSync(fichier)).digest('hex') : 'oversized';
      resultat.push([racines.indexOf(racine), relatif, 'file', stat.size, stat.mtimeMs, hash]);
    }
  };
  for (const racine of racines) visiter(racine);
  return createHash('sha256').update(JSON.stringify(resultat)).digest('hex');
}

export async function creerAncienServeurSynthétique(port = 8000) {
  verifier(Number.isInteger(port) && port >= 0 && port < 65536, 'legacyStubPortInvalid');
  const nonce = randomBytes(32).toString('hex'), sockets = new Set();
  let appHealthRequests = 0, ferme = false;
  const serveur = http.createServer((req, res) => {
    if (req.url === '/health' && req.method === 'GET') {
      if (req.headers['x-diapason-qa-owner'] !== nonce) appHealthRequests++;
      res.writeHead(200, { 'Content-Type': 'application/json', 'X-Diapason-QA-Owner': nonce });
      res.end('{"status":"ok"}');
    } else { res.writeHead(404); res.end('{}'); }
  });
  serveur.on('connection', socket => { sockets.add(socket); socket.once('close', () => sockets.delete(socket)); });
  await new Promise((resolve, reject) => {
    serveur.once('error', reject); serveur.listen({ host: '127.0.0.1', port, exclusive: true }, resolve);
  });
  const adresse = serveur.address();
  return Object.freeze({
    port: adresse.port,
    mesures: () => ({ appHealthRequests, listening: serveur.listening && !ferme }),
    async verifierVivant() {
      verifier(serveur.listening && !ferme, 'legacyStubStoppedUnexpectedly');
      const r = await fetch(`http://127.0.0.1:${adresse.port}/health`, {
        headers: { 'X-Diapason-QA-Owner': nonce }, signal: AbortSignal.timeout(2000), redirect: 'error',
      });
      verifier(r.status === 200 && r.headers.get('X-Diapason-QA-Owner') === nonce
        && (await r.json()).status === 'ok', 'legacyStubOwnershipChanged');
      return true;
    },
    async fermer() {
      if (ferme) return;
      ferme = true;
      await new Promise((resolve, reject) => {
        serveur.close(e => e ? reject(e) : resolve());
        for (const socket of sockets) socket.destroy();
        serveur.closeAllConnections();
      });
    },
  });
}

export function verifierRefusServeurLegacy(etat, log, version, faits) {
  verifier(typeof etat?.error === 'string' && etat.error.length > 0
    && etat.server_ready === false && etat.backend_ready === false
    && etat.ollama_ready === false && etat.model_ready === false, 'legacyServerNotRejected');
  verifier(log.split(/\r?\n/).some(ligne => {
    const champs = ligne.trim().split(/\s+/);
    return champs[0] === 'DIAPASON_WINDOWS_BACKEND_MISMATCH'
      && champs.includes('expectedVersion=' + version);
  }), 'legacyRefusalReasonUnproven');
  verifier(faits.ownedServerAlive === true && Number.isSafeInteger(faits.appHealthRequests)
    && faits.appHealthRequests > 0, 'legacyServerNotPreserved');
  verifier(faits.bootstrapUnchanged === true, 'legacyBootstrapMutated');
  return true;
}

export async function verifierBlocageLegacy({ version, empreinte, lancer, arreter, lireLog,
  creerStub = () => creerAncienServeurSynthétique() }) {
  const avant = empreinte();
  const stub = await creerStub();
  let applicationArretee = false, preuve;
  try {
    const etat = await lancer(stub);
    const faits = { ownedServerAlive: await stub.verifierVivant(),
      appHealthRequests: stub.mesures().appHealthRequests,
      bootstrapUnchanged: empreinte() === avant };
    verifierRefusServeurLegacy(etat, lireLog(), version, faits);
    await arreter(stub); applicationArretee = true;
    await stub.verifierVivant();
    verifier(empreinte() === avant, 'legacyCleanupMutatedBootstrap');
    preuve = { ...faits, observed: true, ownedServerStopped: false };
  } finally {
    // Fermer la fenêtre QA avant de libérer le port du stub, même en échec :
    // une app encore vivante ne doit pas repartir en amorçage à cet instant.
    // Si l'arrêt de la fenêtre échoue, garder le port occupé : le nettoyage
    // extérieur réessaiera. Le libérer ici autoriserait un amorçage tardif.
    if (!applicationArretee) await arreter(stub);
    await stub.fermer();
  }
  preuve.ownedServerStopped = true;
  return preuve;
}

export function erreurDemarragePubliable(erreur) {
  // 07/11/2026 : 1 500 caractères coupaient la pile avant l'appel fautif.
  // Garder 12 Kio de diagnostic du seul profil synthétique, chemins masqués.
  return String(erreur).replace(/[A-Za-z]:[\\/][^\s"']+/g, '<qa-path>')
    .replace(/Bearer\s+\S+/gi, 'Bearer <redacted>').slice(0, 12000);
}

export function residuFermable(bureau, pid) {
  const apps = bureau.existingApplications;
  return Number.isInteger(pid) && pid > 0 && bureau.interactive === true
    && Array.isArray(apps) && apps.length === 1 && apps[0].processId === pid
    && apps[0].sessionId === bureau.sessionId && apps[0].hasWindow === false
    && apps[0].pathReadable === true && apps[0].processName?.toLowerCase() === 'diapason';
}

export function ollamaPartageable(listeners, sessionId) {
  if (!Array.isArray(listeners) || listeners.length === 0) return false;
  const pid = listeners[0].processId;
  return Number.isInteger(pid) && pid > 0 && listeners.every(p => p.port === 11434
    && p.processId === pid && p.sessionId === sessionId && p.loopback === true
    && p.processName?.toLowerCase() === 'ollama' && p.executableIsOllama === true);
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
  if (r.code !== 0) {
    const code = r.stderr.match(/\b(registry(?:ParentMissing|RenameFailed|ExportFailed|SelfTestFailed|ScopeRefused|StateMismatch|BackupAlreadyExists|ModeRefused)|machineInstallationRequiresSeparatePc|originalRegistryChanged|originalBinaryChanged|residualProcessChanged|residualProcessStopFailed)\b/);
    throw new Error(code?.[1] || 'windowsPreflightOrMetadataFailed');
  }
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
            if ($env:DIAPASON_E2E_SUFFIX -and $nom.EndsWith($env:DIAPASON_E2E_SUFFIX, [StringComparison]::Ordinal)) { continue }
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

// Le PC de construction porte déjà Diapason. Ses clés sont RENOMMÉES,
// jamais réécrites : l'installateur voit un emplacement neuf et les clés
// d'origine restent récupérables même si le runner s'arrête brutalement.
const REGISTRE_ISOLE = String.raw`
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DiapasonRegRename {
  [DllImport("advapi32.dll", CharSet=CharSet.Unicode, ExactSpelling=true)]
  public static extern int RegRenameKey(IntPtr parent, string oldName, string newName);
}
'@
$base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
$etatPath = Join-Path $env:DIAPASON_E2E_BACKUP 'etat.json'
$reg = Join-Path $env:SystemRoot 'System32\reg.exe'
function Renommer([string]$path, [string]$nouveau) {
  $parentPath = $path.Substring(0, $path.LastIndexOf('\'))
  $ancien = $path.Substring($path.LastIndexOf('\') + 1)
  $parent = $base.OpenSubKey($parentPath, $true)
  try {
    if (-not $parent) { throw 'registryParentMissing' }
    $code = [DiapasonRegRename]::RegRenameKey($parent.Handle.DangerousGetHandle(), $ancien, $nouveau)
    if ($code -ne 0) { throw 'registryRenameFailed' }
  } finally { if ($parent) { $parent.Dispose() } }
}
function Exporter([string]$path, [string]$fichier) {
  & $reg export ('HKCU\' + $path) $fichier /y 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'registryExportFailed' }
  return (Get-FileHash -LiteralPath $fichier -Algorithm SHA256).Hash
}
function Autorisee([string]$path) {
  return $path -ieq 'Software\Microsoft\Windows\CurrentVersion\Uninstall\Diapason' -or
    $path -ieq 'Software\Classes\diapason' -or $path -match '^Software\\[^\\]+\\Diapason$'
}
function Cles([string]$suffixe) {
  $paths = @('Software\Microsoft\Windows\CurrentVersion\Uninstall\Diapason', 'Software\Classes\diapason')
  $software = $base.OpenSubKey('Software')
  try {
    foreach ($nom in $software.GetSubKeyNames()) {
      if ($nom -ieq 'Classes') { continue }
      $path = 'Software\' + $nom + '\Diapason'
      $cle = $base.OpenSubKey($path)
      if ($cle) { $paths += $path; $cle.Dispose() }
    }
  } finally { $software.Dispose() }
  return @($paths | Select-Object -Unique | Where-Object {
    $cle = $base.OpenSubKey($_)
    if ($cle) { $cle.Dispose(); $true } else { $false }
  })
}
function Appartient([Microsoft.Win32.RegistryKey]$cle, [string]$dossier, [int]$profondeur=0) {
  if ($profondeur -gt 8) { throw 'unexpectedRegistryDepth' }
  foreach ($nom in $cle.GetValueNames()) {
    $v = $cle.GetValue($nom, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    if ($v -is [string] -and $v.IndexOf($dossier, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
  }
  foreach ($nom in $cle.GetSubKeyNames()) {
    $enfant = $cle.OpenSubKey($nom)
    try { if (Appartient $enfant $dossier ($profondeur+1)) { return $true } }
    finally { $enfant.Dispose() }
  }
  return $false
}
try {
  if ($env:DIAPASON_E2E_REG_MODE -eq 'prepare') {
    if (Test-Path -LiteralPath $etatPath) { throw 'registryBackupAlreadyExists' }
    New-Item -ItemType Directory -Path $env:DIAPASON_E2E_BACKUP -Force | Out-Null
    # Eprouver le renommage sur NOTRE clé avant de toucher à Diapason.
    $test = 'Software\DiapasonInstallationTests\' + $env:DIAPASON_E2E_NONCE
    $k = $base.CreateSubKey($test + '\avant'); $k.SetValue('preuve', '37'); $k.Dispose()
    try {
      Renommer ($test + '\avant') 'apres'
      $k = $base.OpenSubKey($test + '\apres')
      try { if ($k.GetValue('preuve') -ne '37') { throw 'registrySelfTestFailed' } } finally { $k.Dispose() }
      Renommer ($test + '\apres') 'avant'
    } finally { $base.DeleteSubKeyTree($test, $false) }
    # Aucun ancien MSI ni installation machine ne doit être désinstallé.
    foreach ($vue in @([Microsoft.Win32.RegistryView]::Registry64,[Microsoft.Win32.RegistryView]::Registry32)) {
      $machine = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,$vue)
      try {
        $u = $machine.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall')
        try {
          foreach ($nom in $u.GetSubKeyNames()) {
            $k=$u.OpenSubKey($nom)
            try { if ($k -and ([string]$k.GetValue('DisplayName')) -match '^Diapason(?:\s|$)') { throw 'machineInstallationRequiresSeparatePc' } }
            finally { if ($k) {$k.Dispose()} }
          }
        } finally { if ($u) {$u.Dispose()} }
      } finally {$machine.Dispose()}
    }
    $cles = @(); $binaires = @(); $i = 0
    foreach ($path in @(Cles '')) {
      if (-not (Autorisee $path)) { throw 'registryScopeRefused' }
      $fichier = Join-Path $env:DIAPASON_E2E_BACKUP ('cle-{0}.reg' -f $i)
      $empreinte = Exporter $path $fichier
      $cle = $base.OpenSubKey($path)
      try {
        foreach ($valeur in @('InstallLocation','')) {
          $dir = ([string]$cle.GetValue($valeur)).Trim('"')
          if ($dir -notmatch '^[A-Za-z]:\\' -or $dir -eq $env:DIAPASON_E2E_INSTALL) { continue }
          foreach ($nom in @('diapason.exe','diapason-desktop.exe','uninstall.exe')) {
            $exe = Join-Path $dir $nom
            if (@($binaires | Where-Object { $_.path -ieq $exe }).Count -gt 0) { continue }
            if (Test-Path -LiteralPath $exe -PathType Leaf) {
              $hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
              $copie = Join-Path $env:DIAPASON_E2E_BACKUP ('binaire-{0}.bin' -f $binaires.Count)
              Copy-Item -LiteralPath $exe -Destination $copie
              $binaires += @{ path=$exe; sha256=$hash; copy=$copie }
            }
          }
        }
      } finally {$cle.Dispose()}
      $cles += @{path=$path; backupName=($path.Substring($path.LastIndexOf('\')+1)+$env:DIAPASON_E2E_SUFFIX); sha256=$empreinte}
      $i++
    }
    $etat = @{ nonce=$env:DIAPASON_E2E_NONCE; installDir=$env:DIAPASON_E2E_INSTALL; keys=$cles; binaries=$binaires; restored=$false; appPid=0 }
    $etat | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $etatPath -Encoding UTF8
    foreach ($cle in $cles) {
      $k=$base.OpenSubKey($cle.path)
      if ($k) { $k.Dispose(); Renommer $cle.path $cle.backupName }
    }
    @{ prepared=$true; selfTestPassed=$true; originalKeys=$cles.Count; originalBinaries=$binaires.Count } | ConvertTo-Json -Compress
  } elseif ($env:DIAPASON_E2E_REG_MODE -eq 'restore') {
    if (-not (Test-Path -LiteralPath $etatPath)) { @{restored=$true; preserved=$true} | ConvertTo-Json -Compress; exit }
    $etat = Get-Content -LiteralPath $etatPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($etat.nonce -ne $env:DIAPASON_E2E_NONCE -or $etat.installDir -ne $env:DIAPASON_E2E_INSTALL) { throw 'registryStateMismatch' }
    if (-not $etat.restored) {
      foreach ($path in @(Cles '')) {
        $k = $base.OpenSubKey($path)
        try { $notre = Appartient $k $etat.installDir } finally {$k.Dispose()}
        # Supprimer uniquement les clés créées par CET installateur.
        if ($notre) { $base.DeleteSubKeyTree($path, $false) }
      }
      foreach ($cle in $etat.keys) {
        if (-not (Autorisee $cle.path) -or -not $cle.backupName.EndsWith($env:DIAPASON_E2E_SUFFIX,[StringComparison]::Ordinal)) { throw 'registryScopeRefused' }
        $parent = $cle.path.Substring(0,$cle.path.LastIndexOf('\'))
        $backup = $parent + '\' + $cle.backupName
        $k=$base.OpenSubKey($backup)
        if ($k) { $k.Dispose(); Renommer $backup $cle.path.Substring($cle.path.LastIndexOf('\')+1) }
        $apres = Exporter $cle.path (Join-Path $env:DIAPASON_E2E_BACKUP 'controle.reg')
        if ($apres -ne $cle.sha256) { throw 'originalRegistryChanged' }
      }
      foreach ($b in $etat.binaries) {
        if (-not (Test-Path -LiteralPath $b.path) -or (Get-FileHash -LiteralPath $b.path -Algorithm SHA256).Hash -ne $b.sha256) { throw 'originalBinaryChanged' }
      }
      $etat.restored=$true
      $etat | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $etatPath -Encoding UTF8
    }
    @{ restored=$true; preserved=$true; originalKeys=@($etat.keys).Count; originalBinaries=@($etat.binaries).Count } | ConvertTo-Json -Compress
  } else { throw 'registryModeRefused' }
} finally { $base.Dispose() }
`;

function contexteRegistre(travail) {
  const nonce = path.basename(travail);
  verifier(/^diapason-installation-\d+-\d+$/.test(nonce), 'registryWorkdirRefused');
  const sauvegarde = path.join(process.env.LOCALAPPDATA, 'DiapasonInstallationTests', nonce);
  return { ...process.env, DIAPASON_E2E_NONCE: nonce, DIAPASON_E2E_SUFFIX: `.Banc-${nonce}`,
    DIAPASON_E2E_BACKUP: sauvegarde, DIAPASON_E2E_INSTALL: path.join(travail, 'application') };
}

export async function recupererInstallation(travail) {
  verifier(process.platform === 'win32', 'windowsRequired');
  const env = contexteRegistre(path.resolve(travail));
  const etatPath = path.join(env.DIAPASON_E2E_BACKUP, 'etat.json');
  if (!fs.existsSync(etatPath)) return { restored: true, preserved: true };
  const etat = JSON.parse(fs.readFileSync(etatPath, 'utf8').replace(/^\uFEFF/, ''));
  if (etat.restored) return { restored: true, preserved: true,
    originalKeys: etat.keys.length, originalBinaries: etat.binaries.length };
  verifier(etat.nonce === env.DIAPASON_E2E_NONCE && etat.installDir === env.DIAPASON_E2E_INSTALL, 'registryStateMismatch');
  if (etat.appPid) {
    const p = await powershell(String.raw`
$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$env:DIAPASON_E2E_PID)
if ($p -and $p.ExecutablePath -eq (Join-Path $env:DIAPASON_E2E_INSTALL 'diapason-desktop.exe')) {
  & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $p.ProcessId /T /F | Out-Null
}
@{ stopped=$true } | ConvertTo-Json -Compress
`, { ...env, DIAPASON_E2E_PID: String(etat.appPid) });
    verifier(p.stopped, 'testProcessRecoveryFailed');
  }
  const desinstalleur = path.join(etat.installDir, 'uninstall.exe');
  if (fs.existsSync(desinstalleur)) {
    const u = await executer(desinstalleur, ['/S', '/UPDATE'], { cwd: travail });
    verifier(u.code === 0, 'recoveryUninstallFailed');
    await attendre(() => !fs.existsSync(path.join(etat.installDir, 'diapason-desktop.exe')), 30000, 'recoveryLeftApplication');
  }
  return powershell(REGISTRE_ISOLE, { ...env, DIAPASON_E2E_REG_MODE: 'restore' });
}

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

async function lirePorts() {
  return powershell(String.raw`
$ports = @(Get-NetTCPConnection -State Listen -LocalPort 8000,11434 -ErrorAction SilentlyContinue)
$sortie = @($ports | ForEach-Object {
  $p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_.OwningProcess)
  $g=Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
  @{ port=$_.LocalPort; processId=$_.OwningProcess; sessionId=$g.SessionId;
     processName=$g.ProcessName; executableIsOllama=([IO.Path]::GetFileName([string]$p.ExecutablePath) -ieq 'ollama.exe');
     loopback=($_.LocalAddress -in @('127.0.0.1','::1')) }
})
@{ listeners=$sortie } | ConvertTo-Json -Compress
`);
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
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DiapasonCommandLine {
  [DllImport("shell32.dll", CharSet=CharSet.Unicode, ExactSpelling=true)]
  public static extern IntPtr CommandLineToArgvW(string command, out int count);
  [DllImport("kernel32.dll", ExactSpelling=true)]
  public static extern IntPtr LocalFree(IntPtr memory);
}
'@
$port = [int]$env:DIAPASON_E2E_PORT
$racine = [int]$env:DIAPASON_E2E_PID
$connexions = @(Get-NetTCPConnection -State Listen -LocalPort $port)
$valide = $false
$profilValide = $false
$relation = 'missing'
$nombreProfils = 0
foreach ($c in $connexions) {
  if ($c.LocalAddress -ne '127.0.0.1') { continue }
  $courant = [int]$c.OwningProcess
  $navigateur = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $courant)
  $descendant = $false
  for ($i=0; $i -lt 12 -and $courant -gt 0; $i++) {
    if ($courant -eq $racine) { $descendant=$true; break }
    $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $courant)
    if (-not $p) { break }
    $courant = [int]$p.ParentProcessId
  }
  if (-not $descendant) { continue }
  $valide = $true
  $argc = 0
  $argv = [DiapasonCommandLine]::CommandLineToArgvW($navigateur.CommandLine, [ref]$argc)
  if ($argv -eq [IntPtr]::Zero) { throw 'webviewCommandLineUnreadable' }
  try {
    for ($i=0; $i -lt $argc; $i++) {
      $arg = [Runtime.InteropServices.Marshal]::PtrToStringUni([Runtime.InteropServices.Marshal]::ReadIntPtr($argv, $i*[IntPtr]::Size))
      if (-not $arg.StartsWith('--user-data-dir=',[StringComparison]::Ordinal)) { continue }
      $nombreProfils++
      $reel = [IO.Path]::GetFullPath($arg.Substring('--user-data-dir='.Length)).TrimEnd([char]'\')
      $attendu = [IO.Path]::GetFullPath($env:DIAPASON_E2E_WEBVIEW).TrimEnd([char]'\')
      if ($reel.Equals($attendu,[StringComparison]::OrdinalIgnoreCase)) {
        $profilValide=$true; $relation='exact'
      } elseif ($reel.StartsWith($attendu+'\',[StringComparison]::OrdinalIgnoreCase)) {
        # WebView2 place notamment EBWebView dans le dossier utilisateur.
        $profilValide=$true; $relation='privateDescendant'
      } else { $relation='outside' }
    }
  } finally { [DiapasonCommandLine]::LocalFree($argv) | Out-Null }
}
@{ owned=$valide; privateProfile=($profilValide -and $nombreProfils -eq 1); profileRelation=$relation } | ConvertTo-Json -Compress
`, { ...process.env, DIAPASON_E2E_PORT: String(port), DIAPASON_E2E_PID: String(appPid),
    DIAPASON_E2E_WEBVIEW: profilWebview });
  verifier(origine.owned === true, 'debugPortNotOwnedByTestApp');
  verifier(origine.privateProfile === true, `webviewProfileNotIsolated:${origine.profileRelation}`);
  const canal = await Cdp.connecter(cible.webSocketDebuggerUrl);
  canal.isolation = { owned: true, privateProfileVerified: true, profileRelation: origine.profileRelation };
  return canal;
}

async function capture(cdp, fichier) {
  const image = await cdp.appel('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(fichier, Buffer.from(image.data, 'base64'));
}

async function dialogue(cdp, question, attendu, preuve = {}) {
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
      const dernier = messages.at(-1);
      return { count: messages.length, text: dernier?.querySelector('.frappe-reponse .prose')?.innerText || '',
        typing: !!dernier?.querySelector('.frappe-curseur:not([hidden])'),
        generating: !!document.querySelector('button[aria-label="Stop generating"],button[aria-label="Arrêter la génération"]') };
    })()`);
    if (r.count <= nombre || r.generating || r.typing || !r.text.trim()) return false;
    stable = r.text === dernier ? stable + 1 : 0; dernier = r.text;
    if (stable < 2) return false;
    preuve.response = erreurDemarragePubliable(r.text);
    preuve.complete = true;
    preuve.expectedResultFound = attendu.test(r.text);
    verifier(preuve.expectedResultFound, 'conversationAnswerIncorrect');
    return { complete: true, expectedResultFound: true };
  }, 300000, 'conversationIncomplete');
}

export async function premierLancement(options) {
  const autorisationAncien = autorisationArretAncien(options);
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
  let envApp; let exe; let port; let regEnv; let ollamaExistant;
  const scenario = options.scenario ?? 'fresh';
  verifier(['fresh', 'legacy'].includes(scenario), 'invalidInstallationScenario');
  rapport.scenario = scenario;
  let ancienneSourcePreservee; let fixtureLegacy; let stubLegacy;
  if (scenario === 'legacy') {
    for (const controle of CONTROLES_LEGACY) rapport.checks[controle] = false;
    rapport.legacyRefusal = { observed: false, ownedServerAlive: false, bootstrapUnchanged: false,
      ownedServerStopped: false, appHealthRequests: 0 };
    rapport.legacyPersistence = { seededBeforeLaunch: false, afterStartup: false,
      afterRestart: false, sameKey: false };
  }
  async function inferenceOriginalePreservee() {
    if (!ollamaExistant) return true;
    const { listeners } = await lirePorts();
    const infer = listeners.filter(p => p.port === 11434);
    return ollamaPartageable(infer, rapport.preflight.sessionId)
      && infer[0].processId === ollamaExistant.processId;
  }
  async function verifierAucuneApp() {
    const actif = await powershell(String.raw`
@{ count=@(Get-Process -Name 'diapason-desktop','Diapason' -ErrorAction SilentlyContinue).Count } | ConvertTo-Json -Compress
`);
    verifier(actif.count === 0, 'applicationRunningBeforeUninstall');
  }
  async function arreter({ garderStub = false } = {}) {
    if (!enfant && !cdp) return;
    if (cdp) {
      try { await cdp.invoquer('stop_backend'); } catch { /* récolte par PID ensuite */ }
      cdp.fermer(); cdp = null;
    }
    if (enfant && enfant.exitCode === null) {
      if (enfant.signalCode === null) {
        verifier(Number.isSafeInteger(enfant.pid) && enfant.pid > 0, 'testApplicationPidMissing');
        await executer(path.join(process.env.SystemRoot, 'System32', 'taskkill.exe'),
          ['/PID', String(enfant.pid), '/T', '/F']);
      }
      await attendre(() => enfant.exitCode !== null || enfant.signalCode !== null,
        10000, 'testApplicationStillRunning', 100);
    }
    await attendre(async () => (garderStub ? await garderStub.verifierVivant() : !(await portOccupe(8000))) && (ollamaExistant
      ? await inferenceOriginalePreservee() : !(await portOccupe(11434))),
      30000, 'testProcessesNotStopped');
    enfant = null;
  }
  async function preparerEnvironnement() {
    port = await portLibre();
    envApp = environnementApplication(process.env, path.join(travail, 'profil'), port);
    for (const cle of ['HOME', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'WEBVIEW2_USER_DATA_FOLDER']) {
      fs.mkdirSync(envApp[cle], { recursive: true });
    }
    verifierProfilQa(envApp, travail);
  }
  async function lancer({ attendreRefus = false } = {}) {
    const debut = Date.now();
    await preparerEnvironnement();
    const log = fs.openSync(path.join(travail, 'application-prive.log'), 'a');
    enfant = spawn(exe, [], { cwd: path.dirname(exe), env: envApp, shell: false,
      stdio: ['ignore', log, log], windowsHide: false });
    enfant.once('error', () => {});
    fs.closeSync(log);
    const etatPath = path.join(regEnv.DIAPASON_E2E_BACKUP, 'etat.json');
    const etatInstallation = JSON.parse(fs.readFileSync(etatPath, 'utf8').replace(/^\uFEFF/, ''));
    etatInstallation.appPid = enfant.pid || 0;
    fs.writeFileSync(etatPath + '.new', JSON.stringify(etatInstallation));
    fs.renameSync(etatPath + '.new', etatPath);
    cdp = await connecterApplication(port, enfant.pid, envApp.WEBVIEW2_USER_DATA_FOLDER);
    rapport.webviewIsolation = cdp.isolation;
    verifier(await cdp.invoquer('plugin:app|version') === cible.version, 'installedVersionMismatch');
    rapport.checks.versionMatches = true;
    let phase = '';
    const etatFinal = await attendre(async () => {
      verifier(enfant.exitCode === null, 'appExitedDuringStartup');
      const etat = await cdp.invoquer('get_setup_status');
      if (etat.phase !== phase) {
        phase = etat.phase; noter(/^[a-z_]+$/.test(phase) ? `startup:${phase}` : 'startup');
      }
      if (attendreRefus) {
        verifier(!etat.server_ready && !etat.backend_ready && !etat.ollama_ready && !etat.model_ready,
          'legacyServerNotRejected');
        return etat.error ? etat : false;
      }
      if (etat.error) {
        // Uniquement le profil neuf, sans conserver de clé ou d'environnement.
        rapport.startupError = erreurDemarragePubliable(etat.error);
        throw new Error('firstLaunchStartupError');
      }
      return etat.backend_ready && etat.ollama_ready && etat.model_ready && etat.server_ready;
    }, attendreRefus ? 45000 : (options.startupTimeoutMs || 7200000),
    attendreRefus ? 'legacyRefusalTimeout' : 'firstLaunchTimeout', 2000);
    if (attendreRefus) return etatFinal;
    rapport.startupDurationsSeconds ??= [];
    rapport.startupDurationsSeconds.push(Math.round((Date.now() - debut) / 1000));
    return cdp;
  }
  try {
    noter('preflight');
    rapport.residualBackendStop = await arreterAncienBackend(autorisationAncien);
    if (autorisationAncien) {
      noter('targetedOldBackendStop');
      verifier(rapport.residualBackendStop.status === 'stopped'
        && rapport.residualBackendStop.targetStopped && rapport.residualBackendStop.portFree
        && rapport.residualBackendStop.launcherExited, rapport.residualBackendStop.code || 'oldBackendStopUnconfirmed');
    }
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
    rapport.preflight.listeners = (await lirePorts()).listeners;
    verifier(!rapport.preflight.listeners.some(p => p.port === 8000), 'preexistingDiapasonServerPort');
    verifier(!(await portOccupe(8000)), 'preexistingDiapasonServerPort');
    if (await portOccupe(11434)) {
      const infer = rapport.preflight.listeners.filter(p => p.port === 11434);
      verifier(ollamaPartageable(infer, bureau.sessionId), 'preexistingInferenceServerNotRecognized');
      const res = await fetch('http://127.0.0.1:11434/api/version', { signal: AbortSignal.timeout(5000) });
      const version = res.ok && (await res.json()).version;
      verifier(typeof version === 'string' && /^\d+\.\d+\.\d+(?:[-.+\w]*)?$/.test(version), 'preexistingInferenceVersionUnreadable');
      ollamaExistant = { processId: infer[0].processId, version };
      rapport.preexistingInferenceServer = { ...ollamaExistant, modelDownloadColdVerified: false };
    }
    noter('downloadInstaller');
    const r = await fetch(cible.url, { signal: AbortSignal.timeout(300000) });
    verifier(r.ok, 'installerDownloadFailed');
    const octets = Buffer.from(await r.arrayBuffer());
    verifier(createHash('sha256').update(octets).digest('hex') === cible.sha256, 'installerHashMismatch');
    verifier(octets.toString('ascii', 0, 2) === 'MZ', 'installerNotExecutable');
    const installateur = path.join(travail, cible.nom); fs.writeFileSync(installateur, octets);
    rapport.checks.installerHashVerified = true;
    noter('isolateInstallationRegistry');
    regEnv = contexteRegistre(travail);
    rapport.registryIsolation = await powershell(REGISTRE_ISOLE,
      { ...regEnv, DIAPASON_E2E_REG_MODE: 'prepare' });
    verifier(rapport.registryIsolation.prepared === true && rapport.registryIsolation.selfTestPassed === true,
      'registryIsolationNotReady');
    const avant = await powershell(SONDE_REGISTRE, regEnv);
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
    if (scenario === 'legacy') {
      await preparerEnvironnement();
      ancienneSourcePreservee = preparerAncienneSourceSynthétique(envApp);
      fixtureLegacy = await preparerDonneesLegacy(envApp, travail);
      rapport.checks.legacyFixtureSeeded = true;
      rapport.legacyPersistence.seededBeforeLaunch = true;
      rapport.fixtureSchema = SCHEMA_LEGACY_SOURCE;
      const avantRefus = empreinteAmorcageLegacy(envApp, travail);
      noter('legacyOwnedServerRefusal');
      rapport.legacyRefusal = await verifierBlocageLegacy({
        version: cible.version,
        empreinte: () => empreinteAmorcageLegacy(envApp, travail),
        creerStub: async () => { stubLegacy = await creerAncienServeurSynthétique(); return stubLegacy; },
        lancer: () => lancer({ attendreRefus: true }),
        arreter: stub => arreter({ garderStub: stub }),
        lireLog: () => {
          const fd = fs.openSync(path.join(travail, 'application-prive.log'), 'r');
          try {
            const taille = fs.fstatSync(fd).size, debut = Math.max(0, taille - 65536);
            const fin = Buffer.alloc(taille - debut);
            const lus = fs.readSync(fd, fin, 0, fin.length, debut);
            return fin.subarray(0, lus).toString('utf8');
          } finally { fs.closeSync(fd); }
        },
      });
      stubLegacy = null;
      verifier(empreinteAmorcageLegacy(envApp, travail) === avantRefus, 'legacyCleanupMutatedBootstrap');
      rapport.checks.legacyOldServerRejected = true;
      rapport.checks.legacyOldServerPreserved = true;
      rapport.checks.legacyBootstrapUnmodified = true;
      verifier(!(await portOccupe(8000)), 'legacyOwnedServerNotStopped');
      rapport.legacyRefusal.ownedServerStopped = true;
      rapport.checks.legacyOwnedServerStopped = true;
    }
    noter('firstLaunch'); await lancer(); rapport.checks.firstLaunchReady = true;
    const gere = path.join(envApp.LOCALAPPDATA, 'Diapason');
    const marqueurComplet = path.join(gere, 'runtime-complet', 'src', '.diapason-backend');
    const marqueurs = [marqueurComplet, path.join(gere, 'src', '.diapason-backend'), path.join(gere, '.diapason-backend')];
    verifier(marqueurs.some(p => fs.existsSync(p) && fs.readFileSync(p, 'utf8').trim() === cible.version),
      'downloadedBackendMarkerMissing');
    rapport.checks.newManagedBackendPrepared = true;
    if (scenario === 'legacy') {
      verifier(fs.existsSync(marqueurComplet)
        && fs.readFileSync(marqueurComplet, 'utf8').trim() === cible.version, 'legacySourceReused');
      verifier(ancienneSourcePreservee(), 'legacySourceOverwritten');
    }
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
    verifierBackendCourant(await api('/health'), cible.version);
    rapport.checks.backendVersionMatches = true;
    if (scenario === 'legacy') {
      await verifierDonneesLegacy(fixtureLegacy, api, cle);
      rapport.checks.legacyDataAfterStartup = true;
      rapport.legacyPersistence.afterStartup = true;
    }
    noter('twoTurnConversation');
    rapport.dialogue = [{}, {}];
    await dialogue(cdp, 'Combien font 12 plus 25 ? Réponds en une phrase.', /37|trente[ -]sept/i, rapport.dialogue[0]);
    // 07/11/2026 : l'ancien 3b d'Ollama passait le premier calcul puis
    // envoyait le suivi sur le Web. Le PC32Go doit préparer le 4b du plan.
    const listeModeles = await api('/v1/models');
    rapport.initialModel = listeModeles.data?.[0]?.id;
    const modeleAffiche = await cdp.evaluer(`!![...document.querySelectorAll('button')].find(b => {
      const r = b.getBoundingClientRect();
      return b.innerText.trim() === 'qwen3.5:4b' && r.width > 0 && r.height > 0;
    })`);
    verifier(rapport.initialModel === 'qwen3.5:4b' && modeleAffiche, 'initialModelNotPreparedForWindows');
    rapport.checks.initialModelMatchesValidatedPlan = true;
    await dialogue(cdp, 'Ajoute un au résultat précédent. Réponds en une phrase.', /38|trente[ -]huit/i, rapport.dialogue[1]);
    rapport.checks.twoTurnUiConversation = true;
    await capture(cdp, path.join(sortie, '02-discussion-reelle.png'));
    noter('saveSyntheticNote');
    noter('managementAfterQuota');
    const quotas = await Promise.allSettled(Array.from({ length: 16 }, async () => {
      const res = await fetch(base + '/v1/config', { headers: { Authorization: `Bearer ${cle}` },
        signal: AbortSignal.timeout(10000) });
      await res.body?.cancel();
      return res.status;
    }));
    verifier(quotas.every(r => r.status === 'fulfilled'
      && ((r.value >= 200 && r.value < 300) || r.value === 429)), 'quotaProbeUnexpectedStatus');
    const refusQuota = quotas.filter(r => r.status === 'fulfilled' && r.value === 429).length;
    verifier(refusQuota > 0, 'quotaNotExercised');
    // Les premières réponses peuvent dater de plusieurs secondes : confirmer
    // le refus juste avant le POST, après la fin de toute la rafale.
    const encoreLimite = await fetch(base + '/v1/config', { headers: { Authorization: `Bearer ${cle}` },
      signal: AbortSignal.timeout(10000) });
    await encoreLimite.body?.cancel();
    verifier(encoreLimite.status === 429, 'quotaRefilledBeforeCrud');
    rapport.managementQuota = { requests: 17, throttled: refusQuota + 1, confirmedImmediatelyBeforeCrud: true };
    const projet = (await api('/v1/vie/projects', 'POST', { name: 'Essai installation Windows' })).project;
    const contenu = 'Note créée dans le profil d’essai. Trente-sept pages sont prêtes.';
    const note = (await api('/v1/vie/notes', 'POST', {
      title: 'Note de contrôle', content: contenu, projectId: projet.id,
    })).note;
    verifier(note.content === contenu, 'noteSaveFailed');
    await api('/v1/vie/finances/overview');
    rapport.checks.managementCrudAfterQuota = true;
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
    const maj = await cdp.evaluer(`(() => {
      const b = [...document.querySelectorAll('button')].find(b =>
        /^(Mise à jour|Update|Updates|Check for updates)$/i.test(b.getAttribute('aria-label') || b.title || b.innerText.trim()));
      if (!b || b.disabled) return false;
      const r = b.getBoundingClientRect(), s = getComputedStyle(b);
      const x = r.x + r.width / 2, y = r.y + r.height / 2;
      return r.width > 0 && r.height > 0 && x >= 0 && y >= 0
        && x < innerWidth && y < innerHeight && s.visibility === 'visible'
        && s.display !== 'none' && b.contains(document.elementFromPoint(x, y));
    })()`);
    verifier(maj, 'updateButtonMissing'); rapport.checks.updateButtonVisible = true;
    const navigation = await cdp.evaluer(`(() => {
      const elements = [...document.querySelectorAll('.navigation-rail-rubriques, .navigation-contenu')]
        .filter(e => e.getBoundingClientRect().width > 0 && e.getBoundingClientRect().height > 0);
      return elements.length > 0 && elements.every(e => {
        const s = getComputedStyle(e), barre = getComputedStyle(e, '::-webkit-scrollbar');
        return ['auto', 'scroll'].includes(s.overflowY)
          && (s.scrollbarWidth === 'none' || barre.display === 'none');
      });
    })()`);
    verifier(navigation, 'navigationScrollbarNotHidden');
    rapport.checks.navigationScrollbarHidden = true;
    noter('restartInstalledApplication');
    await arreter(); await lancer();
    cle = await cdp.invoquer('get_local_api_key');
    rapport.checks.backendVersionMatches = false;
    verifierBackendCourant(await api('/health'), cible.version);
    rapport.checks.backendVersionMatches = true;
    if (scenario === 'legacy') {
      await verifierDonneesLegacy(fixtureLegacy, api, cle);
      rapport.checks.legacyDataAfterRestart = true;
      rapport.checks.legacyKeyPreserved = true;
      rapport.legacyPersistence.afterRestart = true;
      rapport.legacyPersistence.sameKey = true;
    }
    const relue = (await api(`/v1/vie/notes/${encodeURIComponent(note.id)}`)).note;
    verifier(relue.content === contenu && relue.projectId === projet.id, 'noteLostAfterRestart');
    rapport.checks.notePersistedAfterRestart = true;
    if (scenario === 'legacy') {
      verifier(ancienneSourcePreservee(), 'legacySourceOverwrittenAfterRestart');
      rapport.checks.legacySourcePreserved = true;
    }
    await capture(cdp, path.join(sortie, '03-apres-relance.png'));
    // 07/11/2026 : le site reste en attente pendant le premier essai réel.
    // Après conversation, voix et relance validées, attendre sa publication
    // exacte ; dix minutes laissent la synchronisation sans accepter l'ancien.
    noter('awaitingExactUpdateCatalogue');
    await attendre(async () => {
      const catalogue = await cdp.invoquer('verifier_telechargements');
      return catalogue.platform === 'windows' && catalogue.currentVersion === cible.version
        && catalogue.catalog?.platforms?.windows?.status === 'ready'
        && catalogue.catalog.platforms.windows.version === cible.version;
    }, 600000, 'updateCatalogueMismatch', 2000);
    rapport.checks.updateCatalogueMatches = true;
    await arreter(); rapport.checks.processesStopped = true;
    noter('uninstallTestCopy');
    await verifierAucuneApp();
    const desinstallation = await executer(path.join(dossierApp, 'uninstall.exe'), ['/S', '/UPDATE'], { cwd: travail });
    verifier(desinstallation.code === 0, 'uninstallerFailed');
    await attendre(() => !fs.existsSync(exe), 30000, 'uninstallerLeftApplication');
    rapport.checks.uninstallSucceeded = true; installe = false;
  } catch (e) {
    rapport.failureCode = /^[A-Za-z0-9_:<>/-]{1,180}$/.test(e.message) ? e.message : 'unexpectedTestFailure';
    try { if (cdp) await capture(cdp, path.join(sortie, 'echec-application.png')); } catch { /* facultatif */ }
  } finally {
    try { await arreter({ garderStub: stubLegacy }); } catch { rapport.cleanupFailed = true; }
    try {
      if (stubLegacy && !enfant && !cdp) await stubLegacy.fermer();
    } catch { rapport.cleanupFailed = true; }
    if (regEnv) {
      try {
        rapport.registryRestoration = await recupererInstallation(travail);
        rapport.checks.registryRestored = rapport.registryRestoration.restored === true;
        rapport.checks.originalInstallationPreserved = rapport.registryRestoration.preserved === true;
        if (installe && exe && !fs.existsSync(exe)) rapport.checks.uninstallSucceeded = true;
      } catch { rapport.cleanupFailed = true; }
    }
    try { rapport.checks.originalInferenceServerPreserved = await inferenceOriginalePreservee(); }
    catch { rapport.cleanupFailed = true; }
    rapport.passed = rapportValide(rapport) && !rapport.cleanupFailed;
    rapport.status = rapport.passed ? 'passed' : 'failed';
    noter(rapport.status);
  }
  return rapport;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const valeurs = {};
  for (let i = 2; i < process.argv.length; i += 2) valeurs[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
  const action = valeurs['restore-workdir']
    ? recupererInstallation(valeurs['restore-workdir']).then(r => ({ passed: r.restored && r.preserved }))
    : premierLancement(valeurs);
  action.then(r => { process.exitCode = r.passed ? 0 : 1; }).catch(() => {
    console.error('Préparation de l’essai refusée. Aucun succès déclaré.'); process.exitCode = 1;
  });
}
