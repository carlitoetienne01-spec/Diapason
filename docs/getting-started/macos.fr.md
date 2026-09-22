# Installation sur macOS

```bash
curl -fsSL https://carlitoetienne01-spec.github.io/Diapason/install.sh | bash
```

Fonctionne sur Intel comme sur Apple Silicon. L'installateur détecte tout seul ton
processeur et ta carte graphique.

## Les prérequis

Si tu n'as jamais lancé `git` ni `curl` sur ce Mac, macOS te proposera d'installer
les Xcode Command Line Tools au premier appel. Accepte la proposition ; elle
t'installe les deux d'un coup.

Si tu préfères les installer d'avance :

```bash
xcode-select --install
```

## Notes sur Apple Silicon

- L'installateur retient `mlx` comme moteur d'inférence recommandé, par la
  détection matérielle habituelle, mais le défaut affiché reste Ollama, par
  compatibilité. Tu peux changer plus tard avec `diapason init --force` et
  choisir `mlx` si tu as installé `mlx-lm`.
- L'installateur annonce la mémoire unifiée comme de la « VRAM » — c'est voulu :
  sur Apple Silicon, c'est la mémoire vive du système que les modèles accélérés
  par le GPU peuvent utiliser.

## Voir aussi

- [La référence complète de l'installateur](install.md)
