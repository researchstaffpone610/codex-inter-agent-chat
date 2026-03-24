from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from codex_inter_agent_chat import registry, transport


class TransportTests(unittest.TestCase):
    def test_build_wire_message_wraps_sender_and_submit(self) -> None:
        message = transport.build_wire_message(
            recipient="agent-b",
            body="status?",
            sender="agent-a",
            submit=True,
        )
        self.assertEqual(message, "[@agent-b] (from agent-a) status?\r")

    def test_build_wire_message_allows_raw(self) -> None:
        message = transport.build_wire_message(
            recipient="ignored",
            raw="[@stop]\r",
            submit=True,
        )
        self.assertEqual(message, "[@stop]\r")

    def test_inject_tiocsti_calls_ioctl_per_character(self) -> None:
        calls: list[str] = []

        def fake_ioctl(fd: int, op: int, payload: bytes) -> None:
            calls.append(payload.decode())

        with mock.patch("os.open", return_value=42), \
             mock.patch("os.close"), \
             mock.patch("fcntl.ioctl", side_effect=fake_ioctl), \
             mock.patch("time.sleep"):
            transport.inject_tiocsti("/dev/ttys044", "abc\r", per_char_delay=0.0)

        self.assertEqual(calls, ["a", "b", "c", "\r"])

    def test_inject_tmux_sends_literal_text_and_double_enter_for_submit(self) -> None:
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("shutil.which", return_value="/opt/homebrew/bin/tmux"), \
             mock.patch("subprocess.run", side_effect=fake_run):
            transport.inject_tmux("%7", "hello\r", tmux_socket="/tmp/tmux-501/default")

        self.assertEqual(
            calls,
            [
                ["/opt/homebrew/bin/tmux", "-S", "/tmp/tmux-501/default", "send-keys", "-t", "%7", "-l", "hello"],
                ["/opt/homebrew/bin/tmux", "-S", "/tmp/tmux-501/default", "send-keys", "-t", "%7", "Enter"],
                ["/opt/homebrew/bin/tmux", "-S", "/tmp/tmux-501/default", "send-keys", "-t", "%7", "Enter"],
            ],
        )

    def test_inject_tmux_uses_single_enter_for_internal_newlines(self) -> None:
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("shutil.which", return_value="/opt/homebrew/bin/tmux"), \
             mock.patch("subprocess.run", side_effect=fake_run):
            transport.inject_tmux("%7", "hello\nworld\r", tmux_socket="/tmp/tmux-501/default")

        self.assertEqual(
            calls,
            [
                ["/opt/homebrew/bin/tmux", "-S", "/tmp/tmux-501/default", "send-keys", "-t", "%7", "-l", "hello"],
                ["/opt/homebrew/bin/tmux", "-S", "/tmp/tmux-501/default", "send-keys", "-t", "%7", "Enter"],
                ["/opt/homebrew/bin/tmux", "-S", "/tmp/tmux-501/default", "send-keys", "-t", "%7", "-l", "world"],
                ["/opt/homebrew/bin/tmux", "-S", "/tmp/tmux-501/default", "send-keys", "-t", "%7", "Enter"],
                ["/opt/homebrew/bin/tmux", "-S", "/tmp/tmux-501/default", "send-keys", "-t", "%7", "Enter"],
            ],
        )

    def test_dispatch_messages_dry_run(self) -> None:
        recipients = [
            registry.AgentRecord(
                agent_name="agent-b",
                device_path="/dev/ttys044",
                platform="darwin",
                pid=1,
                cwd="/tmp/agent-b",
                registered_at=0.0,
            )
        ]
        results = transport.dispatch_messages(
            recipients=recipients,
            sender_name="agent-a",
            body="ping",
            dry_run=True,
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].dry_run)
        self.assertIn("(from agent-a)", results[0].message)

    def test_dispatch_messages_prefers_tmux_when_pane_metadata_exists(self) -> None:
        recipients = [
            registry.AgentRecord(
                agent_name="agent-b",
                device_path="/dev/ttys044",
                platform="darwin",
                pid=1,
                cwd="/tmp/agent-b",
                registered_at=0.0,
                tmux_pane="%7",
                tmux_socket="/tmp/tmux-501/default",
            )
        ]
        with mock.patch("shutil.which", return_value="/opt/homebrew/bin/tmux"), \
             mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="", stderr="")):
            results = transport.dispatch_messages(
                recipients=recipients,
                sender_name="agent-a",
                body="ping",
                dry_run=False,
            )
        self.assertEqual(results[0].transport, "tmux")

    def test_resolve_recipients_broadcast_excludes_sender(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry.register_agent(agent_name="agent-a", device_path="/dev/ttys041", registry_dir=tmp)
            registry.register_agent(agent_name="agent-b", device_path="/dev/ttys042", registry_dir=tmp)
            registry.register_agent(agent_name="agent-c", device_path="/dev/ttys043", registry_dir=tmp)
            recipients = transport.resolve_recipients(
                recipients=["all"],
                registry_dir=tmp,
                sender_name="agent-a",
            )
            self.assertEqual({record.agent_name for record in recipients}, {"agent-b", "agent-c"})


if __name__ == "__main__":
    unittest.main()
