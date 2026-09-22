---
title: Téléchargements
description: Télécharge l'app de bureau Diapason, l'app navigateur, la CLI ou le SDK Python
---

# Téléchargements

Diapason tourne entièrement sur ta machine. Choisis l'interface qui te convient.

---

## L'app de bureau

L'app de bureau est une fenêtre native pour l'interface de discussion. Le modèle et
tout le traitement s'exécutent chez toi — l'app se connecte au serveur qui tourne
sur ta machine.

### macOS (Apple Silicon)

**[Télécharger la dernière version](https://github.com/carlitoetienne01-spec/Diapason/releases/latest)** —
le fichier `Diapason_<version>_aarch64.dmg`. Ouvre-le, glisse Diapason dans
Applications, lance-le.

L'app installe tout le reste elle-même au premier lancement — `uv`, Ollama, le
serveur Python et l'extension native — avec un écran de progression et sans
terminal. Détails : [premier-lancement.md](premier-lancement.md). Une fois
installée, les nouvelles versions apparaissent dans la barre latérale avec un
bouton **Installer**.

!!! note "Apple Silicon seulement, pour l'instant"
    Les versions sont construites sur un seul Mac Apple Silicon. Il n'y a pas
    encore de version Intel ni d'installateur Linux ; le workflow est prêt pour
    eux, mais rien n'est publié.

### « Diapason est endommagé et ne peut pas être ouvert »

La version n'est pas encore notariée par Apple (pas de compte Developer), donc
Gatekeeper met l'app téléchargée en quarantaine. Si tu vois ce message, lance ceci
une fois dans le Terminal pour lever le drapeau :

```bash
xattr -cr /Applications/Diapason.app
```

Ouvre ensuite l'app normalement. Si tu l'as installée depuis le DMG sans l'avoir
encore déplacée dans `/Applications`, pointe la commande là où se trouve le
paquet `.app` :

```bash
xattr -cr ~/Downloads/Diapason.app
```

!!! note
    C'est le cas courant des apps macOS open-source distribuées hors de l'App
    Store. La commande retire l'attribut étendu de quarantaine — elle ne modifie
    pas l'application.

### Ce qu'elle contient

L'app de bureau apporte :

- **L'interface de discussion complète** — la même que l'app navigateur, dans une fenêtre native
- **Le suivi de consommation** — la puissance électrique, en direct
- **Le tableau de bord** — débit de jetons, latence, et comparaison de coût avec les modèles distants
- **La barre de menus** — un accès rapide sans garder un terminal ouvert

Le serveur (Ollama, l'API Python, l'inférence) tourne sur ta machine, installé par
l'app elle-même au premier lancement.

### Construire depuis les sources

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason/frontend
npm install
npm run tauri:build
```

L'installateur construit se trouvera dans `frontend/src-tauri/target/release/bundle/`.

---

## L'app navigateur

Lance l'interface complète dans ton navigateur. Tout reste local — le serveur
tourne sur ta machine et l'interface s'y connecte par `localhost`.

### Installation en une commande

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
./scripts/quickstart.sh
```

Le script s'occupe de tout :

1. Vérifie que Python 3.10–3.13 et Node.js 18+ sont présents
2. Installe Ollama s'il manque et télécharge un premier modèle
3. Installe les dépendances Python et celles de l'interface
4. Démarre le serveur d'API et le serveur de développement de l'interface
5. Ouvre `http://localhost:5173` dans ton navigateur

### Installation pas à pas

Si tu préfères faire chaque étape toi-même :

=== "1. Cloner et installer"

    ```bash
    git clone https://github.com/carlitoetienne01-spec/Diapason.git
    cd Diapason
    uv sync --extra desktop
    cd frontend && npm install && cd ..
    ```

=== "2. Démarrer Ollama"

    ```bash
    # À installer depuis https://ollama.com si ce n'est pas déjà fait
    ollama serve &
    ollama pull qwen3:0.6b
    ```

=== "3. Démarrer le serveur"

    ```bash
    uv run diapason serve --port 8000
    ```

=== "4. Démarrer l'interface"

    ```bash
    cd frontend
    npm run dev
    ```

Ouvre ensuite [http://localhost:5173](http://localhost:5173).

### Ce que tu obtiens

- **L'interface de discussion** — rendu markdown, réponses au fil de l'eau, historique
- **Les outils** — calculatrice, recherche web, interpréteur de code, lecture et écriture de fichiers
- **Le panneau système** — télémétrie en direct, consommation, comparaison de coût
- **Le tableau de bord** — courbes d'énergie, débogage des traces, détail des coûts
- **Les réglages** — choix du modèle, configuration de l'agent, thème

---

## La ligne de commande

La CLI est le chemin le plus direct pour se servir de Diapason par programme.
Tout est accessible depuis le terminal.

### Installer

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync
```

### Vérifier

```bash
diapason --version
# diapason, version 0.1.0
```

### Premières commandes

```bash
# Poser une question
diapason ask "Quelle est la capitale de la France ?"

# Utiliser un agent avec des outils
diapason ask --agent orchestrator --tools calculator "Combien font 137 * 42 ?"

# Démarrer le serveur d'API
diapason serve --port 8000

# Lancer un diagnostic
diapason doctor

# Lister les modèles disponibles
diapason model list

# Discussion interactive
diapason chat
```

!!! info "Un moteur d'inférence est nécessaire"
    La CLI a besoin d'un moteur d'inférence en marche (Ollama, par exemple). Voir
    le [guide d'installation](getting-started/installation.md#mettre-en-place-un-moteur-d-inference-setting-up-an-inference-backend)
    pour la marche à suivre.

---

## Le SDK Python

Pour un accès par programme, la classe `Diapason` offre une API synchrone de haut
niveau.

### Installer

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync
```

### Exemple minimal

```python
from diapason import Diapason

j = Diapason()
print(j.ask("Explique le tri rapide en deux phrases."))
j.close()
```

### Avec des agents et des outils

```python
result = j.ask_full(
    "Quelle est la racine carrée de 144 ?",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(result["content"])       # « 12 »
print(result["tool_results"])  # les appels d'outils
print(result["turns"])         # le nombre de tours d'agent
```

### La couche de composition

Pour tout contrôler, passe par `SystemBuilder` :

```python
from diapason import SystemBuilder

system = (
    SystemBuilder()
    .engine("ollama")
    .model("qwen3:8b")
    .agent("orchestrator")
    .tools(["calculator", "web_search", "file_read"])
    .enable_telemetry()
    .enable_traces()
    .build()
)

result = system.ask("Résume l'actualité de l'IA.")
system.close()
```

Voir le [guide du SDK Python](user-guide/python-sdk.md) pour la référence complète.
