from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import registry, transport


def _json_dump(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_register(args: argparse.Namespace) -> int:
    record = registry.register_agent(
        agent_name=args.agent_name,
        device_path=args.device,
        registry_dir=args.registry_dir,
        cwd=args.cwd,
        pid=args.pid,
    )
    effective_team = registry.current_team()
    effective_registry_dir = str(registry.ensure_registry_dir(args.registry_dir).resolve())
    registry.write_session_context(
        team=effective_team,
        registry_dir=effective_registry_dir,
        agent_name=record.agent_name,
    )
    if args.hook_json:
        current_records = registry.list_records(effective_registry_dir)
        known_agents = sorted({item.agent_name for item in current_records})
        other_agents = [name for name in known_agents if name != record.agent_name]
        known_agents_text = ", ".join(known_agents) if known_agents else "-"
        other_agents_text = ", ".join(other_agents) if other_agents else "-"
        additional_context = "\n".join(
            [
                "Codex inter-agent chat ready.",
                f"team={effective_team}",
                f"agent_name={record.agent_name}",
                f"registry_dir={effective_registry_dir}",
                f"device={record.device_path}",
                f"tmux_pane={record.tmux_pane or '-'}",
                f"tmux_socket={record.tmux_socket or '-'}",
                f"known_agents={known_agents_text}",
                f"other_agents={other_agents_text}",
                "",
                "Runtime rules:",
                "- Use live registry state, not user wording heuristics.",
                "- For any inter-agent request, first run `codex-team list`.",
                "- If the requested target exists in that live list, immediately run `codex-team send --to <agent> --message \"...\"`.",
                "- Do not ask whether another agent needs to be started or registered unless `codex-team list` fails or the target is absent from the live registry.",
                "- For demo/showcase requests with a live peer present, the request itself is permission for a real exchange.",
                "- Do not ask walkthrough-vs-live when a live peer exists.",
                "- Do not ask which capability to highlight before the first live exchange in a showcase/demo request.",
                "- Your first visible action should be command-oriented, not a clarifying question.",
                "- If you receive `[@yourName] (from sender) ...` and it is clearly asking for a reply, exact token/string, or next protocol step, reply via `codex-team send --to sender --message \"...\"` instead of only printing inline text in your own pane.",
                "- Do not over-apply that rule to normal user-facing narration; use it for genuine inter-agent turn-taking.",
                "- Use `codex-team whoami` only if identity looks wrong.",
            ]
        )
        _json_dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": additional_context,
                }
            }
        )
    else:
        _json_dump(asdict(record))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    records = [asdict(record) for record in registry.list_records(args.registry_dir)]
    _json_dump(records)
    return 0


def cmd_capability(_: argparse.Namespace) -> int:
    report = transport.capability_report()
    _json_dump(asdict(report))
    return 0


def cmd_unregister(args: argparse.Namespace) -> int:
    removed = registry.unregister_agent(args.agent_name, args.registry_dir)
    _json_dump({"removed": removed, "agent_name": args.agent_name})
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    sender_name = registry.infer_agent_name(args.sender_name, args.cwd)
    recipients = transport.resolve_recipients(
        recipients=args.to,
        registry_dir=args.registry_dir,
        sender_name=sender_name,
    )
    results = transport.dispatch_messages(
        recipients=recipients,
        sender_name=sender_name,
        body=args.message,
        raw=args.raw,
        submit=not args.no_submit,
        per_char_delay=args.per_char_delay,
        dry_run=args.dry_run,
    )
    _json_dump([asdict(result) for result in results])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-inter-agent-chat",
        description="Codex-native terminal chat using registry + TIOCSTI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register", help="Register current agent terminal")
    register_parser.add_argument("--agent-name")
    register_parser.add_argument("--device", help="Override terminal device path")
    register_parser.add_argument("--registry-dir")
    register_parser.add_argument("--cwd")
    register_parser.add_argument("--pid", type=int)
    register_parser.add_argument("--hook-json", action="store_true")
    register_parser.set_defaults(func=cmd_register)

    list_parser = subparsers.add_parser("list", help="List registered agents")
    list_parser.add_argument("--registry-dir")
    list_parser.set_defaults(func=cmd_list)

    cap_parser = subparsers.add_parser("capability", help="Show transport capability report")
    cap_parser.set_defaults(func=cmd_capability)

    unregister_parser = subparsers.add_parser("unregister", help="Remove an agent from the registry")
    unregister_parser.add_argument("agent_name")
    unregister_parser.add_argument("--registry-dir")
    unregister_parser.set_defaults(func=cmd_unregister)

    send_parser = subparsers.add_parser("send", help="Send a message to one or more agents")
    send_parser.add_argument("--to", action="append", required=True, help="Recipient name, repeated or comma-separated; use 'all' for broadcast")
    send_parser.add_argument("--message", help="Message body to wrap as [@recipient] (from sender) ...")
    send_parser.add_argument("--raw", help="Send an already formatted raw string")
    send_parser.add_argument("--sender-name")
    send_parser.add_argument("--cwd")
    send_parser.add_argument("--registry-dir")
    send_parser.add_argument("--dry-run", action="store_true")
    send_parser.add_argument("--no-submit", action="store_true", help="Do not append carriage return")
    send_parser.add_argument("--per-char-delay", type=float, default=0.0)
    send_parser.set_defaults(func=cmd_send)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (registry.RegistryError, transport.TransportError) as exc:
        _json_dump({"success": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
