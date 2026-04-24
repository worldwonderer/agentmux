# AgentMux

[![CI](https://github.com/worldwonderer/agentmux/actions/workflows/ci.yml/badge.svg)](https://github.com/worldwonderer/agentmux/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A robust HTTP bridge for managing **AI agent REPL** sessions via `tmux` on macOS.

- Keep multiple agent sessions alive inside `tmux` (Claude, Codex, GLM, etc.)
- Send prompts and special keys via a local HTTP API
- Ideal for long-running or scheduled agent tasks, avoiding rate limits from repeated `claude -p` style invocations
- Integrates with macOS `LaunchAgent`, cron, or custom schedulers

---

## Features

- **Multi-session management** – Each task gets a fresh agent context without killing old sessions
- **Idle detection** – Automatically detect when the agent is ready for the next prompt
- **Auto-cleanup** – Remove idle old sessions when approaching the session limit
- **Bearer token auth** – Secure the local HTTP API with an optional token
- **Zero third-party runtime dependencies** – Only needs Python 3.10+ and `tmux`

---

## Requirements

- macOS (tested on macOS 14+)
- Python 3.10 or newer
- `tmux` installed and available in `PATH`
- An AI agent CLI available in `PATH` (e.g. `claude`, `codex`, etc.)

---

## Installation

### From source

```bash
git clone https://github.com/worldwonderer/agentmux.git
cd agentmux
pip install -e ".[dev]"
```

### Via pip (when published)

```bash
pip install agentmux
```

<details>
<summary>Installing the latest dev build</summary>

```bash
pip install agentmux --pre --index-url https://test.pypi.org/simple/
```

</details>

---

## Quick Start

### 1. Start the bridge server

```bash
agentmux serve
# or
python -m agentmux serve
```

### 2. Send a message

```bash
curl -s \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"text":"Check for failing tests and summarize"}' \
  http://127.0.0.1:8765/run
```

### 3. Check bridge health

```bash
curl -s \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  http://127.0.0.1:8765/health
```

### 4. Capture recent output

```bash
curl -s \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  'http://127.0.0.1:8765/capture?lines=80'
```

---

## Configuration

All settings are controlled via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTMUX_HOST` | `127.0.0.1` | HTTP server bind address |
| `AGENTMUX_PORT` | `8765` | HTTP server port |
| `AGENTMUX_TOKEN` | *(empty)* | Bearer token for API auth |
| `AGENTMUX_SESSION` | `agentmux` | tmux session name prefix |
| `AGENTMUX_WINDOW` | `repl` | tmux window name |
| `AGENTMUX_WORKDIR` | `$HOME` | Working directory for new sessions |
| `AGENTMUX_REPL_CMD` | `claude` | Command to launch the agent REPL |
| `AGENTMUX_STARTUP_DELAY` | `3.0` | Seconds to wait after launching the REPL |
| `AGENTMUX_LOG_FILE` | `~/.agentmux/agentmux.log` | Path to bridge log file |

---

## API Reference

### GET

| Endpoint | Description |
|----------|-------------|
| `/health` | Full bridge status including all sessions |
| `/capture?lines=60&target=...` | Capture recent tmux pane output (explicit `target` must be managed unless external targets are enabled) |
| `/idle` | Check if active session is idle + ctx% |
| `/sessions` | List all tracked sessions |

### POST

| Endpoint | Body | Description |
|----------|------|-------------|
| `/send` | `{"text":"...","target?":"..."}` | Send literal text to a session (explicit `target` must be managed unless external targets are enabled) |
| `/run` | `{"text":"..."}` | Create a new session, wait for ready, then send text |
| `/key` | `{"key":"enter","repeat?":1}` | Send special key |
| `/restart` | `{}` | Create a fresh ready session, then replace the active one |
| `/cleanup` | `{}` | Kill all idle old sessions |
| `/kill` | `{"session":"name"}` | Kill a specific session |

---

## macOS LaunchAgent

Copy and customize the provided plist template:

```bash
cp contrib/macos-launchagent.plist ~/Library/LaunchAgents/com.yourname.agentmux.plist
# Edit paths and token in the plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.yourname.agentmux.plist
launchctl kickstart -k gui/$(id -u)/com.yourname.agentmux
```

---

## Development

```bash
# Install in editable mode with dev dependencies
make install

# Run tests
make test

# Run linter
make lint

# Auto-format code
make format

# Type check
make type-check

# Coverage report
make coverage
```

### Running integration tests

Integration tests require a live `tmux` installation and are skipped by default:

```bash
pytest -m integration
```

---

## Architecture

```
┌─────────────┐     HTTP      ┌─────────────────┐     subprocess     ┌────────┐
│  Scheduler  │ ◄────────────► │    agentmux     │ ◄────────────────► │  tmux  │
│   / Cron    │   127.0.0.1   │   HTTP server   │    send-keys/      │sessions│
│  / LaunchAgent│              │                 │    capture-pane    └────┬───┘
└─────────────┘                └─────────────────┘                         │
                                                                           │
                                                                    ┌──────┴──────┐
                                                                    │  AI Agent   │
                                                                    │   (repl)    │
                                                                    └─────────────┘
```

### Module layout

| Module | Responsibility |
|--------|--------------|
| `config.py` | Environment-based configuration + logging setup |
| `session.py` | Thread-safe session registry (`SessionManager`) |
| `tmux.py` | All tmux subprocess operations (`TmuxController`) |
| `server.py` | HTTP API handler and server lifecycle |
| `cli.py` | Argument parsing and command dispatch |

---

## License

MIT – see [LICENSE](LICENSE).


