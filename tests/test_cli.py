from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
ENV = {
    **os.environ,
    "PYTHONPATH": str(ROOT / "src"),
}
REGISTER_WRAPPER = ROOT / "skills" / "inter-agent-chat-codex" / "scripts" / "register-codex-tty.py"
TEAM_LAUNCHER = ROOT / "tools" / "codex-team.sh"

from codex_inter_agent_chat import registry, team_cli


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [PYTHON, "-m", "codex_inter_agent_chat.cli", *args],
            capture_output=True,
            text=True,
            env=ENV,
            check=False,
        )

    def test_register_command_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(
                "register",
                "--agent-name",
                "agent-a",
                "--device",
                "/dev/ttys044",
                "--registry-dir",
                tmp,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["agent_name"], "agent-a")

    def test_register_hook_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(
                "register",
                "--agent-name",
                "agent-b",
                "--device",
                "/dev/ttys045",
                "--registry-dir",
                tmp,
                "--pid",
                str(os.getpid()),
            )
            result = self.run_cli(
                "register",
                "--agent-name",
                "agent-a",
                "--device",
                "/dev/ttys044",
                "--registry-dir",
                tmp,
                "--pid",
                str(os.getpid()),
                "--hook-json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn("team=default", context)
            self.assertIn("agent_name=agent-a", context)
            self.assertIn(str(Path(tmp).resolve()), context)
            self.assertIn("known_agents=agent-a, agent-b", context)
            self.assertIn("first run `codex-team list`", context)
            self.assertIn("Do not ask whether another agent needs to be started or registered", context)
            self.assertIn("reply via `codex-team send --to sender --message", context)

    def test_send_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(
                "register",
                "--agent-name",
                "agent-b",
                "--device",
                "/dev/ttys044",
                "--registry-dir",
                tmp,
                "--pid",
                str(os.getpid()),
            )
            result = self.run_cli(
                "send",
                "--to",
                "agent-b",
                "--sender-name",
                "agent-a",
                "--registry-dir",
                tmp,
                "--message",
                "status?",
                "--dry-run",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload[0]["recipient"], "agent-b")
            self.assertTrue(payload[0]["dry_run"])

    def test_unregister_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(
                "register",
                "--agent-name",
                "agent-b",
                "--device",
                "/dev/ttys044",
                "--registry-dir",
                tmp,
                "--pid",
                str(os.getpid()),
            )
            result = self.run_cli("unregister", "agent-b", "--registry-dir", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["removed"])
            self.assertEqual(payload["agent_name"], "agent-b")

    def test_register_wrapper_is_inert_when_not_enabled(self) -> None:
        result = subprocess.run(
            [PYTHON, str(REGISTER_WRAPPER)],
            capture_output=True,
            text=True,
            env={k: v for k, v in ENV.items() if k != "CODEX_INTER_AGENT_CHAT_ENABLE"},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("disabled", payload["hookSpecificOutput"]["additionalContext"])

    def test_team_launcher_print_env(self) -> None:
        result = subprocess.run(
            [str(TEAM_LAUNCHER), "--team", "reverse", "--agent-name", "agent-a", "--print-env"],
            capture_output=True,
            text=True,
            env=ENV,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["enabled"], "1")
        self.assertEqual(payload["team"], "reverse")
        self.assertEqual(payload["agent_name"], "agent-a")
        self.assertTrue(payload["registry_dir"].endswith("/reverse"))

    def test_team_launcher_list_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(
                "register",
                "--agent-name",
                "agent-a",
                "--device",
                "/dev/ttys044",
                "--registry-dir",
                tmp,
                "--pid",
                str(os.getpid()),
            )
            result = subprocess.run(
                [str(TEAM_LAUNCHER), "list", "--team", "reverse", "--registry-dir", tmp],
                capture_output=True,
                text=True,
                env=ENV,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload[0]["agent_name"], "agent-a")

    def test_team_launcher_send_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(
                "register",
                "--agent-name",
                "agent-b",
                "--device",
                "/dev/ttys044",
                "--registry-dir",
                tmp,
                "--pid",
                str(os.getpid()),
            )
            result = subprocess.run(
                [
                    str(TEAM_LAUNCHER),
                    "send",
                    "--team",
                    "reverse",
                    "--registry-dir",
                    tmp,
                    "--sender-name",
                    "agent-a",
                    "--to",
                    "agent-b",
                    "--message",
                    "status?",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                env=ENV,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload[0]["recipient"], "agent-b")
            self.assertTrue(payload[0]["dry_run"])

    def test_team_cli_start_preregisters_before_exec(self) -> None:
        args = team_cli.build_parser().parse_args(
            ["start", "--team", "reverse", "--agent-name", "agent-a", "--registry-dir", "/tmp/reverse-team"]
        )
        calls: list[str] = []

        def fake_register(**kwargs):
            calls.append("register")
            return registry.AgentRecord(
                agent_name="agent-a",
                device_path="/dev/ttys044",
                platform="darwin",
                pid=1234,
                cwd="/tmp/worktree-a",
                registered_at=1.0,
            )

        def fake_execvpe(*_args):
            calls.append("exec")
            raise RuntimeError("exec called")

        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(team_cli, "_compose_team_developer_instructions", return_value="TEAM OVERRIDE"), \
             mock.patch.object(team_cli.shutil, "which", return_value="/opt/homebrew/bin/codex"), \
             mock.patch.object(team_cli.registry, "register_agent", side_effect=fake_register) as register_mock, \
             mock.patch.object(team_cli.os, "execvpe", side_effect=fake_execvpe):
            with self.assertRaisesRegex(RuntimeError, "exec called"):
                team_cli.cmd_start(args)

        self.assertEqual(calls, ["register", "exec"])
        self.assertEqual(register_mock.call_args.kwargs["agent_name"], "agent-a")
        self.assertEqual(
            register_mock.call_args.kwargs["registry_dir"],
            str(Path("/tmp/reverse-team").resolve()),
        )

    def test_team_cli_start_appends_team_developer_override(self) -> None:
        args = team_cli.build_parser().parse_args(
            ["start", "--team", "reverse", "--agent-name", "agent-a", "--registry-dir", "/tmp/reverse-team"]
        )

        def fake_execvpe(_path, argv, _env):
            raise RuntimeError(json.dumps(argv))

        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(team_cli.shutil, "which", return_value="/opt/homebrew/bin/codex"), \
             mock.patch.object(
                 team_cli.registry,
                 "register_agent",
                 return_value=registry.AgentRecord(
                     agent_name="agent-a",
                     device_path="/dev/ttys044",
                     platform="darwin",
                     pid=1234,
                     cwd="/tmp/worktree-a",
                     registered_at=1.0,
                 ),
             ), \
             mock.patch.object(team_cli, "_compose_team_developer_instructions", return_value="TEAM OVERRIDE"), \
             mock.patch.object(team_cli.os, "execvpe", side_effect=fake_execvpe):
            with self.assertRaises(RuntimeError) as exc:
                team_cli.cmd_start(args)

        argv = json.loads(str(exc.exception))
        self.assertIn("-c", argv)
        joined = " ".join(argv)
        self.assertIn("developer_instructions=", joined)
        self.assertIn("TEAM OVERRIDE", joined)

    def test_team_session_override_mentions_reply_via_send_for_inter_agent_turns(self) -> None:
        self.assertIn(
            "reply to that sender with `codex-team send --to <sender> --message",
            team_cli.TEAM_SESSION_DEVELOPER_APPEND,
        )

    def test_team_cli_loads_developer_instructions_without_tomllib(self) -> None:
        with tempfile.TemporaryDirectory() as codex_home:
            config_path = Path(codex_home) / "config.toml"
            config_path.write_text(
                'developer_instructions = """Line one\nLine two"""\n',
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"CODEX_HOME": codex_home}, clear=False), \
                 mock.patch.object(team_cli, "tomllib", None):
                self.assertEqual(
                    team_cli._load_base_developer_instructions(),
                    "Line one\nLine two",
                )

    def test_team_cli_uses_session_context_when_team_env_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as codex_home, tempfile.TemporaryDirectory() as registry_dir:
            with mock.patch.dict(
                os.environ,
                {"CODEX_HOME": codex_home, "CODEX_THREAD_ID": "thread-reverse"},
                clear=True,
            ):
                registry.write_session_context(
                    team="reverse",
                    registry_dir=registry_dir,
                    agent_name="agent-a",
                )
                payload = team_cli._apply_team_env(team=None, registry_dir=None, agent_name=None)
                self.assertEqual(payload[registry.ENV_TEAM], "reverse")
                self.assertEqual(payload[registry.ENV_REGISTRY_DIR], str(Path(registry_dir).resolve()))
                self.assertEqual(payload["AGENT_NAME"], "agent-a")

    def test_team_cli_can_infer_team_from_registry_with_only_agent_name_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_root:
            registry_root = Path(tmp_root) / f"codex-agent-pts-{os.getuid()}"
            reverse_dir = registry_root / "reverse"
            reverse_dir.mkdir(parents=True)
            registry.register_agent(
                agent_name="agent-b",
                device_path="/dev/ttys044",
                registry_dir=reverse_dir,
            )
            with mock.patch.dict(
                os.environ,
                {"TMPDIR": tmp_root, "AGENT_NAME": "agent-b"},
                clear=True,
            ):
                payload = team_cli._apply_team_env(team=None, registry_dir=None, agent_name=None)
                self.assertEqual(payload[registry.ENV_TEAM], "reverse")
                self.assertEqual(payload[registry.ENV_REGISTRY_DIR], str(reverse_dir.resolve()))

    def test_team_cli_whoami_outputs_resolved_identity(self) -> None:
        args = team_cli.build_parser().parse_args(["whoami", "--team", "reverse", "--agent-name", "agent-a"])
        with mock.patch("builtins.print") as print_mock, \
             mock.patch.dict(os.environ, {}, clear=True):
            rc = team_cli.cmd_whoami(args)
        self.assertEqual(rc, 0)
        rendered = "".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn('"team": "reverse"', rendered)
        self.assertIn('"agent_name": "agent-a"', rendered)


if __name__ == "__main__":
    unittest.main()
