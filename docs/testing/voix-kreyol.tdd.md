# TDD — voix kreyòl

Pas de plan `*.plan.md`. Les parcours viennent de la demande du
29/09/2026 : répondre dans la langue de l'utilisateur, prononcer le
kreyòl sans avaler les consonnes, ne pas mélanger les langues.

Aucun commit de jalon : la session ne committe que sur demande.

## Parcours

- En tant qu'utilisateur, je parle kreyòl, français ou anglais, pour que
  Diapason réponde dans la même langue et change dès le tour suivant.
- En tant qu'utilisateur, j'entends tèt, jèn, kè, sè, peyi, mèsi, avni,
  lapòs et « gen » sans les déformations du français oral.
- En tant qu'utilisateur, une phrase française ou anglaise n'est pas
  réécrite en graphie kreyòl.

## Preuves

RED, avant le module :

```text
.venv/bin/python -m pytest tests/speech/test_langues.py -q --tb=line
ModuleNotFoundError: No module named 'diapason.speech.langues'
```

GREEN, après le module et le branchement dans `local_voice.py` :

```text
.venv/bin/python -m pytest tests/speech/test_langues.py -q --tb=short
25 passed
```

Puis deux cas de bord (ò inconnu, question déjà pointée, « Men wi ») :
les deux tests ciblés passent. La couverture du paquet
`diapason.speech.langues` sur `tests/speech/test_langues.py` :

```text
TOTAL  179 stmts, 6 miss, 97%
```

Les voix déjà là (`test_local_voice` des classes prompt et cliché,
conversation entre IA, téléphone, actualité) : 175 passed au premier
passage complet, 2 échecs corrigés ensuite (espace avant `?`).

## Ce que les tests garantissent

| # | Garantie | Test | Résultat |
|---|---|---|---|
| 1 | Une phrase kreyòl, française ou anglaise est nommée | `TestDetection` | PASS |
| 2 | La phrase mixte suit la langue dominante | `test_la_phrase_mixte_suit_la_langue_dominante` | PASS |
| 3 | « ok » garde la langue précédente ; l'égalité ne tranche pas | `TestDetection` | PASS |
| 4 | Le switch ht → fr → en est immédiat | `test_le_switch_est_immediat_puis_le_court_suit` | PASS |
| 5 | Les quatre idiomes et l'interdiction de calque sont dans les consignes | `test_les_consignes_tiennent_les_idiomes_et_interdisent_le_melange` | PASS |
| 6 | Le guide phonétique et « gen » → « gain » | `TestPhonetique` | PASS |
| 7 | Le français et l'anglais ne sont pas réécrits | `test_le_francais_et_l_anglais_ne_sont_pas_reecrits` | PASS |
| 8 | L'écran garde « fèt », la synthèse reçoit « fète » | `test_l_affichage_garde_l_orthographe_et_la_voix_la_phonetique` | PASS |
| 9 | `language = "fr"` laisse la bascule ; « français » la ferme | `TestLaVoix` | PASS |

## Trous assumés

Pas d'écoute réelle d'Orion : les tests tiennent la graphie envoyée au
synthétiseur, pas le son. Pas de modèle acoustique kreyòl. La discussion
écrite n'est pas branchée : `agentic_stream.py` était déjà modifié par
une autre session.
