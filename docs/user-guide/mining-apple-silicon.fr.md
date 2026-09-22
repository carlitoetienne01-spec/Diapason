# Miner Pearl sur Apple Silicon (et sur les autres machines CPU)

Diapason sait miner la chaîne [Pearl](https://github.com/pearl-research-labs/pearl)
sur les Mac Apple Silicon (M1/M2/M3/M4), avec le fournisseur `cpu-pearl`. **C'est
la v1** : du minage CPU découplé. Ton usage habituel des modèles locaux (Ollama,
MLX-LM, llama.cpp, vLLM) n'est pas touché ; le minage tourne en arrière-plan,
dans un processus à part.

## Des attentes honnêtes

**Le taux de hachage d'un CPU Apple Silicon est très loin de ce qu'une H100
produit avec le `vllm-miner` de Pearl.** Un ordre de grandeur, à la difficulté du
réseau près :

- M2 Max / M4 Max : ≪ 1 part par seconde à la difficulté habituelle du réseau principal
- H100 avec `vllm-miner` : nettement plus, et le travail de minage s'amortit en
  plus sur de la vraie inférence

Si tu veux miner pour le rendement, ce n'est pas le bon chemin. Si tu veux
participer au réseau avec le matériel que tu as déjà, sans rien acheter de
spécial, c'est celui-là.

Un fournisseur expérimental `apple-mps-pearl` existe pour les développeurs. Il
passe par PyTorch MPS pour les produits matriciels NoisyGEMM, pendant que le
hachage du transcript et la construction de la preuve restent sur le CPU. Cela
prouve que le chemin GPU d'Apple peut produire des `PlainProof` acceptées par les
validateurs, mais ce n'est pas encore le chemin performant du noyau Metal.

## Prérequis

- macOS arm64 (M1, M2, M3, M4) — ou Linux x86_64 / aarch64
- Python 3.12 (`brew install python@3.12`, ou bien `uv venv --python 3.12`)
- La chaîne d'outils Rust (`brew install rust` ou `curl https://sh.rustup.rs -sSf | sh`)
- Ton propre nœud [`pearld`](https://github.com/pearl-research-labs/pearl#node)
  en marche, RPC joignable sur `http://localhost:44107`
- Une adresse de portefeuille Pearl Taproot obtenue avec `oyster` (la CLI de portefeuille de Pearl)
- ~1 Go de disque libre pour le clone des sources de Pearl et les artefacts de construction

## Installer

```bash
# depuis ton dépôt Diapason
uv sync --extra mining-pearl-cpu
```

Si les wheels de Pearl ne sont pas encore sur PyPI (toujours vrai au 5 mai 2026),
`uv sync` réussit mais n'installe pas les vrais paquets Python de Pearl.
Construis-les et installe-les depuis une copie locale de Pearl :

```bash
cd /path/to/pearl/py-pearl-mining
maturin build --release
uv pip install target/wheels/py_pearl_mining-*.whl
uv pip install ../miner/miner-utils ../miner/pearl-gateway ../miner/miner-base
```

## Configurer

Crée un portefeuille Pearl et démarre à part un `pearld` synchronisé, en suivant
le README de Pearl. Écris ensuite la configuration de minage de Diapason :

```bash
export PEARLD_RPC_PASSWORD="rpcpass"

diapason mine init \
  --provider cpu-pearl \
  --wallet-address "<your-prl1...address>" \
  --pearld-rpc-url http://127.0.0.1:44107 \
  --pearld-rpc-user rpcuser \
  --pearld-rpc-password-env PEARLD_RPC_PASSWORD
```

Sur Apple Silicon, `--provider auto` choisit `apple-mps-pearl` ; prends
`--provider cpu-pearl` pour le chemin CPU prudent. Le chemin MPS est
expérimental et ne sert pour l'instant qu'à valider et à profiler, pas à gagner
quoi que ce soit.

Cela écrit :

```toml
[mining]
provider = "cpu-pearl"
wallet_address = "prl1..."
submit_target = "solo"
fee_bps = 0

[mining.extra]
pearld_rpc_url = "http://127.0.0.1:44107"
pearld_rpc_user = "rpcuser"
pearld_rpc_password_env = "PEARLD_RPC_PASSWORD"
gateway_host = "127.0.0.1"
gateway_port = 8337
metrics_port = 9109
```

## Lancer

```bash
diapason mine doctor        # la matrice des capacités
diapason mine start         # démarre les sous-processus passerelle + boucle de minage
diapason mine status        # l'état du sidecar et les métriques de la passerelle
diapason mine logs -n 120   # affiche les journaux récents
diapason mine stop          # arrête les sous-processus de minage
```

## Lire `mine doctor`

Chaque ligne est un contrôle. `✓` veut dire qu'il est passé ; `✗` affiche le
correctif à appliquer.

```
$ diapason mine doctor
Hardware
  GPU vendor          apple                            ✓
  Apple chip          M2 Max                           ✓
Pearl install
  py-pearl-mining     0.1.0 (cp312-abi3-macos-arm64)   ✓
  miner-base          0.1.0                            ✓
  pearl-gateway       0.1.0                            ✓
Pearl node
  RPC                 http://localhost:44107           ✓
  Block height        442107 (synced)                  ✓
Wallet
  Address format      prl1q...                         ✓
Provider capability
  cpu-pearl           SUPPORTED  (calibrated 0.X share/h on M2 Max)
Notes
  - This is decoupled mining: your normal LLM inference is unaffected
  - Hashrate is far below H100 mining; see this doc above
  - MPS mining: available as experimental apple-mps-pearl
Session
  Sidecar             absent (not running)
```

## Les limites

- **Windows n'est pas pris en charge en v1.** Le mineur tout-Rust de Pearl se
  construit sur Windows en principe, mais le chemin d'installation
  multiplateforme n'est pas testé. Passe par WSL2 s'il le faut.
- **Pas encore de couplage avec l'inférence.** La v1 est un processus à part :
  ton CPU mine, ton GPU fait l'inférence. Ils ne partagent aucun travail. La v2
  changera ça.
- **PyTorch-MPS expérimental, rien de plus.** `apple-mps-pearl` déplace les
  produits matriciels NoisyGEMM sur MPS, mais il repasse encore par le CPU pour
  le hachage du transcript et la construction de la preuve. Sers-t'en pour
  valider et profiler, pas pour en espérer un revenu.
- **Pas de pool multi-machines.** Minage solo seulement. Les pools font l'objet
  d'une spécification à part.

## Dépannage

| Symptôme | Cause probable | Correctif |
|---|---|---|
| `mine doctor` dit `Pearl Python packages not installed` | Les wheels ne sont pas encore construites | Lance `diapason mine init` |
| Le journal de `pearl-gateway` affiche `connection refused` vers `http://localhost:44107` | `pearld` n'est pas en marche | Démarre `pearld` en suivant le README de Pearl |
| `mine status` affiche `last_error: gateway metrics unreachable` | `pearl-gateway` a planté | Regarde `~/.diapason/logs/mining/pearl-gateway.log` |
| La construction échoue sur `error: linker 'cc' not found` | Les outils en ligne de commande Xcode ne sont pas installés | `xcode-select --install` |
| `maturin build` se plaint de `tikv-jemallocator` | Le SDK macOS est trop ancien | Mets macOS / Xcode à jour |

Pour tout ce qui n'est pas dans cette liste, récupère `~/.diapason/logs/mining/`
et ouvre un ticket sur https://github.com/carlitoetienne01-spec/Diapason/issues.

## Ce qui change en v2 / v3

- **v2 :** optimiser le chemin `apple-mps-pearl` actuel, puis éventuellement le
  brancher sur MLX-LM ou `llama-cpp-python` pour que les produits matriciels de
  l'inférence deviennent du travail de minage.
- **v3 (seulement si les performances de la v2 ne suffisent pas) :** un noyau
  Metal natif, contribué en amont à Pearl. Aucun changement visible pour
  l'utilisateur, sinon un taux de hachage plus élevé.
