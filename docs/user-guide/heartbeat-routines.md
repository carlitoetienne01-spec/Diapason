# Heartbeat & routines

OpenJarvis ports Diapason-style ambient automation on top of the existing
`TaskScheduler` (no second daemon).

## Heartbeat

Markdown queue at `~/.openjarvis/workspace/HEARTBEAT.md`.

```bash
jarvis heartbeat add "Check calendar before 11"
jarvis heartbeat list
jarvis heartbeat tick --force    # drain first pending item
jarvis heartbeat status
```

Every `interval_seconds` (default 1800), task `heartbeat:tick` runs and
processes **one** `- [ ]` under `## Now`. Empty queue = silent no-op.

## Routines

Catalog at `~/.openjarvis/workspace/ROUTINES.json` (builtins: morning-digest,
calendar-ping, idle-check).

```bash
jarvis routines list
jarvis routines run morning-digest --force
jarvis routines enable idle-check
jarvis routines sync             # upsert into scheduler.db
jarvis scheduler start           # daemon that fires cron/interval
```

## Privacy

- Quiet hours suppress delivery (default 22:00–07:00).
- No auto-send email/SMS from heartbeat.
- `shell` kind disabled unless `[routines] allow_shell = true`.
