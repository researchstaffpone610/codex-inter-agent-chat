#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def _bootstrap() -> None:
    root = Path(__file__).resolve().parents[3]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _hook_output(message: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": message,
                }
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    _bootstrap()
    from codex_inter_agent_chat import registry
    from codex_inter_agent_chat.cli import main as cli_main

    if not registry.inter_agent_chat_enabled():
        _hook_output(
            "Codex inter-agent chat is disabled for this session. Start Codex through codex-team to enable it explicitly."
        )
        return 0

    return int(cli_main(["register", "--hook-json", *sys.argv[1:]]))


if __name__ == "__main__":
    raise SystemExit(main())
