# Desktop app (Tauri)

Global hotkeys and paste-to-frontmost live in the **Tauri** binary, not the Python server.

## Hotkeys (already wired in Rust)

| Shortcut | Event | Effect |
|----------|-------|--------|
| **⌥Space** (Alt+Space) | `talk-toggle` | Open/close Talk to Jarvis |
| **⌘⌥Space** (Cmd+Alt+Space) | `ptt-start` / `ptt-stop` | Push-to-talk → paste to frontmost app |
| **⌘⇧Space** | overlay | Native overlay toggle |

Source of truth: `frontend/src-tauri/src/lib.rs`  
(`dictation.hotkey` in TOML is informational — changing it does **not** change Rust until you edit `lib.rs` and rebuild.)

## Rebuild (required after Rust / hotkey changes)

```bash
# From repo root
./scripts/rebuild-desktop.sh
# or:
cd frontend
npm install
npm run tauri:dev    # develop
npm run tauri:build  # release → src-tauri/target/release/bundle/
```

Wrong path (do **not** use): `cd desktop && npm run tauri build` — the app lives under **`frontend/`**.

## Backend still separate

```bash
uv sync --extra desktop
# optional ML wake:
uv sync --extra speech-wake
jarvis serve
```
