# API Reference

Base URL: `http://127.0.0.1:8765`

Auth: `Authorization: Bearer TOKEN` (required if `AGENTMUX_TOKEN` is set)

## Endpoints

| Method | Path | Body / Query | Description |
|--------|------|--------------|-------------|
| GET | `/health` | — | Full bridge status with all sessions |
| GET | `/sessions` | — | List tracked sessions |
| GET | `/idle` | — | Active session idle state + ctx% |
| GET | `/capture` | `?lines=60&target=...` | tmux pane output |
| POST | `/run` | `{"text":"..."}` | Create new session and send text |
| POST | `/send` | `{"text":"...","target?":"..."}` | Send literal text |
| POST | `/key` | `{"key":"enter","repeat?":1}` | Send special key |
| POST | `/restart` | `{}` | Kill active session and start fresh |
| POST | `/cleanup` | `{}` | Kill all idle old sessions |
| POST | `/kill` | `{"session":"name"}` | Kill specific session |

## Notes

- `/run` returns `409 Conflict` if the active session is busy. Poll `/idle` until `"idle": true` before retrying.
- `/run` and `/restart` return `503 Service Unavailable` if the newly created session never becomes ready.
- `/send`, `/key`, `/capture`, `/idle` return `404` when there is no active session and no `target` is provided.
- Invalid JSON, invalid integer fields, unsupported explicit targets, and other bad inputs return `400 Bad Request`.
