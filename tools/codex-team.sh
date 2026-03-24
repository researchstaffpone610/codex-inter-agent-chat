#!/usr/bin/env bash
set -euo pipefail

pick_python_bin() {
  local -a candidates=()
  local candidate=""
  local resolved=""

  if [[ -n "${PYTHON_BIN:-}" ]]; then
    candidates+=("$PYTHON_BIN")
  fi

  candidates+=(
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3"
    "python3.14"
    "python3.13"
    "python3.12"
    "python3.11"
    "python3.10"
    "python3"
    "python"
  )

  for candidate in "${candidates[@]}"; do
    [[ -n "$candidate" ]] || continue
    if [[ -x "$candidate" ]]; then
      resolved="$candidate"
    else
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
    fi
    [[ -n "$resolved" ]] || continue
    if "$resolved" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
    then
      printf '%s\n' "$resolved"
      return 0
    fi
  done

  echo "codex-team requires Python >= 3.10. Set PYTHON_BIN to a compatible interpreter." >&2
  return 1
}

PYTHON_BIN="$(pick_python_bin)"
SCRIPT_PATH="$("$PYTHON_BIN" - "$0" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

exec "$PYTHON_BIN" -m codex_inter_agent_chat.team_cli "$@"
