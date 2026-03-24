from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import sys
import termios
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .registry import AgentRecord, RegistryError, is_supported_device_path, list_records, read_record

TMUX_SUBMIT_CONFIRM_DELAY_SECONDS = 0.2


class TransportError(RuntimeError):
    """Raised when the selected transport fails."""


@dataclass
class CapabilityReport:
    platform: str
    tiocsti_available: bool
    tmux_available: bool
    transport_name: str
    notes: list[str]


@dataclass
class DispatchResult:
    recipient: str
    device_path: str
    transport: str
    message: str
    dry_run: bool


def capability_report() -> CapabilityReport:
    notes: list[str] = []
    tiocsti_available = hasattr(termios, "TIOCSTI")
    tmux_available = shutil.which("tmux") is not None
    if tmux_available:
        transport_name = "tmux-preferred"
    elif tiocsti_available:
        transport_name = "tiocsti"
    else:
        transport_name = "unsupported"

    if sys.platform == "darwin":
        notes.append("macOS often denies TIOCSTI with PermissionError unless terminal/OS policy allows it.")
        if tmux_available:
            notes.append("tmux is installed; tmux send-keys is the preferred transport when target agents were started inside tmux.")
    if sys.platform.startswith("linux"):
        notes.append("Linux 6.2+ may require sudo or dev.tty.legacy_tiocsti=1.")
        if tmux_available:
            notes.append("tmux send-keys is available when target agents were started inside tmux.")
    if not tiocsti_available:
        notes.append("termios.TIOCSTI is missing on this Python/platform build.")
    if not tmux_available:
        notes.append("tmux not found on PATH.")

    return CapabilityReport(
        platform=sys.platform,
        tiocsti_available=tiocsti_available,
        tmux_available=tmux_available,
        transport_name=transport_name,
        notes=notes,
    )


def normalize_recipients(raw_recipients: Optional[Sequence[str]]) -> list[str]:
    recipients: list[str] = []
    for item in raw_recipients or []:
        for token in str(item).split(","):
            token = token.strip()
            if token:
                recipients.append(token)
    return recipients


def build_wire_message(
    *,
    recipient: str,
    body: Optional[str] = None,
    sender: Optional[str] = None,
    raw: Optional[str] = None,
    submit: bool = True,
) -> str:
    if raw is not None:
        message = raw
    else:
        cleaned_body = str(body or "").strip()
        if not cleaned_body:
            raise TransportError("message 不能为空；或者改用 --raw")
        if sender:
            message = f"[@{recipient}] (from {sender}) {cleaned_body}"
        else:
            message = f"[@{recipient}] {cleaned_body}"

    if submit and not message.endswith("\r"):
        message += "\r"
    return message


def resolve_recipients(
    *,
    recipients: Sequence[str],
    registry_dir: Optional[str] = None,
    sender_name: Optional[str] = None,
) -> list[AgentRecord]:
    normalized = normalize_recipients(recipients)
    if not normalized:
        raise TransportError("至少需要一个接收方")

    if len(normalized) == 1 and normalized[0].lower() == "all":
        records = list_records(registry_dir)
        if sender_name:
            records = [record for record in records if record.agent_name != sender_name]
        if not records:
            raise TransportError("广播失败：当前 registry 中没有其他 agent")
        return records

    return [read_record(recipient, registry_dir) for recipient in normalized]


