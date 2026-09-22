# Installation sur Linux

```bash
curl -fsSL https://carlitoetienne01-spec.github.io/Diapason/install.sh | bash
```

Testé sur : Ubuntu 22.04 / 24.04, Fedora 40, Debian 12, Arch.

## Les prérequis

La plupart des distributions fournissent déjà `git` et `curl`. Si ce n'est pas le cas de la tienne :

```bash
# Debian / Ubuntu
sudo apt install git curl

# Fedora / RHEL
sudo dnf install git curl

# Arch
sudo pacman -S git curl
```

## Carte graphique NVIDIA / AMD

L'installateur la détecte tout seul, via `nvidia-smi` / `rocm-smi`. Pour les cartes de centre de données (A100, H100, MI300+), le moteur recommandé est vLLM ; pour les cartes grand public, c'est Ollama (NVIDIA) ou Lemonade (AMD).

## À lire aussi

- [La référence complète de l'installateur](install.md)
