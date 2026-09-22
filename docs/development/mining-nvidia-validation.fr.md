# Procédure de validation du minage Pearl sur NVIDIA

Cette procédure est le verrou de publication du fournisseur `vllm-pearl` en v1.
Les tests unitaires prouvent que le câblage de Diapason tient ; ce qui suit
valide qu'une vraie machine H100/H200 sait miner à travers Pearl et servir
l'inférence à travers Diapason.

## L'hôte requis

Lance ceci sur une machine Linux qui a :

- une carte NVIDIA H100 ou H200, capacité de calcul 9.0, au moins 70 Go de VRAM
- un pilote NVIDIA à jour, compatible avec les conteneurs CUDA
- Docker 24+ et `nvidia-container-toolkit`
- au moins 200 Go de disque libre
- un point d'accès JSON-RPC `pearld` joignable
- une adresse de versement Pearl commençant par `prl1q` ou `prl1p`
- un accès Hugging Face à `pearl-ai/Llama-3.3-70B-Instruct-pearl`

La configuration H100 validée utilise `gpu_memory_utilization = 0.96` avec
`max_model_len = 8192`. Une utilisation mémoire plus basse peut faire échouer le
démarrage de vLLM : le modèle de minage Pearl 70B laisse alors trop peu de cache
KV pour un contexte de 8 k.

Ne lance pas ceci sur macOS, Apple Silicon, AMD, RTX 4090 ni sur une machine sans
carte graphique. Ce sont des fournisseurs distincts.

## Préparer l'adresse du portefeuille

Crée le portefeuille depuis la racine du dépôt Pearl :

```bash
./bin/oyster -u rpcuser -P rpcpass --create
```

Si tu acceptes l'invite facultative de chiffrement des données publiques, Oyster
exigera cette phrase de passe publique au démarrage, via `--walletpass`. Garde
autant que possible les phrases de passe privée et publique hors de l'historique
du shell.

Démarre Oyster :

```bash
./bin/oyster \
  -u rpcuser \
  -P rpcpass \
  --walletpass '<public-wallet-passphrase-if-configured>' \
  &
```

Génère ensuite une adresse de minage par le RPC du portefeuille :

```bash
./bin/prlctl \
  --wallet \
  --skipverify \
  -u rpcuser \
  -P rpcpass \
  -s localhost:44207 \
  getnewaddress
```

À noter :

- `--wallet` est obligatoire. Sans lui, `prlctl` parle à `pearld` et non à
  Oyster, et peut aller chercher `Pearld/pearld.conf`.
- Écris `-s localhost:44207`, pas `-s https://localhost:44207`. `prlctl` attend
  un hôte et un port, pas une URL.
- `--skipverify` est acceptable dans ce parcours de validation local, sauf si tu
  as configuré le chemin du certificat RPC d'Oyster.
- Si une phrase mnémonique a été collée dans des journaux, une discussion ou une
  PR, jette ce portefeuille et crées-en un neuf avant de miner.

## L'environnement

```bash
git checkout feat/mining-spec-a-only
uv sync --extra dev --extra mining-pearl-vllm

export PEARLD_RPC_PASSWORD='<pearld-rpc-password>'
export HF_TOKEN='<huggingface-token>'
```

Confirme les prérequis de la machine :

```bash
nvidia-smi
docker info
docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
df -h ~/.cache
```

Attendu :

- `nvidia-smi` affiche une H100 ou une H200.
- Docker sait lancer un conteneur CUDA avec accès à la carte graphique.
- `~/.cache`, ou le volume de cache Hugging Face, a au moins 200 Go de libre.

Sur une machine partagée, ne retiens que les cartes inoccupées au moment du
`mine init` :

```bash
uv run diapason mine init --cuda-visible-devices 0
```

Ceci écrit `[mining.extra].cuda_visible_devices`. `mine start` transmet cette
liste de périphériques à Docker et pose `CUDA_VISIBLE_DEVICES` /
`NVIDIA_VISIBLE_DEVICES` dans le conteneur. N'omets l'option que sur une machine
dédiée, où le mineur peut prendre toutes les cartes.

## Configurer le minage

Lance :

```bash
uv run diapason mine doctor
```

Avant qu'une configuration existe, `doctor` doit montrer le matériel et Docker au
vert, et le nœud Pearl / le portefeuille comme non configurés.

Initialise ensuite :

```bash
uv run diapason mine init
```

Renseigne :

- Portefeuille : l'adresse Pearl `prl1q...` ou `prl1p...` de l'utilisateur
- URL de `pearld` : en général `http://localhost:44107`
- Utilisateur RPC : l'utilisateur configuré dans `pearld`, souvent `rpcuser`
- Variable du mot de passe : `PEARLD_RPC_PASSWORD`
- Modèle : `pearl-ai/Llama-3.3-70B-Instruct-pearl`
- Image : celle par défaut, sauf si tu valides une image Pearl personnalisée
- Cartes CUDA : l'identifiant d'une carte inoccupée, `0` par exemple, sur une
  machine partagée

Attendu :

- `[mining]` et `[mining.extra]` sont écrits dans la configuration.
- L'image est trouvée localement, téléchargée, ou construite depuis la référence
  Pearl épinglée.
