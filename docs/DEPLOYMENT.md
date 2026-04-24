# Deployment

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTMUX_HOST` | `127.0.0.1` | Bind address |
| `AGENTMUX_PORT` | `8765` | Port |
| `AGENTMUX_TOKEN` | — | Bearer token (strongly recommended) |
| `AGENTMUX_AGENT` | `claude` | Agent type: `claude` or `codex` |
| `AGENTMUX_REPL_CMD` | *(profile default)* | REPL command (overrides profile default) |
| `AGENTMUX_WORKDIR` | `$HOME` | Working directory for new sessions |
| `AGENTMUX_STARTUP_DELAY` | *(profile default)* | Seconds to wait after launching the REPL (overrides profile default) |

### Agent defaults

| Agent | REPL command | Startup delay |
|-------|-------------|---------------|
| `claude` | `claude` | 3.0s |
| `codex` | `codex --no-alt-screen --full-auto` | 5.0s |

## macOS LaunchAgent

```bash
cp contrib/macos-launchagent.plist ~/Library/LaunchAgents/com.yourname.agentmux.plist
# Edit token and paths in the plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.yourname.agentmux.plist
```

Unload: `launchctl bootout gui/$(id -u)/com.yourname.agentmux`

## systemd (Linux)

Create `/etc/systemd/system/agentmux.service`:

```ini
[Unit]
Description=AgentMux HTTP Bridge
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m agentmux serve
Restart=always
Environment=AGENTMUX_TOKEN=your-token
Environment=AGENTMUX_AGENT=claude

[Install]
WantedBy=multi-user.target
```

Then: `sudo systemctl daemon-reload && sudo systemctl enable --now agentmux`

## Manual

```bash
AGENTMUX_TOKEN=my-token agentmux serve
```

## Security

- Set a strong `AGENTMUX_TOKEN`.
- Keep the default bind `127.0.0.1`. Do not expose to the internet without TLS.
