# Fil de coordination avec Pearl — brouillon

**Pour :** publication sur les GitHub Discussions de `pearl-research-labs/pearl` (catégorie : General / Q&A).
**Par :** l'équipe Diapason (Stanford Hazy Research) ; contact : [user fills in].
**Statut :** brouillon — à relire et à corriger avant publication.

---

## Titre proposé

> Prise en charge d'Apple Silicon pour le minage Pearl — coordination et confirmation

## Corps proposé

Bonjour l'équipe Pearl — ici [Diapason](https://github.com/carlitoetienne01-spec/Diapason), un cadre d'agents d'IA personnels, local d'abord, issu de Stanford Hazy Research. Nous travaillons sur un sous-système `mining` qui permet aux utilisateurs d'OJ de miner Pearl au travers du cadre d'agents. La première intégration est le chemin `vllm-miner` sur H100/H200, et elle va de soi. La seconde est Apple Silicon, où la situation est plus intéressante et où nous aimerions confirmer deux ou trois choses avant de livrer.

Nous avons une architecture v1 qui sort **aujourd'hui** en n'utilisant que vos paquets Python déjà publiés (`py-pearl-mining`, `miner-base`, `pearl-gateway`), sans une ligne de code nouvelle dans votre arbre, plus un chemin v2/v3 ambitieux qui, lui, suppose d'éventuelles contributions en amont. Trois demandes ci-dessous, plus un signalement.

### Ce que nous avons construit et vérifié en local (aucun changement de protocole ; rien que des chemins de code en amont)

Nous avons lu attentivement les sources de Pearl — en particulier :

- `zk-pow/src/api/verify.rs` — le validateur
- `zk-pow/src/ffi/mine.rs` — la fonction `mine()` tout en Rust
- `zk-pow/src/circuit/pearl_noise.rs` — la génération du bruit
- `py-pearl-mining/` — les liaisons PyO3 qui exposent ce qui précède à Python
- `miner/miner-base/src/miner_base/noisy_gemm.py` — la référence PyTorch NoisyGEMM

…puis nous avons construit `py-pearl-mining` depuis les sources sur un Apple Silicon M2 Max (macOS 26.4, Python 3.12, Rust 1.94). La construction a produit `py_pearl_mining-0.1.0-cp312-abi3-macosx_11_0_arm64.whl` en ~56 secondes. Nous l'avons installé, puis lancé le cycle `mine()` + `verify_plain_proof()` de `tests/test_python_api.py` :

```
running mine(m=256, n=128, k=1024, rank=32) on Apple Silicon CPU…
  mine() returned a proof in 0.078s
  verify_plain_proof: ok=True, msg='Mining solution verified successfully'
```

Notre plan v1 est donc celui-ci : livrer aux utilisateurs d'OJ sur Apple Silicon (et potentiellement sur d'autres plateformes sans CUDA) un mode de minage CPU qui enveloppe `pearl_mining.mine()` et votre `pearl-gateway` lancé comme sous-processus. **Nous ne modifions rien dans l'arbre de Pearl pour la v1.** Nous consommons seulement ce que vous avez déjà publié.

### Trois demandes

**1. Confirmation de l'acceptation par le protocole.**

À la lecture du chemin de validation, nous pensons que `verify_block` et `verify_plain_proof` acceptent n'importe quelle `PlainProof` produite par une implémentation correcte, quel que soit le matériel qui l'a produite. Le STARK plonky2 et le contrôle de difficulté ne font aucune référence au matériel.

**Pourriez-vous confirmer par écrit que les blocs minés par le chemin `mine()` tout en Rust (depuis une machine sans CUDA, comme Apple Silicon) seront acceptés par les validateurs Pearl sur le testnet et sur le mainnet ?** Nous n'attendons pas de surprise ici, mais c'est porteur pour notre spec et nous voulons consigner votre accord avant de livrer.

**2. Signalement : votre `Taskfile.yml` restreint `build:miner` à `[linux, windows]`.**

Cela se comprend parfaitement pour le mineur GPU (CUDA + vLLM, c'est Linux et rien d'autre). Mais les paquets `py-pearl-mining` et `miner-base` n'ont pas réellement besoin de cette restriction — ils s'installent très bien sur macOS. Nous contournons le verrou en installant les paquets un par un. Deux questions :

   - La restriction `[linux, windows]` est-elle porteuse d'une manière qui nous échappe (comptez-vous par exemple garder `py-pearl-mining` lié à CUDA sur le long terme) ?
   - Seriez-vous ouverts à une petite PR qui sépare `build:miner-cpu` (multiplateforme) de `build:miner-gpu` (Linux + CUDA) ? Cela aiderait les consommateurs en aval comme nous — et tout amateur qui veut expérimenter `pearl_mining.mine()` sur le matériel qu'il possède.

