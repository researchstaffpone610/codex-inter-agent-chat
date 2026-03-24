#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
DEST_DIR="$CODEX_HOME_DIR/skills/inter-agent-chat-codex"
SRC_DIR="$ROOT_DIR/skills/inter-agent-chat-codex"
LAUNCHER_SRC="$ROOT_DIR/tools/codex-team.sh"
LAUNCHER_NAME="codex-team"
MARKER_BEGIN="# >>> codex-inter-agent-chat PATH >>>"
MARKER_END="# <<< codex-inter-agent-chat PATH <<<"

pick_launcher_dir() {
  if command -v codex >/dev/null 2>&1; then
    local codex_dir
    codex_dir="$(dirname "$(command -v codex)")"
    if [[ -w "$codex_dir" ]]; then
      printf '%s\n' "$codex_dir"
      return 0
    fi
  fi

  for candidate in "$HOME/.local/bin" "$HOME/bin" "$CODEX_HOME_DIR/bin"; do
    mkdir -p "$candidate"
    if [[ -w "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  echo "failed to find a writable launcher directory" >&2
  exit 1
}

ensure_path_entry() {
  local target_dir="$1"
  local rc_file="$HOME/.zshrc"

  case ":$PATH:" in
    *":$target_dir:"*) return 0 ;;
  esac

  touch "$rc_file"
  if grep -Fq "$MARKER_BEGIN" "$rc_file"; then
    return 0
  fi

  cat >> "$rc_file" <<EOF

$MARKER_BEGIN
export PATH="$target_dir:\$PATH"
$MARKER_END
EOF
}

mkdir -p "$(dirname "$DEST_DIR")"
ln -sfn "$SRC_DIR" "$DEST_DIR"

LAUNCHER_DIR="$(pick_launcher_dir)"
LAUNCHER_DEST="$LAUNCHER_DIR/$LAUNCHER_NAME"
ln -sfn "$LAUNCHER_SRC" "$LAUNCHER_DEST"
chmod +x "$LAUNCHER_SRC"
ensure_path_entry "$LAUNCHER_DIR"

echo "Installed skill symlink:"
echo "  $DEST_DIR -> $SRC_DIR"
echo "Installed launcher symlink:"
echo "  $LAUNCHER_DEST -> $LAUNCHER_SRC"
echo "Launcher behavior:"
echo "  codex-team inherits your normal codex config/MCP/skills and only appends team-specific environment."
if ! command -v codex-team >/dev/null 2>&1; then
  echo "Note:"
  echo "  codex-team was installed, but your current shell may need: source ~/.zshrc"
fi
