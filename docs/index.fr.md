---
title: Diapason
description: L'IA personnelle, sur des appareils personnels
search:
  boost: 2
hide:
  - navigation
---

# L'IA personnelle, sur des appareils personnels

<p class="hero-tagline">
Diapason est un cadre de recherche pour des systèmes d'IA composables qui tournent sur l'appareil.
Construis une IA personnelle qui tourne sur ton matériel. Les API distantes sont facultatives.
</p>

<div class="grid cards" markdown>

-   :material-image-multiple:{ .lg .middle } **Ce que les gens en font**

    ---

    Une galerie de montages réels — des points du matin qui résument ton Slack et tes courriels de la nuit, un compagnon Discord qui connaît ton agenda, un relecteur de code qui travaille à 10 000 mètres d'altitude. Le résultat d'abord, avec des liens vers la documentation qui explique comment construire chacun.

    [:octicons-arrow-right-24: Parcourir la galerie](showcase/index.md)

</div>

---

## Pourquoi Diapason ?

Les agents d'IA personnels explosent en popularité, mais presque tous font encore transiter l'intelligence par des API distantes. Ton IA « personnelle » continue de dépendre du serveur de quelqu'un d'autre. Dans le même temps, notre recherche [Intelligence Per Watt](https://www.intelligence-per-watt.ai/) a montré que les modèles de langue locaux traitent déjà 88,7 % des questions de discussion et de raisonnement à un seul tour, avec une efficacité de l'intelligence multipliée par 5,3 entre 2023 et 2025. Les modèles et le matériel sont de plus en plus prêts. Ce qui manquait, c'est la pile logicielle qui rende praticable une IA personnelle locale d'abord.

Diapason est cette pile. C'est un cadre pour une IA personnelle locale d'abord, bâti autour de trois idées : des primitives partagées pour construire des agents qui tournent sur l'appareil ; des évaluations qui traitent l'énergie, les FLOPs, la latence et le coût en dollars comme des contraintes de premier rang, au même titre que la justesse ; et une boucle d'apprentissage qui améliore les modèles à partir des traces locales. Le but est simple : rendre possibles des agents d'IA personnels qui tournent en local par défaut et ne font appel au distant que lorsque c'est vraiment nécessaire. Diapason veut être à la fois une plateforme de recherche et une fondation de production pour l'IA locale, dans l'esprit de PyTorch.

---

## Pour commencer

=== "App navigateur"

    Lance l'interface de discussion complète en local avec un seul script :

    ```bash
    git clone https://github.com/carlitoetienne01-spec/Diapason.git
    cd Diapason
    ./scripts/quickstart.sh
    ```

    Le script installe les dépendances, démarre Ollama et un modèle local, lance le
    serveur et l'interface, puis ouvre `http://localhost:5173` dans ton navigateur.

=== "App de bureau"

    L'app de bureau est une fenêtre native pour l'interface de Diapason.
    Le serveur (Ollama et l'inférence) tourne sur ta machine — démarre-le d'abord, puis ouvre l'app.

    **Étape 1.** Démarre le serveur :

    ```bash
    git clone https://github.com/carlitoetienne01-spec/Diapason.git
    cd Diapason
    ./scripts/quickstart.sh
    ```

    **Étape 2.** Construis et ouvre l'app de bureau depuis le dépôt cloné.

    Aucune version de bureau n'est publiée pour l'instant. Sur le Mac de Carlito, le
    chemin validé est `./scripts/install-desktop.sh`. Les installateurs Windows et
    Linux restent indisponibles tant qu'ils n'ont pas tourné sur de vraies machines.
    La page [Téléchargements](downloads.md) donne l'état exact.

    L'app se connecte toute seule à `http://localhost:8000`.

    !!! warning "Premier lancement sur macOS"

        Lance `xattr -cr /Applications/Diapason.app` si l'app s'affiche comme « endommagée ».

=== "SDK Python"

    ```python
    from diapason import Diapason

    j = Diapason()                              # détection automatique du moteur
    response = j.ask("Explique le tri rapide.")
    print(response)
    ```

    Pour plus de contrôle, `ask_full()` rend les statistiques d'usage, les informations du modèle et les résultats d'outils :

    ```python
    result = j.ask_full(
        "Combien font 2 + 2 ?",
        agent="orchestrator",
        tools=["calculator"],
    )
    print(result["content"])       # "4"
    print(result["tool_results"])  # [{tool_name: "calculator", ...}]
    ```

=== "CLI"

    ```bash
    diapason ask "Quelle est la capitale de la France ?"

    diapason ask --agent orchestrator --tools calculator "Combien font 137 * 42 ?"

    diapason serve --port 8000

    diapason memory index ./docs/
    diapason memory search "options de configuration"
    ```

---

## Cinq primitives pour l'IA personnelle

Diapason est bâti sur cinq couches composables. Chacune a une interface nette et se remplace indépendamment des autres.

1. **Intelligence** — Choisis un modèle, ou laisse Diapason en choisir un pour ton matériel. Gère tout le catalogue des modèles locaux, tous fournisseurs confondus.
2. **Moteur** — Le moteur d'inférence : [Ollama](https://ollama.com), [vLLM](https://github.com/vllm-project/vllm), [SGLang](https://github.com/sgl-project/sglang), [llama.cpp](https://github.com/ggerganov/llama.cpp), les API distantes, et d'autres. Détecte ton matériel tout seul et recommande ce qui lui convient le mieux.
3. **Agents** — Un raisonnement en plusieurs étapes, avec des outils. Huit types d'agents intégrés, de la simple discussion aux workflows orchestrés.
4. **Outils et mémoire** — Recherche web, calculatrice, lecture et écriture de fichiers, interpréteur de code, recherche documentaire, état local persistant, et n'importe quel serveur MCP externe.
5. **Apprentissage** — Ton IA s'améliore avec le temps. Chaque interaction produit des traces qui pilotent l'amélioration automatique des poids du modèle, des prompts et du comportement des agents.

---

## Ce qu'elle sait faire

<div class="grid cards" markdown>

-   **Plus de 10 moteurs d'inférence**

    ---

    [Ollama](https://ollama.com), [vLLM](https://github.com/vllm-project/vllm), [SGLang](https://github.com/sgl-project/sglang), [llama.cpp](https://github.com/ggerganov/llama.cpp), [MLX](https://github.com/ml-explore/mlx), [Exo](https://github.com/exo-explore/exo), [LiteLLM](https://github.com/BerriAI/litellm), le distant (OpenAI/Anthropic/Google), et d'autres. La même interface `InferenceEngine` : tu passes de l'un à l'autre librement.

-   **Des workflows automatisés**

    ---

    Des agents programmés par cron qui surveillent, résument et agissent. Relecture de code, tri des courriels, synthèses de recherche — en marche jour et nuit sur ton matériel.

-   **À l'écoute du matériel**

    ---

    Détecte tout seul le fabricant de la carte graphique, son modèle et sa VRAM. Recommande le moteur optimal pour ton matériel.

-   **Hors ligne d'abord**

    ---

    Tout le cœur fonctionne sans connexion réseau. Les API distantes sont un supplément facultatif.

-   **Une API compatible OpenAI**

    ---

    `diapason serve` démarre un serveur FastAPI avec des réponses au fil de l'eau en SSE. Un remplacement direct pour les clients OpenAI.

-   **Suivi de l'énergie et du coût**

    ---

    Une télémétrie intégrée pour la consommation électrique de la carte graphique, le coût en jetons et la latence. Tu vois exactement ce que coûte chaque question, en watts et en dollars.

</div>

---

## La documentation

<div class="grid cards" markdown>

-   **[Premiers pas](getting-started/installation.md)**

    ---

    Installe Diapason, configure ton premier moteur et lance ta première question.

-   **[Guide d'utilisation](user-guide/cli.md)**

    ---

    La CLI, le SDK Python, et les guides du [point du matin](user-guide/morning-digest.md), de la [recherche approfondie](user-guide/deep-research.md), de l'[assistant de code](user-guide/code-assistant.md), de la [surveillance programmée](user-guide/scheduled-monitor.md), de la [discussion simple](user-guide/chat-simple.md), des [évaluations](user-guide/evaluations.md), des agents, de la mémoire, des outils et de la télémétrie.

-   **[Architecture](architecture/overview.md)**

    ---

    Le dessin à cinq primitives, le motif du registre, le trajet d'une question et l'apprentissage transversal.

-   **[Référence de l'API](api-reference/diapason/index.md)**

    ---

    Une référence générée automatiquement pour chaque module.

-   **[Déploiement](deployment/docker.md)**

    ---

    Docker, systemd, launchd. Des images de conteneur accélérées par la carte graphique.

-   **[Développement](development/contributing.md)**

    ---

    Le guide de contribution, les motifs d'extension, la feuille de route et le journal des changements.

</div>

## La recherche

Diapason fait partie d'[Intelligence Per Watt](https://www.intelligence-per-watt.ai/), une initiative de recherche qui étudie l'efficacité des systèmes d'IA qui tournent sur l'appareil. Développé au [Hazy Research](https://hazyresearch.stanford.edu/) et au [Scaling Intelligence Lab](https://scalingintelligence.stanford.edu/) du [Stanford SAIL](https://ai.stanford.edu/).

Le [billet de blog](https://diapason.stanford.edu/) donne la motivation de recherche complète, le détail de l'architecture et les résultats expérimentaux.

## Citation

```bibtex
@misc{saadfalcon2026diapasonpersonalaipersonal,
      title={Diapason: Personal AI, On Personal Devices}, 
      author={Jon Saad-Falcon and Avanika Narayan and Robby Manihani and Tanvir Bhathal and Herumb Shandilya and Hakki Orhun Akengin and Gabriel Bo and Andrew Park and Matthew Hart and Caia Costello and Chuan Li and Christopher Ré and Azalia Mirhoseini},
      year={2026},
      eprint={2605.17172},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2605.17172}, 
}
```

## Les soutiens

<p>
  <a href="https://www.laude.org/">Laude Institute</a> &bull;
  <a href="https://datascience.stanford.edu/marlowe">Stanford Marlowe</a> &bull;
  <a href="https://cloud.google.com/">Google Cloud Platform</a> &bull;
  <a href="https://lambda.ai/">Lambda Labs</a> &bull;
  <a href="https://ollama.com/">Ollama</a> &bull;
  <a href="https://research.ibm.com/">IBM Research</a> &bull;
  <a href="https://hai.stanford.edu/">Stanford HAI</a>
</p>

Suis [@DiapasonAI](https://x.com/DiapasonAI) sur X pour les nouveautés.
