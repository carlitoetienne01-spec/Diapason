"""Realtime duplex voice — Gemini Live / OpenAI Realtime.

## What this is

A low-latency **audio in ↔ audio out** session so Diapason can talk like a
person (interruptible), similar to commercial "Talk to Diapason" / Gemini Live.

This is **not** the turn-based STT → agent → TTS pipeline used by dictation
(PTT). For always-on « Hey Diapason », see `WAKEWORD.md` and `diapason wake-listen`.
and welcome-clap.

## Config

```toml
[speech.realtime]
enabled = true
provider = "gemini"          # or "openai"
model = ""                   # empty = provider default
voice = "Puck"               # Gemini: Puck, Charon, Fenrir, Aoede, …
# voice = "alloy"            # OpenAI: alloy, verse, …
language = "fr"
enable_tools = true
max_tool_steps = 6
tools = ""                   # empty = open_uri, focus_app, run_voice_command
```

Environment:

- Gemini: `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- OpenAI: `OPENAI_API_KEY`

## API

- `WS /v1/voice/live` — duplex bridge (see `voice_live_routes.py`)
- `GET /v1/voice/live/health` — key / config / tools status

Client messages: `start`, `audio` (base64 PCM16), `text`, `interrupt`, `stop`.
Server messages: `ready`, `audio`, `transcript`, `tool`, `interrupted`, `error`, `closed`.

## UI / hotkeys

- Chat header **Talk to Diapason**
- Global **⌥Space** (Alt+Space) — desktop Tauri + web when focused
- Space = interrupt, Esc = close

## Tools (Phase C+)

Allow-listed desktop tools run inside the live session (default budget 12):

- **`open_anything`** — open any app, URL, file/folder, or browser search; YouTube / Amazon / Netflix / site phrases via `desktop/smart_intents.py`
- **`calendar_query`** — today / tomorrow (macOS Calendar; grant Calendar privacy)
- **`spotify_play`** — search/play via Spotify URI (also “joue X sur Spotify”)
- **`mail_compose`** — Mail.app **draft** only (never auto-sends)
- **`messages_compose`** — Messages **draft** via `sms:`/`imessage:` (never auto-sends)
- **`web_search`** — Tavily or DuckDuckGo; summarize orally
- **`find_files`** — Spotlight `mdfind` (grant **Full Disk Access** for some folders)
- **`screen_describe`** — one-shot screenshot → local vision
- **`screen_share_start` / `screen_share_stop` / `screen_share_status`** — continuous share session (periodic captures until stop)
- `open_uri` / `focus_app` / `open_browser_on_monitor` / `run_voice_command`

Oral rules (2–3 sentences, clarifications, Zephyr default) live in
`speech/realtime/oral_prompt.py`.

Examples: « ouvre Cursor », « ouvre youtube et cherche chats », « joue Daft Punk sur Spotify »,
« écris un mail à ada@example.com sujet Hello », « envoie un message à +15551234567 disant Salut »,
« cherche casque sur amazon », « qu'est-ce qu'il y a demain ? », « trouve mon fichier facture »,
« je veux partager mon écran », « arrête le partage ».

Results are spoken by the model after `toolResponse`.

## Screen vision / share

Opt-in: `[desktop.vision] enabled = true`. Uses macOS `screencapture` + a **local**
vision model (Ollama) by default.

- **One-shot:** `screen_describe` / « regarde mon écran »
- **Share session:** `screen_share_start` → captures every `share_interval_s` (default 5s)
  until `screen_share_stop` or `share_max_minutes` (default 30). No continuous cloud stream.

Grant **Screen Recording** in System Settings.

## Limits

- Wake-word: see `WAKEWORD.md` (`diapason wake-listen`).
- Browser uses ScriptProcessor for PCM capture (AudioWorklet later).
- Rebuild the Tauri desktop app to pick up the ⌥Space global shortcut.
"""
