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

Depuis le 26/09/2026, un vecteur y est **nommé** : `enveloppe-de-session`,
l'enveloppe `webview-session` que le téléphone signe pour ouvrir sa
session d'appareil sur la passerelle du tailnet. Les octets ne suffisent
pas pour elle : l'hôte refuse une clé en trop ou en moins avant toute
cryptographie. Pytest exige donc ses clés (`SESSION_REQUEST_FIELDS`), et le
Dart exige que son constructeur rende exactement ce vecteur.

Dans l'autre sens, `test/mesh/telecommande_signee.json` (dépôt mobile) porte
deux ordres `desktop.open` signés par le vrai constructeur Dart, l'un
confirmé, l'autre non ; `tests/contract/test_telecommande_du_telephone.py`
les passe au vrai `verify_command` (contrôle n°10).

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

Depuis le 26/09/2026 (phase 3, étape 9), le téléphone n'ouvre plus une vue
de sa Life OS native : la coquille traduit la route en **chemin React**
(`cheminReact`, table `_chemins`) et demande l'écran au bundle du Mac par le
verbe `naviguer` du pont ; elle n'acquitte SUCCESS qu'une fois la page
montée. Les chemins sont tenus d'accord par un fichier de vecteurs écrit à
la main, `frontend/src/features/mesh/vecteurs_routes.json`, copié **à
l'octet** dans `diapason_mobile/test/mesh/vecteurs_routes.json` : vitest et
`flutter test` le lisent contre leur table, pytest exige les deux copies
égales, `parse_mesh_route` d'accord sur chaque refus et les chemins de
`_chemins` égaux à ceux de `PATHS`.

### 3. Les 100 routes `/v1/vie`

La WebView les appelle toutes, par la passerelle de la phase 2. Le Dart en
appelle six depuis le 26/09/2026, par sa **propre** session d'appareil
(`SessionNative` : la même enveloppe signée que la coquille, le cookie
gardé dans le trousseau, jamais celui de la WebView) : l'import unique
(`POST /v1/vie/import/legacy`), puis, une fois la Life OS sur le Mac, les
trois lectures des rappels (`GET /v1/vie/tasks?include_done=false`,
`/v1/vie/habits`, `/v1/vie/habits/logs`) et les deux gestes « Marquer
fait » (`POST /v1/vie/tasks/{id}/done`, `/v1/vie/habits/{id}/log`, avec un
`opId`). La forme des lectures est figée par une fixture réelle :

```bash
.venv/bin/python scripts/gen_vie_rappels.py   # diapason_mobile/test/rappels/vie_rappels.json
```

(l'état `test/rappels/etat_rappels.json`, écrit par le Dart, importé par la
vraie route puis relu ; `tests/contract/test_vie_rappels.py` exige le
fichier identique à ce que les routes rendent). Deux instantanés figent les
routes :

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
| `build_session_request` ou `SESSION_REQUEST_FIELDS` a changé | régénérer les vecteurs, adapter `MeshApi.enveloppeDeSession` dans le même thème |
| la télécommande signée n'est plus acceptée (ou plus refusée sans confirmation) | voir `verify_command` ; régénérer la fixture côté mobile (`DIAPASON_ECRIRE_TELECOMMANDE=1`) si le Dart a changé |
| une route `/v1/vie` disparaît ou est renommée | régénérer les deux instantanés **dans le même commit**, et prévoir la version mobile qui cessera de fonctionner |
| une route neuve n'est pas dans l'instantané | régénérer — ajouter est inoffensif, mais l'instantané doit rester un miroir exact |
| un écran ou un schéma de route n'est accepté que d'un côté | corriger la table en retard, dans les deux dépôts s'il le faut |
| les deux copies de `vecteurs_routes.json` diffèrent, ou un chemin de `_chemins` n'est plus celui de `PATHS` | éditer le fichier du bundle, le recopier à l'octet côté mobile, adapter la table en retard — même thème |
| `vie_rappels.json` n'est plus ce que `/v1/vie` rend | relancer `gen_vie_rappels.py`, puis `flutter test test/rappels` : l'adaptateur doit suivre dans le même thème |

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
