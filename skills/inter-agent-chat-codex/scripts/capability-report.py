#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap() -> None:
    root = Path(__file__).resolve().parents[3]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def main() -> int:
    _bootstrap()
    from codex_inter_agent_chat.team_cli import main as team_main

    return int(team_main(["capability", *sys.argv[1:]]))


if __name__ == "__main__":
    raise SystemExit(main())
