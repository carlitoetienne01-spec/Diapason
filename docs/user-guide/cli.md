# CLI Reference

Diapason provides a command-line interface through the `diapason` command. Built on [Click](https://click.palletsprojects.com/), it offers subcommands for querying models, managing memory, running benchmarks, and serving an OpenAI-compatible API.

## Global Options

```bash
diapason --version   # Print the Diapason version
diapason --help      # Show top-level help with all subcommands
```

## `diapason init`

Detect local hardware (CPU, GPU, RAM) and generate a configuration file at `~/.diapason/config.toml`.

```bash
diapason init           # Interactive — refuses to overwrite existing config
diapason init --force   # Overwrite existing config without prompting
```

| Option    | Description                                   |
|-----------|-----------------------------------------------|
| `--force` | Overwrite existing configuration without prompting |

The `init` command auto-detects:

- **Platform** (Linux, macOS, Windows)
- **CPU** brand and core count
- **RAM** in GB
- **GPU** vendor, model, VRAM, and count (via `nvidia-smi`, `rocm-smi`, or `system_profiler`)

Based on the detected hardware, it recommends an appropriate inference engine and writes a pre-configured TOML file.

**Example output:**

```
Detecting hardware...
  Platform : linux
  CPU      : AMD Ryzen 9 7950X (32 cores)
  RAM      : 64 GB
  GPU      : NVIDIA RTX 4090 (24.0 GB VRAM, x1)

Config written successfully.
```

---

## `diapason ask`

Send a query to the inference engine (directly or through an agent) and print the response.

```bash
diapason ask "What is the capital of France?"
```

### Options

| Option                        | Type    | Default    | Description                                           |
|-------------------------------|---------|------------|-------------------------------------------------------|
| `-m`, `--model MODEL`         | string  | auto       | Model to use for inference                             |
| `-e`, `--engine ENGINE`       | string  | auto       | Engine backend (ollama, vllm, llamacpp, etc.)          |
| `-t`, `--temperature TEMP`    | float   | `0.7`      | Sampling temperature                                   |
| `--max-tokens N`              | int     | `1024`     | Maximum tokens to generate                             |
| `--json`                      | flag    | off        | Output raw JSON result instead of plain text           |
| `--no-stream`                 | flag    | off        | Disable streaming (synchronous mode)                   |
| `--no-context`                | flag    | off        | Disable memory context injection                       |
| `-a`, `--agent AGENT`         | string  | none       | Agent to use (`simple`, `orchestrator`)                |
| `--tools TOOLS`               | string  | none       | Comma-separated tool names to enable                   |
| `-i`, `--image PATH`          | path    | none       | Image file for a vision model (e.g. `gemma3:4b`); repeatable |
| `-S`, `--screen`              | flag    | off        | Capture the current screen and send it to the vision model  |

### Direct Mode vs Agent Mode

**Direct mode** (default) sends the query straight to the inference engine:

```bash
diapason ask "Explain quantum computing"
```

**Agent mode** routes the query through an agent that can use tools and manage multi-turn interactions:

```bash
diapason ask --agent orchestrator "What is 2+2?"
diapason ask --agent orchestrator --tools calculator,think "Calculate sqrt(144) + 3^2"
diapason ask --agent simple "Hello"
```

### Usage Examples

```bash
# Basic query
diapason ask "What is machine learning?"

# Specify a model
diapason ask -m qwen3:8b "Summarize this concept"

# Use the orchestrator agent with tools
diapason ask --agent orchestrator --tools calculator "What is 15% of 340?"

# Get JSON output
diapason ask --json "Hello"

# Disable memory context injection
diapason ask --no-context "Tell me about Python"

# Set maximum token generation
diapason ask --max-tokens 2048 "Write a detailed essay about AI"
```

### Vision Input

Vision-capable models (such as `gemma3:4b`) can read images alongside your
text prompt. Attach one or more image files with `-i`/`--image`, or capture
the current screen with `-S`/`--screen`:

```bash
# Ask about a local image
diapason ask -i screenshot.png "What is shown in this image?"

# Send multiple images (the flag is repeatable)
diapason ask -i chart-a.png -i chart-b.png "Compare these two charts"

# Capture the current screen and ask about it
diapason ask --screen "Summarize what's on my screen"
```

Vision runs in **direct mode** only. If you also pass `--agent`, the image is
ignored and a note is printed — re-run with `--agent ""` to force direct mode.

The Ollama context window can be tuned for large images or long prompts with
the `JARVIS_NUM_CTX` environment variable (default `16384`):

```bash
JARVIS_NUM_CTX=8192 diapason ask --screen "What's on my screen?"
```

!!! note "Keep vision on-device"
    Images are sensitive. Diapason prints a privacy warning before sending
    an image to a non-local engine, so a screenshot never leaves your machine
    unnoticed. Use a local engine (e.g. `ollama` with `gemma3:4b`) to keep
    vision fully local.

### JSON Output Format

When using `--json` in **direct mode**, the output includes:

```json
{
  "content": "The response text...",
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 85,
    "total_tokens": 97
  }
}
```

When using `--json` in **agent mode**, the output includes:

```json
{
  "content": "The response text...",
  "turns": 3,
  "tool_results": [
    {
      "tool_name": "calculator",
      "content": "51.0",
      "success": true
    }
  ]
}
```

---

## `diapason model`

Manage and inspect language models available on running engines.

### `diapason model list`

List all models available from running inference engines, displayed as a Rich table with model parameters, context length, and VRAM requirements.

```bash
diapason model list
```

**Example output:**

```
           Available Models
┌─────────┬────────────────┬────────┬─────────┬──────┐
│ Engine  │ Model          │ Params │ Context │ VRAM │
├─────────┼────────────────┼────────┼─────────┼──────┤
│ ollama  │ qwen3:8b       │ 8B     │ 32,768  │ 6GB  │
│ ollama  │ llama3.2:3b    │ 3B     │ 8,192   │ 3GB  │
└─────────┴────────────────┴────────┴─────────┴──────┘
```

### `diapason model info <model>`

Show detailed information about a specific model.

```bash
diapason model info qwen3:8b
```

**Example output:**

```
┌─ Qwen 3 8B ──────────────────────────────┐
│ Model ID:     qwen3:8b                    │
│ Name:         Qwen 3 8B                   │
│ Parameters:   8B                          │
│ Context:      32,768                      │
│ Quantization: none                        │
│ Min VRAM:     6GB                         │
│ Engines:      ollama, vllm                │
│ Provider:     Alibaba                     │
│ API Key:      not required                │
└───────────────────────────────────────────┘
```

### `diapason model pull <model>`

Download a model via Ollama. Shows a progress bar during download.

```bash
diapason model pull qwen3:8b
```

!!! note
    The `pull` command requires a running Ollama instance. It connects to the Ollama API at the host configured in your `config.toml`.

---

## `diapason pearl`

Access Pearl's native node, wallet, and RPC tools from the Diapason CLI.

```bash
diapason pearl doctor
diapason pearl node -- <pearld args>
diapason pearl wallet -- <oyster args>
diapason pearl ctl -- <prlctl args>
diapason pearl address
```

All Pearl wrapper commands use the `diapason pearl <command>` shape. The
pass-through commands map to Pearl's native binaries:

| Diapason command | Pearl binary | Use |
|--------------------|--------------|-----|
| `diapason pearl doctor` | n/a | Check whether `pearld`, `oyster`, and `prlctl` are discoverable |
| `diapason pearl node` | `pearld` | Run the Pearl full node |
| `diapason pearl wallet` | `oyster` | Run the Oyster wallet daemon |
| `diapason pearl ctl` | `prlctl` | Query Pearl node or wallet RPC |
| `diapason pearl address` | `prlctl --wallet getnewaddress` | Generate a wallet address from Oyster |

Use `PEARL_HOME=/path/to/pearl` or `--pearl-home /path/to/pearl` if Pearl's
`bin/` directory is not on `PATH`. See the [Pearl CLI guide](pearl.md) for
examples.

---

## `diapason memory`

Manage the document memory store for retrieval-augmented generation.

### `diapason memory index <path>`

Index documents from a file or directory into the memory store.

```bash
diapason memory index ./docs/
diapason memory index ./notes.md
diapason memory index ./data/ --chunk-size 256 --chunk-overlap 32
diapason memory index ./docs/ --backend sqlite
```

| Option                      | Type   | Default | Description                          |
|-----------------------------|--------|---------|--------------------------------------|
| `--backend`, `-b`           | string | config  | Override the default memory backend  |
| `--chunk-size`              | int    | `512`   | Chunk size in tokens                 |
| `--chunk-overlap`           | int    | `64`    | Overlap between chunks in tokens     |

The ingestion pipeline supports text, markdown, code files, and PDF (with `pdfplumber` installed). Binary files and hidden directories are automatically skipped.

### `diapason memory search <query>`

Search the memory store for relevant document chunks.

```bash
diapason memory search "machine learning basics"
diapason memory search -k 10 "neural networks"
diapason memory search --backend faiss "embeddings"
```

| Option             | Type   | Default | Description                          |
|--------------------|--------|---------|--------------------------------------|
| `--top-k`, `-k`    | int    | `5`     | Number of results to return          |
| `--backend`, `-b`  | string | config  | Override the default memory backend  |

Results are displayed in a table with rank, score, source file, and a content preview.

### `diapason memory stats`

Show memory store statistics including document count and database size.

```bash
diapason memory stats
diapason memory stats --backend sqlite
```

| Option             | Type   | Default | Description                          |
|--------------------|--------|---------|--------------------------------------|
| `--backend`, `-b`  | string | config  | Override the default memory backend  |

---

## `diapason telemetry`

Query and manage inference telemetry data stored in SQLite.

### `diapason telemetry stats`

Show aggregated telemetry statistics including total calls, tokens, cost, and latency, broken down by model and engine.

```bash
diapason telemetry stats
diapason telemetry stats -n 5    # Show top 5 models
```

| Option          | Type | Default | Description                   |
|-----------------|------|---------|-------------------------------|
| `-n`, `--top`   | int  | `10`    | Number of top models to show  |

### `diapason telemetry export`

Export raw telemetry records in JSON or CSV format.

```bash
diapason telemetry export                          # JSON to stdout
diapason telemetry export --format csv             # CSV to stdout
diapason telemetry export --format json -o data.json  # JSON to file
diapason telemetry export -f csv -o metrics.csv    # CSV to file
```

| Option                | Type   | Default  | Description                     |
|-----------------------|--------|----------|---------------------------------|
| `-f`, `--format`      | choice | `json`   | Output format: `json` or `csv`  |
| `-o`, `--output`      | path   | stdout   | Output file path                |

### `diapason telemetry clear`

Delete all telemetry records from the database.

```bash
diapason telemetry clear         # Interactive confirmation
diapason telemetry clear --yes   # Skip confirmation
```

| Option         | Type | Default | Description                   |
|----------------|------|---------|-------------------------------|
| `-y`, `--yes`  | flag | off     | Skip confirmation prompt      |

!!! warning
    This permanently deletes all stored telemetry data. Use `--yes` to skip the confirmation prompt in automated scripts.

---

## `diapason bench`

Run inference benchmarks against a running engine.

### `diapason bench run`

Execute benchmarks and report results.

```bash
diapason bench run                               # Run all benchmarks, 10 samples
diapason bench run -n 20                         # 20 samples per benchmark
diapason bench run -b latency                    # Only the latency benchmark
diapason bench run -b throughput -n 50 --json    # Throughput, 50 samples, JSON output
diapason bench run -o results.jsonl              # Write JSONL results to file
diapason bench run -m qwen3:8b -e ollama         # Specific model and engine
```

| Option                     | Type   | Default | Description                              |
|----------------------------|--------|---------|------------------------------------------|
| `-m`, `--model MODEL`      | string | auto    | Model to benchmark                       |
| `-e`, `--engine ENGINE`    | string | auto    | Engine backend                           |
| `-n`, `--samples N`        | int    | `10`    | Number of samples per benchmark          |
| `-b`, `--benchmark NAME`   | string | all     | Specific benchmark to run                |
| `-o`, `--output PATH`      | path   | none    | Write JSONL results to file              |
| `--json`                   | flag   | off     | Output JSON summary to stdout            |

Available benchmarks:

- **latency** -- Measures per-call inference latency (mean, p50, p95, min, max)
- **throughput** -- Measures tokens-per-second throughput

---

## `diapason channel`

Manage messaging channels for multi-platform communication. Channels connect directly to platform APIs (Telegram, Discord, Slack, etc.) -- no gateway required.

### `diapason channel list`

List registered channel backends and their connection status.

```bash
diapason channel list
```

### `diapason channel send`

Send a message to a specific channel.

```bash
diapason channel send slack "Hello from Diapason!"
diapason channel send discord "Build complete"
```

| Argument    | Type   | Description                          |
|-------------|--------|--------------------------------------|
| `TARGET`    | string | Channel name to send to              |
| `MESSAGE`   | string | Message content                      |

### `diapason channel status`

Show connection status for configured channels.

```bash
diapason channel status
```

!!! note "Channel Dependencies"
    Each channel requires its platform-specific credentials (bot tokens, API keys) configured in the `[channel.<platform>]` section of your config. See [Configuration](../getting-started/configuration.md) for details.

---

## `diapason serve`

Start an OpenAI-compatible API server.

```bash
diapason serve                                 # Default host/port from config
diapason serve --port 8000                     # Custom port
diapason serve --host 0.0.0.0 --port 9000      # Bind to all interfaces
diapason serve --model qwen3:8b                # Specify default model
diapason serve --agent orchestrator            # Route requests through an agent
```

| Option                   | Type   | Default | Description                              |
|--------------------------|--------|---------|------------------------------------------|
| `--host HOST`            | string | config  | Bind address                             |
| `--port PORT`            | int    | config  | Port number                              |
| `-e`, `--engine ENGINE`  | string | auto    | Engine backend                           |
| `-m`, `--model MODEL`    | string | config  | Default model for inference              |
| `-a`, `--agent AGENT`    | string | none    | Agent for non-streaming requests         |

!!! note "Server Dependencies"
    The `serve` command requires the server extra:

    ```bash
    uv sync --extra server
    ```

    This installs FastAPI, uvicorn, and related dependencies.

### API Endpoints

The server exposes the following OpenAI-compatible endpoints:

| Method | Path                     | Description                    |
|--------|--------------------------|--------------------------------|
| POST   | `/v1/chat/completions`   | Chat completions (streaming & non-streaming) |
| GET    | `/v1/models`             | List available models          |
| GET    | `/health`                | Health check                   |
| GET    | `/v1/channels`           | List available messaging channels    |
| POST   | `/v1/channels/send`      | Send a message to a channel          |
| GET    | `/v1/channels/status`    | Channel bridge connection status     |

**Example with curl:**

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:8b",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

When an agent is configured (e.g., `--agent orchestrator`), non-streaming requests are routed through the agent with access to all registered tools. For tool-capable agents (`orchestrator`, `react`, `openhands`), all registered tools are automatically loaded and made available.

---

## LLM-guided spec search (no CLI yet)

LLM-guided spec search (the frontier-driven harness-learning subsystem)
is exposed as a Python library only — there is currently no top-level
`diapason` subcommand for it. Construct a `SpecSearchOrchestrator`
directly from `diapason.learning.spec_search.orchestrator` and call
`.run(trigger)` with a trigger from
`diapason.learning.spec_search.triggers`. See
[`docs/user-guide/llm-guided-spec-search.md`](llm-guided-spec-search.md)
for the architecture and the building blocks
(`splits.py`, external corpora, `external_adapter`).