**3. Publication sur PyPI de `py-pearl-mining` / `miner-base` / `pearl-gateway`.**

Avez-vous une feuille de route pour publier ces paquets en wheels PyPI (`pip install py-pearl-mining`, etc.) ? Aujourd'hui, nous embarquerions un commit épinglé et un `maturin build` en local : cela marche, mais c'est fragile. Si une publication sur PyPI en 2026 est plausible, nous repousserions le chemin de construction locale ; si elle n'est pas à la feuille de route, nous prévoirons ce chemin pour le long terme.

### Ambitions (v2 / v3) — contexte seulement, aucune demande pour l'instant

Une fois la v1 livrée, nous aimerions explorer une accélération native Apple :

- **v2 :** se servir de PyTorch MPS pour accélérer `miner-base.NoisyGemm` sur le GPU d'Apple Silicon. Cela pourrait devenir un greffon dans `mlx-lm` ou `llama-cpp-python`, de sorte que les multiplications de matrices de l'*inférence* d'un utilisateur Mac fassent le travail de minage — le même cadrage « travail utile » que votre vllm-miner. Nous n'avons besoin de rien de la part de Pearl pour cela ; nous le construirions par-dessus votre référence PyTorch existante.
- **v3 (seulement si la v2 ne suffit pas) :** un portage natif de NoisyGEMM en Metal Shading Language, en parallèle de `pearl-gemm/`. Ce serait un vrai candidat à une contribution en amont (`pearl/miner/pearl-gemm-metal/`), et nous voudrions nous coordonner avec vous avant de commencer le travail sur le noyau, pour éviter de faire deux fois la même chose.

Si vous construisez déjà la prise en charge d'Apple Silicon en interne (ou si quelqu'un chez vous la prépare), dites-le-nous — nous préférons nous coordonner plutôt que dupliquer.

### Logistique

- Compatibilité des licences : Pearl est sous ISC, Diapason sous Apache-2.0. Nous ne voyons de conflit ni pour la consommation (v1) ni pour la contribution (v3), mais signalez-le si vous en voyez un.
- CLA : en exigez-vous un pour les contributions en amont ? Cela ne bloque pas la v1 — nous voulons simplement savoir pour la v3.
- Canal de coordination préféré : ce fil de Discussion, un Discord, un courriel ? Nous prendrons volontiers celui qui vous arrange.

Merci d'avoir construit tout cela — la preuve de travail utile par multiplication de matrices est vraiment intéressante, et l'idée d'amener au réseau du matériel supplémentaire (et plus lent !) nous enthousiasme.

— [user name], au nom de Diapason

---

## Notes à lire avant de publier

- Remplace `[user fills in]` par tes coordonnées et `[user name]` par ton nom.
- Les affirmations sur l'architecture et les performances s'appuient toutes sur du code et sur une vraie construction locale : tu peux les assumer.
- Le cadrage en « signalement » du `Taskfile.yml` est délibéré — on ne leur demande pas de le *changer*, on pointe le frottement au cas où ils le voudraient.
- Ne publie pas avant que la Spec A d'OJ soit au moins poussée sur une branche (c'est fait : PR #310) — cela donne à Pearl un moyen de voir l'intégration plus large que nous construisons.
- Quand leur réponse arrive, mets à jour la Spec B §10 (questions ouvertes 1, 5 et 7) et le §11 (renvois → URL du fil de coordination).

## Les réponses possibles de Pearl, à anticiper

- **Meilleur cas :** « Confirmé, ça a l'air très bien, nous n'avons pas de plan Apple Silicon, allez-y. » — on poursuit avec le §13.
- **Cas intermédiaire :** « Confirmé, mais un portage Metal est en cours chez nous. » — se coordonner, partager la Spec B §6.1, trancher entre l'amont et le fork. La v1 (CPU) n'est pas touchée.
- **Pire cas :** « Nous préférons que le minage sans CUDA en aval reste désactivé pour l'instant. » — peu probable, leur README de `pearl-gateway` annonçant explicitement des « greffons pour d'autres bibliothèques d'inférence LLM » ; mais si cela arrive, le problème devient bien plus dur et il faudra tout reconsidérer.
