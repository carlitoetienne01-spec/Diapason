# Desktop auto-update

> **Prepared, not released.** The updater code and release channels described
> below exist, but the repository currently has no GitHub release and therefore
> no `desktop-latest/latest.json`. Installed development builds receive a 404
> and no update is offered. This page is the release design, not evidence that
> an installer has already shipped.

The Diapason desktop app includes [Tauri's updater
plugin](https://v2.tauri.app/plugin/updater/), which checks for new
versions on launch and every 30 minutes. When a newer signed build is
available, the app prompts the user to download and install it.

## How it works

```
on launch / every 30 min
        │
        ▼
GET https://github.com/carlitoetienne01-spec/Diapason/releases/download/desktop-latest/latest.json
        │
        ▼
Parse manifest: { "version": "X.Y.Z", "platforms": { ... } }
        │
        ▼
If manifest.version > installed_version:
   download signed .dmg / .deb / .msi from manifest.platforms[target].url
   verify against the minisign pubkey baked into the app
   prompt user to install
```

The frontend code lives in
[`frontend/src/components/Desktop/BandeauMiseAJour.tsx`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/frontend/src/components/Desktop/BandeauMiseAJour.tsx)
(the banner, shown in the sidebar just above *Réglages* / *Parler*) and
[`frontend/src/components/Desktop/miseAJour.ts`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/frontend/src/components/Desktop/miseAJour.ts)
(the pure logic, unit-tested); the Tauri wiring is in
[`frontend/src-tauri/tauri.conf.json`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/frontend/src-tauri/tauri.conf.json)
under `plugins.updater`.

## Publier une version (depuis le 13 septembre 2026)

Les runners GitHub ne démarrent plus (facturation) : la matrice
`build-and-release` ci-dessous est en sommeil. La seule voie réelle est le
job **`publish-macos-local`** de `desktop.yml`, sur le Mac de Carlito
(`self-hosted, macos-local`). Il publie, à la même version, tout ce que
l'app installée attend :

| Fichier | Qui le lit |
|---|---|
| `Diapason_<v>_aarch64.dmg` | l'utilisateur, depuis la page de release |
| `Diapason.app.tar.gz` + `.sig` | l'updater (signature minisign) |
| `latest.json` | l'updater, via le miroir `desktop-latest` |
| `backend.json`, `diapason-src-<v>.tar.gz`, `diapason_rust-….whl` | l'amorçage au premier lancement — [`premier-lancement.md`](premier-lancement.md) |

Apple Silicon seulement (le seul constructeur est ce Mac ; la wheel n'existe
que pour lui). Signature Apple « - » (ad hoc) tant qu'aucun compte Developer
n'existe.

La procédure, en trois commandes :

```bash
scripts/bump-desktop-version.sh 1.0.1        # tauri.conf.json, Cargo.toml, package.json
git commit -am "Version 1.0.1 de l'app de bureau" && git push
git tag desktop-v1.0.1 && git push origin desktop-v1.0.1
```

Le job refuse un tag dont la version n'est pas celle de `tauri.conf.json` :
l'app cherche son backend et ses mises à jour **sous sa propre version**, un
tag qui dirait autre chose publierait des fichiers introuvables.

Pour répéter la construction sans rien publier : *Actions → Desktop Build &
Release → Run workflow → « dry_run_macos »* (ou
`gh workflow run desktop.yml -f dry_run_macos=true`). Les fichiers sortent
en artefact de workflow.

Si le dépôt reste privé, les assets ne se téléchargent pas sans jeton — et
l'app installée n'en a aucun. Deux issues : rendre le dépôt public, ou poser
la variable de dépôt `DIAPASON_RELEASES_REPO=<owner>/<repo-public>` avec le
secret `RELEASES_TOKEN` (PAT, `contents: write` sur ce dépôt-là), puis
changer l'URL dans `tauri.conf.json` (`plugins.updater.endpoints`) et
`DEPOT_RELEASES` dans `amorcage.rs`.

## How releases reach the update endpoint

The `Desktop Build & Release` GitHub Action
([`.github/workflows/desktop.yml`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/.github/workflows/desktop.yml))
builds signed binaries plus a `latest.json` manifest with the
`tauri-action` step (`includeUpdaterJson: true` generates the manifest
automatically). Where it publishes depends on the trigger.

The separate `build-windows-local` job is deliberately outside these release
streams. It runs on `self-hosted,windows-local`, disables updater artifacts,
and leaves an unsigned validation MSI under the runner root's `artifacts`
directory (`C:\actions-runner\artifacts` on Carlito's PC). The service runs
as `NETWORK SERVICE`, so its `%LOCALAPPDATA%` is not Carlito's profile and
must never be advertised as one. This MSI exists for physical testing while
hosted minutes are unavailable; it never updates `desktop-edge` or
`desktop-latest`.

Three release streams are prepared:

- **`desktop-latest`** (stable auto-update channel): **this is the
  channel the installed app polls.** It is *not* built directly —
  instead, when a stable `desktop-vX.Y.Z` release is published, the
  `refresh-stable-channel` job copies that release's `latest.json`
  into `desktop-latest`. So the app is only ever offered vetted stable
  builds, and `latest.json` here points at the current `desktop-v*`
  assets.
- **`desktop-vX.Y.Z`** (tagged stable): created when someone pushes a
  `desktop-v*` git tag. The user-facing stable release with full
  installers; also the source of truth the stable channel mirrors.
- **`desktop-edge`** (rolling pre-release): rebuilt on every push to
  `main` (via the `autotag` → `desktop.yml` dispatch) and on manual
  `workflow_dispatch`. Carries the most recent CI build for testers.
  The shipped app does **not** poll this stream, so dev builds never
  auto-install onto stable users.

This split means security and telemetry-policy fixes reach users on
the next **stable** `desktop-v*` tag — cut one to ship an update.
Edge builds are available for anyone who wants to test `main` ahead of
a stable tag, without risking the stable population.

## Signing

Binaries are signed by `tauri-action` using the minisign key pair
referenced via these GitHub Actions secrets:

| Secret | Purpose |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | Private key (PEM-formatted minisign) |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Passphrase for the private key |

The current key pair (`minisign 1816AAE0E0C71A6F`) was generated on
13 September 2026 with `tauri signer generate --ci` (no passphrase, so
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` stays empty). The private key lives
**only** on Carlito's Mac, at `~/.diapason/updater/diapason.key` (mode
600), and in the GitHub secret — nowhere in the repository. Back it up
with the rest of `~/.diapason`: a lost private key means every installed
app rejects future updates, and the only way out is a manual reinstall
of a build carrying a new public key.

The previous public key (`1E75338D8F623D03`) had no surviving private
half — nothing could ever have been signed against it — which is why it
was replaced rather than reused.

To (re)load the secret from the local file:

```bash
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.diapason/updater/diapason.key
```

The matching public key is baked into the app at
`tauri.conf.json:plugins.updater.pubkey`. If you ever need to rotate
the key, replace the public key in the JSON file *and* update both
secrets atomically — mismatched keys cause every update download to
fail signature verification with no recovery path other than a manual
reinstall.

## Disabling the updater locally

For frontend development, set `VITE_DIAPASON_NO_UPDATER=1` in your
shell before running `npm run tauri dev`. Vite injects any
`VITE_`-prefixed env var into `import.meta.env`, and the
`miseAJour.ts` (`doitVerifier`) honors it to skip the 30-minute poll.

To see the banner without a published release, set
`localStorage['diapason-simuler-maj'] = '1.2.3'` in the browser preview
(ignored inside the real desktop app).

```bash
export VITE_DIAPASON_NO_UPDATER=1
npm run tauri dev
```

This is purely a dev escape hatch — it has no effect on production
builds (where `import.meta.env.VITE_DIAPASON_NO_UPDATER` will be
`undefined` unless you explicitly set it at build time).

## Verifying a release manually

```bash
# Download the latest manifest and confirm it parses cleanly
curl -fsSL https://github.com/carlitoetienne01-spec/Diapason/releases/download/desktop-latest/latest.json | jq .

# Fields:
#   version       — semver string, must match the tag (without leading "v")
#   notes         — release notes string
#   pub_date      — RFC3339 timestamp
#   platforms     — map keyed by "<target>-<arch>" e.g. "darwin-aarch64"
#                   each entry has { signature: "...", url: "..." }
```

A 404 on the manifest URL means the most recent desktop CI run
didn't complete or didn't have signing secrets — check the
`Desktop Build & Release` workflow logs.
