# Installation sous WSL2

Sous Windows, Diapason s'installe de deux façons : par **WSL2** (cette
page — la voie recommandée ; identique à Linux natif) ou en
**[Windows natif (avancé)](windows-native.md)** (phase 1 ; installateur
PowerShell, sans WSL2 ni Docker). Prends WSL2 pour le chemin le plus
confortable.

## La préparation de WSL, une fois pour toutes

Dans un PowerShell administrateur :

```powershell
wsl --install
```

Ouvre ensuite le shell Ubuntu (ou Debian) qui vient d'être installé.

## Installer Diapason

```bash
curl -fsSL https://carlitoetienne01-spec.github.io/Diapason/install.sh | bash
```

Environ 3 minutes. Tape `diapason` pour démarrer.

## Ce qui est propre à WSL

- L'installateur détecte WSL par `/proc/sys/kernel/osrelease` et démarre le démon Ollama avec `nohup ollama serve &` plutôt qu'avec systemd (WSL2 n'embarque pas systemd par défaut).
- Au premier lancement de `diapason`, le noyau WSL peut afficher une notification « process running in background » — c'est l'orchestrateur d'arrière-plan qui se détache. C'est normal.
- Les modèles vivent dans le système de fichiers de WSL (`~/.diapason/`), pas sur ton disque Windows. Pour récupérer de la place plus tard : `diapason-uninstall` retire tout.

## Voir aussi

- [La référence complète de l'installateur](install.md)
