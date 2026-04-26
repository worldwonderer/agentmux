#!/bin/bash
# agentmux-submit.sh — Send prompt to agentmux, wait for completion
#
# Usage:
#   agentmux-submit.sh --prompt "text" [--output FILE] [--timeout SECONDS]
#   echo "prompt" | agentmux-submit.sh [--output FILE]
#
# Flow:
#   1. POST /run — creates new session, sends prompt
#   2. Poll GET /idle until agent finishes
#   3. If --output: verify file written by agent
#      Else: capture tmux pane and print to stdout
set -euo pipefail

AGENTMUX_URL="${AGENTMUX_URL:-http://127.0.0.1:8765}"
TOKEN="${AGENTMUX_TOKEN:-}"
TIMEOUT="${AGENTMUX_TIMEOUT:-600}"
PROMPT=""
OUTPUT_FILE=""
POLL_INTERVAL="${AGENTMUX_POLL_INTERVAL:-10}"
IDLE_STABLE_COUNT="${AGENTMUX_IDLE_STABLE_COUNT:-3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)       AGENTMUX_URL="$2"; shift 2 ;;
    --token)     TOKEN="$2"; shift 2 ;;
    --timeout)   TIMEOUT="$2"; shift 2 ;;
    --prompt)    PROMPT="$2"; shift 2 ;;
    --output)    OUTPUT_FILE="$2"; shift 2 ;;
    --poll-interval) POLL_INTERVAL="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: agentmux-submit.sh --prompt TEXT [--output FILE] [--timeout SEC]"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$PROMPT" ]] && PROMPT=$(cat)
[[ -z "$PROMPT" ]] && { echo "Error: No prompt provided" >&2; exit 1; }

AUTH_ARGS=()
[[ -n "$TOKEN" ]] && AUTH_ARGS+=(-H "Authorization: Bearer $TOKEN")

# JSON-encode safely
PAYLOAD=$(python3 -c "import json,sys; print(json.dumps({'text':sys.stdin.read()}))" <<< "$PROMPT")

# ── 1. Submit ──────────────────────────────────────────────
RUN_RESP=$(curl -sf -X POST "$AGENTMUX_URL/run" \
  "${AUTH_ARGS[@]}" \
  -H "Content-Type: application/json" \
  --data-binary "$PAYLOAD" 2>&1) || {
  echo "Error: Cannot reach agentmux at $AGENTMUX_URL" >&2
  echo "$RUN_RESP" >&2; exit 1
}

OK=$(echo "$RUN_RESP" | jq -r '.ok')
if [[ "$OK" != "true" ]]; then
  BUSY=$(echo "$RUN_RESP" | jq -r '.busy // false')
  if [[ "$BUSY" == "true" ]]; then
    echo "Error: Agent is busy" >&2
  else
    echo "Error: /run failed: $RUN_RESP" >&2
  fi
  exit 1
fi

SESSION=$(echo "$RUN_RESP" | jq -r '.session')
echo "[agentmux] sent → $SESSION" >&2

# ── 2. Poll idle (require N consecutive idle=true to confirm) ──
ELAPSED=0
CONSECUTIVE_IDLE=0
while [[ $ELAPSED -lt $TIMEOUT ]]; do
  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))

  IDLE_RESP=$(curl -sf "${AUTH_ARGS[@]}" "$AGENTMUX_URL/idle" 2>/dev/null) || {
    CONSECUTIVE_IDLE=0
    continue
  }
  IDLE=$(echo "$IDLE_RESP" | jq -r '.idle')

  if [[ "$IDLE" == "true" ]]; then
    CONSECUTIVE_IDLE=$((CONSECUTIVE_IDLE + 1))
    if [[ $CONSECUTIVE_IDLE -ge $IDLE_STABLE_COUNT ]]; then
      echo "[agentmux] done (${ELAPSED}s, session: $SESSION, stable after ${CONSECUTIVE_IDLE} checks)" >&2

      # ── 3. Retrieve output ──────────────────────────────
      if [[ -n "$OUTPUT_FILE" && -s "$OUTPUT_FILE" ]]; then
        echo "[agentmux] output → $OUTPUT_FILE" >&2
      elif [[ -n "$OUTPUT_FILE" ]]; then
        CAPTURE=$(curl -sf "${AUTH_ARGS[@]}" "$AGENTMUX_URL/capture?lines=500" 2>/dev/null || true)
        if [[ -n "$CAPTURE" ]]; then
          echo "$CAPTURE" | jq -r '.content' > "$OUTPUT_FILE" 2>/dev/null || true
        fi
        echo "[agentmux] captured pane → $OUTPUT_FILE" >&2
      else
        CAPTURE=$(curl -sf "${AUTH_ARGS[@]}" "$AGENTMUX_URL/capture?lines=500" 2>/dev/null || true)
        if [[ -n "$CAPTURE" ]]; then
          echo "$CAPTURE" | jq -r '.content'
        fi
      fi
      exit 0
    fi
  else
    CONSECUTIVE_IDLE=0
  fi

  (( ELAPSED % 30 == 0 )) && {
    CTX=$(echo "$IDLE_RESP" | jq -r '.ctx_percent // "?"')
    echo "[agentmux] waiting... ${ELAPSED}s, ctx: ${CTX}%" >&2
  }
done

echo "Error: Timeout (${TIMEOUT}s)" >&2
exit 1
