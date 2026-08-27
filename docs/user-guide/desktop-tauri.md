# Application de bureau (Tauri)

Tauri fournit la fenêtre native, la barre système, les raccourcis et la mise à
jour. Le cœur Python reste local, mais il n'est pas encore embarqué dans le
`.msi`, le `.dmg` ou l'AppImage : il doit être installé avant le premier
lancement. Si un serveur Diapason sain tourne déjà sur `127.0.0.1:8000`, la
fenêtre s'y attache sans en démarrer un second.

## État réel par plateforme

| Plateforme | Compilation | Validation sur machine réelle | Distribution actuelle |
|---|---:|---:|---|
| macOS | oui | oui, sur le Mac de Carlito | construction locale avec `scripts/install-desktop.sh` |
| Windows | code, workflow et `.msi` de validation préparés | non | aucun `.msi` publié ; bootstrap PowerShell requis |
| Linux | workflow préparé | non | aucun `.deb`, `.rpm` ou AppImage publié |

Le dépôt GitHub ne contient actuellement **aucune release**. Toute page qui
présente un lien `desktop-v1.0.2` comme un téléchargement existant est
périmée.

## Raccourcis réellement actifs

| Plateforme | Raccourci | Effet |
|---|---|---|
| macOS | `⌥ Espace` | montre la fenêtre et émet `talk-toggle` |
| Windows / Linux | `Ctrl + Maj + Espace` | montre la fenêtre et émet `talk-toggle` |
| macOS seulement | `⌘ + Maj + Espace` | bascule la superposition native |

La dictée native et le collage dans l'application au premier plan sont encore
macOS seulement. Sur Windows et Linux, ces commandes répondent explicitement
« non pris en charge » ; elles ne rendent jamais un faux succès. Sous Wayland,
le raccourci global est désactivé explicitement parce que le plugin ne prend en
charge que X11 ; le bouton visible de l'interface reste disponible.

## Windows

Le bootstrap installe le dépôt, Python, le venv et le serveur sous
`%LOCALAPPDATA%\Diapason\src`. Tauri recherche désormais exactement ce chemin
avant les emplacements de développement :

```powershell
git clone https://github.com/carlitoetienne01-spec/Diapason.git `
  "$env:LOCALAPPDATA\Diapason\src"
powershell -ExecutionPolicy Bypass `
  -File "$env:LOCALAPPDATA\Diapason\src\deploy\windows\install.ps1"
```

Le dépôt étant privé, le clone exige un compte GitHub autorisé. L'application
ne tente plus de le cloner silencieusement au premier lancement.

Une fois le runner du PC étiqueté `self-hosted,windows-local` et la variable
de dépôt `RUNNER_WINDOWS_LOCAL=true`, un lancement manuel de **Desktop Build
& Release** exécute le job `build-windows-local`. Il produit uniquement un
`.msi` de validation, sans artefact de mise à jour ni prétention de release
signée. Il n'embarque ni Ollama ni le cœur Python : le bootstrap ci-dessus doit
avoir réussi avant son installation. Une copie reste sur le PC dans :

```text
%LOCALAPPDATA%\Diapason\artifacts
```

Le job tente aussi de joindre le `.msi` au rapport GitHub, mais cet envoi est
secondaire : le fichier local et son SHA-256 sont la preuve principale.

## Développement et construction

```bash
cd frontend
npm install
npm run tauri:dev
npm run tauri:build
```

Les artefacts locaux sont écrits sous
`frontend/src-tauri/target/release/bundle/`. Une construction sur macOS ne
valide pas Windows ou Linux : la publication multiplateforme doit tourner sur
les trois systèmes réels.

Sur le Mac de Carlito, l'installation reproductible est :

```bash
./scripts/install-desktop.sh
```

Elle compile, sauvegarde l'application précédente hors de `/Applications`,
installe la nouvelle et vérifie son démarrage.
