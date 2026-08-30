# Reconstruire et installer l'application de bureau

```bash
./scripts/install-desktop.sh
```

Compile, ferme l'application, sauvegarde celle en place, installe la neuve,
relance, et vérifie qu'elle a démarré.

## Pourquoi un script plutôt qu'à la main

Le geste fait à la main a laissé, en trois jours, **sept copies** de
`Diapason.app` dans `/Applications` :

```
Diapason.app.phase1-20260814        Diapason.app.phase3-20260815
Diapason.app.phase2-20260815        Diapason.app.before-project-3d-20260815
Diapason.app.phase2-pre-ratefix-…   Diapason.app.pre-succes-20260814
```

Toutes avec le **même identifiant** (`com.diapason.desktop`) et la **même
version** (`1.0.0`). Spotlight ne pouvait pas les distinguer et les
affichait comme des applications concurrentes.

Le risque n'était pas les 123 Mo : c'était d'en lancer une ancienne sans le
savoir, et de croire qu'une correction n'avait pas pris.

## Les trois règles

1. **La sauvegarde sort de `/Applications`** → `~/.diapason/backups/`, donc
   Spotlight ne l'indexe plus.
2. **Il n'y en a qu'une**, écrasée à chaque installation. Un filet, pas un
   musée : ces bundles se reconstruisent depuis le code, ils n'ont aucune
   valeur que git ne contienne déjà.
3. **L'ancienne n'est retirée qu'après** que la nouvelle soit en place.

## Si l'application ne démarre pas

Le script le dit au lieu de prétendre le contraire, et donne la commande :

```bash
rm -rf /Applications/Diapason.app
cp -R ~/.diapason/backups/Diapason.app.precedente /Applications/Diapason.app
```

## Signature et Accessibilité

Tauri produit encore un bundle *ad hoc*. Le script le re-signe ensuite avec
une identité Apple Development du trousseau, pour que le droit Accessibilité
survie aux rebuilds. Sans cette identité, Réglages Système peut afficher
Diapason coché alors que le pointeur est refusé : retirer l'entrée, ajouter
`/Applications/Diapason.app`, quitter et relancer.

## Ce que le script ne fait pas

Il ne redémarre pas le serveur Python : celui-ci tourne comme agent launchd
et se recharge séparément.

```bash
launchctl kickstart -k gui/$(id -u)/com.diapason.serve
```

Les deux sont indépendants par choix — le serveur ne doit pas mourir parce
que l'interface se recompile.
