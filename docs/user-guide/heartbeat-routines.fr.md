# Le battement de cœur et les routines

Diapason greffe une automatisation ambiante, dans l'esprit de Diapason, par-dessus
le `TaskScheduler` déjà en place (pas de second démon).

## Le battement de cœur

Une file d'attente en Markdown, dans `~/.diapason/workspace/HEARTBEAT.md`.

```bash
diapason heartbeat add "Vérifier l'agenda avant 11 h"
diapason heartbeat list
diapason heartbeat tick --force    # traite la première entrée en attente
diapason heartbeat status
```

Toutes les `interval_seconds` (1800 par défaut), la tâche `heartbeat:tick` se
réveille et traite **une seule** ligne `- [ ]` sous `## Now`. File vide = rien ne
se passe, en silence.

## Les routines

Le catalogue vit dans `~/.diapason/workspace/ROUTINES.json` (fournies d'office :
morning-digest, calendar-ping, idle-check).

```bash
diapason routines list
diapason routines run morning-digest --force
diapason routines enable idle-check
diapason routines sync             # insère ou met à jour dans scheduler.db
diapason scheduler start           # le démon qui déclenche cron et intervalle
```

## La vie privée

- Pendant les heures calmes, rien n'est remis (par défaut de 22 h à 7 h).
- Aucun courriel ni SMS n'est envoyé automatiquement depuis le battement de cœur.
- Le type `shell` est désactivé, sauf si `[routines] allow_shell = true`.
