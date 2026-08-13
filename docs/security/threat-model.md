# Threat model

## Scope

Diapason is a local-first assistant that can read files, execute code, access
networks, call external models, and send messages when those tools are enabled.
The protected assets are user data, credentials, local files, model context,
audit integrity, and control of the host.

## Trust boundaries

| Boundary | Untrusted input | Required control |
|---|---|---|
| Browser/desktop → local API | Requests, WebSockets | Bearer authentication, CORS allowlist, rate limit |
| Prompt/model → tool executor | Tool name and arguments | Exact tool allowlist, capabilities, confirmation, timeout |
| Device → network/cloud | Prompts, files, audio, screenshots | Local-only gate, SSRF checks, secret/PII boundary scan |
| Runtime → filesystem/process | Paths and commands | Sensitive-file policy, capability check, confirmation, sandbox where configured |
| Runtime → logs/traces | Results and metadata | Redaction before persistence, hashed security evidence, owner-only files |
| Desktop webview → native host | Tauri commands | Narrow command surface and capability manifest; no shell plugin permission |

## Main threats and mitigations

- **Prompt injection and confused-deputy tool use:** tools are limited to the
  configured set, capability grants are scoped to exact tool names, and
  sensitive tools require approval.
- **Credential or PII exfiltration:** local-only mode blocks remote paths by
  default; outbound payloads and model traffic are scanned and redacted or
  blocked according to profile.
- **Unauthenticated local API access:** every server start resolves an explicit
  key or creates a 256-bit owner-only key; HTTP and WebSocket data routes check
  it.
- **Abuse and resource exhaustion:** API and per-tool token buckets, tool
  timeouts, request-size limits where endpoints define them, and constrained
  concurrency.
- **SSRF and unsafe file access:** URL destinations and sensitive paths are
  checked before access.
- **Secret leakage through observability:** audit entries store hashes and
  lengths rather than matched values; tool events redact arguments and results.
- **Native desktop privilege expansion:** the webview has no generic shell
  execute, spawn, stdin, kill, or open permissions.
- **Supply-chain compromise:** lockfiles are tracked; CI must run dependency,
  secret, license, and provenance checks before release.

## Security profiles

- `personal` (default): loopback server, local-only privacy, redaction, 60
  requests/minute with burst 10, approval required for sensitive tools.
- `shared`: loopback server with the same enforcement; administrators should
  provide an explicit capability policy for multiple operators.
- `server`: block mode, 30 requests/minute with burst 5. Exposure outside
  loopback requires TLS at a reverse proxy and a managed secret.

## Residual risks

Model output is untrusted, regex detection cannot recognize every secret,
local code execution inherits the host user's authority unless sandboxing is
enabled, and a compromised dependency can execute in-process. Release approval
therefore requires no known High/Critical findings plus independent review for
internet-exposed or high-value deployments.
