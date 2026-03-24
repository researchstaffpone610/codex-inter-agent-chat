from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None  # type: ignore[assignment]

from . import cli as base_cli
from . import registry

TEAM_SESSION_DEVELOPER_APPEND = """
[codex-team team-session override]
When running under codex-team, these rules override any generic instruction that says to ask a question before answering.

For inter-agent requests:
- First run `codex-team list`.
- If the requested peer exists in the live roster, immediately run `codex-team send --to <agent> --message "..."`.
- Do not ask whether the peer should be started or registered if it is already present in the live roster.

For demo / showcase / “show what you can do” requests with at least one live peer present:
- Treat the request itself as permission to perform a real live exchange.
- Do not ask walkthrough-vs-live.
- Do not ask which capability to highlight before the first live exchange.
- Your first visible action should be command-oriented, not a clarifying question.

For incoming inter-agent traffic:
- If you receive `[@yourName] (from sender) ...` and the message is clearly asking for a reply, an ack, an exact token/string, or the next protocol turn, reply to that sender with `codex-team send --to <sender> --message "..."`.
- Do not satisfy those inter-agent reply requests by only printing the reply inline in your own pane.
- Do not over-apply this rule to normal local narration or messages intended for the human.
"""


def _json_dump(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _sanitize_token(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "-" for char in str(value or ""))


def _default_agent_name() -> str:
    env_name = os.environ.get("AGENT_NAME")
    if env_name:
        return registry.sanitize_agent_name(env_name)

    session_context = registry.read_session_context()
    if session_context is not None:
        return registry.sanitize_agent_name(session_context.agent_name)

    base_name = _sanitize_token(Path.cwd().name or "codex-agent") or "codex-agent"
    tmux_pane = os.environ.get("TMUX_PANE", "")
    if tmux_pane:
        pane_id = _sanitize_token(tmux_pane.lstrip("%")) or "0"
        return registry.sanitize_agent_name(f"{base_name}-pane-{pane_id}")
    return registry.sanitize_agent_name(base_name)


def _resolve_team(team: str | None) -> str:
    if team:
        return registry.sanitize_team_name(team)
    env_team = os.environ.get(registry.ENV_TEAM)
    if env_team:
        return registry.sanitize_team_name(env_team)
    session_context = registry.read_session_context()
    if session_context is not None:
        return registry.sanitize_team_name(session_context.team)
    inferred_team = registry.infer_team_from_registry(os.environ.get("AGENT_NAME"))
    if inferred_team:
        return inferred_team
    return registry.DEFAULT_TEAM_NAME


def _resolve_registry_dir(team: str, registry_dir: str | None, *, use_session_context: bool) -> str:
    if registry_dir:
        return str(Path(registry_dir).expanduser().resolve())
    env_registry = os.environ.get(registry.ENV_REGISTRY_DIR)
    if env_registry:
        return str(Path(env_registry).expanduser().resolve())
    session_context = registry.read_session_context() if use_session_context else None
    if session_context is not None and session_context.team == team:
        return str(Path(session_context.registry_dir).expanduser().resolve())
    return str(registry.default_registry_root() / team)


def _apply_team_env(*, team: str | None, registry_dir: str | None, agent_name: str | None) -> dict[str, str]:
    effective_team = _resolve_team(team)
    effective_registry_dir = _resolve_registry_dir(
        effective_team,
        registry_dir,
        use_session_context=(team is None and registry_dir is None),
    )
    payload = {
        registry.ENV_ENABLE: "1",
        registry.ENV_TEAM: effective_team,
        registry.ENV_REGISTRY_DIR: effective_registry_dir,
    }
    if agent_name:
        payload["AGENT_NAME"] = registry.sanitize_agent_name(agent_name)
    elif "AGENT_NAME" not in os.environ:
        payload["AGENT_NAME"] = _default_agent_name()
    os.environ.update(payload)
    return payload


def _config_path() -> Path:
    return registry.codex_home_dir() / "config.toml"


def _load_base_developer_instructions() -> str:
    path = _config_path()
    if not path.exists():
        return ""
    raw = path.read_text()
    if tomllib is not None:
        try:
            data = tomllib.loads(raw)
        except Exception:
            data = None
        if isinstance(data, dict):
            value = data.get("developer_instructions")
            return str(value) if value is not None else ""

    for pattern in (
        r'(?ms)^[ \t]*developer_instructions[ \t]*=[ \t]*"""(.*?)"""[ \t]*$',
        r"(?ms)^[ \t]*developer_instructions[ \t]*=[ \t]*'''(.*?)'''[ \t]*$",
        r'(?m)^[ \t]*developer_instructions[ \t]*=[ \t]*"(.*)"[ \t]*$',
        r"(?m)^[ \t]*developer_instructions[ \t]*=[ \t]*'(.*)'[ \t]*$",
    ):
        match = re.search(pattern, raw)
        if match:
            return match.group(1)
    return ""


def _compose_team_developer_instructions() -> str:
    base = _load_base_developer_instructions().rstrip()
    appendix = TEAM_SESSION_DEVELOPER_APPEND.strip()
    if not base:
        return appendix
    if appendix in base:
        return base
    return f"{base}\n\n{appendix}\n"


def cmd_start(args: argparse.Namespace) -> int:
    payload = _apply_team_env(
        team=args.team,
        registry_dir=args.registry_dir,
        agent_name=args.agent_name,
    )
    payload["codex_bin"] = args.codex_bin

    if args.print_env:
        _json_dump(
            {
                "enabled": payload[registry.ENV_ENABLE],
                "team": payload[registry.ENV_TEAM],
                "registry_dir": payload[registry.ENV_REGISTRY_DIR],
                "agent_name": os.environ.get("AGENT_NAME"),
                "codex_bin": args.codex_bin,
            }
        )
        return 0

    codex_path = shutil.which(args.codex_bin)
    if not codex_path:
        _json_dump({"success": False, "error": f"codex binary not found: {args.codex_bin}"})
        return 127

    try:
        registry.register_agent(
            agent_name=os.environ.get("AGENT_NAME"),
            registry_dir=payload[registry.ENV_REGISTRY_DIR],
            cwd=str(Path.cwd().resolve()),
            pid=os.getpid(),
        )
    except registry.RegistryError:
        pass

    codex_argv = [
        args.codex_bin,
        "-c",
        f"developer_instructions={json.dumps(_compose_team_developer_instructions())}",
        *args.codex_args,
    ]
    os.execvpe(codex_path, codex_argv, os.environ)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    _apply_team_env(team=args.team, registry_dir=args.registry_dir, agent_name=None)
    return int(base_cli.main(["list"]))


def cmd_capability(args: argparse.Namespace) -> int:
    if args.team or args.registry_dir:
        _apply_team_env(team=args.team, registry_dir=args.registry_dir, agent_name=None)
    return int(base_cli.main(["capability"]))


def cmd_whoami(args: argparse.Namespace) -> int:
    payload = _apply_team_env(team=args.team, registry_dir=args.registry_dir, agent_name=args.agent_name)
    _json_dump(
        {
            "enabled": payload[registry.ENV_ENABLE],
            "team": payload[registry.ENV_TEAM],
            "registry_dir": payload[registry.ENV_REGISTRY_DIR],
            "agent_name": os.environ.get("AGENT_NAME"),
            "thread_id": os.environ.get(registry.ENV_THREAD_ID),
        }
    )
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    sender_name = args.sender_name or args.agent_name
    _apply_team_env(team=args.team, registry_dir=args.registry_dir, agent_name=sender_name)
    argv = ["send"]
    for target in args.to:
        argv.extend(["--to", target])
    if args.message is not None:
        argv.extend(["--message", args.message])
    if args.raw is not None:
        argv.extend(["--raw", args.raw])
    if sender_name is not None:
        argv.extend(["--sender-name", sender_name])
    if args.dry_run:
        argv.append("--dry-run")
    if args.no_submit:
        argv.append("--no-submit")
    if args.per_char_delay != 0.0:
        argv.extend(["--per-char-delay", str(args.per_char_delay)])
    return int(base_cli.main(argv))


def cmd_unregister(args: argparse.Namespace) -> int:
    _apply_team_env(team=args.team, registry_dir=args.registry_dir, agent_name=None)
    return int(base_cli.main(["unregister", args.agent_name]))


def _add_team_options(parser: argparse.ArgumentParser, *, include_agent_name: bool = False) -> None:
    parser.add_argument("--team")
    parser.add_argument("--registry-dir")
    if include_agent_name:
        parser.add_argument("--agent-name")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-team",
        description="Team-scoped Codex launcher and inter-agent chat CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Start a Codex session with team-scoped chat enabled")
    _add_team_options(start_parser, include_agent_name=True)
    start_parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    start_parser.add_argument("--print-env", action="store_true")
    start_parser.add_argument("codex_args", nargs=argparse.REMAINDER)
    start_parser.set_defaults(func=cmd_start)

    list_parser = subparsers.add_parser("list", help="List registered agents in a team")
    _add_team_options(list_parser)
    list_parser.set_defaults(func=cmd_list)

    capability_parser = subparsers.add_parser("capability", help="Show transport capability")
    _add_team_options(capability_parser)
    capability_parser.set_defaults(func=cmd_capability)

    whoami_parser = subparsers.add_parser("whoami", help="Show resolved session identity")
    _add_team_options(whoami_parser, include_agent_name=True)
    whoami_parser.set_defaults(func=cmd_whoami)

    send_parser = subparsers.add_parser("send", help="Send a message to one or more agents in a team")
    _add_team_options(send_parser, include_agent_name=True)
    send_parser.add_argument("--to", action="append", required=True)
    send_parser.add_argument("--message")
    send_parser.add_argument("--raw")
    send_parser.add_argument("--sender-name")
    send_parser.add_argument("--dry-run", action="store_true")
    send_parser.add_argument("--no-submit", action="store_true")
    send_parser.add_argument("--per-char-delay", type=float, default=0.0)
    send_parser.set_defaults(func=cmd_send)

    unregister_parser = subparsers.add_parser("unregister", help="Remove an agent registration from a team")
    _add_team_options(unregister_parser)
    unregister_parser.add_argument("agent_name")
    unregister_parser.set_defaults(func=cmd_unregister)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    known_commands = {"start", "list", "send", "capability", "whoami", "unregister"}
    if not argv or argv[0] not in known_commands:
        argv = ["start", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
