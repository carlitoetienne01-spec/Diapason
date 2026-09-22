# Windows natif (avancé)

Phase 1 de la RFC sur la prise en charge native de Windows (#298). Elle
reprend les déploiements Linux (systemd) et macOS (launchd) — mais pour
PowerShell, sans WSL2 ni Docker. Ne choisis cette voie plutôt que
[WSL2](wsl2.md) que si tu tiens à éviter une machine virtuelle Linux ; WSL2
reste le chemin le plus confortable pour la plupart des gens.

## Ce que tu obtiens

- Un installateur PowerShell qui sonde les prérequis, installe `uv`, clone le
  dépôt et installe les dépendances du bureau et du serveur sans supposer que
  Rust est là.
- Un service Windows facultatif, sous forme de tâche planifiée, équivalent à
  l'unité systemd et au plist launchd.
- La boucle locale par défaut — le service écoute sur `127.0.0.1`, donc
  aucune clé d'API n'est demandée.

C'est le serveur Python natif et son interface navigateur. Ce n'est **pas
encore l'app de bureau Tauri `.msi`** ; cet artefact demande toujours une
vraie construction Windows, et sa validation.

## Ce qu'il te faut

- Windows 10 1809 ou plus récent, ou Windows 11.
- Python 3.10 – 3.13 (Python 3.14 n'a pas encore de wheels numpy pour
  Windows — voir
  [#432](https://github.com/carlitoetienne01-spec/Diapason/issues/432)).
- `git` dans le PATH.
- ~5 Go de disque libre sur `%LOCALAPPDATA%`.

## Installer

Dans n'importe quel PowerShell :

```powershell
# NE FONCTIONNE PAS : le dépôt est privé, cette URL rend 404.
# Voir deploy/windows/README.md pour la procédure à jour :
#   gh auth login
#   git clone https://github.com/carlitoetienne01-spec/Diapason.git `
#     "$env:LOCALAPPDATA\Diapason\src"
#   powershell -ExecutionPolicy Bypass `
#     -File "$env:LOCALAPPDATA\Diapason\src\deploy\windows\install.ps1"
```

L'installateur va :

1. Refuser les hôtes qui ne sont pas Windows, et les vieilles versions de
   Windows.
2. Confirmer Python 3.10 – 3.13.
3. Confirmer `git`.
4. Installer `uv` s'il manque (par l'installateur PowerShell officiel
   `astral.sh/uv`).
5. Cloner le dépôt dans `%LOCALAPPDATA%\Diapason\src`.
6. Lancer `uv sync --extra desktop` ; ne construire le groupe natif que si
   Rust et les outils de compilation Windows sont présents.
7. Installer Ollama et le modèle de départ s'ils sont joignables.
8. Proposer d'enregistrer le service en tâche planifiée (à sauter avec
   `-SkipService`).

## Le lancer

```powershell
cd "$env:LOCALAPPDATA\Diapason\src"
diapason serve
```

Ouvre `http://127.0.0.1:8000/health` pour vérifier.

## Le service en tâche planifiée

Si tu as sauté la question pendant l'installation, enregistre toi-même la
tâche de démarrage automatique :

```powershell
$srv = "$env:LOCALAPPDATA\Diapason\src\deploy\windows\diapason-service.ps1"
powershell -ExecutionPolicy Bypass -File $srv install

# Ou garde l'API complète sur la boucle locale et n'expose que le maillage
# aux appareils appairés :
powershell -ExecutionPolicy Bypass -File $srv install -MaillageReseau
```

L'état :

```powershell
powershell -ExecutionPolicy Bypass -File $srv status
```

## Vérifier avant de dire que c'est prêt

La tâche planifiée en marche, lance le banc en lecture seule du dépôt :

```powershell
$verify = "$env:LOCALAPPDATA\Diapason\src\deploy\windows\verify.ps1"
powershell -ExecutionPolicy Bypass -File $verify -RequireNative -RequireMesh
```

C'est plus strict que de constater qu'un processus existe. Le banc importe le
paquet Python et l'extension PyO3, interroge `/health`, vérifie que le port
8000 n'écoute que sur la boucle locale, et prouve que le port 8001 tient une
porte du maillage pendant que le chat, la santé et la documentation rendent
tous 404. `-Json` produit un rapport à joindre aux notes de validation
Mac↔Windows.

Retirer :

```powershell
powershell -ExecutionPolicy Bypass -File $srv uninstall
```

Voir [`deploy/windows/README.md`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/deploy/windows/README.md)
pour la configuration exposée au réseau local et le tableau de parité face à
systemd / launchd.

## À lire aussi

- [Installation par WSL2](wsl2.md) — le chemin Windows recommandé.
- [La référence complète de l'installateur](install.md).
