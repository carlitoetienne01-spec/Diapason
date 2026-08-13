# Migration to Diapason

Diapason `1.0.0` is the first release of the Diapason product line. Git history
and legal provenance are preserved; active product names, package metadata,
services, documentation, and release URLs use Diapason.

Run an audit without changing local state:

```bash
diapason migrate --check
```

Apply safe directory and launchd renames:

```bash
diapason migrate --apply
```

Environment variables use the `DIAPASON_` prefix. Legacy `OPENJARVIS_` and
`JARVIS_` names remain readable through Diapason `1.x`, with the Diapason name
taking precedence when both are set. The migration command reports variables
that must be renamed in shell profiles, CI secrets, containers, and services.

The canonical project identity is
[`open-diapason/Diapason`](https://github.com/open-diapason/Diapason). New
releases use one version across Python, frontend, desktop, and protocol
metadata.
