# Security Policy

## Supported version

Security fixes are provided for the latest Diapason `1.x` release. Users
should reproduce an issue on the latest release before reporting it.

## Reporting a vulnerability

Do not open a public issue for an unpatched vulnerability. Use the private
security-advisory form in the
[carlitoetienne01-spec/Diapason repository](https://github.com/carlitoetienne01-spec/Diapason/security/advisories/new).

Include the affected version and platform, a minimal reproduction, expected
impact, and any proposed mitigation. Do not include real credentials or
personal data. Maintainers should acknowledge a complete report within five
business days and coordinate disclosure after a fix is available.

## Security defaults

- Local-only privacy mode is enabled on a fresh installation.
- API routes require an automatically generated 256-bit local key.
- Sensitive tools require explicit confirmation by default.
- Secret and PII scanning, audit chaining, capability checks, and rate limits
  are enabled by default.

No software can guarantee absolute security. These controls reduce the
documented risks; deployments exposed to untrusted networks still require TLS,
host hardening, dependency maintenance, and an independent security review.

## Dependency exceptions

The complete lockfile is audited in CI. Two narrowly scoped upstream
exceptions are temporarily accepted and must be reviewed on every release:

- `diskcache` (`GHSA-w8v5-vhqr-4h9v` / `PYSEC-2026-2447`) has no fixed
  release. It is pulled only by the optional DSPy optimizer. Do not point its
  cache at data writable by another user and do not reuse an untrusted cache.
- `setuptools` (`GHSA-h35f-9h28-mq5c` / `PYSEC-2026-3447`) is constrained
  below the fixed release by optional inference/voice dependencies. The issue
  affects source-distribution manifest construction; Diapason does not invoke
  that path at runtime. Release artifacts must be built in an isolated CI
  environment.

These are risk acceptances, not claims that the findings are fixed. Remove
each CI exception as soon as the upstream dependency graph permits it.

RustSec reports no vulnerability in either Rust lockfile. It does report one
allowed unsoundness warning for `anyhow` (`RUSTSEC-2026-0190`) with no patched
release, plus warnings in the desktop lock for Tauri's transitive Linux GTK3
stack and legacy Unicode/proc-macro crates. The GTK3 warnings do not affect the
macOS/Windows desktop binaries, but Linux packaging must track Tauri's GTK4
migration. These warnings remain release-review items and must not be hidden or
reclassified as fixed.
