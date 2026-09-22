# Activer un modèle Pearl

Cette page suit le travail à faire pour qu'un nouveau modèle Hugging Face
devienne minable à travers le mineur vLLM de Pearl et Diapason.

Diapason sait pointer `vllm-pearl` vers un identifiant de modèle, mais un modèle
Hugging Face brut ne suffit pas. Le greffon vLLM de Pearl attend un modèle
quantifié compatible Pearl, dont les métadonnées marquent les couches de minage
pour le NoisyGEMM 7 bits et les couches hors minage pour le chemin GEMM
ordinaire de Pearl.

## Les modèles pris en charge

Diapason ne prend en charge que les modèles Pearl publiés par l'organisation
Hugging Face `pearl-ai`. Les artefacts privés de pré-production et les dépôts de
conversion propres à Diapason ne sont pas des modèles de minage pris en charge
côté utilisateur.

L'ensemble public actuellement pris en charge :

| Modèle brut | Modèle Pearl | État |
|---|---|---|
| `meta-llama/Llama-3.3-70B-Instruct` | `pearl-ai/Llama-3.3-70B-Instruct-pearl` | Défaut validé |
| `google/gemma-4-31B-it` | `pearl-ai/Gemma-4-31B-it-pearl` | Prévu, jusqu'à ce que la validation H100/H200 passe |
| `meta-llama/Llama-3.1-8B-Instruct` | `pearl-ai/Llama-3.1-8B-Instruct-pearl` | Prévu, jusqu'à ce que la validation H100/H200 passe |

## Ce que la validation a montré à ce jour

Le passage à blanc sur H100 a validé le modèle Pearl Llama par défaut de bout en
bout : `diapason mine start`, le `/v1/models` de vLLM, l'acheminement de
l'inférence par Diapason, le rafraîchissement du gabarit de la passerelle Pearl
et `diapason mine validate-model`.

`pearl-ai/Gemma-4-31B-it-pearl` et
`pearl-ai/Llama-3.1-8B-Instruct-pearl` figurent ici parce que ce sont des
artefacts publics de l'organisation Pearl. Ils restent `planned` dans Diapason
tant que nous n'avons pas d'artefacts de validation H100/H200 propres pour les
dépôts publiés.

## La liste de contrôle

1. Reproduire la recette du modèle Pearl Llama actuel.
   - Noter la configuration compressed-tensors.
   - Noter quelles couches linéaires sont des couches de minage 7 bits.
   - Noter quelles couches sont des couches 8 bits hors minage.
   - Noter les données de calibration et les réglages SmoothQuant, s'il y en a.

2. Convertir le modèle visé.
   - Partir d'un modèle que Pearl compte publier sous l'organisation `pearl-ai`.
   - Produire des poids quantifiés et des métadonnées compatibles Pearl.
   - Pour les artefacts Gemma4, inclure les métadonnées de processeur du modèle
     de base, exigées par le profileur multimodal Gemma4 de vLLM.
   - Publier sous l'identifiant `pearl-ai/*-pearl` prévu avant de l'activer dans
     Diapason.

   Diapason embarque un convertisseur local expérimental pour ce travail :

   ```bash
   python scripts/pearl/model_converter.py \
     meta-llama/Llama-3.1-8B-Instruct \
     /tmp/pearl-ai-Llama-3.1-8B-Instruct-pearl \
     --device cuda
   ```

   Le convertisseur copie les métadonnées Hugging Face, émet
   `quantization_config.quant_method = "pearl"`, écrit un index safetensors,
   convertit les projections q/k/v de l'attention et les projections down du MLP
   en couches int8 hors minage, et convertit le reste des poids linéaires du
   texte en couches int7 de minage. Traite sa sortie comme un artefact de
   pré-production tant que `diapason mine inspect-model` et
   `diapason mine validate-model` ne passent pas sur du matériel H100/H200.

   Un artefact local de pré-production peut être inspecté avant d'être téléversé :

   ```bash
   diapason mine inspect-model \
     --model /tmp/pearl-ai-Llama-3.1-8B-Instruct-pearl
   ```

   Pour faire passer un artefact local de pré-production dans le mineur Docker,
   garde `--model` sur le nom du modèle servi visé et pointe
   `--local-model-path` vers le répertoire du point de contrôle converti :

   ```bash
   diapason mine init \
     --provider vllm-pearl \
     --wallet-address <prl1...> \
     --model pearl-ai/Llama-3.1-8B-Instruct-pearl \
     --local-model-path /tmp/pearl-ai-Llama-3.1-8B-Instruct-pearl \
     --cuda-visible-devices 1 \
     --vllm-arg=--language-model-only \
     --vllm-arg=--skip-mm-profiling
   diapason mine start
   ```

3. Valider le chemin du greffon vLLM de Pearl.
   - Lancer `diapason mine inspect-model --model <pearl-model-id>
     --allow-planned` avant de démarrer le mineur.
   - Le modèle se charge dans le conteneur `vllm-miner` de Pearl.
   - vLLM enregistre le greffon de quantification de Pearl.
   - Les couches de minage utilisent le NoisyGEMM int7.
   - Les couches hors minage utilisent le GEMM Pearl ordinaire int8.
   - La génération de texte marche avec le minage activé comme désactivé.

4. Valider l'intégration à la chaîne.
   - `pearld` est joignable.
   - `pearl-gateway` reçoit du travail.
   - NoisyGEMM soumet des preuves candidates.
   - La passerelle rend des métriques.
   - `diapason mine status` sait lire ces métriques.

5. Promouvoir le modèle dans Diapason.
   - Passer son état de registre de `planned` à `validated`.
   - Fixer les valeurs mesurées de VRAM et de contexte par défaut.
   - Ajouter le modèle à la documentation utilisateur.
   - Joindre les journaux de validation à la PR.

## Le registre de Diapason

Les métadonnées de prise en charge des modèles vivent dans :

```text
src/diapason/mining/_models.py
```

`diapason mine models` affiche ce registre. Les modèles prévus sont visibles par
les utilisateurs, mais bloqués par la détection de capacités tant que l'artefact
du modèle Pearl et la validation H100/H200 n'existent pas.

## Les critères d'acceptation

Un modèle n'est `validated` que lorsque tout ceci passe sur du vrai matériel :

- `diapason mine inspect-model --model <pearl-model-id> --allow-planned`
- `diapason mine init --model <pearl-model-id>`
- `diapason mine start`
- `curl http://127.0.0.1:8000/v1/models`
- `diapason ask "Say hello in one sentence."`
- `diapason mine status`
- `diapason mine validate-model --model <pearl-model-id> --allow-planned --prompt
  "Say hello in one sentence." --output <artifact>.json`
- Les métriques de la passerelle Pearl montrent que le chemin de minage est actif.
- Aucune erreur de soumission de bloc ou de part n'apparaît dans les journaux de
  la passerelle ni du mineur.

Ne marque pas un modèle comme validé au seul motif que vLLM l'a chargé. Il doit
exercer le NoisyGEMM et le chemin de soumission de Pearl.

## Le suivi

Utilise le gabarit d'issue GitHub `Pearl Model Validation` pour chaque modèle
candidat. L'issue doit contenir la recette de quantification, les détails du
matériel, la sortie des commandes, des extraits de métriques, et la PR qui fait
passer l'état du modèle à `validated`. Joins-y l'artefact JSON produit par
`diapason mine validate-model --output`.
