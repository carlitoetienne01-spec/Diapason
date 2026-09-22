# Heartbeat & routines

Diapason ports Diapason-style ambient automation on top of the existing
`TaskScheduler` (no second daemon).

## Heartbeat

Markdown queue at `~/.diapason/workspace/HEARTBEAT.md`.

```bash
diapason heartbeat add "Check calendar before 11"
diapason heartbeat list
diapason heartbeat tick --force    # drain first pending item
diapason heartbeat status
```

Every `interval_seconds` (default 1800), task `heartbeat:tick` runs and
processes **one** `- [ ]` under `## Now`. Empty queue = silent no-op.

## Routines

Catalog at `~/.diapason/workspace/ROUTINES.json` (builtins: morning-digest,
calendar-ping, idle-check).

```bash
diapason routines list
diapason routines run morning-digest --force
diapason routines enable idle-check
diapason routines sync             # upsert into scheduler.db
diapason scheduler start           # daemon that fires cron/interval
```

## Privacy

- Quiet hours suppress delivery (default 22:00–07:00).
- No auto-send email/SMS from heartbeat.
- `shell` kind disabled unless `[routines] allow_shell = true`.
