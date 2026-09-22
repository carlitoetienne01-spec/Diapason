# Le minage Pearl

Diapason sait miner la chaîne Pearl — une chaîne à preuve de travail utile
(Proof-of-Useful-Work) — par de l'inférence LLM locale. Le chemin principal de
la v1 vise les machines NVIDIA H100/H200 qui font tourner vLLM avec le mineur
Docker de Pearl. L'intégration Pearl consolidée comprend aussi des fournisseurs
Apple Silicon et CPU expérimentaux, offerts par le même registre
`MiningProvider`.

## Prérequis

| Ce qu'il faut | Ce qu'attend la v1 |
|---|---|
| GPU | NVIDIA H100 ou H200, classe sm_90a, au moins 70 Go de VRAM |
| Système | Linux avec `nvidia-container-toolkit` configuré |
| Docker | Docker 24+ avec accès au runtime GPU |
| Disque | Au moins 200 Go libres pour le modèle 70B et le cache de construction |
| Nœud Pearl | Un point d'accès JSON-RPC `pearld` joignable, `http://localhost:44107` par défaut |
| Portefeuille | Une adresse Pearl commençant par `prl1q` ou `prl1p` |

La configuration vLLM par défaut utilise `gpu_memory_utilization = 0.96` et
`max_model_len = 8192` pour le modèle de minage Pearl 70B, sur les GPU
H100/H200 de 80 Go.

Pour obtenir une adresse de portefeuille avec Oyster, le portefeuille de Pearl,
lance le démon de portefeuille de Pearl et interroge-le avec `prlctl --wallet
--skipverify -s localhost:44207 getnewaddress`. Ne réutilise pas un
portefeuille dont la phrase mnémonique a été collée dans un journal, une
conversation ou un gestionnaire de tickets.

## Démarrage rapide

```bash
uv sync --extra mining-pearl-vllm
export PEARLD_RPC_PASSWORD=<your-pearld-password>
export HF_TOKEN=<your-huggingface-token>

uv run diapason mine init
uv run diapason mine start
uv run diapason mine status
```

`mine init` écrit une section de configuration `[mining]` et résout l'image
Docker de Pearl. Si Pearl n'a pas publié d'image convenable pour la référence
épinglée, Diapason se rabat sur une construction depuis la copie épinglée des
sources de Pearl. Une première construction peut prendre de 30 à 60 minutes.

Sur une machine NVIDIA partagée, restreins le mineur aux GPU inoccupés :

```bash
uv run diapason mine init --cuda-visible-devices 0
```

Cela écrit `[mining.extra].cuda_visible_devices`, que `mine start` passe à
Docker au lieu d'exposer tous les GPU de la machine.

## Les commandes

- `diapason mine models` liste l'état de prise en charge des modèles Pearl.
- `diapason mine inspect-model` vérifie l'artefact d'un modèle Pearl avant de
  lancer le GPU.
- `diapason mine doctor` affiche les contrôles du matériel, de Docker, du nœud
  Pearl, du portefeuille, du fournisseur et de la session.
- `diapason mine init` écrit la configuration de minage locale et résout
  l'image.
- `diapason mine start` lance le conteneur du mineur Pearl et écrit le sidecar
  d'exécution.
- `diapason mine stop` arrête le fournisseur et retire le sidecar.
- `diapason mine status` lit les métriques de la passerelle en direct.
- `diapason mine attach` écrit un sidecar pour un mineur que tu as lancé à la
  main.
- `diapason mine logs` affiche la fin du journal du conteneur Docker.
- `diapason mine validate-model` sonde le mineur vLLM actif et la passerelle
  avant de faire passer un modèle Pearl prévu au rang de validé.

## Les modèles pris en charge

Lance :

```bash
diapason mine models
```

Diapason ne liste que les modèles compatibles Pearl publiés par
l'organisation Hugging Face de Pearl Research Labs. Les modèles de base bruts
de Hugging Face, comme `meta-llama/Llama-3.3-70B-Instruct` ou
`google/gemma-4-31B-it`, ne minent rien par eux-mêmes : il leur faut la
variante `pearl-ai/*-pearl` correspondante.

Les identifiants de modèles Pearl pris en charge sont :

```text
pearl-ai/Llama-3.3-70B-Instruct-pearl
pearl-ai/Gemma-4-31B-it-pearl
pearl-ai/Llama-3.1-8B-Instruct-pearl
```

`pearl-ai/Llama-3.3-70B-Instruct-pearl` est le modèle validé par défaut.
D'autres artefacts publics `pearl-ai/*` peuvent rester marqués `planned` tant
qu'ils n'ont pas passé la campagne de validation Diapason sur H100/H200.

Pour valider un modèle de l'organisation Pearl sur une machine de minage,
lance :

```bash
diapason mine inspect-model \
  --model pearl-ai/Gemma-4-31B-it-pearl \
  --allow-planned

diapason mine validate-model \
  --model pearl-ai/Gemma-4-31B-it-pearl \
  --allow-planned \
  --prompt "Dis bonjour en une phrase." \
  --output gemma-4-31b-pearl-validation.json
```

Joins l'artefact JSON au ticket de validation quand tu fais promouvoir
d'autres modèles.

## Le périmètre de la v1

La v1 ne fait que du minage en solo. Diapason ne prélève aucune commission, ne
garde aucun fonds, ne génère aucune clé de portefeuille, n'opère ni pool ni
`pearld`. Tu fournis ton propre nœud Pearl et ton adresse de versement.

Ce que cette PR ne prend pas en charge :

- Le minage en pool et le futur modèle de commission Diapason à 20 %
- Le minage sur GPU AMD et les moteurs autres que Pearl
- Les RTX 4090 et les autres GPU NVIDIA qui ne sont pas de génération Hopper
- La génération de portefeuille ou la signature de transaction depuis Diapason

## Dépannage

Lance :

```bash
uv run diapason mine doctor
```

Lis les lignes de haut en bas. Corrige la première dépendance en échec avant de
relancer `mine start`. Un Mac ou une machine AMD doit échouer honnêtement au
contrôle de capacité du fournisseur : ces chemins-là arriveront sous forme de
fournisseurs distincts.

## Prêt pour la production

Le chemin NVIDIA réclame une vraie campagne de validation sur H100/H200 avant
qu'on puisse l'annoncer comme un moyen éprouvé de gagner quelque chose. Le
guide pour développeurs est
[`../development/mining-nvidia-validation.md`](../development/mining-nvidia-validation.md).
