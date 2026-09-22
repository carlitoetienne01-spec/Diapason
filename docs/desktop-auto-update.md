# La mise à jour automatique de l'app de bureau

> **Préparée, pas encore publiée.** Le code de l'updater et les canaux de
> publication décrits ci-dessous existent, mais le dépôt n'a pour l'instant
> aucune release GitHub, donc aucun `desktop-latest/latest.json`. Les versions
> de développement déjà installées reçoivent un 404 et aucune mise à jour ne
> leur est proposée. Cette page décrit la publication telle qu'elle est conçue ;
> elle ne prouve pas qu'un installateur soit déjà sorti.

L'app de bureau Diapason embarque le [plugin updater de
Tauri](https://v2.tauri.app/plugin/updater/), qui cherche une nouvelle version
au lancement, puis toutes les 30 minutes. Quand une version signée plus récente
existe, l'app propose de la télécharger et de l'installer.

## Comment ça marche

```
au lancement / toutes les 30 min
        │
        ▼
GET https://github.com/carlitoetienne01-spec/Diapason/releases/download/desktop-latest/latest.json
        │
        ▼
Lire le manifeste : { "version": "X.Y.Z", "platforms": { ... } }
        │
        ▼
Si manifest.version > version installée :
   télécharger le .dmg / .deb / .msi signé depuis manifest.platforms[target].url
   vérifier la signature avec la clé publique minisign gravée dans l'app
   proposer l'installation à l'utilisateur
```

Le code du frontend vit dans
[`frontend/src/components/Desktop/BandeauMiseAJour.tsx`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/frontend/src/components/Desktop/BandeauMiseAJour.tsx)
(le bandeau, affiché dans la barre latérale juste au-dessus de *Réglages* /
*Parler*) et
[`frontend/src/components/Desktop/miseAJour.ts`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/frontend/src/components/Desktop/miseAJour.ts)
(la logique pure, couverte par des tests unitaires) ; le câblage Tauri est dans
[`frontend/src-tauri/tauri.conf.json`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/frontend/src-tauri/tauri.conf.json)
sous `plugins.updater`.

## Publier une version (depuis le 13 septembre 2026)

Les runners GitHub ne démarrent plus (facturation) : la matrice
`build-and-release` ci-dessous est en sommeil. La seule voie réelle est le
job **`publish-macos-local`** de `desktop.yml`, sur le Mac de Carlito
(`self-hosted, macos-local`). Il publie, à la même version, tout ce que
l'app installée attend :

| Fichier | Qui le lit |
|---|---|
| `Diapason_<v>_aarch64.dmg`, `Diapason_<v>_x64-setup.exe` | l'utilisateur, depuis la page de release |
| `Diapason.app.tar.gz` + `.sig`, `-setup.exe` + `.sig` | l'updater (signature minisign) |
| `latest.json` | l'updater, via le miroir `desktop-latest` |
| `backend.json`, `diapason-src-<v>.tar.gz`, `diapason_rust-….whl` | l'amorçage au premier lancement — [`premier-lancement.md`](premier-lancement.md) |

Apple Silicon seulement (le seul constructeur est ce Mac ; la wheel n'existe
que pour lui). Signature Apple « - » (ad hoc) tant qu'aucun compte Developer
n'existe.

La procédure, en trois commandes :

```bash
scripts/bump-desktop-version.sh 1.0.1        # tauri.conf.json, Cargo.toml, package.json
git commit -am "Version 1.0.1 de l'app de bureau" && git push
git tag desktop-v1.0.1 && git push origin desktop-v1.0.1
```

Le job refuse un tag dont la version n'est pas celle de `tauri.conf.json` :
l'app cherche son backend et ses mises à jour **sous sa propre version**, un
tag qui dirait autre chose publierait des fichiers introuvables.

Pour répéter la construction sans rien publier : *Actions → Desktop Build &
Release → Run workflow → « dry_run_macos »* (ou
`gh workflow run desktop.yml -f dry_run_macos=true`). Les fichiers sortent
en artefact de workflow.

Si le dépôt reste privé, les assets ne se téléchargent pas sans jeton — et
l'app installée n'en a aucun. Deux issues : rendre le dépôt public, ou poser
la variable de dépôt `DIAPASON_RELEASES_REPO=<owner>/<repo-public>` avec le
secret `RELEASES_TOKEN` (PAT, `contents: write` sur ce dépôt-là), puis
changer l'URL dans `tauri.conf.json` (`plugins.updater.endpoints`) et
`DEPOT_RELEASES` dans `amorcage.rs`.

## Comment une version parvient jusqu'au point de mise à jour

L'action GitHub `Desktop Build & Release`
([`.github/workflows/desktop.yml`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/.github/workflows/desktop.yml))
construit les binaires signés, plus un manifeste `latest.json`, à l'étape
`tauri-action` (`includeUpdaterJson: true` produit le manifeste tout seul).
L'endroit où elle publie dépend de ce qui l'a déclenchée.

Windows est publié par `publish-windows-local` sur le PC de Carlito
(`self-hosted, windows-local`), après le job macOS : un `-setup.exe` NSIS
(signé — l'installateur lui-même est l'artefact de l'updater), la wheel
`win_amd64` de l'extension native, et `backend.json` / `latest.json` complétés
avec la plateforme `windows-x86_64`. Un `workflow_dispatch` se contente de les
garder en artefact ; `deploy_windows` met en plus le PC lui-même à jour.

Trois flux de publication sont prêts :

- **`desktop-latest`** (le canal stable de mise à jour automatique) : **c'est
  ce canal-là que l'app installée interroge.** Il n'est *pas* construit
  directement — à la place, quand une release stable `desktop-vX.Y.Z` paraît,
  le job `refresh-stable-channel` recopie le `latest.json` de cette release
  dans `desktop-latest`. L'app ne se voit donc jamais proposer que des versions
  stables vérifiées, et le `latest.json` d'ici pointe vers les fichiers
  `desktop-v*` du moment.
- **`desktop-vX.Y.Z`** (la stable étiquetée) : créée quand quelqu'un pousse un
  tag git `desktop-v*`. C'est la release stable destinée aux utilisateurs, avec
  les installateurs complets ; c'est aussi la source de vérité que le canal
  stable recopie.
- **`desktop-edge`** (la pré-version continue) : reconstruite à chaque poussée
  sur `main` (par le relais `autotag` → `desktop.yml`) et sur un
  `workflow_dispatch` manuel. Elle porte la construction CI la plus récente,
  pour les testeurs. L'app livrée n'interroge **pas** ce flux : une version de
  développement ne s'installe donc jamais toute seule chez les utilisateurs
  stables.

Ce découpage fait que les correctifs de sécurité et de politique de télémétrie
atteignent les utilisateurs au prochain tag **stable** `desktop-v*` — pour
livrer une mise à jour, il faut en poser un. Les versions edge restent à la
disposition de qui veut tester `main` avant un tag stable, sans faire courir de
risque à la population stable.

## La signature

Les binaires sont signés par `tauri-action`, avec la paire de clés minisign
désignée par ces secrets GitHub Actions :

| Secret | À quoi il sert |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | La clé privée (minisign, au format PEM) |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | La phrase de passe de la clé privée |

La paire de clés actuelle (`minisign 1816AAE0E0C71A6F`) a été produite le
13 septembre 2026 avec `tauri signer generate --ci` (sans phrase de passe, donc
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` reste vide). La clé privée vit
**uniquement** sur le Mac de Carlito, dans `~/.diapason/updater/diapason.key`
(mode 600), et dans le secret GitHub — nulle part dans le dépôt. Sauvegarde-la
avec le reste de `~/.diapason` : une clé privée perdue, et toutes les apps
installées refusent les mises à jour à venir ; la seule issue est alors de
réinstaller à la main une version qui porte une nouvelle clé publique.

L'ancienne clé publique (`1E75338D8F623D03`) n'avait plus de moitié privée —
rien n'aurait jamais pu être signé avec elle : c'est pourquoi elle a été
remplacée plutôt que reprise.

Pour (re)charger le secret depuis le fichier local :

```bash
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.diapason/updater/diapason.key
```

La clé publique correspondante est gravée dans l'app, à
`tauri.conf.json:plugins.updater.pubkey`. Si tu dois un jour faire tourner la
clé, remplace la clé publique dans le fichier JSON *et* mets à jour les deux
secrets d'un même geste — des clés qui ne se correspondent plus font échouer la
vérification de signature à chaque téléchargement de mise à jour, sans autre
recours qu'une réinstallation à la main.

## Couper l'updater en local

Pour développer le frontend, pose `VITE_DIAPASON_NO_UPDATER=1` dans ton shell
avant de lancer `npm run tauri dev`. Vite injecte dans `import.meta.env` toute
variable d'environnement préfixée par `VITE_`, et `miseAJour.ts`
(`doitVerifier`) en tient compte pour sauter la vérification des 30 minutes.

Pour voir le bandeau sans aucune release publiée, pose
`localStorage['diapason-simuler-maj'] = '1.2.3'` dans l'aperçu navigateur
(ignoré à l'intérieur de la vraie app de bureau).

```bash
export VITE_DIAPASON_NO_UPDATER=1
npm run tauri dev
```

C'est une porte de sortie réservée au développement — elle n'a aucun effet sur
les versions de production, où `import.meta.env.VITE_DIAPASON_NO_UPDATER` vaut
`undefined` tant que tu ne l'as pas posée explicitement au moment de la
construction.

## Vérifier une version à la main

```bash
# Télécharge le dernier manifeste et confirme qu'il se lit sans erreur
curl -fsSL https://github.com/carlitoetienne01-spec/Diapason/releases/download/desktop-latest/latest.json | jq .

# Les champs :
#   version       — chaîne semver, identique au tag (sans le "v" du début)
#   notes         — les notes de version, en texte
#   pub_date      — horodatage RFC3339
#   platforms     — table indexée par "<cible>-<arch>", par exemple "darwin-aarch64"
#                   chaque entrée porte { signature: "...", url: "..." }
```

Un 404 sur l'URL du manifeste signifie que la dernière exécution de la CI
desktop n'est pas allée au bout, ou qu'elle n'avait pas les secrets de
signature — regarde les journaux du workflow `Desktop Build & Release`.
