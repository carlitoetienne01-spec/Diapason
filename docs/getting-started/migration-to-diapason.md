# Migration vers Diapason

Diapason `1.0.0` est la première version de la gamme de produits Diapason.
L'historique Git et la provenance légale sont conservés ; les noms de produit
actifs, les métadonnées de paquet, les services, la documentation et les URL de
publication, eux, utilisent Diapason.

Lance un audit sans rien changer à l'état local :

```bash
diapason migrate --check
```

Applique les renommages sûrs de dossiers et d'agents launchd :

```bash
diapason migrate --apply
```

Les variables d'environnement utilisent le préfixe `DIAPASON_`. Les anciens noms
`OPENJARVIS_` et `JARVIS_` restent lisibles pendant toute la série `1.x` de
Diapason, et le nom Diapason l'emporte quand les deux sont définis. La commande
de migration signale les variables qu'il faut renommer dans les profils de shell,
les secrets de CI, les conteneurs et les services.

L'identité canonique du projet est
[`carlitoetienne01-spec/Diapason`](https://github.com/carlitoetienne01-spec/Diapason).
Les nouvelles versions portent un seul et même numéro pour Python, l'interface,
le bureau et les métadonnées de protocole.
