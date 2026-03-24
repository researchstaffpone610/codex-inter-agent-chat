from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_inter_agent_chat import registry


class RegistryTests(unittest.TestCase):
    def test_supported_device_paths(self) -> None:
        self.assertTrue(registry.is_supported_device_path("/dev/pts/12"))
        self.assertTrue(registry.is_supported_device_path("/dev/ttys044"))
        self.assertFalse(registry.is_supported_device_path("/tmp/not-a-tty"))

    def test_register_and_read_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = registry.register_agent(
                agent_name="agent-a",
                device_path="/dev/ttys044",
                registry_dir=tmp,
                cwd="/tmp/worktree-a",
                pid=os.getpid(),
            )
            self.assertEqual(record.agent_name, "agent-a")
            path = Path(tmp) / "agent-a.json"
            self.assertTrue(path.exists())
            payload = json.loads(path.read_text())
            self.assertEqual(payload["device_path"], "/dev/ttys044")

            loaded = registry.read_record("agent-a", tmp)
            self.assertEqual(loaded.agent_name, "agent-a")
            self.assertEqual(loaded.pid, os.getpid())

    def test_detect_current_tty_prefers_valid_fd_tty(self) -> None:
        with mock.patch.object(registry, "_candidate_ttys_from_fds", return_value=["/dev/ttys123"]), \
             mock.patch.object(registry, "_walk_process_tree_for_tty", return_value=[]):
            self.assertEqual(registry.detect_current_tty(), "/dev/ttys123")

    def test_default_registry_dir_uses_tmpdir_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"TMPDIR": tmp}, clear=False), \
                 mock.patch("sys.platform", "darwin"):
                directory = registry.default_registry_dir()
                self.assertIn("codex-agent-pts-", str(directory))
                self.assertTrue(str(directory).startswith(str(Path(tmp).resolve())))
                self.assertEqual(directory.name, "default")

    def test_default_registry_dir_uses_team_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                "os.environ",
                {"TMPDIR": tmp, "CODEX_INTER_AGENT_CHAT_TEAM": "red"},
                clear=False,
            ), mock.patch("sys.platform", "darwin"):
                directory = registry.default_registry_dir()
                self.assertEqual(directory.name, "red")

    def test_default_registry_dir_honors_explicit_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            explicit = Path(tmp) / "manual-registry"
            with mock.patch.dict(
                "os.environ",
                {"CODEX_INTER_AGENT_CHAT_REGISTRY_DIR": str(explicit)},
                clear=False,
            ):
                self.assertEqual(registry.default_registry_dir(), explicit.resolve())

    def test_inter_agent_chat_enabled_parses_truthy_values(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"CODEX_INTER_AGENT_CHAT_ENABLE": "true"},
            clear=False,
        ):
            self.assertTrue(registry.inter_agent_chat_enabled())

    def test_session_context_roundtrip_uses_codex_home_and_thread_id(self) -> None:
        with tempfile.TemporaryDirectory() as codex_home, tempfile.TemporaryDirectory() as registry_dir:
            with mock.patch.dict(
                "os.environ",
                {"CODEX_HOME": codex_home, "CODEX_THREAD_ID": "thread-abc"},
                clear=False,
            ):
                context = registry.write_session_context(
                    team="reverse",
                    registry_dir=registry_dir,
                    agent_name="agent-a",
                )
                self.assertIsNotNone(context)
                loaded = registry.read_session_context()
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded.thread_id, "thread-abc")
                self.assertEqual(loaded.team, "reverse")
                self.assertEqual(loaded.agent_name, "agent-a")
                self.assertEqual(loaded.registry_dir, str(Path(registry_dir).resolve()))

    def test_register_agent_captures_tmux_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                "os.environ",
                {"TMUX_PANE": "%7", "TMUX": "/tmp/tmux-501/default,123,0"},
                clear=False,
            ):
                record = registry.register_agent(
                    agent_name="agent-a",
                    device_path="/dev/ttys044",
                    registry_dir=tmp,
                )
                self.assertEqual(record.tmux_pane, "%7")
                self.assertEqual(record.tmux_socket, "/tmp/tmux-501/default")

    def test_infer_team_from_registry_by_agent_name(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            reverse = Path(root) / "reverse"
            reverse.mkdir()
            registry.register_agent(
                agent_name="agent-b",
                device_path="/dev/ttys042",
                registry_dir=reverse,
            )
            self.assertEqual(registry.infer_team_from_registry("agent-b", root), "reverse")

    def test_list_records_prunes_stale_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-a.json"
            path.write_text(
                json.dumps(
                    {
                        "agent_name": "agent-a",
                        "device_path": "/dev/ttys044",
                        "platform": "darwin",
                        "pid": 999999,
                        "cwd": "/tmp",
                        "registered_at": 0.0,
                        "tmux_pane": None,
                        "tmux_socket": None,
                    }
                )
            )
            with mock.patch.object(registry, "_pid_exists", return_value=False):
                records = registry.list_records(tmp)
            self.assertEqual(records, [])
            self.assertFalse(path.exists())

    def test_read_record_rejects_stale_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry.register_agent(
                agent_name="agent-a",
                device_path="/dev/ttys044",
                registry_dir=tmp,
                pid=1234,
            )
            with mock.patch.object(registry, "_pid_exists", return_value=False):
                with self.assertRaisesRegex(registry.RegistryError, "已失效"):
                    registry.read_record("agent-a", tmp)


if __name__ == "__main__":
    unittest.main()
