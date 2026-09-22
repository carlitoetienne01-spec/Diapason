# Ajouter un fournisseur de minage

Le sous-système `diapason.mining` suit le même motif de registre que les
moteurs, les agents, les outils, la mémoire et les canaux. Un nouveau chemin de
minage doit être un module de fournisseur, pas un cas particulier dans la CLI
ou dans la couche moteur.

## Le contrat d'un fournisseur

Chaque fournisseur implémente `diapason.mining.MiningProvider` :

- `detect(hw, engine_id, model)` ne fait que détecter des capacités. Il ne doit
  ni lancer de sous-processus, ni toucher au réseau, ni modifier d'état.
- `start(config)` prend en charge la mise en route du fournisseur et écrit le
  sidecar de minage lorsqu'il change le routage de l'inférence.
- `stop()` démonte les processus ou les conteneurs qui appartiennent au
  fournisseur.
- `is_running()` répond à partir de l'état que le fournisseur possède.
- `stats()` rend un `MiningStats` bâti sur la surface de télémétrie la plus
  stable du fournisseur.

Enregistre les fournisseurs par `MinerRegistry` et expose un
`ensure_registered()` idempotent :

```python
from diapason.core.registry import MinerRegistry


def ensure_registered() -> None:
    if not MinerRegistry.contains("my-provider"):
        MinerRegistry.register_value("my-provider", MyProvider)
```

`tests/conftest.py` vide les registres entre les tests : les fixtures de test
et les points d'entrée de la CLI doivent donc appeler `ensure_registered()`
avant de compter sur un fournisseur.

## Les dépendances optionnelles

Les dépendances d'un fournisseur vivent dans des extras délimités :

- `mining-pearl-vllm` pour le fournisseur Docker NVIDIA/vLLM
- Le travail Apple à venir doit utiliser un extra distinct, par exemple
  `mining-pearl-metal` ou `mining-pearl-cpu`

Évite un extra générique `mining-pearl` tant qu'il n'existe pas un jeu de
dépendances communes dont chaque fournisseur a réellement besoin.

## Le contrat du sidecar

Le sidecar d'exécution vit dans `~/.diapason/runtime/mining.json`. Le passage
de relais au moteur est piloté par les données :

- Si le sidecar porte `vllm_endpoint`, la découverte des moteurs enregistre
  `vllm-pearl-mining`.
- Si un futur fournisseur mine à côté du moteur habituel de l'utilisateur, il
  doit omettre `vllm_endpoint` ; la découverte des moteurs l'ignorera.

Ne branche pas sur `provider == "vllm-pearl"` dans du code générique. Branche
sur la forme du sidecar ou sur la capacité du fournisseur.

## Le relais Apple Silicon

Le chantier Apple Silicon doit ajouter son propre module de fournisseur et
réutiliser :

- `MiningProvider`
- `MinerRegistry`
- `MiningConfig`
- `MiningStats`
- `Sidecar`
- le parcours des capacités de `diapason mine doctor`

Ce travail ne doit avoir à réécrire ni le fournisseur NVIDIA, ni le groupe de
commandes de la CLI, ni le collecteur de télémétrie, ni le relais du sidecar
vers le moteur.

## Le verrou de publication NVIDIA

Le fournisseur NVIDIA n'est pas tenu pour économiquement prouvé tant que le
runbook H100/H200 n'est pas passé sur du vrai matériel. Voir
[`mining-nvidia-validation.md`](./mining-nvidia-validation.md) pour les
commandes, les artefacts et les critères de réussite exigés.

## L'activation des modèles

Les nouveaux modèles de langue compatibles Pearl sont suivis à part du support
des fournisseurs. Voir
[`pearl-model-enablement.md`](./pearl-model-enablement.md) pour la liste de
contrôle de conversion et de validation.
