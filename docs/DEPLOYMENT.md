# Deployment

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTMUX_HOST` | `127.0.0.1` | Bind address |
| `AGENTMUX_PORT` | `8765` | Port |
| `AGENTMUX_TOKEN` | — | Bearer token (strongly recommended) |
| `AGENTMUX_REPL_CMD` | `claude` | REPL command (e.g. `claude`, `codex`) |
| `AGENTMUX_WORKDIR` | `$HOME` | Working directory for new sessions |
| `AGENTMUX_STARTUP_DELAY` | `3.0` | Seconds to wait after launching the REPL |

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
Environment=AGENTMUX_REPL_CMD=claude

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
