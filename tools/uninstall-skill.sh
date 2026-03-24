#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
DEST_DIR="$CODEX_HOME_DIR/skills/inter-agent-chat-codex"
SRC_DIR="$ROOT_DIR/skills/inter-agent-chat-codex"
LAUNCHER_NAME="codex-team"
LAUNCHER_SRC="$ROOT_DIR/tools/codex-team.sh"
SKILL_REMOVED=0

remove_link_if_matches() {
  local candidate="$1"
  local expected_target="$2"
  local label="$3"

  if [[ -L "$candidate" ]]; then
    local target
    target="$(readlink "$candidate" || true)"
    if [[ "$target" == "$expected_target" ]]; then
      rm -f "$candidate"
      echo "Removed $label symlink:"
      echo "  $candidate"
      return 0
    fi
  fi
  return 1
}

if remove_link_if_matches "$DEST_DIR" "$SRC_DIR" "skill"; then
  SKILL_REMOVED=1
fi

if [[ "$SKILL_REMOVED" == "0" && -e "$DEST_DIR" ]]; then
  echo "Refusing to remove non-matching path:"
  echo "  $DEST_DIR"
  exit 1
fi

if [[ "$SKILL_REMOVED" == "0" ]]; then
  echo "Skill symlink not present:"
  echo "  $DEST_DIR"
fi

if command -v "$LAUNCHER_NAME" >/dev/null 2>&1; then
  remove_link_if_matches "$(command -v "$LAUNCHER_NAME")" "$LAUNCHER_SRC" "launcher" || true
fi

for candidate in \
  "$HOME/.local/bin/$LAUNCHER_NAME" \
  "$HOME/bin/$LAUNCHER_NAME" \
  "$CODEX_HOME_DIR/bin/$LAUNCHER_NAME" \
  "/opt/homebrew/bin/$LAUNCHER_NAME" \
  "/usr/local/bin/$LAUNCHER_NAME"
do
  remove_link_if_matches "$candidate" "$LAUNCHER_SRC" "launcher" || true
done
