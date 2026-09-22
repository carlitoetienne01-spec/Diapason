# Spec B — rendre le minage Pearl possible sur Apple Silicon

| | |
|---|---|
| **Date** | 2026-05-05 |
| **Statut** | Conception — investigation de la phase 0 terminée ; portée v1 réduite (voir §1.5) |
| **Responsable** | Équipe Diapason (compatible avec des agents parallèles) |
| **Spec compagne** | [Spec A — intégration du minage Pearl par vLLM (v1)](2026-05-05-vllm-pearl-mining-integration-design.md) |
| **Dépôts cités** | `Diapason`, `pearl-research-labs/pearl`, éventuellement `ml-explore/mlx` et `ggerganov/llama.cpp` en amont |

> **Si tu arrives ici à froid :** lis d'abord le §1 (« Briefing de démarrage à froid »), puis le **§1.5 (« Constats de la phase 0 »)**, qui simplifie beaucoup la portée de la v1. Le plan d'origine des phases 1 à 4 (noyau GPU), aux §5–§8, est conservé comme chemin v2/v3 ; la v1 sort en s'appuyant sur la référence PyTorch et le mineur tout-Rust de Pearl en amont.

## 1. Briefing de démarrage à froid

**Le problème en un paragraphe.** Diapason ajoute un sous-système `mining` (Spec A) qui permet de miner la chaîne de blocs Pearl (preuve de travail utile, PoUW) au moyen de l'inférence LLM locale. Le mineur de référence de Pearl ne fonctionne qu'en CUDA, et seulement sur NVIDIA Hopper (`sm_90a`, H100/H200) : la plupart des utilisateurs de Diapason, sur Apple Silicon, sont exclus au niveau du protocole. **Cette spec est le plan pour les débloquer.** Le travail d'intégration côté OJ est petit (une nouvelle implémentation de `MiningProvider` qui se branche sur le `MinerRegistry` existant de la Spec A) ; le gros morceau, c'est un portage Metal du noyau `NoisyGEMM` de Pearl et le greffon correspondant dans un moteur d'inférence natif Apple (MLX ou llama.cpp Metal). Le chemin de validation de Pearl repose sur des STARK plonky2 et il est **déjà neutre vis-à-vis du matériel** — les preuves sont au §3 — donc une implémentation Metal correcte produit des blocs que les validateurs Pearl acceptent, sans aucun changement de consensus.

**Trois choses à savoir avant de toucher à quoi que ce soit.**

1. Le validateur Pearl (`pearl/zk-pow/src/api/verify.rs::verify_block`) travaille sur une preuve STARK et ne mentionne aucun matériel. **Le protocole se moque de savoir quel GPU a produit le travail**, du moment que le calcul est juste et que la preuve se vérifie. « CUDA seulement » est un choix de performance, pas un choix de consensus.
2. Le noyau CUDA de Pearl (`pearl/miner/pearl-gemm/csrc/gemm/`) emploie des primitives propres à Hopper (TMA, WGMMA, grappes de blocs de fils, CUTLASS 3.x). Un portage Metal n'est **pas une traduction** : c'est une réimplémentation depuis zéro face à un autre modèle de programmation. Prévois l'effort en conséquence.
3. La frontière d'intégration côté OJ est l'ABC `MiningProvider` définie au §4.4 de la Spec A. **Ne modifie pas la Spec A.** Ajoute un nouveau fichier de fournisseur (`mining/mlx_pearl.py` ou `mining/llamacpp_pearl_metal.py`), implémente l'ABC, enregistre-le via `MinerRegistry`, publie un nouvel extra optionnel. Tout le reste de la Spec A — la forme du sidecar, le schéma de configuration, le contrat de l'adaptateur de télémétrie, les points d'accroche v2 pour les frais et les pools — s'applique inchangé.

## 1.5. Constats de la phase 0 — la portée se simplifie beaucoup (2026-05-05)

L'investigation de la phase 0 a produit quatre constats qui remodèlent cette spec. **Le plan d'origine des §5–§8 (noyau Metal NoisyGEMM + greffon MLX/llama.cpp sur mesure) est conservé comme v2/v3, mais il n'est plus nécessaire à la v1.**

### 1.5.1 Le validateur est neutre vis-à-vis du matériel (confirmé)

`zk-pow/src/api/verify.rs::verify_block` et `verify_plain_proof` sont du Rust pur plus plonky2 : pas de CUDA, pas de chemin GPU, aucune introspection du matériel. L'affirmation du §3.1 est **vérifiée par lecture directe du code** (chemins de fichiers au §11). Le protocole accepte les blocs de n'importe quelle implémentation qui produit le bon calcul.

### 1.5.2 Un mineur complet et neutre existe déjà en amont

`pearl/zk-pow/src/ffi/mine.rs::mine()` est une fonction de minage tout en Rust :

- elle engendre des matrices `i8` aléatoires `A` (m×k) et `B` (k×n) à valeurs dans `[-64, 64]` ;
- elle calcule le bruit dérivé de blake3 via `circuit/pearl_noise.rs::compute_noise_for_indices` ;
- elle effectue les produits scalaires bruités selon des motifs de tuiles (`PeriodicPattern.rows_pattern × cols_pattern`) ;
- elle hache la tuile jackpot et vérifie la cible de difficulté ;
- elle renvoie un `PlainProof` que `verify_plain_proof` accepte.

Elle est exposée à Python par `py-pearl-mining` (`pearl_mining.mine`). Dépendances : du Rust pur (`zk-pow`, `pearl-blake3`, `blake3`, `rayon`, `pyo3`, `tikv-jemallocator`). **Pas de CUDA, aucun code spécifique à une plateforme dans l'arbre de dépendances Cargo.**

### 1.5.3 Une référence PyTorch du NoisyGEMM *de production* existe aussi en amont

`pearl/miner/miner-base/src/miner_base/noisy_gemm.py::NoisyGemm` est une référence PyTorch complète du même NoisyGEMM que le noyau CUDA H100 accélère dans vllm-miner :

- les méthodes `noise_A`, `noise_B`, `gemm` et `noisy_gemm` reproduisent le calcul du noyau avec des appels `torch.matmul` ;
- le chemin de débruitage produit des résultats **exacts au bit près** face à un `torch.matmul(A.int32, B.int32)` ordinaire — vérifié par le test `assert torch.equal(result, expected)` à `miner/miner-base/tests/test_noisy_gemm.py:92`. Le budget de « tolérance fp16 » que je supposais dans le §5.2 d'origine est inutile pour le chemin protocolaire int7×int7→int32 ;
- dépendances : `torch==2.11.0`, `blake3`, `numpy`, `pearl-gateway`, `py-pearl-mining` — tout s'installe sur macOS arm64.

### 1.5.4 Confirmation empirique (2026-05-05, sur cette machine)

`py-pearl-mining` a été construit depuis les sources amont sur le M2 Max de l'auteur de la spec. La construction a produit `py_pearl_mining-0.1.0-cp312-abi3-macosx_11_0_arm64.whl` en 56 secondes. Cycle de minage de bout en bout :

```
running mine(m=256, n=128, k=1024, rank=32) on Apple Silicon CPU…
  mine() returned a proof in 0.078s
  verify_plain_proof: ok=True, msg='Mining solution verified successfully' (0.3 ms)
END-TO-END MINING ON APPLE SILICON SUCCEEDED
```

La difficulté de test est ici `nbits=0x1D2FFFFF` (le harnais de test de `py-pearl-mining/tests/test_python_api.py`), bien plus basse que celle du réseau principal : ces 78 ms sont donc **le temps par part à la difficulté de test**, pas le temps réellement attendu par part à la difficulté actuelle du réseau. Mais la *justesse* du chemin, elle, est prouvée.

### 1.5.5 La v1 recadrée — ce qu'on construit, ce qu'on repousse

