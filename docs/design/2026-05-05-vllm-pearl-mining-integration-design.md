# Spec A — intégration du minage vLLM-Pearl (v1)

| | |
|---|---|
| **Date** | 2026-05-05 |
| **Statut** | Conception — plan de mise en œuvre à venir |
| **Responsable** | L'équipe Diapason |
| **Spécification compagnon** | [Spec B — activation d'Apple Silicon](2026-05-05-apple-silicon-pearl-mining-design.md) (chantier distinct, mené en parallèle) |
| **Dépôts référencés** | `Diapason` (ce dépôt), `pearl-research-labs/pearl` |

## 1. Résumé

Ajouter un sous-système frère, `diapason.mining`, qui permet de faire tourner le minage Proof-of-Useful-Work de [Pearl](https://github.com/pearl-research-labs/pearl) comme une propriété de l'inférence LLM locale. La v1 livre le minage en solo pour ceux qui ont déjà une H100/H200 et font tourner vLLM — la seule configuration que le mineur de référence de Pearl sache traiter aujourd'hui. L'architecture laisse trois amorces délibérées pour la v2 (prise en charge des pools + une commission OJ de 20 %) et elle est agnostique du moteur par construction : les chemins Apple Silicon, AMD, Ollama, llama.cpp et MLX se brancheront par le registre, sans réécriture, quand Pearl livrera les greffons correspondants.

La thèse, racontée : le `vllm-miner` de Pearl est un greffon vLLM qui remplace les opérations linéaires quantifiées par `NoisyGEMM`, un noyau CUDA qui produit à la fois le bon résultat de multiplication matricielle *et* un engagement de preuve de travail. Miner, C'EST inférer. Pour un utilisateur d'OJ qui sert déjà ses requêtes sur un GPU local puissant, c'est une façon de capter la valeur économique d'un calcul qu'il allait faire de toute façon — dans le sens de la thèse Intelligence-Per-Watt d'OJ, et non contre elle.

## 2. Périmètre

### Dans le périmètre (v1)
- Nouveau sous-système `diapason.mining` avec l'ABC `MiningProvider`, le `MinerRegistry` et les dataclasses `MiningCapabilities` / `MiningConfig` / `MiningStats`
- Implémentation du fournisseur `vllm-pearl` : orchestrer le conteneur Docker `vllm-miner` publié par Pearl
- Section TOML `[mining]` dans la configuration d'OJ ; champ `MiningConfig` dans `DiapasonConfig`
- Nouvel espace de commandes : `diapason mine init|start|stop|status|doctor|attach|logs`
- Fichier compagnon d'exécution dans `~/.diapason/runtime/mining.json` pour le relais entre le moteur et le minage
- Obtention hybride de l'image Docker : la tirer si elle est publiée, sinon la construire depuis une révision Pearl épinglée
- Télémétrie à la demande via la passerelle Pearl `:8339/metrics` ; colonne `mining_session_id` nullable sur les lignes d'inférence de la télémétrie
- Amorces pour la v2 : analyse de `submit_target` en union étiquetée, câblage à zéro de `fee_bps` / `fees_owed`, emplacement `mining/pools/` réservé
- Une stratégie de test qui ne réclame pas de H100 en CI
- Documentation : `docs/user-guide/mining.md`, `docs/development/mining.md`, un paragraphe dans `CLAUDE.md`, une puce dans `REVIEW.md`

### Hors périmètre (v1) — reporté, ou traité ailleurs
- La prise en charge des pools et le mécanisme de commission OJ de 20 % (spécification à part, v2)
- La garde, la signature ou l'acheminement de fonds Pearl (anti-objectif — doit rester à zéro en v1)
- Les chemins de minage Apple Silicon, AMD ROCm, NVIDIA sm89 (RTX 4090), CPU, MLX, Ollama, llama.cpp, SGLang (Spec B pour Apple ; les autres chemins matériels et moteurs sont bloqués sur Pearl)
- La création de portefeuille, l'intégration d'Oyster, la garde des clés (l'adresse se colle à la main, rien d'autre)
- La gestion du cycle de vie de pearld (le nœud est fourni par l'utilisateur)
- La collecte de télémétrie en arrière-plan dans le démon passerelle d'OJ (v1.x ; le point d'accroche est réservé)
- La détection de dérive de la qualité d'inférence (v1.x au plus tôt)
- La remédiation automatique `mine doctor --fix` (ébauche en v1.x)
- Multi-GPU, multi-travailleur, plusieurs sessions par machine (v2 et au-delà)

## 3. Les décisions porteuses, issues de l'exploration

Voici les bifurcations où la conception pouvait partir dans plusieurs directions. Elles sont consignées pour que les lecteurs à venir puissent vérifier le raisonnement au lieu de le refaire.

| Décision | Ce qu'on a retenu | Pourquoi |
|---|---|---|
| Public visé par la v1 | Les propriétaires de H100/H200 qui font tourner vLLM (la seule configuration qui marche chez Pearl aujourd'hui) | Tout ce qui est plus large est bloqué tant que Pearl ne livre pas de greffons hors CUDA ou hors vLLM. Un MVP pour utilisateurs avancés se livre en quelques semaines ; le pool, la commission et Apple sont des spécifications à part. |
| Modèle de minage | Co-localisé : toute inférence qui passe par le vLLM version Pearl est du travail de minage | Correspond à la conception du greffon `vllm-miner` de Pearl et à la thèse Intelligence-Per-Watt d'OJ. Le mode side-car est reporté tant que Pearl n'aura pas livré de greffons pour les moteurs que les gens utilisent hors minage. |
| Couplage au processus mineur de Pearl | L'envelopper et le lancer via Docker | L'image Docker de Pearl (ou son Dockerfile) est le contrat le plus stable qu'ils exposent. (1) « à toi d'apporter ton mineur » est trop maigre pour être une fonctionnalité ; (3) faire tourner leur espace de travail `uv` nativement nous attacherait à leur système de construction. |
| Emplacement du module | Sous-système frère de premier niveau, `mining/` (pair de `engine/`, `agents/`) | Correspond au découpage en modules déjà en place chez OJ. `MinerRegistry` est un registre pair. Les futurs fournisseurs non-vLLM s'inséreront à l'identique. |
| Rattachement au moteur | Un fichier compagnon d'exécution JSON, `~/.diapason/runtime/mining.json` | La classe du moteur vLLM existante n'est pas touchée. Le compagnon est la source de vérité unique qui relie le cycle de vie du minage à la résolution du moteur. Lisible d'un simple `cat`. |
| Forme de la configuration | Une section TOML `[mining]` plate, au premier niveau | Un seul fournisseur en v1 ; une configuration imbriquée par moteur pourra pousser plus tard si le multi-fournisseur devient réel. |
| Gestion du portefeuille | Une adresse Taproot Pearl collée à la main, rien d'autre | Les clés sont sensibles ; le RPC de portefeuille de Pearl est une surface instable. La v1.x pourra ajouter l'intégration d'Oyster une fois le contrat stabilisé. |
| pearld | À l'utilisateur de le fournir ; il pointe OJ vers son propre nœud | OJ n'orchestre pas de nœuds L1. Le docteur signale proprement un nœud injoignable. |
| Collecte de télémétrie | Lectures à la demande en v1 ; la classe collectrice persistante (`MiningTelemetryCollector`) est livrée non branchée | La plupart des gens n'activeront pas le minage ; le démon n'a pas à grossir pour eux. La v1.x allume le point d'accroche sans remuer l'API. |
| Amorces commission/pool de la v1 | Trois amorces : `submit_target` analysé (une seule variante marche), `fee_bps` / `fees_owed` câblés à zéro, `mining/pools/` réservé | Peu coûteux à laisser ; pénible à rajouter après coup. Ne préjuge pas de l'API de la v2. |
| Garde des fonds | **Anti-objectif** : zéro. La v1 ne doit ni accepter, ni signer, ni acheminer de fonds Pearl. | Évite de figer prématurément une position juridique et réglementaire. La v2 y reviendra dans le cadre de la conception des pools. |
| Prise en charge d'Apple Silicon | Pas en v1. Prévue par l'ABC `MiningProvider` + `MiningCapabilities.detect()`. La Spec B documente le travail d'activation. | Le noyau `pearl-gemm` de Pearl est fortement lié à Hopper (`sm_90a`, WGMMA, TMA, mode cluster, CUTLASS 3.x). Un portage Metal, c'est du vrai travail de noyau GPU, pas un drapeau de configuration. |

## 4. Architecture et découpage des modules

### 4.1 Le nouvel arbre de modules

```
src/diapason/mining/
    __init__.py          # importe les fournisseurs en douceur (try/except ImportError)
    _stubs.py            # l'ABC MiningProvider + les dataclasses (MiningCapabilities, MiningConfig, MiningStats, SoloTarget, PoolTarget)
    _discovery.py        # detect_providers(hardware, engine, model) -> list[MiningCapabilities]
    _docker.py           # PearlDockerLauncher — orchestration Docker partagée (obtention de l'image + cycle de vie du conteneur)
    _collector.py        # la classe MiningTelemetryCollector — définie mais NON BRANCHÉE en v1 ; allumée en v1.x
    _constants.py        # PEARL_REPO, PEARL_PINNED_REF, PEARL_IMAGE_TAG, étiquette par défaut d'OJ
    vllm_pearl.py        # @MinerRegistry.register("vllm-pearl") — seule implémentation en v1
    pools/               # RÉSERVÉ pour la v2. Vide en v1, hormis un __init__.py dont la docstring le dit.

src/diapason/cli/
    mine_cmd.py          # diapason mine init|start|stop|status|doctor|attach|logs

tests/mining/
    __init__.py
    conftest.py          # fixtures propres au minage (HardwareInfo synthétique, sortie Prometheus d'exemple)
    fixtures/
        gateway_metrics_sample.txt   # sortie Prometheus capturée sur une vraie session Pearl
        config_*.toml                # fichiers TOML de référence
    test_stubs.py
    test_discovery.py
    test_docker.py
    test_collector.py
    test_vllm_pearl.py
    test_cli.py
```

### 4.2 Ce qui s'ajoute au registre

`MinerRegistry` est ajouté à `src/diapason/core/registry.py`, pair d'`EngineRegistry`, `AgentRegistry`, etc. La fixture autouse `_clean_registries` de `tests/conftest.py` est mise à jour pour inclure `MinerRegistry.clear()`.

`mining/vllm_pearl.py` expose un `ensure_registered()` idempotent :

```python
def ensure_registered() -> None:
    if not MinerRegistry.contains("vllm-pearl"):
        MinerRegistry.register_value("vllm-pearl", VllmPearlProvider)
```

`mining/__init__.py` importe `vllm_pearl` en douceur dans un `try / except ImportError` et appelle `ensure_registered()`. Le motif habituel d'OJ.

### 4.3 Les extras de dépendances optionnelles

```toml
mining-pearl       = ["docker>=7.0"]   # la v1 n'a besoin que du SDK Docker
# mining-pearl-mlx   = [...]            # à venir, du ressort de la Spec B
# mining-pearl-rocm  = [...]            # à venir
```

### 4.4 L'ABC centrale

```python
# src/diapason/mining/_stubs.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from diapason.core.config import HardwareInfo

@dataclass(slots=True)
class MiningCapabilities:
    supported: bool
    reason: str | None = None              # lisible par un humain : "il faut sm90", "aucun greffon Pearl pour le moteur ollama"
    estimated_hashrate: float | None = None

@dataclass(slots=True)
class SoloTarget:
    pearld_rpc_url: str

@dataclass(slots=True)
class PoolTarget:
    url: str
    worker_id: str | None = None

SubmitTarget = SoloTarget | PoolTarget

@dataclass(slots=True)
class MiningConfig:
    provider: str                          # clé du MinerRegistry
    wallet_address: str
    submit_target: SubmitTarget            # analysé depuis le TOML "solo" / "pool:<url>" ; la v1 n'accepte que SoloTarget à l'exécution
    fee_bps: int = 0                       # v1 : 0 ; v2 : 2000 (= 20 %)
    fee_payout_address: str | None = None  # v1 : ignoré ; v2 : l'adresse d'OJ
    extra: dict = field(default_factory=dict)

@dataclass(slots=True)
class MiningStats:
    provider_id: str
    shares_submitted: int = 0
    shares_accepted: int = 0
    blocks_found: int = 0
    hashrate: float = 0.0
    uptime_seconds: float = 0.0
    last_share_at: float | None = None
    last_error: str | None = None
    payout_target: str = "solo"            # remontée de la v2 ; toujours "solo" en v1
    fees_owed: int = 0                     # point d'accroche comptable de la v2 ; 0 en v1

class MiningProvider(ABC):
    provider_id: str

    @classmethod
    @abstractmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities: ...

    @abstractmethod
    async def start(self, config: MiningConfig) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    def is_running(self) -> bool: ...
    @abstractmethod
    def stats(self) -> MiningStats: ...
```

## 5. Schéma de configuration et rattachement au moteur

### 5.1 Le schéma TOML

```toml
[mining]
provider                = "vllm-pearl"               # clé du MinerRegistry
wallet_address          = "prl1q..."                 # adresse Taproot Pearl de l'utilisateur (collée à la main)
submit_target           = "solo"                     # v1 : "solo" uniquement ; "pool:<url>" lève NotImplementedError dans start()
fee_bps                 = 0                          # v1 : 0 ; v2 : 2000
fee_payout_address      = ""                         # v1 : ignoré ; v2 : l'adresse d'OJ

[mining.extra]
docker_image_tag         = "diapason/pearl-miner:<pinned-ref>"
model                    = "pearl-ai/Llama-3.3-70B-Instruct-pearl"
gateway_port             = 8337
gateway_metrics_port     = 8339
vllm_port                = 8000
gpu_memory_utilization   = 0.9
max_model_len            = 8192
pearld_rpc_url           = "http://localhost:44107"
pearld_rpc_user          = "rpcuser"
pearld_rpc_password_env  = "PEARLD_RPC_PASSWORD"     # le nom de la variable d'environnement, pas le secret
hf_token_env             = "HF_TOKEN"                # le nom de la variable d'environnement
```

Les secrets : des *noms* de variables d'environnement, jamais des valeurs littérales. Comme la convention déjà en place chez OJ pour les clés d'API distantes.

### 5.2 Le champ dans DiapasonConfig

`core/config.py` ajoute :

```python
@dataclass(slots=True)
class DiapasonConfig:
    ...
    mining: MiningConfig | None = None
```

Le chargeur TOML lit `[mining]`, analyse `submit_target` en `SoloTarget | PoolTarget`, valide contre la dataclass et signale les clés `extra` inconnues par un avertissement. Section absente → `mining = None` → aucun changement de comportement.

### 5.3 Le fichier compagnon d'exécution

`~/.diapason/runtime/mining.json` (créé par `mine start`, supprimé par `mine stop`) :

```json
{
  "provider": "vllm-pearl",
  "vllm_endpoint": "http://127.0.0.1:8000/v1",
  "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
  "gateway_url": "http://127.0.0.1:8337",
  "gateway_metrics_url": "http://127.0.0.1:8339",
  "container_id": "abc123...",
  "wallet_address": "prl1q...",
  "started_at": 1714867200
}
```

Le compagnon omet délibérément tous les secrets et tous les identifiants de processus. `container_id` est la poignée qui fait foi (Docker est la source de vérité pour savoir si ça tourne) ; `wallet_address` est capturée pour détecter une dérive entre la configuration et l'exécution.

### 5.4 Le relais vers le moteur

1. `diapason mine start` → `MinerRegistry.get("vllm-pearl").start(config)`.
2. `VllmPearlProvider.start()` appelle `_docker.PearlDockerLauncher.start(config)` et écrit le compagnon.
3. `engine/_discovery.py` cherche `mining.json` à chaque résolution de moteur. S'il est là, il enregistre automatiquement une instance de moteur `vllm` pointant sur `vllm_endpoint`, nommée `vllm-pearl-mining`, marquée par défaut pour les opérations qui connaissent le minage.
4. `diapason ask` et le SDK sont routés vers ce point d'accès de façon transparente. L'inférence ordinaire de l'utilisateur EST le travail de minage.

La classe du moteur vLLM elle-même (`engine/openai_compat_engines.py`) n'est **pas modifiée**. Le changement dans `engine/_discovery.py` est petit et purement additif : il regarde s'il y a un `mining.json` et, si oui, enregistre une instance `vllm` dérivée qui pointe sur le point d'accès de minage. Pas de compagnon → la découverte ne change pas.

### 5.5 Le mode manuel

Les utilisateurs avancés qui font tourner leur propre conteneur Pearl sautent `diapason mine start` et écrivent le compagnon eux-mêmes avec `diapason mine attach --vllm-endpoint=... --gateway-url=...`. Ça découple le cycle de vie du câblage.

## 6. Surface CLI, cycle de vie et intégration au démon

### 6.1 Les sous-commandes

| Commande | Rôle |
|---|---|
| `diapason mine init` | Interactive : contrôles matériel et Docker, demande le portefeuille et les identifiants pearld, écrit `[mining]`, tire ou construit l'image. Ne démarre PAS le minage. Vérifie au préalable qu'il reste au moins 200 Go d'espace disque. |
| `diapason mine start` | Lance le conteneur via le fournisseur enregistré, écrit le compagnon, affiche les infos du point d'accès. Idempotente si ça tourne déjà. |
| `diapason mine stop` | Arrête le conteneur, retire le compagnon. Idempotente si rien ne tourne. |
| `diapason mine status` | Lit le compagnon et interroge la passerelle `:8339/metrics`. Affiche `MiningStats`. |
| `diapason mine doctor` | La matrice des capacités ; chaque contrôle en ✓/✗, avec sa raison. Marche dans n'importe quel état. |
| `diapason mine attach` | Mode manuel : écrit le compagnon sans rien lancer. |
| `diapason mine logs [-f]` | Suit les journaux du conteneur à travers le SDK Docker. |

### 6.2 La sortie du docteur (l'exemple de référence)

```
$ diapason mine doctor
Matériel
  Marque du GPU       nvidia                           ✓
  Capacité de calcul  sm_90a                           ✓
  VRAM                80 Go                            ✓  (il faut ≥ 70 Go pour le Pearl 70 B)
Docker
  Démon               en marche, 24.0.7                ✓
  Runtime GPU         nvidia-container-toolkit         ✓
Disque
  Libre dans le cache HF   312 Go                      ✓  (il faut ≥ 200 Go)
Image
  diapason/pearl-miner:<ref>   présente (construite le 2026-04-30)   ✓
Nœud Pearl
  RPC                 http://localhost:44107           ✓
  Authentification    ok                               ✓
  Hauteur de bloc     442107 (synchronisé)             ✓
Portefeuille
  Format de l'adresse prl1q...                         ✓
Capacité du fournisseur
  vllm-pearl          PRIS EN CHARGE
Session
  Compagnon           absent (rien ne tourne)
  Conteneur           —
```

Chaque ligne correspond à une fonction de contrôle dans `mining/_discovery.py`. Un échec affiche une raison actionnable (par exemple `✗  raison : il faut sm90, tu as sm89 (RTX 4090)`).

### 6.3 Les états du cycle de vie

```
NOT_CONFIGURED  →  CONFIGURED  →  STARTING  →  RUNNING  ⇄  STOPPING  →  STOPPED
                                       ↘
                                       FAILED
```

Les règles de dérivation de l'état (pas de fichier d'état séparé — il se déduit de la configuration, du compagnon et de l'inspection du conteneur) :

- `NOT_CONFIGURED` — pas de `[mining]` dans la configuration
- `CONFIGURED` — configuration présente, pas de compagnon
- `STARTING` — compagnon dont le `started_at` remonte à moins de ~30 s, conteneur existant mais passerelle pas encore saine
- `RUNNING` — compagnon présent, conteneur en marche, passerelle qui répond
- `FAILED` — compagnon présent, mais conteneur sorti ou passerelle en échec au-delà du seuil
- `STOPPING` — `mine stop` appelée, arrêt Docker en cours
- `STOPPED` — `mine stop` terminée, compagnon retiré

### 6.4 L'intégration au démon : délibérément minimale en v1

- Docker se charge de redémarrer le conteneur via `--restart=unless-stopped`. OJ ne le materne pas.
- Le démon `com.diapason.gateway` existant n'est pas touché.
- Point d'accroche pour la v1.x : `MiningTelemetryCollector` (déjà livré en v1, non branché) pourra être ajouté à la passerelle comme tâche asynchrone toutes les 30 secondes.
- La surface d'installation launchd/systemd (`diapason daemon install`) reste intacte.

### 6.5 La concurrence

Un `flock` POSIX sur `~/.diapason/runtime/mining.lock` empêche deux `mine start` de se marcher dessus.

### 6.6 L'indice affiché par `diapason ask`

Quand `[mining]` est configuré mais qu'aucun compagnon n'existe, `cli/hints.py` émet une ligne : `"minage configuré mais à l'arrêt — démarre-le avec \`diapason mine start\`"`. Un coup de coude d'une ligne, sans aucune infrastructure nouvelle.

## 7. L'intégration Docker de Pearl

### 7.1 Ce qu'on a constaté en inspectant le dépôt de Pearl

- **Le contexte de construction, c'est tout le monorepo Pearl.** Le Dockerfile copie les `pyproject.toml` / `uv.lock` de la racine, `miner/`, `pearl-blake3/`, `py-pearl-mining/`, `zk-pow/`, `plonky2/`. Construire exige le dépôt complet.
- **Pearl ne publie aucune image de registre à ce jour.** Le README ne documente que `docker buildx build -t vllm_miner . -f miner/vllm-miner/Dockerfile`.
- **Un seul conteneur, trois ports.** `entrypoint.sh` lance `pearl-gateway` en arrière-plan, attend `:8339/metrics`, puis fait un `exec` de `vllm serve`. Les ports : `8000` (vLLM), `8337` (RPC du mineur), `8339` (métriques de la passerelle).
- **Une pile épinglée à l'intérieur de l'image.** CUDA 12.9.1, vLLM 0.20.0+cu129, Python 3.12, `compute_90a/sm_90a`. C'est Pearl qui le fixe, pas nous.
- **Le coût du premier lancement.** vLLM tire le modèle de 70 B depuis HF au premier service (~140 Go). La construction elle-même prend 30 à 60 min au premier `init`.

### 7.2 L'obtention hybride de l'image

| Mode | Comportement | Quand |
|---|---|---|
| **Tirer une image déjà construite** | OJ fait un `docker pull` de l'étiquette configurée si elle se résout dans un registre | Par défaut, le jour où Pearl publiera ; utilisateurs avec registre privé ; CI |
| **Construire depuis la révision épinglée** | OJ clone Pearl à une révision épinglée dans `~/.diapason/cache/pearl/`, puis fait un `docker buildx build` | Le défaut en v1 (Pearl ne publie rien aujourd'hui) |
| **Image fournie par l'utilisateur** | L'utilisateur met dans `mining.extra.docker_image_tag` une image qu'il a construite ou tirée lui-même | Utilisateurs avancés, environnements coupés du réseau |

La logique de choix, dans `_docker.PearlDockerLauncher.ensure_image()` :
1. Si `docker_image_tag` se résout en local → on l'utilise.
2. Sinon `docker pull <tag>` → si ça réussit, on l'utilise.
3. Sinon, si `tag == OJ_DEFAULT_TAG`, on se rabat sur le clone-et-construis depuis `PEARL_PINNED_REF`.
4. Sinon, on échoue avec une erreur claire qui renvoie vers `mine doctor`.

### 7.3 L'épinglage de la version de Pearl

`mining/_constants.py` :

```python
PEARL_REPO       = "https://github.com/pearl-research-labs/pearl.git"
PEARL_PINNED_REF = "<sha-or-tag>"            # relevé à chaque version d'OJ, après essai de la révision
PEARL_IMAGE_TAG  = f"diapason/pearl-miner:{PEARL_PINNED_REF}"
```

Les notes de version d'OJ annoncent la révision Pearl livrée. Relever la révision fait l'objet de sa propre PR, avec un flux de travail documenté.

### 7.4 La forme du lancement du conteneur

Via le SDK `docker>=7.0`, dans `_docker.PearlDockerLauncher.start()` :

```python
container = client.containers.run(
    image=PEARL_IMAGE_TAG,
    command=[
        config.extra["model"],
        "--host", "0.0.0.0",
        "--port", str(config.extra["vllm_port"]),
        "--gpu-memory-utilization", str(config.extra["gpu_memory_utilization"]),
        "--enforce-eager",
        "--max-model-len", str(config.extra.get("max_model_len", 8192)),
    ],
    name="diapason-pearl-miner",
    detach=True,
    auto_remove=False,
    restart_policy={"Name": "unless-stopped"},
    device_requests=[ DeviceRequest(count=-1, capabilities=[["gpu"]]) ],
    shm_size="8g",
    network_mode="host",
    volumes={
        str(Path.home() / ".cache/huggingface"): {
            "bind": "/root/.cache/huggingface",
            "mode": "rw",
        },
    },
    environment={
        "PEARLD_RPC_URL":         config.extra["pearld_rpc_url"],
        "PEARLD_RPC_USER":        config.extra["pearld_rpc_user"],
        "PEARLD_RPC_PASSWORD":    os.environ[config.extra["pearld_rpc_password_env"]],
        "PEARLD_MINING_ADDRESS":  config.wallet_address,
        "HF_TOKEN":               os.environ.get(config.extra.get("hf_token_env", "HF_TOKEN"), ""),
        "MINER_RPC_TRANSPORT":    "tcp",
    },
)
```

### 7.5 Les compromis, dits à voix haute

- **`network_mode="host"`** parce que le RPC de pearld, sur `http://localhost:44107`, vit sur la machine hôte. Un réseau Docker défini par l'utilisateur ajoute des étapes de configuration sans bénéfice réel d'isolation sur une machine dédiée au minage. Le pragmatisme l'emporte sur la pureté. À noter : le réseau en mode hôte a une sémantique Linux ; Docker sur macOS et Windows le traite autrement. Acceptable en v1, puisque H100/H200 + nvidia-container-toolkit contraint de toute façon le déploiement à Linux.
- **`auto_remove=False`** pour qu'un conteneur qui s'écroule reste là et qu'on puisse l'autopsier avec `diapason mine logs`.
- **Le cache HF est monté depuis l'hôte.** Les 140 Go de poids ne se téléchargent qu'une fois, survivent aux redémarrages du conteneur et restent visibles par les autres outils.
- **Les secrets passent par des noms de variables d'environnement**, jamais écrits dans l'image du conteneur, ni dans le compagnon, ni dans les étiquettes Docker.

### 7.6 La frontière autour du portefeuille

OJ ne voit jamais de phrase secrète Pearl, n'importe jamais de clé Oyster, ne signe jamais de transaction Pearl. Le seul secret Pearl qu'OJ touche est le mot de passe RPC de pearld (passé dans l'environnement du conteneur, récupéré par son nom depuis l'environnement de l'hôte). L'adresse de minage, elle, est publique — en clair dans la configuration, c'est très bien.

### 7.7 Le cycle de vie de l'image, vu de l'utilisateur

- `diapason mine init` déclenche `ensure_image()` et fait défiler la sortie de construction ou de tirage dans la CLI, avec une estimation de durée franche (`"Construction de l'image du mineur Pearl — le premier passage prend ~45 min sur une machine rapide"`).
- `diapason mine doctor` rapporte `image : présente (étiquette, âge, sha)` ou `image : manquante (lance mine init)`.
- `diapason mine prune` (v1.x) nettoiera les vieilles étiquettes `diapason/pearl-miner:*`. En v1, un `docker image rm` à la main fait l'affaire.

## 8. Les accroches de télémétrie et les amorces commission/pool de la v2

### 8.1 La télémétrie — la surface de lecture

Le conteneur de Pearl expose `:8339/metrics` (format d'exposition Prometheus). La v1 ne lit que ce point d'accès. L'introspection RPC plus profonde via `:8337` est reportée à la v2.

### 8.2 L'adaptateur et la correspondance des métriques

`mining/vllm_pearl.py::_parse_gateway_metrics()` traduit les lignes Prometheus en `MiningStats`. Les noms de métriques restent à confirmer à la mise en œuvre — à vérifier contre la fixture capturée `tests/mining/fixtures/gateway_metrics_sample.txt`. La correspondance attendue (repli : remplir de zéros tout champ manquant et journaliser un avertissement unique) :

| Champ de `MiningStats` | Métrique Pearl probable (à vérifier à la mise en œuvre) |
|---|---|
| `shares_submitted` | `pearl_gateway_shares_submitted_total` |
| `shares_accepted` | `pearl_gateway_shares_accepted_total` |
| `blocks_found` | `pearl_gateway_blocks_found_total` |
| `hashrate` | taux dérivé de `shares_submitted_total` |
| `uptime_seconds` | `process_start_time_seconds` |
| `last_share_at` | `pearl_gateway_last_share_timestamp` |
| `last_error` | dérivé des écarts de `pearl_gateway_errors_total` |

### 8.3 La cadence de collecte

- **v1 : à la demande, uniquement.** `diapason mine status` fait un GET HTTP par appel (~10 ms). Aucun sondage en arrière-plan.
- **v1.x : `MiningTelemetryCollector` allumé dans le démon passerelle.** La classe est livrée en v1 mais non branchée. La v1.x ajoutera une tâche asyncio périodique ; même schéma `MiningStats`, même point d'accès de passerelle. L'API ne bouge pas d'un pouce.

### 8.4 L'extension Intelligence-Per-Watt

Le schéma de `telemetry/store.py` gagne une colonne `mining_session_id` nullable sur les lignes d'inférence :

- Marquée quand une inférence passe par le point d'accès de minage Pearl ; nulle sinon.
- Les lignes non marquées se comportent exactement comme aujourd'hui — aucun impact sur le chemin sans minage.
- `diapason telemetry stats --mining` (v1.x) joindra le dernier instantané `MiningStats` et rapportera `tokens / share`, `joules / share`, `est. PRL / kWh`.

La v1 livre la colonne et le chemin de jointure qui ne fait rien. La v1.x allume la remontée. C'est la métrique qui intéresse vraiment la thèse IPW.

### 8.5 Les amorces commission/pool de la v2 (trois, concrètes, pas une de plus)

**1. `submit_target` analysé en union étiquetée ; une seule variante fonctionne.** `SoloTarget` est accepté à l'exécution en v1 ; `PoolTarget` lève `NotImplementedError("le support des pools est en v2 — voir diapason#XYZ")`. Atteignable seulement par ceux qui modifient leur configuration pour s'y engager.

**2. `fee_bps` / `fee_payout_address` câblés ; à zéro en v1.** `MiningStats.fees_owed = 0` et `MiningStats.payout_target = "solo"`, toujours, en v1. Le schéma est réel ; les valeurs sont nulles. Aucune migration en v2.

**3. L'emplacement de module `mining/pools/` est réservé.** Vide en v1, hormis un `__init__.py` dont la docstring dit que l'emplacement est réservé au travail `PoolClient` de la v2. La spécification v1 **ne définit pas** d'ABC `PoolClient` — prédire l'API de la v2 au détail près ne créerait que de la dette de migration. La spécification v2 écrira dans un emplacement vide.

### 8.6 Ce que la v1 se garde délibérément de figer

- Le protocole de pool (PPLNS / PPS / SOLO+ / maison)
- Le modèle de garde (séquestre, partage de coinbase sans confiance, contrat de règlement)
- L'URL du pool OJ, le format des parts, leur difficulté
- KYC, conditions d'utilisation, seuils de versement

### 8.7 L'anti-objectif de la garde des fonds

La v1 ne doit introduire aucun chemin de code où OJ prend la garde de fonds Pearl, les signe ou les achemine. Le plus loin où la v1 aille, c'est lire `wallet_address` (publique) et la passer au conteneur. La v2 y reviendra.

### 8.8 L'hypothèse d'une seule session (dite, mais pas amorcée)

La v1 suppose une seule session de minage par machine (un seul compagnon). L'éventail multi-GPU et multi-travailleur, c'est la v2 et au-delà. Le compagnon deviendrait alors une liste, ou un répertoire.

## 9. Traitement des pannes et stratégie de test

### 9.1 Les principes

1. **Échouer fort, ne pas se soigner tout seul.** Docker gère les redémarrages de conteneur ; `mine doctor` dit ce qui ne va pas. OJ ne réessaie pas un travail de minage, ne redémarre pas pearld, ne maquille pas un plantage.
2. **`mine doctor` est la surface de panne qui fait foi.** Chaque mode de défaillance ci-dessous correspond à une ou plusieurs lignes de la sortie du docteur.
3. **Le compagnon fait foi ; la configuration dit l'intention.** Une dérive se signale par un avertissement, pas par un plantage.

### 9.2 La matrice des modes de défaillance

| Panne | Comportement en v1 | Où ça se voit |
|---|---|---|
| Image manquante | `mine start` échoue avec « lance `mine init` pour construire ou tirer l'image » | `mine doctor : image : manquante` |
| GPU injoignable dans le conteneur | Erreur Docker, avec un indice sur `nvidia-container-toolkit` | `mine doctor : docker.gpu_runtime : ✗` |
| Disque trop plein | `mine init` vérifie d'abord avec `shutil.disk_usage` ; échoue s'il reste moins de 200 Go | `mine doctor : disk_free : ✗` |
| Échec du chargement du modèle par vLLM (authentification HF, mémoire saturée, modèle introuvable) | Le conteneur sort ; `mine status` rapporte `FAILED` avec un `last_error` pris à la fin de `docker logs` | `mine status` + `mine logs` |
| pearl-gateway n'atteint pas pearld | `:8339/metrics` expose l'erreur ; l'adaptateur remplit `MiningStats.last_error` | `mine status : last_error` |
| Le conteneur s'écroule en cours de route | Le `--restart=unless-stopped` de Docker le relance ; `mine status` montre un bref `STARTING` → `RUNNING` | se répare seul, et c'est journalisé |
| Compagnon périmé (le conteneur est mort, le compagnon n'a pas été nettoyé) | `mine start` valide le `container_id` ; si Docker dit qu'il n'existe plus, il retire le compagnon et continue | un avertissement d'une ligne |
| Deux `mine start` en même temps | `flock` POSIX sur `~/.diapason/runtime/mining.lock` ; le second appel échoue clairement | message clair |
| `mine start` alors que ça tourne déjà | Idempotent : détection par le compagnon et l'inspection du conteneur, affichage du statut, sortie 0 | informatif |
| Dérive entre le portefeuille et la configuration | Le compagnon porte le portefeuille du moment du démarrage ; `mine status` recoupe et avertit en cas d'écart | avertissement, pas de redémarrage automatique |
| Quelqu'un écrit `submit_target = "pool:..."` en v1 | `start()` lève `NotImplementedError`, avec le lien vers le ticket de suivi | erreur claire |
| Montée de version du protocole Pearl (format de bloc ou noms de métriques changés) | L'adaptateur remplit de zéros avec un avertissement unique. `mine doctor` fait un contrôle au mieux : il lit l'étiquette Docker `image: diapason/pearl-miner:<ref>` et la compare au `PEARL_PINNED_REF` cuit dans la version d'OJ ; un écart remonte un avertissement. **OJ n'interroge pas le GitHub de Pearl à l'exécution.** | avertissement + le flux de relève de révision Pearl spécifié |
| Régression de qualité d'inférence due à NoisyGEMM | **Hors du périmètre de détection de la v1.** Risque documenté ; la v1.x pourra ajouter une détection de dérive automatique. | documentation seulement |

### 9.3 La stratégie de test

Contrainte dure : **la CI d'OJ n'a pas de H100, pas de GPU, pas d'image Pearl, pas de pearld.** Presque tout doit pouvoir se tester sans ça.

| Couche | Motif | Marqueur | Tourne en CI ? |
|---|---|---|---|
| La matrice de `MiningCapabilities.detect()` | Unitaire pur, paramétré sur des `HardwareInfo` synthétiques | sans marqueur | oui |
| L'analyse de `MiningConfig` (TOML → dataclass, y compris l'union étiquetée `submit_target`) | Unitaire, fixtures TOML de référence | sans marqueur | oui |
| La forme du lancement Docker | `unittest.mock.patch("docker.from_env")` ; on vérifie les kwargs de `containers.run(...)` | sans marqueur | oui |
| L'adaptateur des métriques de la passerelle | `tests/mining/fixtures/gateway_metrics_sample.txt`, on analyse et on vérifie `MiningStats` | sans marqueur | oui |
| Le cycle de vie du compagnon (écriture, lecture, nettoyage d'un périmé, prise du `flock`) | `tmp_path`, vrai système de fichiers, vrai `flock` | sans marqueur | oui |
| La fumée de la CLI | `CliRunner` de Click, `MiningProvider` simulé | sans marqueur | oui |
| Démarrage et arrêt du conteneur avec un vrai démon Docker | Vrai Docker, l'image Pearl remplacée par une petite image bouchon à base d'`alpine` qui ouvre les bons ports | nouveau marqueur `docker` | optionnel en CI |
| Le minage de bout en bout (vrai conteneur, vrai pearld, vraies parts) | Vraie H100 + testnet pearld + image Pearl épinglée | `live and nvidia and slow` | **non** — fumée manuelle avant publication |

**Un nouveau marqueur pytest.** `docker` est déclaré dans `pyproject.toml` à côté de `live`, `cloud`, `nvidia`, etc. La matrice CI peut, en option, lancer `-m "docker and not live"` sur un runner qui a Docker.

**Hygiène du conftest.** La fixture autouse de `tests/conftest.py` vide `MinerRegistry`. L'`ensure_registered()` de `mining/__init__.py` survit à ce vidage grâce à `MinerRegistry.contains(...)`.

**La fixture Prometheus capturée.** Une vraie sortie de métriques prise sur une passerelle Pearl en marche, commitée dans le dépôt. Elle fige les hypothèses sur les noms de métriques et sert de sentinelle si Pearl les renomme.

### 9.4 Ce que la v1 se garde délibérément de tester

- Le débit et l'économie du minage sur une vraie H100 (la CI de Pearl teste leurs noyaux)
- La dérive de qualité d'inférence due à NoisyGEMM (hors périmètre v1)
- Les chemins de soumission de parts à un pool (spécification v2)
- Les chemins Apple Silicon (Spec B)

## 10. La documentation à livrer (elle fait partie de cette spécification)

- `docs/user-guide/mining.md` — côté utilisateur : les prérequis, le déroulé d'`init`, un guide de lecture de la sortie du docteur, comment interpréter `mine status`, et la liste de ce qui n'est délibérément pas pris en charge (Mac, AMD, sm89, moteurs autres que vLLM)
- `docs/development/mining.md` — pour ceux qui contribuent : l'ABC `MiningProvider`, le motif du registre, comment ajouter un fournisseur (la Spec B est l'exemple travaillé de référence)
- Un paragraphe dans `CLAUDE.md`, sous « Architecture », qui envoie le Claude de demain vers `mining/` comme sous-système frère, avec sa propre discipline de dépendances optionnelles
- `REVIEW.md` gagne une puce sous la conformité au registre, qui nomme explicitement `MinerRegistry`

## 11. Les points ouverts, à trancher au moment de la mise en œuvre

1. **Les noms des métriques de la passerelle Pearl.** Vérifier les vraies étiquettes d'exposition en capturant `:8339/metrics` sur une passerelle Pearl en marche. Mettre à jour la correspondance de l'adaptateur et commiter la fixture.
2. **`PEARL_PINNED_REF`.** Choisir un commit ou une étiquette précise au démarrage de la mise en œuvre. Documenter le flux de relève de révision.
3. **Le modèle HF `pearl-ai/Llama-3.3-70B-Instruct-pearl`.** Confirmer qu'il existe et s'il est sous accès restreint ; documenter ce qu'il faut comme authentification HF.
4. **L'expression régulière de l'adresse Taproot Pearl.** Confirmer le préfixe et la longueur pour le contrôle de format d'adresse de `mine doctor`.
5. **Le comportement du port TCP du RPC mineur `:8337` de Pearl.** Confirmer que `MINER_RPC_TRANSPORT=tcp` fait ce qui est documenté et écoute bien sur `0.0.0.0`, pas seulement sur `127.0.0.1`, dans l'espace de noms réseau de l'hôte.
6. **L'étiquette Docker par défaut d'OJ.** Décider si l'on publie sur GHCR ou Docker Hub une fois qu'on aura une construction, ou si l'on laisse tout le monde sur le construis-depuis-la-révision. Probablement v1.x.
7. **Le relais vers la création de portefeuille (v1.x).** Décider si `mine init` délègue à l'`oyster` de Pearl pour ceux qui veulent être guidés, ou si l'on s'en tient au collage à la main.
8. **L'approche de migration du schéma de télémétrie.** Ajouter la colonne `mining_session_id` nullable à `telemetry/store.py` est un changement de schéma SQLite. Choisir entre (a) un `ALTER TABLE` au premier démarrage, protégé par une montée de `PRAGMA user_version`, (b) un `try/except` par requête sur la colonne, ou (c) une table compagnon jointe sur l'identifiant d'inférence. Vérifier d'abord quelle convention OJ applique déjà à l'évolution du schéma de `telemetry/` ; la pente par défaut est (a).

## 12. Renvois

- **[Spec B — activation d'Apple Silicon](2026-05-05-apple-silicon-pearl-mining-design.md)** — chantier distinct qui suit le travail, côté Pearl comme côté OJ, pour faire d'Apple Silicon un `MiningProvider` enregistré. La Spec A est agnostique du moteur par conception ; la Spec B s'y insère par `MinerRegistry` sans rien modifier de ce qui est écrit ici.
- **Le dépôt Pearl :** [`pearl-research-labs/pearl`](https://github.com/pearl-research-labs/pearl) — chemins référencés : `miner/vllm-miner/`, `miner/pearl-gemm/`, `miner/pearl-gateway/`, `miner/vllm-miner/Dockerfile`, `miner/vllm-miner/entrypoint.sh`.
- **L'article de Pearl :** [Proof-of-Useful-Work par multiplication matricielle (arXiv:2504.09971)](https://arxiv.org/abs/2504.09971).
- **Le guide de contribution d'OJ :** `docs/development/contributing.md` — le motif du registre, les conventions `_stubs.py` / `_discovery.py`, la discipline d'`ensure_registered()`, le motif d'import en douceur des dépendances optionnelles. Tout est suivi dans cette spécification.

## 13. Le plan de mise en œuvre

Le plan de mise en œuvre de la Spec A est un document à part, rédigé avec la compétence `superpowers:writing-plans` une fois cette conception approuvée par l'utilisateur. Il décomposera les sections 4 à 9 ci-dessus en étapes ordonnées et relisibles une à une, et dira lesquelles peuvent être menées en parallèle.