def inject_tiocsti(device_path: str, message: str, *, per_char_delay: float = 0.0) -> None:
    if not hasattr(termios, "TIOCSTI"):
        raise TransportError("当前平台/Python 不支持 termios.TIOCSTI")

    if not is_supported_device_path(device_path):
        raise TransportError(f"非法或不支持的终端设备路径: {device_path}")

    fd = None
    try:
        fd = os.open(device_path, os.O_WRONLY | getattr(os, "O_NOCTTY", 0))
        for char in message:
            fcntl.ioctl(fd, termios.TIOCSTI, char.encode())
            time.sleep(per_char_delay)
    except PermissionError as exc:
        raise TransportError(
            f"TIOCSTI 注入被拒绝: {exc}. 这通常意味着需要 sudo、内核/系统策略放行，或当前平台不允许。"
        ) from exc
    except OSError as exc:
        raise TransportError(f"TIOCSTI 注入失败: {exc}") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _split_tmux_chunks(message: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    buffer: list[str] = []
    last_index = len(message) - 1
    for index, char in enumerate(message):
        if char in {"\r", "\n"}:
            if buffer:
                chunks.append(("text", "".join(buffer)))
                buffer = []
            chunk_type = "submit" if index == last_index else "enter"
            chunks.append((chunk_type, ""))
        else:
            buffer.append(char)
    if buffer:
        chunks.append(("text", "".join(buffer)))
    return chunks


def inject_tmux(pane: str, message: str, *, tmux_socket: Optional[str] = None) -> None:
    pane = str(pane or "").strip()
    if not pane:
        raise TransportError("tmux pane 不能为空")

    tmux_bin = shutil.which("tmux")
    if not tmux_bin:
        raise TransportError("tmux 不在 PATH 中，无法使用 tmux transport")

    base_cmd = [tmux_bin]
    socket = str(tmux_socket or "").strip()
    if socket:
        base_cmd.extend(["-S", socket])

    try:
        for chunk_type, chunk_value in _split_tmux_chunks(message):
            if chunk_type == "text" and chunk_value:
                result = subprocess.run(
                    [*base_cmd, "send-keys", "-t", pane, "-l", chunk_value],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            else:
                enter_count = 2 if chunk_type == "submit" else 1
                result = None
                for enter_index in range(enter_count):
                    result = subprocess.run(
                        [*base_cmd, "send-keys", "-t", pane, "Enter"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if result.returncode != 0:
                        detail = (result.stderr or result.stdout or "").strip()
                        raise TransportError(f"tmux send-keys 失败: {detail or 'unknown error'}")
                    if chunk_type == "submit" and enter_index == 0 and enter_count > 1:
                        time.sleep(TMUX_SUBMIT_CONFIRM_DELAY_SECONDS)
            if result is not None and result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                raise TransportError(f"tmux send-keys 失败: {detail or 'unknown error'}")
    except OSError as exc:
        raise TransportError(f"tmux transport 执行失败: {exc}") from exc


def select_transport(record: AgentRecord) -> str:
    if getattr(record, "tmux_pane", None) and shutil.which("tmux"):
        return "tmux"
    if hasattr(termios, "TIOCSTI"):
        return "tiocsti"
    return "unsupported"


def dispatch_messages(
    *,
    recipients: Sequence[AgentRecord],
    sender_name: Optional[str],
    body: Optional[str] = None,
    raw: Optional[str] = None,
    submit: bool = True,
    per_char_delay: float = 0.0,
    dry_run: bool = False,
) -> list[DispatchResult]:
    results: list[DispatchResult] = []
    for record in recipients:
        message = build_wire_message(
            recipient=record.agent_name,
            body=body,
            sender=sender_name,
            raw=raw,
            submit=submit,
        )
        selected_transport = select_transport(record)
        if selected_transport == "unsupported":
            raise TransportError(
                f"没有可用 transport: recipient={record.agent_name}, tmux_pane={record.tmux_pane!r}, device={record.device_path}"
            )
        if not dry_run:
            if selected_transport == "tmux":
                inject_tmux(record.tmux_pane or "", message, tmux_socket=record.tmux_socket)
            else:
                inject_tiocsti(record.device_path, message, per_char_delay=per_char_delay)
        results.append(
            DispatchResult(
                recipient=record.agent_name,
                device_path=record.device_path,
                transport=selected_transport,
                message=message,
                dry_run=dry_run,
            )
        )
    return results
