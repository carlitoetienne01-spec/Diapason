# Liste de contrôle avant publication

Avant de poser le tag d'une version, déroule cette liste sur de vraies machines (pas seulement dans des conteneurs de CI).

## Tests de fumée manuels (~30 min en tout)

Pour chaque plateforme ci-dessous, pars d'un compte utilisateur neuf ou d'un instantané de machine virtuelle. Lance la commande d'installation en une ligne et vérifie les étapes du tableau.

| Plateforme | Commande en une ligne | À vérifier |
|---|---|---|
| Portable macOS Intel | `curl -fsSL <url> \| bash` | (1)–(8) ci-dessous |
| Portable macOS ARM | idem | (1)–(8) |
| Machine virtuelle Ubuntu 22.04 neuve | idem | (1)–(8) |
| Machine virtuelle Fedora 40 neuve | idem | (1)–(8) |
| WSL2 Ubuntu sous Windows | idem | (1)–(8) |

### Les étapes de vérification

1. **L'installation s'achève en 5 min ou moins** sur une connexion haut débit ordinaire.
2. **`diapason` (sans argument)** ouvre une session de discussion en moins de 2 s.
3. **Le premier tour de discussion rend une réponse** venue de `qwen3.5:2b` via Ollama.
4. **La bannière annonce le travail en arrière-plan** (« Setting up in background: … ») tant qu'il continue.
5. **La notification de fin se déclenche** entre deux tours quand le travail de fond s'achève (extension Rust ou modèle).
6. **`diapason doctor`** sort avec le code 0 une fois tout le travail de fond terminé ; il affiche le tableau des tâches de fond.
7. **Relance `curl … | bash`** sur la même machine. Elle s'achève en 30 s ou moins et dit `[ok] step already done` à chaque étape.
8. **`diapason-uninstall`** retire `~/.diapason/` et `~/.local/bin/diapason*`. Vérifie avec `ls`.

## Vérification du chemin rapide vers le cloud

Sur n'importe laquelle des plateformes :

```bash
export ANTHROPIC_API_KEY=test-fake-key
diapason init --force
```

Vérifie qu'`init` propose le cloud (le mot « anthropic » apparaît dans l'invite) et que le `config.toml` obtenu porte `[intelligence] provider = "anthropic"`.

## Contrôles ponctuels des modes de défaillance

Joue au moins un scénario de panne par version ; change de scénario à chaque fois.

- Coupe le réseau au milieu de l'installation — vérifie que l'erreur est claire et que la relance va au bout.
- Supprime `~/.diapason/config.toml` — vérifie que `diapason` seul relance `init`.
- Supprime `~/.diapason/.venv` — vérifie qu'une relance du curl le répare.
- `EUID=0 bash install.sh` — vérifie l'échec net avec « don't run as root ».

## Les verrous de la CI (automatiques, rien à faire à la main)

- Tous les tests pytest passent : `uv run pytest tests/`
- Tous les tests bats passent : voir `.github/workflows/bash-tests.yml`
- La matrice d'intégration en conteneur est verte : voir `.github/workflows/installer-integration.yml`
