# Diapason mobile — le client mobile de Diapason

Diapason et Diapason mobile (ex-« Succès ») sont **deux dépôts**,
délibérément : les deux écosystèmes ne se mélangent pas bien, Python/Rust
d'un côté, Dart/Gradle/Xcode de l'autre. Le chantier qui les rapproche, et
ce qu'on a trouvé en regardant, vit dans
[`development/diapason-mobile.md`](development/diapason-mobile.md).

Ce ne sont pas pour autant deux projets voisins : c'est un cerveau et un
corps. Ce document dit où passe la frontière et ce qui la garde.

```
Diapason (ce dépôt)                    Diapason mobile (~/Projets/diapason_mobile)
├── src/diapason/vie/      12 614 l.   ├── lib/            22 320 l. Dart
│   ├── store, workspace              │   ├── services/mesh/
│   ├── continuity, finances          │   └── screens/
│   └── relay.py                      └── test/mesh/
├── tools/vie_*.py  (4 outils           canonical_vectors.json  ← engendré ici
│   vocaux : « ajoute une dépense »)
└── vie/routes.py   100 routes
```

(Comptes du 25/09/2026. Le domaine s'appelait `succes` jusqu'à cette date :
`/v1/succes`, `succes.db`, `tools/succes_*.py`. Voir le plan 1b.)

## Les trois surfaces de contact

### 1. L'encodage canonique du maillage

Des octets **signés** : un écart d'un seul caractère et toutes les
signatures Ed25519 échouent, sans qu'aucun message ne l'explique. Le Dart
réimplémente `canonical_bytes` ; les vecteurs de test viennent de
l'implémentation Python réelle.

```bash
.venv/bin/python scripts/gen_canonical_vectors.py
```

Écrit dans `~/Projets/diapason_mobile/test/mesh/canonical_vectors.json`, à
commiter **dans le dépôt diapason_mobile**.

### 2. Les routes du maillage : `success://` et `vie://`

`app.navigate` et `app.show_resource` nomment un écran par une route
(`vie://notes/n1`). Trois récepteurs la traduisent, chacun avec sa table :
`mesh/executor.py` (qui répond à l'émetteur), `frontend/src/features/mesh/routes.ts`
(la fenêtre du bureau) et `lib/services/mesh/mesh_routes.dart` (le
téléphone). Depuis le 25/09/2026, les trois acceptent **les deux schémas** ;
les émetteurs écrivent encore `success://` jusqu'à l'étape 14a du plan 1b.
`diapason://` est refusé partout : c'est l'espace des liens profonds du
système.

`tests/contract/test_routes_du_maillage.py` lit les deux fichiers sources
et exige les mêmes écrans et les mêmes schémas des trois côtés.

### 3. Les 100 routes `/v1/vie`

Le Dart n'en appelle **aucune** aujourd'hui (inventaire du 25/09/2026 : la
Life OS de l'app se synchronisait avec le site PHP). La WebView de la
phase 3 les appellera toutes, par la passerelle de la phase 2. Deux
instantanés les figent :

```bash
.venv/bin/python scripts/gen_vie_surface.py      # tests/contract/vie_api_surface.json
.venv/bin/python scripts/gen_succes_surface.py   # l'alias /v1/succes, miroir exact
```

L'alias `/v1/succes` reste monté (hors du schéma OpenAPI) tant que son
compteur d'accès n'est pas resté à zéro : c'est l'étape 14c du plan.

## Ce qui garde la frontière

`tests/contract/test_succes_client_contract.py` et
`tests/contract/test_routes_du_maillage.py` échouent **du côté où le
changement est fait** — ici, dans Diapason — au lieu de laisser la rupture
se manifester au téléphone, loin du commit qui l'a causée.

| Le test échoue quand… | Ce qu'il faut faire |
|---|---|
| `canonical_bytes` a changé sans régénération | relancer `gen_canonical_vectors.py`, commiter côté diapason_mobile |
| une route `/v1/vie` disparaît ou est renommée | régénérer les deux instantanés **dans le même commit**, et prévoir la version mobile qui cessera de fonctionner |
| une route neuve n'est pas dans l'instantané | régénérer — ajouter est inoffensif, mais l'instantané doit rester un miroir exact |
| un écran ou un schéma de route n'est accepté que d'un côté | corriger la table en retard, dans les deux dépôts s'il le faut |

Les tests qui lisent le dépôt mobile **échouent** quand il est absent de
`~/Projets/diapason_mobile`, et ne se **sautent** que si la variable
d'environnement `CI` est posée (le runner Windows `pc-bureau` n'a que
Diapason). Avant le 25/09/2026 ils se sautaient partout : le déménagement du
dépôt depuis `~/Desktop/Porfolio/Succes` les avait rendus muets sans que
rien ne le dise.

## Faire évoluer les deux ensemble

1. Changer Diapason, lancer `pytest tests/contract` — il dira ce qui casse.
2. Régénérer ce qu'il demande.
3. Commiter **ici** le changement plus l'instantané.
4. Commiter **là-bas** les vecteurs, et adapter le Dart.

L'ordre compte : le contrat est régénéré avant que le mobile ne soit
touché, jamais après. Pour un nouveau nom (un schéma, une route), la même
règle que le plan 1b : **accepter le nouveau nom partout avant de
l'émettre**, et ne retirer l'ancien qu'une fois vérifié que plus rien ne
l'utilise.
