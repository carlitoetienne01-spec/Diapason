---
title: Suis ce que tu économises
description: Un tableau de bord local qui te dit exactement ce que tu économises en faisant tourner le modèle chez toi
---

# 💸 Suis ce que tu économises — le tableau de bord local qui rend le « local d'abord » concret

<figure markdown>
  ![Le tableau de bord des économies de Diapason](../assets/showcase/cost-savings.png){ .showcase-screenshot loading=lazy }
  <figcaption>Le tableau de bord des économies, calculé sur la machine. La comparaison, c'est ce qu'un mois d'usage de Diapason aurait coûté dans le nuage — mesuré requête par requête, pas estimé. Rien n'est envoyé nulle part.</figcaption>
</figure>

Diapason enregistre chaque appel d'inférence que tu fais — les jetons, la latence, l'énergie consommée par la carte graphique — et calcule ce que le même appel *aurait coûté* chez OpenAI, Anthropic, Google ou Bedrock. Ces chiffres restent sur ta machine.

Mon mois en cours ressemble à peu près à ça :

| | |
|---|---|
| Coût de l'inférence locale | **`$0.00`** |
| Coût équivalent dans le nuage | **`$342.18`** (référence Claude Sonnet 4.6) |
| Énergie consommée | **`1.4 kWh`** (~12 ¢ d'électricité du réseau) |
| Prompts envoyés à un tiers | **`0`** |

Le chiffre en dollars, c'est l'accroche. La dernière ligne, c'est la vraie raison pour laquelle je fais tourner Diapason.

## Pourquoi c'est agréable

- **Tu vois ce que chaque question te coûte.** Pas une estimation, pas un « à peu près » — une mesure. Wattheures par jeton, FLOPs par jeton, latence. Dans Diapason, chaque primitive traite le coût de calcul comme une grandeur de premier rang, au même titre que la justesse.
- **Le « local d'abord » cesse d'être abstrait.** Voir un histogramme accumuler chaque semaine des `$X` qui ne sont *pas* sortis de chez toi, ça motive autrement qu'une promesse de « tes données sont privées » que rien ne te permet de vérifier.
- **La confidentialité cesse d'être un acte de foi.** Chaque prompt que j'envoie à Diapason se suit dans le code jusqu'à des chemins strictement locaux. Pas de « bascule vers le nuage » cachée derrière une option.

## Comment j'ai mis ça en place

En fait, tu n'as rien à mettre en place — la mesure est active par défaut et reste locale. Chaque `diapason ask`, chaque requête à `diapason serve` et chaque message routé par un canal est enregistré par le [système de télémétrie](../telemetry.md).

→ **[Vue d'ensemble de la télémétrie](../telemetry.md)** — ce qui est mesuré, où c'est stocké, et comment l'inspecter toi-même avec `diapason telemetry`.