| Couche | Plan d'origine (§5–§8) | Nouveau plan v1 |
|---|---|---|
| Oracle de référence (phase 0-B) | Le bâtir depuis zéro en PyTorch, le valider contre le CUDA H100 | **Existe déjà en amont** — `miner-base.noisy_gemm` + `pearl_mining.mine`. OJ livre une fine enveloppe, sans rien réimplémenter. |
| Greffon dans le moteur d'inférence (phase 2) | Greffon MLX ou llama.cpp Metal sur mesure faisant le NoisyGEMM | **Repoussé en v2.** La v1, c'est du **minage découplé** : le minage tourne dans un processus séparé via le mineur Rust amont ; l'inférence existante de l'utilisateur (Ollama, MLX, llama.cpp) n'est pas touchée. |
| Noyau Metal NoisyGEMM (phase 1) | Des mois d'ingénierie de noyau GPU | **Repoussé en v3**, comme optimisation de performance une fois la v1 sortie et la demande avérée. Le contenu du §6.1 d'origine est conservé comme plan v3. |
| Intégration du fournisseur OJ (phase 3) | Nouvelle implémentation de `MiningProvider` | **La v1 le livre** — voir §13. L'ABC `MiningProvider` de la Spec A est inchangée. |
| Mise en route et vérification (phase 4) | Matrice matérielle + testnet | **La v1 le livre** — voir §14. Même matrice matérielle, portée plus simple. |
| Coordination avec Pearl (phase 0-A) | Trancher la posture amont vs fork | Toujours nécessaire (voir §12) — mais l'enjeu baisse, puisque la v1 n'exige aucun code de notre part dans l'arbre de Pearl. |

### 1.5.6 Ce qu'on peut honnêtement attendre de la v1 en performance

Ce **n'est pas** du minage compétitif. Tout l'intérêt de vllm-miner, c'est d'amortir le travail de minage sur les produits matriciels de l'inférence LLM (le matmul que tu fais déjà pour inférer *est* le travail de minage). La v1 les découple : ton processeur mine, ton GPU infère. Le taux de hachage sera bas. **Mais ça marche aujourd'hui, et ça part avec un chemin de montée en puissance crédible.** À documenter sans détour dans `mine doctor` et dans le guide utilisateur.