- La première construction peut prendre de 30 à 60 minutes.

Relance `doctor` :

```bash
uv run diapason mine doctor
```

Attendu :

- Matériel OK
- Docker OK
- Disque OK
- RPC du nœud Pearl OK et synchronisé
- Format du portefeuille OK
- `vllm-pearl SUPPORTED`
- Aucun fichier compagnon

## Démarrer le minage

```bash
uv run diapason mine start
```

Attendu :

- Le conteneur Docker `diapason-pearl-miner` démarre.
- `~/.diapason/runtime/mining.json` est écrit.
- Le fichier compagnon (*sidecar*) contient `vllm_endpoint`, `gateway_url`,
  `gateway_metrics_url` et `container_id`.

Inspecte :

```bash
docker ps --filter name=diapason-pearl-miner
cat ~/.diapason/runtime/mining.json
uv run diapason mine logs --tail 200
uv run diapason mine status
```

Attendu :

- Le conteneur tourne.
- vLLM écoute sur le port configuré, `8000` par défaut.
- Les métriques de la passerelle Pearl sont disponibles sur le port de métriques
  configuré, `8339` par défaut.
- `mine status` sort avec le code 0 et affiche `provider: vllm-pearl`.

## Vérifier que l'inférence de Diapason passe par le point d'accès de minage

Lance :

```bash
uv run diapason mine doctor
uv run diapason ask "Say hello in one sentence."
```

Attendu :

- `doctor` montre le fichier compagnon présent.
- La découverte des moteurs enregistre `vllm-pearl-mining`.
- Le prompt aboutit à travers le point d'accès Pearl/vLLM.
- Les journaux du conteneur montrent une activité vLLM pendant le prompt.

Si l'inférence réussit mais que les statistiques de minage restent à zéro,
enchaîne sur les contrôles du réseau Pearl ci-dessous : servir de l'inférence
avec vLLM ne prouve pas à soi seul qu'on mine.

## Vérifier la soumission au réseau Pearl

Interroge directement les métriques de la passerelle :

```bash
curl -fsS http://127.0.0.1:8339/metrics | tee /tmp/pearl-gateway-metrics.txt
uv run diapason mine status
```

Attendu :

- Le point d'accès des métriques rend du texte Prometheus.
- Si Pearl expose des compteurs de parts, `mine status` les fait correspondre
  correctement.
- Si les noms des métriques diffèrent, joins
  `/tmp/pearl-gateway-metrics.txt` à la PR et mets à jour
  `src/diapason/mining/_metrics.py`.

Vérifie la connectivité de `pearld` avec la même configuration RPC que celle du
minage :

```bash
curl --user "rpcuser:${PEARLD_RPC_PASSWORD}" \
  --data-binary '{"jsonrpc":"1.0","id":"oj","method":"getblockchaininfo","params":[]}' \
  -H 'content-type: text/plain;' \
  http://127.0.0.1:44107
```

Attendu :

- `blocks` et `headers` sont présents.
- Le nœud est synchronisé, ou assez proche pour valider le minage.

Prouver un gain réel demande une part ou un bloc accepté, et un crédit au
portefeuille. Selon la difficulté du réseau Pearl, cela peut dépasser la durée du
test de fumée. Note :

- la durée d'exécution
- `mine status` avant et après
- un instantané des métriques de la passerelle
- la fin des journaux du conteneur, pour ce qui est pertinent
- le solde du portefeuille ou la trace de la transaction, si une récompense
  tombe

## Arrêter et nettoyer

```bash
uv run diapason mine stop
docker ps --filter name=diapason-pearl-miner
test ! -e ~/.diapason/runtime/mining.json
```

Attendu :

- Le conteneur s'arrête.
- Le fichier compagnon est retiré.
- `diapason ask` ne passe plus par `vllm-pearl-mining`, sauf si un autre fichier
  compagnon de minage est attaché.

## Les critères de réussite

Le fournisseur NVIDIA est tenu pour prouvé quand tout ceci est vrai :

- `mine doctor` annonce le support sur H100/H200.
- `mine init` trouve ou construit l'image Pearl.
- `mine start` lance le conteneur et écrit le fichier compagnon.
- L'inférence de Diapason aboutit à travers `vllm-pearl-mining`.
- Les métriques de la passerelle Pearl sont joignables et `mine status` les
  analyse.
- `pearld` accepte le chemin réseau du mineur.
- Au moins une part ou un bloc accepté est observé — ou bien une confirmation
  documentée d'un mainteneur de Pearl établit que l'état observé de la passerelle
  suffit à prouver que le minage est en cours.

## Les pièces à joindre en cas d'échec

Quel que soit l'échec, rassemble :

```bash
uv run diapason mine doctor
uv run diapason mine status || true
uv run diapason mine logs --tail 300 || true
docker inspect diapason-pearl-miner || true
curl -fsS http://127.0.0.1:8339/metrics || true
nvidia-smi
docker info
```

Joins les sorties à la PR d'implémentation ou au ticket de suivi. Ne colle jamais
`PEARLD_RPC_PASSWORD`, le matériel de graine du portefeuille ni un jeton Hugging
Face.
