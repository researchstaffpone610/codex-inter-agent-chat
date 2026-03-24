#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REGISTRY_DIR="$(mktemp -d "${TMPDIR:-/tmp}/codex-inter-agent-chat-demo.XXXXXX")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DEVICE_A="${DEVICE_A:-/dev/ttys040}"
DEVICE_B="${DEVICE_B:-/dev/ttys041}"
TEAM_NAME="${TEAM_NAME:-demo}"

cleanup() {
  rm -rf "$REGISTRY_DIR"
}
trap cleanup EXIT

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export CODEX_INTER_AGENT_CHAT_ENABLE=1
export CODEX_INTER_AGENT_CHAT_TEAM="$TEAM_NAME"
export CODEX_INTER_AGENT_CHAT_REGISTRY_DIR="$REGISTRY_DIR"

echo "== register demo agents =="
"$PYTHON_BIN" -m codex_inter_agent_chat.cli register \
  --agent-name agent-a \
  --device "$DEVICE_A" \
  --registry-dir "$REGISTRY_DIR" >/dev/null
"$PYTHON_BIN" -m codex_inter_agent_chat.cli register \
  --agent-name agent-b \
  --device "$DEVICE_B" \
  --registry-dir "$REGISTRY_DIR" >/dev/null

echo "== capability report =="
"$PYTHON_BIN" -m codex_inter_agent_chat.cli capability

echo "== registry contents =="
"$PYTHON_BIN" -m codex_inter_agent_chat.cli list --registry-dir "$REGISTRY_DIR"

echo "== dry-run agent-a -> agent-b =="
"$PYTHON_BIN" -m codex_inter_agent_chat.cli send \
  --to agent-b \
  --sender-name agent-a \
  --registry-dir "$REGISTRY_DIR" \
  --message "status check" \
  --dry-run

echo "Demo complete."
echo "For real terminals, start both sessions through codex-team with the same --team, then repeat send without --dry-run."
