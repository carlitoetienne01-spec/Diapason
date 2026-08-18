# Succès — le client mobile de Diapason

Diapason et Succès sont **deux dépôts**, délibérément. Succès doit rester
présentable seul dans un portfolio, et les deux écosystèmes ne se mélangent
pas bien : Python/Rust d'un côté, Dart/Gradle/Xcode de l'autre.

Ce ne sont pas pour autant deux projets voisins : c'est un cerveau et un
corps. Ce document dit où passe la frontière et ce qui la garde.

```
Diapason (ce dépôt)                    Succès (~/Desktop/Porfolio/Succes)
├── src/diapason/succes/    8 602 l.   ├── lib/            23 028 l. Dart
│   ├── store, workspace              │   ├── services/mesh/
│   ├── continuity, finances          │   └── screens/
│   └── relay.py                      └── test/mesh/
├── tools/succes_*.py  (4 outils        canonical_vectors.json  ← engendré ici
│   vocaux : « ajoute une dépense »)
└── succes/routes.py   73 routes
```

## Les deux surfaces de contact

### 1. L'encodage canonique du maillage

Des octets **signés** : un écart d'un seul caractère et toutes les
signatures Ed25519 échouent, sans qu'aucun message ne l'explique. Le Dart
réimplémente `canonical_bytes` ; les vecteurs de test viennent de
l'implémentation Python réelle.

```bash
.venv/bin/python scripts/gen_canonical_vectors.py
```

Écrit dans `~/Desktop/Porfolio/Succes/test/mesh/canonical_vectors.json`, à
commiter **dans le dépôt Succès**.

### 2. Les 73 routes `/v1/succes`

Ce que l'application mobile appelle. L'instantané vit dans
`tests/contract/succes_api_surface.json`.

```bash
.venv/bin/python scripts/gen_succes_surface.py
```

## Ce qui garde la frontière

`tests/contract/test_succes_client_contract.py` échoue **du côté où le
changement est fait** — ici, dans Diapason — au lieu de laisser la rupture
se manifester au téléphone, loin du commit qui l'a causée.

| Le test échoue quand… | Ce qu'il faut faire |
|---|---|
| `canonical_bytes` a changé sans régénération | relancer `gen_canonical_vectors.py`, commiter côté Succès |
| une route `/v1/succes` disparaît ou est renommée | régénérer l'instantané **dans le même commit**, et prévoir la version mobile qui cessera de fonctionner |
| une route neuve n'est pas dans l'instantané | régénérer — ajouter est inoffensif, mais l'instantané doit rester un miroir exact |

Les tests de vecteurs se **sautent** proprement quand le dépôt Succès est
absent (machine de CI, clone de Diapason seul) : leur silence est alors
l'absence d'une vérification, pas un succès.

## Faire évoluer les deux ensemble

1. Changer Diapason, lancer `pytest tests/contract` — il dira ce qui casse.
2. Régénérer ce qu'il demande.
3. Commiter **ici** le changement plus l'instantané.
4. Commiter **là-bas** les vecteurs, et adapter le Dart.

L'ordre compte : le contrat est régénéré avant que le mobile ne soit
touché, jamais après.
