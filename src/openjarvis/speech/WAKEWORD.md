"""Wake-word — local phrase gate + optional openWakeWord ML.

## What ships

1. **Text gate (PTT)** — after STT, if the transcript starts with
   « Jarvis », « Hey Jarvis », « Dis Jarvis », OpenJarvis strips the wake phrase
   and routes the rest as a voice command (or opens Talk if the phrase is alone).

2. **Always-on listener (opt-in)** — ``jarvis wake-listen`` opens the mic locally,
   detects the wake word, then emits ``talk_open`` on
   ``~/.openjarvis/triggers/local_trigger.jsonl``.
   The desktop UI polls ``GET /v1/triggers/poll`` and opens the Talk orb.

### Backends

| Backend | How | Install |
|---------|-----|---------|
| ``phrase_gate`` (default) | Energy gate + Whisper tiny + regex | ``sounddevice`` + ``faster-whisper`` |
| ``openwakeword`` | ML scores (pretrained ``hey_jarvis``) | ``uv sync --extra speech-wake`` |
| ``auto`` | openWakeWord if installed, else phrase_gate | — |

## Privacy

- Default: **no** always-on mic (``[speech.wakeword] enabled = false``).
- Always-on path is **local only** — never streams the wake mic to Gemini/OpenAI.

## Quick start

```bash
# Simulate without mic
jarvis wake-listen --text "Hey Jarvis"

# phrase_gate (Whisper)
jarvis wake-listen --debug

# ML wake (hey Jarvis)
uv sync --extra speech-wake
# in config.toml: backend = "openwakeword"
jarvis wake-listen --backend openwakeword --debug

# Force open Talk
jarvis wake-listen --fire
```

Config::

```toml
[speech.wakeword]
enabled = false
backend = "auto"          # phrase_gate | openwakeword | auto
phrases = "jarvis, hey jarvis, dis jarvis"
action = "talk"
cooldown_s = 2.5
sensitivity = 0.5         # openWakeWord score threshold
# model_path = ""         # optional custom ONNX
text_gate = true
```

Keep Alt+Space (Talk) and Cmd+Alt+Space (PTT) — wake does not replace them.
Those global hotkeys live in the **Tauri** desktop app — rebuild after Rust changes:
``cd frontend && npm run tauri:build``.
"""
