# L'intégration de Pearl à la ligne de commande

Diapason embarque un mince enrobage `diapason pearl` autour des outils en ligne
de commande natifs de Pearl. Il ne remplace ni le nœud ni le portefeuille de
Pearl ; il rend les commandes courantes trouvables depuis la ligne de commande
qui te sert déjà à miner.

## Trouver les binaires

`diapason pearl` cherche `pearld`, `oyster` et `prlctl` dans le `PATH`, puis
sous `$PEARL_HOME/bin`.

```bash
export PEARL_HOME=/path/to/pearl
diapason pearl doctor
```

## Passer la main aux commandes natives

Passe la main quand tu as besoin de toute la surface de Pearl :

```bash
diapason pearl node -- --help
diapason pearl wallet -- --help
diapason pearl ctl -- --help
```

Ces commandes renvoient directement à :

| Commande Diapason | Binaire Pearl |
|---|---|
| `diapason pearl node` | `pearld` |
| `diapason pearl wallet` | `oyster` |
| `diapason pearl ctl` | `prlctl` |

La commande prend toujours la forme `diapason pearl <command>`. Les arguments
natifs de Pearl viennent après cette commande. Mets `--` devant eux quand ils
commencent par des tirets et que tu veux marquer explicitement où passe la
frontière.

## L'aide à la génération d'adresse

Si Oyster tourne déjà, génère une adresse de minage par le RPC du
portefeuille :

```bash
diapason pearl address \
  -u rpcuser \
  -P rpcpass \
  -s localhost:44207
```

Cette aide s'appuie sur `prlctl --wallet` et prend `--notls` par défaut, ce qui
correspond au parcours de validation local. Utilise `--tls --skipverify` si ton
point d'accès RPC Oyster sert du TLS avec un certificat local.

## La frontière

`diapason mine` porte le cycle de vie du minage côté Diapason. `diapason pearl`
est une porte de sortie vers les outils natifs de Pearl — le nœud, le
portefeuille et le RPC. Pour l'administration avancée d'un nœud ou d'un
portefeuille, c'est l'aide de Pearl elle-même qui fait foi.
