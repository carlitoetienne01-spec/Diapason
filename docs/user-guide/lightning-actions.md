# Lightning actions

Diapason executes explicit, reversible desktop commands before memory lookup
and model inference. The desktop client opts in with `action_mode: "auto"`;
the OpenAI-compatible API keeps host actions disabled by default.

## Supported commands

- open or focus an application, URL, or web search;
- prepare an email or message draft without sending it;
- type or paste into a named application or the frontmost application;
- generate requested content, then insert it into a named application;
- run existing media intents such as YouTube and Spotify searches.

On macOS, text insertion tries the Accessibility API first, then falls back to
a paste operation that restores the full clipboard. Diapason verifies that a
requested application reached the foreground and never presses Enter after
inserting text.

## Security boundary

Send, delete, purchase/payment, install/uninstall, administration, and system
restart operations never use the lightning path. They remain in the agent
pipeline with capability enforcement and confirmation. Automatic text entry
also excludes Terminal, iTerm, and System Settings.

Configuration lives under `[desktop.lightning]`. Disabling `allow_type` or
`allow_external_drafts` reduces the authorized surface further. Metrics from
`GET /v1/actions/metrics` never contain prompts, typed text, URLs, paths, or
application targets.

Host actions accept loopback clients only by default, even when a request sets
`action_mode: "auto"`. Set `allow_remote = true` only when the API is strongly
authenticated and remote desktop control is intentional.

## Performance

Ollama receives `keep_alive = "30m"` and is preloaded in the background. The
macOS application index is cached for five minutes. Run the router benchmark
with:

```bash
uv run python scripts/bench_lightning.py
```
