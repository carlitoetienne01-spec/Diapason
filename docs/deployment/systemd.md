# systemd Service (Linux)

Diapason includes a systemd unit file for running the API server as a managed background service on Linux. This provides automatic startup on boot, crash recovery, and integration with standard Linux service management tools.

## Prerequisites

Before installing the service, ensure that:

1. Diapason is installed in a virtual environment at `/opt/diapason/.venv` (or adjust paths accordingly).
2. A dedicated `diapason` system user exists (recommended for security).
3. An inference engine (such as Ollama) is running and accessible.

Create the user and installation directory:

```bash
sudo useradd --system --create-home --home-dir /opt/diapason diapason
sudo -u diapason python3 -m venv /opt/diapason/.venv
sudo -u diapason git clone https://github.com/open-diapason/Diapason.git /opt/diapason/Diapason
cd /opt/diapason/Diapason && sudo -u diapason uv sync --extra server
```

## Installing the Service

The unit binds `0.0.0.0`, so an **API key is required** — and the unit
declares `EnvironmentFile=/etc/diapason/env` (no `-` prefix), so it will
**fail to start** until that file exists with a key. Create it first:

```bash
sudo mkdir -p /etc/diapason
echo "OPENJARVIS_API_KEY=$(diapason auth generate-key)" | sudo tee /etc/diapason/env
sudo chmod 600 /etc/diapason/env
```

Then copy the unit file, reload the daemon, and enable the service:

```bash
sudo cp deploy/systemd/diapason.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable diapason
sudo systemctl start diapason
```

Clients must send `Authorization: Bearer <key>` on `/v1/*` and `/api/*`
requests. (If you instead bind to `127.0.0.1`, the key is optional and you
can drop the `EnvironmentFile` line.)

Verify it is running:

```bash
sudo systemctl status diapason
```

## Service File Reference

The provided unit file at `deploy/systemd/diapason.service`:

```ini
[Unit]
Description=Diapason API Server
After=network.target

[Service]
Type=simple
User=diapason
WorkingDirectory=/opt/diapason
ExecStart=/opt/diapason/.venv/bin/diapason serve --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
Environment=HOME=/opt/diapason

[Install]
WantedBy=multi-user.target
```

### `[Unit]` Section

| Directive     | Value              | Description                                                                 |
|---------------|--------------------|-----------------------------------------------------------------------------|
| `Description` | `Diapason API Server` | Human-readable name shown in `systemctl status` and logs.              |
| `After`       | `network.target`   | Delays startup until the network stack is available, since the server binds to a network socket and may need to reach a remote engine. |

### `[Service]` Section

| Directive          | Value                                                              | Description                                                                                     |
|--------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| `Type`             | `simple`                                                           | The process started by `ExecStart` is the main service process. systemd considers the service started immediately. |
| `User`             | `diapason`                                                       | Runs the server as the `diapason` user rather than root, limiting the blast radius of any security issue. |
| `WorkingDirectory` | `/opt/diapason`                                                  | Sets the working directory for the process. This is where Diapason looks for local files and writes data. |
| `ExecStart`        | `/opt/diapason/.venv/bin/diapason serve --host 0.0.0.0 --port 8000` | The command to start the server. Uses the full path to the `diapason` binary inside the virtual environment. |
| `Restart`          | `on-failure`                                                       | Automatically restarts the service if it exits with a non-zero exit code. Does not restart on clean shutdown (`systemctl stop`). |
| `RestartSec`       | `5`                                                                | Waits 5 seconds before attempting a restart, preventing rapid restart loops if the service crashes immediately on startup. |
| `Environment`      | `HOME=/opt/diapason`                                             | Sets the `HOME` environment variable so Diapason finds its configuration at `~/.diapason/config.toml` (resolving to `/opt/diapason/.diapason/config.toml`). |

### `[Install]` Section

| Directive    | Value               | Description                                                                                 |
|--------------|---------------------|---------------------------------------------------------------------------------------------|
| `WantedBy`   | `multi-user.target` | The service starts when the system reaches multi-user mode (standard boot target for servers). `systemctl enable` creates a symlink under this target. |