Les chemins v2 (NoisyGEMM en PyTorch-MPS couplé à l'inférence MLX/llama.cpp) et v3 (noyau Metal natif) des §5–§8 restent la route vers un minage Apple Silicon compétitif. Ils ne bloquent explicitement pas la v1.

## 2. Pourquoi c'est une spec à part

La portée de la Spec A, c'est l'intégration v1 qui sort aujourd'hui sur la seule configuration qui marche (vLLM + sm90). Rendre Apple Silicon possible est un chantier séparé et parallélisable, pour quatre raisons :

- **La frontière de responsabilité n'est pas la même.** La Spec A, c'est de l'intégration Python d'une image Docker Pearl existante. La Spec B, c'est de l'ingénierie de noyau GPU avec une contribution amont possible chez Pearl. Il faut d'autres relecteurs, d'autres surfaces de CI (pas de H100 nécessaire, mais de l'Apple Silicon obligatoire) et une autre cadence de publication.
- **Le calendrier n'est pas le même.** La Spec A, ce sont des semaines. La Spec B, ce sont plausiblement des mois rien que pour le noyau.
- **L'étendue des dégâts n'est pas la même.** La Spec A ne fait courir aucun risque aux utilisateurs qui ne minent pas ; même celui qui mine et se trompe de configuration obtient une erreur claire. La Spec B porte un risque de justesse protocolaire : un défaut dans NoisyGEMM produit des blocs invalides que les validateurs rejettent.
- **Ergonomie pour des agents parallèles.** L'utilisateur a explicitement demandé que cette spec soit reprise par un agent séparé, en parallèle. L'autosuffisance est un objectif de conception.

## 3. Preuves : Apple Silicon est possible

### 3.1 Le validateur est neutre vis-à-vis du matériel

`pearl/zk-pow/src/api/verify.rs::verify_block` :

```rust
pub fn verify_block(public_params: &PublicProofParams, proof: &ZKProof, cache: &mut CircuitCache) -> Result<()> {
    let (params, pis) = prepare_verification(public_params, proof, None)?;
    PearlRecursion::compile_circuits(params, cache, false)?;
    verify_with_cache(params, cache, &pis, proof)
}
```

La vérification, c'est `PearlRecursion::verify(params, cache, pis, &proof.plonky2_proof)` — un contrôle STARK plonky2 récursif. Aucun chemin GPU, aucune dépendance CUDA. Les nœuds validateurs tournent en Rust pur.

Le travail de minage se compose de trois choses, qui sont toutes des spécifications mathématiques — pas des spécifications d'implémentation :

1. un résultat de NoisyGEMM dont le motif de bruit dérive du blake3 d'une clé propre au bloc ;
2. une empreinte blake3 d'engagement sur le matmul bruité, qui atteint une cible de difficulté ;
3. une preuve STARK plonky2 qui relie le résultat à l'engagement.

Toute implémentation qui produit les mêmes sorties convient au réseau. **C'est l'intention même de la preuve de travail utile** : le travail doit être rejouable et vérifiable, mais pas lié à un matériel.

### 3.2 L'équipe Pearl anticipe explicitement des greffons non-CUDA

Extrait de `pearl/miner/README.md` :

> "Currently only mining via vLLM is supported, in the future we hope to supply plugins for other LLM inference libraries, like SGLang, TensorRT-LLM, Ollama, ..."

Apple n'est pas dans leur liste, mais la formulation — « fournir des greffons pour d'autres bibliothèques d'inférence LLM » — implique que la frontière se situe au moteur d'inférence, pas au protocole de consensus. Cela confirme la lecture architecturale.

### 3.3 Une implémentation de référence existe dans py-pearl-mining

`pearl/py-pearl-mining/` est une caisse PyO3 qui expose les primitives de minage Pearl en Python. **Lis-la avant de concevoir le portage Metal** : elle contient vraisemblablement les constantes protocolaires sous une forme neutre, utilisable comme oracle de référence pour les tests de la phase 0 (§5).

## 4. Périmètre

### 4.1 Dans le périmètre

- **Phase 0** (§5) : vérification de l'acceptation protocolaire, coordination avec l'équipe Pearl, oracle de référence Python
- **Phase 1** (§6.1) : le noyau Metal NoisyGEMM — le gros de l'ingénierie
- **Phase 2** (§6.2) : le greffon dans le moteur d'inférence — MLX ou llama.cpp Metal
- **Phase 3** (§7) : l'intégration du fournisseur OJ — nouvelle implémentation de `MiningProvider`, nouvel extra optionnel, branchement au registre
- **Phase 4** (§8) : la matrice de vérification sur les variantes Apple Silicon et la mise en route sur le testnet Pearl
- Les livrables de documentation et le chemin de contribution amont

### 4.2 Hors périmètre

- Le support des pools et les 20 % de frais OJ (Spec A §8.5 ; cela vit dans une future spec v2 sur les pools)
- La garde, la signature ou le routage de fonds Pearl (anti-objectif de la Spec A ; identique ici)
- Le support d'AMD ROCm (spec séparée, de structure parallèle à celle-ci)
- Le support d'Intel Arc, des Mac Intel et des CUDA plus anciens (specs séparées)
- Toute modification de la Spec A. **La Spec B est purement additive.**
- Les changements de protocole Pearl (aucun n'est requis ; voir §3.1)

### 4.3 Anti-objectif explicite : la rentabilité

Cette spec ne promet pas que le minage sur Apple Silicon sera **rentable**. L'écart de performance avec un noyau H100 bien réglé est probablement grand (le §6.1.5 dit pourquoi). Ce que cette spec promet, en revanche : un chemin Apple Silicon correct et fonctionnel, actif dès le jour où le noyau sort, avec un `doctor` transparent qui dit honnêtement aux utilisateurs Mac à quoi ressemble leur taux de hachage. Savoir si cela vaut l'électricité, c'est leur décision.

## 5. Phase 0 — investigation, coordination, oracle de référence

La phase qui coûte le moins et évite le plus de retouches. Trois chantiers en parallèle.

### 5.1 Chantier P0-A : coordination côté Pearl

**Objectif :** obtenir par écrit des mainteneurs Pearl la confirmation de l'acceptation protocolaire ; s'entendre sur le fait qu'OJ contribue en amont ou livre de son côté.

**Étapes :**

1. Ouvrir une GitHub Discussion sur `pearl-research-labs/pearl` : « Apple Silicon / Metal NoisyGEMM enablement — coordination ». Y référencer l'URL de la Spec B.
2. Obtenir d'un mainteneur Pearl la confirmation explicite que :
   - le chemin de validation est bien neutre vis-à-vis du matériel (§3.1) ;
   - aucun portage Metal interne à Pearl n'est déjà en cours, qui entrerait en conflit ;
   - la LICENSE permet que du code de noyau écrit par OJ soit soit contribué en amont (préférable), soit distribué à côté d'OJ.
3. Discuter la question amont contre fork. Position par défaut, forte : **contribuer en amont dans une nouvelle caisse `pearl/miner/pearl-gemm-metal/`**, en parallèle de `pearl-gemm/`, pour que Pearl possède le noyau sur la durée et que nous profitions de leur CI et de leur relecture. Ne forker que si la contribution amont est bloquée.

**Critères de sortie :**

- [ ] Confirmation écrite de l'acceptation protocolaire
- [ ] Accord sur le modèle de contribution (amont / fork coordonné / indépendant)
- [ ] Aucun risque de travail en double

### 5.2 Chantier P0-B : bâtir un oracle de référence

**Objectif :** une implémentation de NoisyGEMM en Python pur (ou en Rust pur) qui produise des sorties exactes au bit près — ou bornées par la tolérance fp16 — face à la référence CUDA de Pearl. **Elle sert d'oracle de test pour la phase 1** : sans elle, impossible de vérifier la justesse du noyau Metal contre une base portable.

**Étapes :**

1. Lire `pearl/miner/pearl-gemm/csrc/gemm/` de bout en bout. Recenser les constantes protocolaires de `pearl_gemm_constants.hpp` :
   - `kAxEBLScaleFactor = 1 << 14`
   - `kEARxBpEBScaleFactor = 1 << 12`
   - `kIntToFp16ScaleFactor = 1 << 12`
   - `kEBRScaleFactorDenoise`, `kEALScaleFactorDenoise`
2. Lire `pearl/py-pearl-mining/` pour voir ce qui est déjà exposé en Python. Si une implémentation de référence y vit déjà, **s'en servir** ; ne pas la dupliquer.
3. S'il reste des trous, les combler en PyTorch (CPU). Refléter la structure des noyaux CUDA :
   - `noise_generation.cu` → `noise_generation.py` — dériver `EAL`, `EAR`, `EBL`, `EBR` du blake3-de-la-clé et de la graine
   - `pearl_gemm` (matmul + bruit) → `pearl_gemm.py` — calculer `Y_noisy = (A + EAL·EAR) × (B + EBL·EBR)` avec la mise à l'échelle documentée
   - `inner_hash_kernel.cu` → `inner_hash.py` — l'engagement blake3 sur le matmul bruité
   - `denoise_converter.cu` → `denoise.py` — retrouver `Y_clean = A·B` à partir de `Y_noisy` et des composantes de bruit
   - `pow_utils.hpp` → `pow_check.py` — le contrôle de la cible de difficulté
4. Contre-vérifier : passer un corpus de plus de 100 entrées dans la référence CUDA de Pearl (sur une machine de développement H100 ; voir §5.4) et dans la référence Python. Vérifier que les sorties concordent dans la tolérance documentée — très probablement **exactes au bit près pour les chemins entiers, à la tolérance fp16 près pour le résultat débruité**.

**Critères de sortie :**

- [ ] `tools/pearl-reference-oracle/` (dans le dépôt OJ, ou dans un dépôt séparé) se construit et ses tests passent
- [ ] Parité confirmée avec le CUDA Pearl sur ≥ 100 jeux d'entrées
- [ ] Table des constantes documentée dans cette spec (remplacer la liste ci-dessus par les valeurs vérifiées)

### 5.3 Chantier P0-C : viabilité côté Apple

**Objectif :** trancher entre MLX et llama.cpp Metal comme hôte d'intégration, avant de concevoir le noyau.

**Critères de décision :**

| Facteur | MLX (`ml-explore/mlx`, `mlx-lm`) | llama.cpp Metal (`ggerganov/llama.cpp`) |
|---|---|---|
| Points d'accroche pour remplacer une opération | Moins mûrs ; exigerait probablement de rapiécer `mlx.nn.Linear` à chaud, ou une PR amont ajoutant des points d'accroche | Plus mûrs ; l'arbre d'opérations `ggml` est ouvert et le moteur Metal a des points d'extension nets (`ggml-metal.metal`) |
| Quantification native Apple | Excellente (opérations natives 4 et 8 bits) | Bonne, mais moins native |
| Qualité d'inférence pour les utilisateurs OJ d'aujourd'hui | Haute — MLX-LM est la pile LLM de fait sur Mac | Haute — également très répandue |
| Complexité d'une contribution amont | Plus élevée (équipe plus petite, moins de culture du greffon) | Plus faible (grande communauté ouverte, parcours de contribution clair) |
| Alignement avec la carte des moteurs d'OJ | `engine/` d'OJ n'a pas de moteur MLX aujourd'hui ; il faudrait écrire les deux | OJ a déjà llama.cpp via `engine/openai_compat_engines.py` |

**Recommandation : llama.cpp Metal d'abord**, MLX en suivant de près. Le raisonnement : l'arbre d'opérations de ggml donne un chemin d'extension plus propre pour une opération NoisyGEMM sur mesure ; OJ a déjà le câblage du moteur llama.cpp ; et le parcours de contribution amont est plus praticable. MLX convient mieux à long terme aux utilisateurs tout-Apple, mais c'est aujourd'hui une cible d'intégration plus dure.

**Étapes :**

1. Essai rapide : implémenter une « opération sur mesure » qui ne fait rien, en passe-plat, dans llama.cpp Metal. Un à deux jours de travail pour confirmer que le mécanisme d'intégration est réel et que la chaîne de construction coopère.
2. Essai rapide : la même chose dans MLX. Comparer l'effort.
3. Choisir. Documenter la décision dans cette spec.

**Critères de sortie :**

- [ ] Décision prise et documentée au §6.2
- [ ] Point d'accroche trivial prouvé sur le moteur retenu

### 5.4 Matériel nécessaire à la phase 0

- Une machine H100/H200 (la location dans le nuage convient — Lambda, RunPod, Crusoe). Elle sert à faire tourner la référence CUDA de Pearl pour capturer les vecteurs de test de parité, et à faire tourner le mineur Docker Pearl de bout en bout comme base de comparaison connue.
- Des machines de développement Apple Silicon : M2 Max au minimum, M3/M4 Pro et au-delà de préférence. Un M-Ultra est idéal pour les expériences de performance.
- Coût nuage estimé pour la phase 0 : moins de 200 $.

## 6. Phases 1 et 2 — le noyau et le greffon

### 6.1 Phase 1 — le noyau Metal NoisyGEMM

**Objectif :** une implémentation de NoisyGEMM en nuanceur de calcul Metal, qui produise des sorties correspondant à l'oracle de référence de la phase 0 et qui soit assez performante pour faire du minage sur Mac une vraie fonctionnalité, même à faible rendement.

#### 6.1.1 Surface d'implémentation

Deux cibles viables, par ordre de préférence :

**A. Des noyaux de calcul en Metal Shading Language (MSL) directement.** Contrôle maximal, plafond de performance maximal, effort maximal. La référence CUDA est très finement réglée (TMA, WGMMA, pipelines multi-étages) ; un portage MSL direct peut s'appuyer sur les primitives de matmul d'Apple là où elles existent (les opérations `simdgroup_matrix` sur M3 et au-delà).

**B. Metal Performance Shaders Graph (MPSGraph).** Plus haut niveau que le MSL brut ; utilise les noyaux de matmul réglés par Apple en dessous ; contrôle limité sur l'empreinte d'engagement faite dans le noyau. Chemin probable : le matmul par MPSGraph, la génération de bruit et l'empreinte d'engagement dans des noyaux séparés, en acceptant la perte de performance due à une fusion moindre.

**Recommandation :** commencer par B pour la justesse et la vitesse de livraison ; profiler ; déplacer les chemins chauds vers A seulement si l'économie le justifie. Les primitives de matmul d'Apple sont assez rapides pour que l'écart avec une implémentation fusionnée reste peut-être acceptable.

#### 6.1.2 Structure de l'algorithme

D'après la référence CUDA de Pearl, voici le travail accompli de bout en bout pour une tentative de minage :

1. **Quantifier les entrées.** `A: fp16 → int8 + scale_A`, `B: fp16 → int8 + scale_B`. Respecter la sémantique de `quantize_kernel.cu` de Pearl (échelles par ligne ou par canal — à vérifier avec l'oracle de la phase 0).
2. **Engendrer les tenseurs de bruit.** À partir de `key_A` et `key_B` (graines blake3 propres au bloc), produire `EAL` (m, R), `EAR` (k, R), `EBL` (k, R) et `EBR` (n, R) en int8. Facteurs d'échelle selon `pearl_gemm_constants.hpp`.
3. **Matmul bruité.** Calculer `Y_noisy = (A + EAL · EAR_T) × (B + EBL · EBR_T)`. La sortie est en int32, puis convertie en fp16.
4. **Empreinte d'engagement interne.** blake3 sur `Y_noisy` (ou sur une tuile de lignes) pour produire le candidat à la cible de preuve de travail. C'est le chemin le plus chaud : la boucle bruit + engagement tourne à chaque part.
5. **Contrôle de preuve de travail.** Comparer le condensé de l'engagement à la cible de difficulté (sémantique de `make_pow_target_tensor`, depuis l'interface Python de Pearl).
6. **En cas de touche : débruiter.** Calculer `Y_clean = Y_noisy - (contributions de bruit)` pour le réinjecter dans vLLM/MLX comme véritable résultat du matmul. L'inférence n'a pas le droit d'être fausse.
7. **Après la touche : engendrer la preuve STARK.** Quand une part atteint la cible de difficulté du réseau, le mineur engendre une preuve STARK plonky2 qui lie le matmul bruité et l'engagement au bloc. Cette étape de preuve est **séparée du noyau Metal** : elle tourne en Rust pur via les chemins `zk-pow/` et `py-pearl-mining` existants de Pearl, et devrait marcher sur toutes les plateformes sans changement. Coût : de quelques secondes à quelques minutes de processeur par bloc. Confirmer que la construction multiplateforme tient en phase 0-C et au §7.5.

#### 6.1.3 Disposition de la caisse et du paquet

Préférence forte : **une contribution en amont chez Pearl**, sous `pearl/miner/pearl-gemm-metal/`, en parallèle de `pearl-gemm/` :

```
pearl/miner/pearl-gemm-metal/
    Cargo.toml          (ou pyproject.toml + setup.py — suivre les conventions de Pearl)
    metal/              (les fichiers source MSL .metal)
    src/
        lib.rs          (ou src/pearl_gemm_metal/__init__.py)
    tests/
```

Si la contribution amont est bloquée (issue de la phase 0), forker avec attribution dans `Diapason/vendor/pearl-gemm-metal/` et documenter dans cette spec la politique de divergence.

#### 6.1.4 Tests

- **Tests de parité.** Chaque noyau (génération du bruit, matmul, empreinte interne, débruitage, contrôle de preuve de travail) est testé indépendamment contre l'oracle de référence de la phase 0. Exact au bit près pour les chemins entiers ; borné par la tolérance fp16 pour les chemins flottants (tolérance précise : à déterminer par la mesure de la phase 0).
- **Justesse de bout en bout.** Une tentative de minage complète produit une preuve candidate que le prouveur Rust de référence (`zk-pow/`) accepte.
- **Fuzzing matériel.** Faire tourner sur M1 Pro, M2 Max, M3 Max, M4 Max et sur les variantes M-Ultra. Attraper tout comportement matériel silencieusement faux (la variabilité des fonctionnalités Metal d'une génération à l'autre est réelle).

#### 6.1.5 Performance attendue

Base honnête : **compte sur 0,05 à 0,2 fois le taux de parts d'un H100** sur un M-Ultra haut de gamme, et proportionnellement moins sur les puces plus petites. Raisons :

- le H100 a des cœurs tensoriels FP8/FP16 dédiés, avec un débit WGMMA qu'Apple Silicon n'égale pas ;
- le noyau CUDA de Pearl est fortement fusionné (matmul, bruit et engagement dans un seul noyau, par pipeline TMA) ; une version Metal sera vraisemblablement moins fusionnée ;
- les besoins en bande passante d'un modèle de 70 milliards de paramètres mettent la mémoire unifiée à l'épreuve.

Ce n'est pas grave. Le minage sur Mac est une fonctionnalité pour les propriétaires d'Apple Silicon qui veulent participer, pas un produit de rendement compétitif. À documenter sans détour dans `mine doctor` et dans le guide utilisateur.

#### 6.1.6 Critères de sortie de la phase 1

- [ ] Les tests de parité passent sur M2 Max et M4 Max
- [ ] Une tentative de minage de bout en bout produit une preuve valide, acceptée par `zk-pow::verify_block`
- [ ] Les performances sont caractérisées et publiées (matrice des puces M)
- [ ] Le code est fusionné en amont OU forké avec une politique, selon l'issue de la phase 0

### 6.2 Phase 2 — le greffon dans le moteur d'inférence

**Objectif :** un greffon llama.cpp Metal (ou MLX, selon la phase 0-C) qui échange l'opération linéaire quantifiée standard contre le NoisyGEMM de la phase 1 pendant l'inférence, de sorte qu'un Mac équipé de ce greffon produise à la fois des sorties LLM correctes et des parts de minage valides.

#### 6.2.1 Chemin : llama.cpp Metal (en supposant que la phase 0-C l'ait retenu)

- Ajouter une opération `ggml` sur mesure, `GGML_OP_PEARL_NOISY_GEMM`, avec une implémentation de moteur Metal qui appelle les noyaux de la phase 1.
- Point d'entrée du greffon : une petite bibliothèque qui, une fois chargée, remplace l'opération linéaire par défaut dans le graphe du modèle au chargement.
- Artefact construit : `libpearl_metal_plugin.dylib` (ou une bibliothèque statique).

#### 6.2.2 Chemin : MLX (variante)

- Définir `mlx.NoisyLinear` comme sous-classe de `mlx.nn.Linear`, qui appelle les noyaux de la phase 1 via une liaison d'opération Metal sur mesure.
- Fournir une cale de chargement de modèle : `from diapason.mining import patch_mlx_for_pearl; patch_mlx_for_pearl()`, qui rapièce à chaud les instances de `mlx.nn.Linear` au chargement. Moins élégant ; ça marche.

#### 6.2.3 Tests de non-régression sur la qualité d'inférence

Le greffon est critique pour la justesse : un modèle bruité qui ne se débruite pas complètement produit des réponses dégradées. À tester :

- Charger un petit modèle de référence (par exemple un modèle de 1 à 3 milliards de paramètres validé par Pearl s'il en existe un pour les tests, sinon le plus petit modèle que le protocole accepte).
- Passer un jeu de requêtes fixe dans le chemin bruité-puis-débruité et dans le chemin standard.
- Vérifier que les sorties sont exactes au bit près, ou dans la tolérance fp16.
- Faire tourner le cadre d'évaluation existant d'OJ (`src/diapason/evals/`) sur un petit banc d'essai (par exemple un sous-ensemble de MMLU enregistré comme jeu de données en mode minage Pearl). Vérifier qu'il n'y a pas de dégradation au-delà du budget de tolérance. Se rabattre sur `lm-eval-harness` est acceptable si la surface d'évaluation d'OJ pour Mac est incomplète à ce moment-là.

#### 6.2.4 Critères de sortie

- [ ] Le greffon se charge dans le moteur retenu
- [ ] L'inférence de bout en bout produit des sorties correctes (les tests de non-régression passent)
- [ ] Des parts de minage sont soumises à un testnet Pearl pendant l'inférence
- [ ] Au moins un bloc trouvé sur le testnet depuis un Mac

## 7. Phase 3 — intégration du fournisseur Diapason

Là où le travail côté OJ est petit. Il hérite, inchangés de la Spec A, de toute l'ABC `MiningProvider`, du registre, du sidecar, du schéma de configuration, de l'adaptateur de télémétrie et des points d'accroche v2.

### 7.1 Nouveaux fichiers

```
src/diapason/mining/
    llamacpp_pearl_metal.py    # OU mlx_pearl.py — selon le chemin retenu en phase 2
                                # @MinerRegistry.register("llamacpp-pearl-metal")
                                # implémente l'ABC MiningProvider de la Spec A §4.4
```

### 7.2 Nouvel extra optionnel

```toml
# pyproject.toml
mining-pearl-metal = [
    "pearl-metal-plugin>=0.1",   # le greffon de la phase 2, quel que soit son mode de publication
    # chemin MLX : ajouter "mlx>=0.X", "mlx-lm>=0.X"
    # chemin llama.cpp : ajouter "llama-cpp-python>=0.X" avec les extras Metal
]
```

### 7.3 Détection des capacités

```python
# src/diapason/mining/llamacpp_pearl_metal.py
class LlamaCppPearlMetalProvider(MiningProvider):
    provider_id = "llamacpp-pearl-metal"

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        if hw.platform != "darwin":
            return MiningCapabilities(False, reason="Apple Silicon requis (platform != darwin)")
        if hw.gpu is None or hw.gpu.vendor != "apple":
            return MiningCapabilities(False, reason="GPU Apple Silicon requis")
        if engine_id not in {"llamacpp", "llama-cpp"}:
            return MiningCapabilities(False, reason=f"le moteur '{engine_id}' n'a pas de greffon Pearl Metal ; utilise llamacpp")
        if not _pearl_metal_plugin_available():
            return MiningCapabilities(False, reason="installe avec `uv sync --extra mining-pearl-metal`")
        if not _model_has_pearl_variant(model):
            return MiningCapabilities(False, reason=f"le modèle '{model}' n'a pas de variante validée par Pearl")
        return MiningCapabilities(True, estimated_hashrate=_estimate_hashrate(hw))
```

Chaque branche est exactement le genre de message « pourquoi je ne peux pas miner » que le `mine doctor` de la Spec A affiche tel quel.

### 7.4 Cycle de vie

Contrairement au fournisseur vLLM de la Spec A, qui orchestre un conteneur Docker, le fournisseur Apple fait tourner **deux sous-processus coordonnés directement sur l'hôte** :

1. le serveur d'inférence (le serveur llama.cpp avec le greffon Pearl Metal chargé, ou le serveur MLX-LM selon le chemin retenu en phase 0-C) ;
2. `pearl-gateway` comme processus frère — le même que celui qui tourne dans le conteneur Docker de la Spec A, mais ici nativement sur le Mac.

Cycle de vie :

- `start()` : lancer (1) avec le greffon Pearl Metal préchargé (à la `DYLD_INSERT_LIBRARIES` ou par une option `--plugin`, selon le contrat d'invocation du moteur retenu), puis lancer (2) en le pointant dessus. Écrire le même sidecar que celui défini par la Spec A, avec `gateway_url` pointant sur le pearl-gateway natif. Garder les deux PID en interne.
- `stop()` : SIGTERM sur (2) d'abord, puis sur (1), avec des attentes bornées et un SIGKILL en dernier recours. Retirer le sidecar.
- `is_running()` et `stats()` : contrat identique au fournisseur vLLM ; `stats()` lit le `:8339/metrics` du pearl-gateway natif.

**Pas de Docker.** Docker sur Apple Silicon ne laisse pas passer Metal ; faire tourner Pearl dans un conteneur Docker sur Mac irait contre tout le propos. À documenter explicitement au §7 de cette spec ; ne tente pas un chemin Docker.

### 7.5 La passerelle Pearl sur Mac

Le processus `pearl-gateway` de Pearl n'est aujourd'hui documenté que comme partie du conteneur Docker. Sur Mac, il nous le faut natif. Deux options :

1. Construire `pearl-gateway` depuis les sources via `uv sync --package pearl-gateway` — le même paquet de l'espace de travail que l'image Docker utilise. Cela devrait marcher partout, puisque c'est du Python pur plus les liaisons py-pearl-mining. À vérifier.
2. Si (1) échoue sur Apple Silicon, travailler avec les mainteneurs Pearl (phase 0-A) pour le porter — peu de travail comparé au noyau.

**La phase 3 vérifie (1).** C'est un point de coordination de la phase 0-A.

### 7.6 Critères de sortie

- [ ] `LlamaCppPearlMetalProvider` est enregistré, la matrice de détection est correcte sur M1/M2/M3/M4
- [ ] `diapason mine init` va jusqu'au bout sur Apple Silicon
- [ ] `diapason mine start` lance le sous-processus et la passerelle Pearl sur Mac
- [ ] `diapason mine status` renvoie un `MiningStats` valide depuis une vraie session de minage sur Mac
- [ ] `diapason mine doctor` produit une sortie honnête et actionnable pour les utilisateurs Mac

## 8. Phase 4 — vérification et mise en route

### 8.1 Matrice matérielle

| Puce | Priorité de test | Résultat attendu |
|---|---|---|
| M1 / M1 Pro / M1 Max | basse — le GPU de première génération peut avoir des lacunes | fonctionne, mais lentement |
| M2 / M2 Pro / M2 Max | moyenne | fonctionne |
| M2 Ultra | moyenne | le meilleur taux de hachage de la classe M2 |
| M3 / M3 Pro / M3 Max | haute — première génération avec `simdgroup_matrix` | fonctionne, taux de parts significatif |
| M4 / M4 Pro / M4 Max | haute — le fleuron actuel | le meilleur taux de hachage hors M-Ultra |

Pour chaque puce de la matrice, faire tourner :

1. `diapason mine init` de bout en bout
2. `diapason mine start` pendant ≥ 4 h en continu
3. Capturer et publier : parts soumises, parts acceptées, distribution des temps de découverte de bloc, température du GPU, impact de la charge sur l'usage normal
4. Faire tourner un `lm-eval-harness` en parallèle sur le point d'accès de minage, pour vérifier que la qualité d'inférence n'est pas affectée

### 8.2 Mise en route sur le testnet Pearl

Avant toute recommandation sur le réseau principal :

- Miner sur le testnet Pearl pendant ≥ 7 jours d'affilée, depuis au moins deux variantes Apple Silicon
- Trouver au moins un bloc sur le testnet depuis chaque variante
- Vérifier que tous les blocs sont acceptés par `zk-pow::verify_block` sur un nœud validateur de référence
- Remonter les résultats aux mainteneurs Pearl ; conditionner toute annonce sur le réseau principal à leur aval

### 8.3 Livrables de documentation

- `docs/user-guide/mining-apple-silicon.md` — côté utilisateur : prérequis, parcours d'installation, guide de lecture du `doctor`, table des performances attendues, liens vers des calculateurs de taux de parts
- `docs/development/mining-providers.md` — un guide généralisé « comment ajouter un nouveau fournisseur », avec cette spec comme exemple travaillé de référence
- Une mise à jour de `docs/user-guide/mining.md` (Spec A) ajoutant Apple Silicon à la liste des plateformes prises en charge

### 8.4 Critères de sortie

- [ ] La matrice matérielle est couverte
- [ ] La mise en route sur le testnet est terminée
- [ ] La documentation est fusionnée
- [ ] L'aval des mainteneurs Pearl est obtenu
- [ ] Les notes de version d'OJ annoncent le minage Apple Silicon comme pris en charge

## 9. Risques

| ID | Risque | Probabilité | Impact | Atténuation |
|---|---|---|---|---|
| R1 | Le validateur Pearl rejette les blocs minés hors CUDA, malgré un code de validation neutre | faible (code relu) | catastrophique (toute la spec tombe) | Confirmation explicite en phase 0-A ; l'oracle de la phase 0-B réduit le risque de dérive du calcul |
| R2 | Pearl sort son propre portage Metal, en conflit avec celui d'OJ | moyenne (dépend de leur feuille de route) | élevé (retouches ou fork) | Coordination en phase 0-A ; contribuer en amont par défaut |
| R3 | Le NoisyGEMM Metal est si lent que le minage n'est même pas rentable pour un amateur | moyenne à élevée | moyen (la fonctionnalité sort mais reste inutilisée) | Le §4.3 en fait un anti-objectif nommé ; transparence dans `mine doctor` ; envisager de n'activer par défaut que sur M-Ultra en v1 de cette spec |
| R4 | Un défaut de justesse dans NoisyGEMM → des blocs invalides → de l'électricité gaspillée | faible si les tests du §6.1.4 sont rigoureux | élevé (atteinte à la confiance) | Tests de parité solides contre l'oracle ; mise en route sur testnet avant le réseau principal |
| R5 | Régression de la qualité d'inférence — le chemin débruité ne restitue pas totalement la fidélité du modèle | moyenne | élevé | Tests de non-régression du §6.2.3 ; le cadre d'évaluation conditionne la sortie |
| R6 | Le protocole Pearl change entre la phase 0 et la phase 4 (plusieurs mois) | moyenne | moyen | Figer la réf de la phase 0 comme dans la Spec A ; renégocier à chaque révision de Pearl |
| R7 | Apple change l'API Metal dans une mise à jour de macOS | faible à moyenne | moyen | N'utiliser que des fonctionnalités MSL stables ; figer la chaîne d'outils Xcode |
| R8 | La PR amont chez Pearl est refusée | faible (Pearl veut ça) | moyen (fork forcé) | La phase 0-A tranche amont contre fork dès le départ |
| R9 | `pearl-gateway` ne se construit pas sur Apple Silicon (§7.5) | moyenne (c'est du Python — devrait marcher, mais py-pearl-mining a des dépendances Rust) | faible (petit correctif) | La phase 0 vérifie les constructions ; coordination en phase 0-A sinon |

## 10. Questions ouvertes

La phase 0 a répondu à la plupart d'entre elles à partir du code amont (annotations ci-dessous). Ce qui reste ouvert demande soit l'avis d'un mainteneur Pearl, soit une mesure empirique dans les vraies conditions du réseau.

1. **(Ouverte — coordination)** Existe-t-il un « petit » modèle validé par Pearl pour les tests ? Le mineur de référence utilise un modèle de 70 milliards de paramètres — trop gros pour itérer vite. Une variante de 7 ou 13 milliards pour le développement accélérerait énormément le travail de greffon v2/v3. *Moins critique pour la v1, puisqu'elle est découplée de l'inférence et appelle `mine()` directement, sans modèle.*
2. **(Répondue — sans objet pour la v1)** ~~Le budget de tolérance fp16 documenté pour la sortie débruitée du matmul~~ — `miner-base/tests/test_noisy_gemm.py:92` fait `torch.equal(result, expected)` : le chemin int7×int7→int32 est **exact au bit près**, aucun budget de tolérance fp16 n'est nécessaire. (Cela pourrait reparaître dans le travail de noyau Metal v3, si des conversions int↔fp16 sont introduites pour la performance.)
3. **(Répondue — oui)** `py-pearl-mining` expose-t-il déjà assez de NoisyGEMM en Python pour que la phase 0-B se réduise à une fine enveloppe ? **Oui.** `pearl_mining.mine` exécute tout l'algorithme de minage en Rust pur. Et `miner-base.NoisyGemm` fournit en plus une référence PyTorch du NoisyGEMM de production. Le livrable « bâtir un oracle de référence » de la phase 0-B devient une *fine enveloppe côté OJ* qui appelle l'amont — voir §13 et `tools/pearl-reference-oracle/` (créé dans cette session).
4. **(Répondue — probablement oui ; vérifié empiriquement pour `py-pearl-mining`)** `pearl-gateway` est-il multiplateforme ? Son `pyproject.toml` exige Python ≥ 3.10 et dépend d'`aiohttp`, `bitcoin-utils`, `blake3`, `numpy`, `prometheus-client`, `pybase64`, `pydantic`, `pyyaml`, `torch==2.11.0` et `py-pearl-mining` — tout s'installe sur macOS arm64. L'installation empirique de l'espace de travail n'a pas été lancée dans cette session ; **action pour la mise en œuvre v1** : faire un `uv sync` de l'espace de travail sur macOS 15 et capturer la sortie de construction.
5. **(Ouverte — coordination)** Pearl conditionne-t-il des paramètres de difficulté ou de consensus à une introspection du matériel ? La relecture du code n'en a trouvé aucune. À confirmer dans la discussion de la phase 0-A.
6. **(Ouverte — mesure)** Le plancher de taux de hachage acceptable pour `diapason mine init` sur Apple Silicon. Le champ `MiningCapabilities.estimated_hashrate` de la Spec A §4.4 existe pour ça. La v1 le remplira depuis un étalonnage lancé pendant `mine init`. Le *plancher*, lui, est une décision de politique, pas une décision technique : à renvoyer à la recherche utilisateur et aux retours de la communauté une fois la v1 sortie.
7. **(Ouverte — coordination)** Contribution amont, CLA, LICENSE. Pearl est en ISC, OJ en Apache-2.0 ; les deux sont permissives et se combinent proprement. **Le CLA reste à trancher en phase 0-A**, mais pour la v1 la question ne se pose pas : OJ ne contribue aucun code dans l'arbre de Pearl, il consomme seulement leurs paquets Python publiés.
8. **(Répondue — oui)** CI Apple Silicon sur GitHub Actions : les runners `macos-14` et `macos-15` sont en arm64 et peuvent installer `py-pearl-mining` via la wheel dont la construction est vérifiée au §1.5.4. La CI d'OJ peut faire tourner les tests unitaires de minage. Miner *le vrai réseau* en CI reste hors périmètre.
9. **(Répondue — `"llamacpp"`)** L'`engine_id` du moteur llama.cpp d'OJ est `"llamacpp"` (un seul mot, sans tiret). Confirmé à `src/diapason/engine/openai_compat_engines.py:9` et `src/diapason/engine/_discovery.py:18`. Mettre à jour la détection de capacités du §7.3 pour utiliser cette clé. *(Pour la v1 du §13, cela ne compte que si on ajoute au moteur llamacpp existant un indice « informatif » sur le minage — la v1 n'exige aucun greffon dans le moteur.)*
10. **(Ouverte — mesure, mais dérisquée)** La latence de preuve STARK plonky2 sur un processeur Apple Silicon. Le §1 de la Spec A note déjà que la preuve prend de quelques secondes à quelques minutes de processeur par bloc (multiplateforme, tourne sans changement). Pour la v1, le taux de hachage est si bas que le temps de découverte d'un bloc est dominé par la recherche, pas par la preuve. La mesure empirique reste à faire pour la v2/v3.
11. **(Nouvelle — propre à la v1)** `bitcoin-utils>=0.7.0` (une dépendance de `pearl-gateway`) a-t-il des extensions C qui demanderaient des options de compilation propres à Apple ? Probablement du Python pur ; à vérifier pendant le chantier d'installation v1.
12. **(Nouvelle — propre à la v1)** `torch==2.11.0` (la version que `miner-base` et `pearl-gateway` figent) s'installera-t-il proprement sur macOS arm64 ? PyTorch a en général des wheels macOS arm64. À vérifier pendant l'installation v1.

## 11. Renvois

- **[Spec A](2026-05-05-vllm-pearl-mining-integration-design.md)** — l'intégration v1 que celle-ci prolonge. Lis le §4.4 (l'ABC `MiningProvider`), le §5.3 (la forme du sidecar), les §8.1–8.2 (le contrat de l'adaptateur de télémétrie) et le §8.5 (les points d'accroche v2 pour les frais et les pools). Tout s'applique inchangé.
- **Fil de coordination Pearl (brouillon P0-A) :** [`2026-05-05-pearl-coordination-discussion-draft.md`](2026-05-05-pearl-coordination-discussion-draft.md) — le contenu que l'utilisateur publie sur `pearl-research-labs/pearl` pour confirmer l'acceptation protocolaire et s'entendre sur le modèle de contribution.
- **Livrables de la phase 0 côté OJ (créés dans cette session) :**
  - `tools/pearl-reference-oracle/` — une fine enveloppe Python autour des liaisons Pearl amont, plus un test de fumée, exécutable sur Apple Silicon
- **Chemins du dépôt Pearl lus en phase 0 (par ordre de priorité) :**
  1. `pearl/zk-pow/src/api/verify.rs` — le validateur. Rust pur, pas de GPU. **Neutralité matérielle vérifiée.**
  2. `pearl/zk-pow/src/api/proof.rs` — `PublicProofParams`, `ZKProof`, `PrivateProofParams`, `IncompleteBlockHeader`, `MiningConfiguration`, `MMAType`. Définit ce sur quoi le protocole s'engage.
  3. `pearl/zk-pow/src/ffi/mine.rs` — **toute la fonction de minage, neutre vis-à-vis du matériel**. Rust pur. Déjà exposée à Python.
  4. `pearl/zk-pow/src/circuit/pearl_noise.rs` — la génération du bruit : `compute_noise_for_indices`, `generate_uniform_random_matrix`, `generate_permutation_matrix`. Neutre vis-à-vis du matériel.
  5. `pearl/py-pearl-mining/src/lib.rs` — le module PyO3. Ré-exporte `mine`, `verify_plain_proof`, `generate_proof`, `verify_proof`, `warmup_prove`. **Se construit sur macOS arm64, vérifié au §1.5.4.**
  6. `pearl/py-pearl-mining/Cargo.toml` — dépendances Rust pures : `pearl-blake3`, `zk-pow`, `blake3`, `rayon`, `pyo3`, `lazy_static`, `tikv-jemallocator`. Pas de CUDA dans l'arbre.
  7. `pearl/py-pearl-mining/tests/test_python_api.py` — le test canonique de bout en bout. À prendre comme modèle pour le test de fumée d'OJ.
  8. `pearl/miner/miner-base/src/miner_base/noisy_gemm.py` — la référence PyTorch du NoisyGEMM de production. L'« oracle de référence » que le §5.2 voulait construire est ici.
  9. `pearl/miner/miner-base/src/miner_base/noise_generation.py` — la génération de bruit en PyTorch, correspondant à `pearl_noise.rs`.
  10. `pearl/miner/miner-base/src/miner_base/inner_hash.py` — l'empreinte interne en PyTorch, avec réduction par XOR.
  11. `pearl/miner/miner-base/tests/test_noisy_gemm.py` — le débruitage exact au bit près, vérifié à la ligne 92.
  12. `pearl/miner/miner-base/pyproject.toml` — dépendances (`torch==2.11.0`, `blake3`, `numpy`, `pearl-gateway`, `py-pearl-mining`) ; **aucun marqueur de plateforme** → s'installe sur Apple Silicon.
  13. `pearl/miner/pearl-gateway/pyproject.toml` — dépendances (du Python pur, plus py-pearl-mining et torch) ; **aucun marqueur de plateforme**.
  14. `pearl/miner/vllm-miner/src/vllm_miner/register.py` — l'enregistrement du greffon vLLM par le point d'entrée `vllm.general_plugins`. Le motif que la phase 2 (plan v2) reprendrait.
  15. `pearl/miner/pearl-gemm/csrc/gemm/pearl_gemm_constants.hpp` — les facteurs d'échelle du protocole. Valeurs vérifiées :
      - `kAxEBLScaleFactor = 1<<14 = 16384`
      - `kEARxBpEBScaleFactor = 1<<12 = 4096`
      - `kIntToFp16ScaleFactor = 1<<12 = 4096`
      - `kEBRScaleFactorDenoise = -4` (= -kAxEBLScaleFactor / kIntToFp16ScaleFactor)
      - `kEALScaleFactorDenoise = -1` (= -kEARxBpEBScaleFactor / kIntToFp16ScaleFactor)
  16. `pearl/miner/pearl-gemm/setup.py:88` — `COMPUTE_CAPABILITY = "arch=compute_90a,code=sm_90a"`. Confirme que le noyau CUDA est réservé à Hopper.
  17. `pearl/Taskfile.yml` — la tâche `build:miner` est restreinte à `platforms: [linux, windows]`. **Le chemin d'installation Python du mineur que Pearl livre aujourd'hui est donc réservé à Linux et Windows** ; le chemin v1 d'OJ utilise les composants qui, eux, s'installent sur macOS, et contourne ainsi cette restriction.
- **Article Pearl :** [Proof-of-Useful-Work via matrix multiplication (arXiv:2504.09971)](https://arxiv.org/abs/2504.09971) — à lire pour la formalisation mathématique. Moins critique maintenant que la référence PyTorch existe en amont.
- **Références Apple (toujours pertinentes pour la v2/v3) :**
  - [Metal Shading Language Specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf)
  - [Documentation MPS / MPSGraph](https://developer.apple.com/documentation/metalperformanceshadersgraph)
  - [MLX](https://github.com/ml-explore/mlx) — l'hôte de greffon v2 alternatif
  - [Documentation du moteur MPS de PyTorch](https://pytorch.org/docs/stable/notes/mps.html) — utile pour la v2 (minage découplé accéléré par MPS)

## 12. Plan de mise en œuvre

Deux plans de mise en œuvre vivent désormais à côté de cette spec :

- **Plan v1 (minage découplé sur processeur, via le Pearl amont) :** écrit avec `superpowers:writing-plans` après cette mise à jour de la phase 0. Ticket de suivi : [`2026-05-05-apple-silicon-pearl-mining-plan-v1.md`](2026-05-05-apple-silicon-pearl-mining-plan-v1.md).
- **Plan v2 (minage couplé, en PyTorch-MPS ou via MLX/llama.cpp) :** à définir. Il s'écrira quand la v1 sera sortie et que nous aurons des données empiriques de taux de hachage justifiant l'investissement suivant.
- **Plan v3 (noyau Metal NoisyGEMM natif) :** à définir. Il ne s'écrira que si les mesures de la v2 montrent que le travail de noyau supplémentaire est économiquement justifié.

Le contenu d'origine des §5–§8, qui décrit les phases 0 à 4 de l'approche *noyau d'abord*, est conservé comme référence du plan v3. Ne le supprime pas : le jour où il faudra écrire le plan v3, ce contenu est le point de départ.

## 13. Apple Silicon v1 — le chemin minimal

Cette section définit la v1 qui sort en semaines plutôt qu'en mois. La v1, c'est du **minage découplé** : le flux d'inférence existant de l'utilisateur (Ollama, MLX-LM, llama.cpp, vLLM sur processeur, n'importe quoi) reste intact ; le minage tourne dans un processus séparé, via le mineur Pearl amont.

### 13.1 Architecture

```
                   Utilisateur Diapason (Apple Silicon)
                     ┌────────────────────────────────┐
                     │  diapason mine start           │
                     │      ↓                         │
                     │  CpuPearlProvider (cette spec) │
                     │      ↓ subprocess.Popen        │
                     │  ┌──────────────────────────┐  │
                     │  │ pearl-gateway  (Python)  │  │
                     │  │   ↑ JSON-RPC :8337       │  │
                     │  │ pearl-mine-loop (Python) │  │   ← utilise py-pearl-mining
                     │  │  enrobe pearl_mining.mine│  │     (Rust pur)
                     │  └──────────────────────────┘  │
                     │                                │
                     │  Inférence (intacte)           │
                     │  ┌──────────────────────────┐  │
                     │  │ Ollama / MLX / llamacpp  │  │
                     │  └──────────────────────────┘  │
                     └────────────────────────────────┘
                              ↓
                  pearld (à fournir, comme dans la Spec A)
```

La boucle de minage enrobe `pearl_mining.mine()` dans un processus qui :

1. interroge `pearl-gateway` pour obtenir l'`IncompleteBlockHeader` et la `MiningConfiguration` du moment ;
2. appelle `pearl_mining.mine(m, n, k, header, config)` pour trouver un `PlainProof` ;
3. renvoie la preuve à `pearl-gateway`, qui engendre la preuve ZK et la transmet à `pearld` ;
4. recommence.

C'est *exactement* le flot de contrôle que vllm-miner exécute — simplement sans coupler le matmul à l'inférence de vLLM. Le `pearl-gateway` existant de Pearl fait déjà l'orchestration dont nous avons besoin ; il ne manque qu'une petite boucle de minage qui utilise le `mine()` processeur au lieu du chemin CUDA.

### 13.2 Disposition des modules dans OJ

```
src/diapason/mining/
    cpu_pearl.py             # @MinerRegistry.register("cpu-pearl") — le fournisseur v1
    _pearl_subprocess.py     # PearlSubprocessLauncher — sous-processus passerelle + mineur
                             # réutilisé pour les futurs fournisseurs Apple-MPS / Metal
src/diapason/cli/
    # mine_cmd.py est inchangé ; cpu-pearl participe via l'ABC du fournisseur

tests/mining/test_cpu_pearl.py
tools/pearl-reference-oracle/
    README.md                # documentation : l'oracle existe en amont
    smoke_test.py            # test de fumée de bout en bout, mine + verify (créé dans cette session)
```

### 13.3 Extra optionnel

```toml
mining-pearl-cpu = [
    "py-pearl-mining>=0.1",     # la wheel construite au §1.5.4
    "miner-base>=0.1",          # la référence PyTorch (sert aux tests de parité)
    "pearl-gateway>=0.1",       # le service passerelle
]
```

Quand Pearl publiera ces paquets en wheels PyPI, l'installation sera `uv sync --extra mining-pearl-cpu`. En attendant, la spec du plan de mise en œuvre couvre le repli par construction locale (cloner Pearl à la réf figée, `maturin build` pour `py-pearl-mining`, `uv pip install` des paquets de l'espace de travail depuis des chemins locaux).

### 13.4 Détection des capacités

```python
# src/diapason/mining/cpu_pearl.py
class CpuPearlProvider(MiningProvider):
    provider_id = "cpu-pearl"

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        # cpu-pearl ne dépend d'aucun moteur — il ne se branche pas sur l'inférence
        if not _pearl_mining_available():
            return MiningCapabilities(False, reason="installe avec `uv sync --extra mining-pearl-cpu`")
        if not _pearl_gateway_available():
            return MiningCapabilities(False, reason="le paquet pearl-gateway n'est pas installé")
        if hw.platform not in {"darwin", "linux"}:
            return MiningCapabilities(False, reason=f"la plateforme '{hw.platform}' n'est pas encore prise en charge")
        # Facultatif : estimations de taux de hachage selon le matériel
        return MiningCapabilities(True, estimated_hashrate=_estimate_cpu_hashrate(hw))
```

Le paramètre `engine_id` est ignoré, parce que la v1 est découplée : le minage marche avec **n'importe quel** moteur d'OJ, y compris avec aucun moteur du tout. (Un futur fournisseur Apple couplé, lui, inspecterait `engine_id` pour exiger `"llamacpp"` ou `"mlx"`.)

### 13.5 Cycle de vie (depuis l'ABC `MiningProvider` de la Spec A)

- `start(config)` : lancer les sous-processus (1) `pearl-gateway` et (2) `pearl-mine-loop`. Attendre que la passerelle réponde sur `:8339/metrics`. Écrire le sidecar JSON standard (Spec A §5.3) avec `provider="cpu-pearl"`, l'URL de la passerelle et les PID des deux sous-processus.
- `stop()` : SIGTERM sur la boucle de minage, puis sur la passerelle. Attentes bornées, SIGKILL en dernier recours.
- `is_running()` : vérifier le sidecar et les deux PID.
- `stats()` : lire le `:8339/metrics` de `pearl-gateway` exactement comme le spécifie le §8.1 de la Spec A. **Même contrat d'adaptateur de métriques.** Aucun changement de code dans l'adaptateur de métriques de passerelle d'OJ.

### 13.6 Configuration

Hérite du schéma de configuration `[mining]` de la Spec A, inchangé. La v1 utilise :

```toml
[mining]
provider           = "cpu-pearl"     # NOUVEAU : c'était "vllm-pearl" dans la Spec A
wallet_address     = "prl1q..."
submit_target      = "solo"
fee_bps            = 0
fee_payout_address = ""

[mining.extra]
gateway_port           = 8337
metrics_port           = 8339
pearld_rpc_url         = "http://localhost:44107"
pearld_rpc_user        = "rpcuser"
pearld_rpc_password_env = "PEARLD_RPC_PASSWORD"
# propre à la v1 : la forme du matmul pour la boucle de recherche
m = 256
n = 128
k = 1024
rank = 32
```

La forme `m / n / k / rank` peut se régler selon les mesures de la phase 0-A (ou selon la puce). Les formes plus grandes explorent plus d'espace par appel, mais consomment plus de mémoire.

### 13.7 Ce que `doctor` affiche (Apple Silicon)

```
$ diapason mine doctor
Matériel
  Fabricant du GPU    apple                            ✓
  Puce Apple          M2 Max                           ✓
  Mémoire unifiée     96 Go                            ✓
Installation Pearl
  py-pearl-mining     0.1.0 (cp312-abi3-macos-arm64)   ✓
  miner-base          0.1.0                            ✓
  pearl-gateway       0.1.0                            ✓
Nœud Pearl
  RPC                 http://localhost:44107           ✓
  Authentification    ok                               ✓
  Hauteur de bloc     442107 (synchronisé)             ✓
Portefeuille
  Format d'adresse    prl1q...                         ✓
Capacité du fournisseur
  cpu-pearl           PRIS EN CHARGE  (env. 0,X part/h sur M2 Max)
Notes
  - C'est du minage découplé : ton inférence LLM habituelle n'est pas touchée
  - Le taux de hachage est très loin de celui d'un H100 ; voir docs/user-guide/mining-apple-silicon.md
  - Minage accéléré par Metal : prévu pour la v2, pas encore disponible
Session
  Sidecar             absent (à l'arrêt)
```

Chaque ligne correspond à une fonction de contrôle dans `mining/_discovery.py`. La ligne « env. X part/h » est remplie par un étalonnage unique pendant `mine init` : il fait tourner `pearl_mining.mine` dans une boucle de 30 secondes et extrapole.

### 13.8 Anti-objectifs de la v1

- **Aucun couplage à l'inférence.** L'inférence MLX-LM / Ollama / llama.cpp de l'utilisateur reste intacte. La v1 n'introduit pas de matmul sur mesure. Le récit « utiliser l'IA, c'est miner » est **explicitement repoussé en v2**.
- **Aucun noyau Metal.** Tout le calcul est dans le Rust, le PyTorch et le Python amont. Zéro ligne de MSL écrite.
- **Aucun changement dans l'arbre de Pearl.** Nous consommons leurs paquets publiés ; nous ne contribuons aucun code dans leur dépôt pour la v1. (La discussion de la phase 0-A a tout de même lieu — mais l'enjeu est moindre, puisqu'en v1 nous sommes consommateurs en aval, pas contributeurs.)
- **Aucune PR amont ne bloque la sortie de la v1.** La v1 sort contre la réf Pearl figée dans `mining/_constants.py` (Spec A §6), que nos questions de coordination aient trouvé réponse ou non.

### 13.9 Critères de sortie de la v1

- [ ] L'extra `mining-pearl-cpu` s'installe proprement sur macOS arm64 (M1, M2, M3, M4 — au minimum la puce que possède l'auteur de la spec)
- [ ] `diapason mine init` va jusqu'au bout sur macOS arm64
- [ ] `diapason mine start` lance les sous-processus passerelle et mineur ; le sidecar est valide ; `mine status` remonte des données vivantes
- [ ] `mine doctor` produit une sortie honnête et actionnable pour les utilisateurs Mac
- [ ] Au moins un bloc trouvé sur le testnet Pearl, depuis au moins une variante Apple Silicon
- [ ] La page utilisateur `docs/user-guide/mining-apple-silicon.md` sort, avec la mise en garde honnête sur le taux de hachage

### 13.10 Hors de la v1, vers la v2/v3

- **v2 (des mois) :** rerouter le calcul de `noisy_gemm` vers PyTorch-MPS pour accélérer sur le GPU Apple Silicon ; l'intégrer comme greffon dans MLX-LM ou `llama-cpp-python`, pour que les matmuls d'inférence produisent du travail de minage (et préservent le récit « utiliser l'IA, c'est miner »). Le plan d'origine des §5–§8 s'applique, en remplaçant le MSL brut par PyTorch MPS.
- **v3 (des mois — optionnel, seulement si la performance de la v2 ne suffit pas) :** un noyau NoisyGEMM natif en Metal Shading Language, contribué en amont chez Pearl. Le plan d'origine des §5–§8 s'applique tel quel.

## 14. État des livrables de la phase 0 (cette session, 2026-05-05)

Ce qui a réellement été produit, face au plan de phase 0 du §5 et au recadrage du §1.5.

| Chantier | Plan d'origine | État | Livrable |
|---|---|---|---|
| P0-A | Ouvrir une GitHub Discussion chez Pearl, obtenir la confirmation d'acceptation protocolaire | Brouillon écrit ; l'utilisateur le publie | `docs/design/2026-05-05-pearl-coordination-discussion-draft.md` |
| P0-B | Bâtir l'oracle de référence depuis zéro en PyTorch, le valider contre le CUDA H100 | **L'oracle de référence existe en amont.** Fine enveloppe côté OJ construite, et vérification empirique que `pearl_mining.mine` tourne sur Apple Silicon (78 ms par preuve à la difficulté de test) | `tools/pearl-reference-oracle/` |
| P0-C | Trancher entre MLX et llama.cpp Metal | **Repoussé en v2.** La v1 n'a besoin ni de l'un ni de l'autre. | — |
| Mise à jour de la spec | Consigner les constats | Fait | Ce document, §1.5, §10–§14 |
| Plan de mise en œuvre v1 | Plan écrit avec `superpowers:writing-plans` après la phase 0 | En attente | `2026-05-05-apple-silicon-pearl-mining-plan-v1.md` (prochain livrable) |