## Configuration Options

### Changing the Bind Address and Port

Edit the `ExecStart` line to change the host or port:

```ini
ExecStart=/opt/diapason/.venv/bin/diapason serve --host 127.0.0.1 --port 9000
```

!!! tip
    Binding to `127.0.0.1` restricts access to localhost only. Use this when running behind a reverse proxy like Nginx or Caddy.

### Setting the Engine and Model

Pass additional flags to `diapason serve`:

```ini
ExecStart=/opt/diapason/.venv/bin/diapason serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b
```

### Adding Environment Variables

Add multiple `Environment` directives or use `EnvironmentFile` for complex configurations:

```ini
[Service]
Environment=HOME=/opt/diapason
Environment=OPENJARVIS_ENGINE_DEFAULT=vllm
Environment=OPENJARVIS_OLLAMA_HOST=http://localhost:11434
```

Or load from a file:

```ini
[Service]
EnvironmentFile=/opt/diapason/.env
```

### Changing the User

If you prefer a different service user, update both the `User` directive and the paths:

```ini
[Service]
User=myuser
WorkingDirectory=/home/myuser/diapason
ExecStart=/home/myuser/diapason/.venv/bin/diapason serve --host 0.0.0.0 --port 8000
Environment=HOME=/home/myuser/diapason
```

### Using a Configuration File

Ensure the configuration file exists at the path where `HOME` points:

```bash
sudo -u diapason mkdir -p /opt/diapason/.diapason
sudo -u diapason cp config.toml /opt/diapason/.diapason/config.toml
```

The server reads `~/.diapason/config.toml` on startup, where `~` resolves from the `HOME` environment variable.

## Viewing Logs

Diapason logs are captured by journald. View them with `journalctl`:

```bash
# View all logs for the service
sudo journalctl -u diapason

# Follow logs in real time
sudo journalctl -u diapason -f

# View logs since the last boot
sudo journalctl -u diapason -b

# View logs from the last hour
sudo journalctl -u diapason --since "1 hour ago"

# View only error-level messages
sudo journalctl -u diapason -p err
```

## Managing the Service

### Start, Stop, and Restart

```bash
# Start the service
sudo systemctl start diapason

# Stop the service
sudo systemctl stop diapason

# Restart the service (stop + start)
sudo systemctl restart diapason

# Reload configuration without full restart (sends SIGHUP)
sudo systemctl reload-or-restart diapason
```

### Check Status

```bash
sudo systemctl status diapason
```

Example output:

```
● diapason.service - Diapason API Server
     Loaded: loaded (/etc/systemd/system/diapason.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-02-21 10:00:00 UTC; 2h ago
   Main PID: 12345 (diapason)
      Tasks: 4 (limit: 4915)
     Memory: 256.0M
        CPU: 1min 23s
     CGroup: /system.slice/diapason.service
             └─12345 /opt/diapason/.venv/bin/python /opt/diapason/.venv/bin/diapason serve --host 0.0.0.0 --port 8000
```

### Enable and Disable on Boot

```bash
# Enable automatic start on boot
sudo systemctl enable diapason

# Disable automatic start on boot
sudo systemctl disable diapason
```

### Apply Changes After Editing the Unit File

After modifying `/etc/systemd/system/diapason.service`, reload the systemd daemon and restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart diapason
```

## Running Alongside Ollama

If Ollama is also managed via systemd, you can add an ordering dependency so the Diapason service waits for Ollama to start:

```ini
[Unit]
Description=Diapason API Server
After=network.target ollama.service
Requires=ollama.service
```

| Directive  | Description                                                              |
|------------|--------------------------------------------------------------------------|
| `After`    | Ensures Diapason starts after Ollama.                                  |
| `Requires` | If Ollama fails to start, Diapason will not start either.              |

!!! note
    Use `Wants` instead of `Requires` if you want Diapason to start even when Ollama is unavailable (for example, if you plan to start Ollama manually later).
