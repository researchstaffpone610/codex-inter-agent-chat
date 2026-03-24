from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

REGISTRY_LINK_PATH = Path("/tmp/codex-agent-pts")
LINUX_RUNTIME_TEMPLATE = "/run/user/{uid}/codex-agent-pts"
TMP_RUNTIME_TEMPLATE = "/tmp/codex-agent-pts-{uid}"
ENV_ENABLE = "CODEX_INTER_AGENT_CHAT_ENABLE"
ENV_TEAM = "CODEX_INTER_AGENT_CHAT_TEAM"
ENV_REGISTRY_DIR = "CODEX_INTER_AGENT_CHAT_REGISTRY_DIR"
ENV_THREAD_ID = "CODEX_THREAD_ID"
DEFAULT_TEAM_NAME = "default"
SUPPORTED_DEVICE_PATTERNS = (
    re.compile(r"^/dev/pts/\d+$"),
    re.compile(r"^/dev/ttys\d+$"),
    re.compile(r"^/dev/tty\d+$"),
)
SAFE_AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RegistryError(RuntimeError):
    """Raised when registry operations fail."""


@dataclass
class AgentRecord:
    agent_name: str
    device_path: str
    platform: str
    pid: int
    cwd: str
    registered_at: float
    tmux_pane: Optional[str] = None
    tmux_socket: Optional[str] = None


@dataclass
class SessionContext:
    thread_id: str
    team: str
    registry_dir: str
    agent_name: str
    updated_at: float


def inter_agent_chat_enabled() -> bool:
    value = str(os.environ.get(ENV_ENABLE, "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def sanitize_agent_name(agent_name: str) -> str:
    value = str(agent_name or "").strip()
    if not value:
        raise RegistryError("agent_name 不能为空")
    if not SAFE_AGENT_NAME_RE.fullmatch(value):
        raise RegistryError(
            "agent_name 只允许字母、数字、点、下划线和横线，长度不超过 128"
        )
    return value


def sanitize_team_name(team_name: str) -> str:
    value = str(team_name or "").strip() or DEFAULT_TEAM_NAME
    if not SAFE_AGENT_NAME_RE.fullmatch(value):
        raise RegistryError(
            "team_name 只允许字母、数字、点、下划线和横线，长度不超过 128"
        )
    return value


def current_team(team_name: Optional[str] = None) -> str:
    if team_name:
        return sanitize_team_name(team_name)

    env_team = os.environ.get(ENV_TEAM)
    if env_team:
        return sanitize_team_name(env_team)
    return DEFAULT_TEAM_NAME


def _tmux_pane_from_env() -> Optional[str]:
    value = str(os.environ.get("TMUX_PANE", "")).strip()
    return value or None


def _tmux_socket_from_env() -> Optional[str]:
    value = str(os.environ.get("TMUX", "")).strip()
    if not value:
        return None
    return value.split(",", 1)[0].strip() or None


def is_supported_device_path(device_path: str) -> bool:
    path = str(device_path or "").strip()
    return any(pattern.fullmatch(path) for pattern in SUPPORTED_DEVICE_PATTERNS)


def default_registry_root() -> Path:
    uid = os.getuid()
    if sys.platform.startswith("linux"):
        linux_runtime = Path(LINUX_RUNTIME_TEMPLATE.format(uid=uid))
        if linux_runtime.parent.exists():
            return linux_runtime

    tmpdir = os.environ.get("TMPDIR")
    if tmpdir:
        return Path(tmpdir).resolve() / f"codex-agent-pts-{uid}"
    return Path(TMP_RUNTIME_TEMPLATE.format(uid=uid))


def default_registry_dir(team_name: Optional[str] = None) -> Path:
    configured_dir = os.environ.get(ENV_REGISTRY_DIR)
    if configured_dir:
        return Path(configured_dir).expanduser().resolve()
    return default_registry_root() / current_team(team_name)


def codex_home_dir() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def _sanitize_context_token(value: str, *, fallback: str = "default") -> str:
    sanitized = "".join(
        char if char.isalnum() or char in "._-" else "-"
        for char in str(value or "").strip()
    ).strip("-.")
    return sanitized or fallback


def session_context_root() -> Path:
    return codex_home_dir() / "state" / "inter-agent-chat" / "sessions"


def session_context_path(thread_id: Optional[str] = None) -> Optional[Path]:
    effective_thread_id = str(thread_id or os.environ.get(ENV_THREAD_ID, "")).strip()
    if not effective_thread_id:
        return None
    safe_thread_id = _sanitize_context_token(effective_thread_id, fallback="unknown-thread")
    return session_context_root() / f"{safe_thread_id}.json"


def infer_team_from_registry(
    agent_name: Optional[str] = None,
    registry_root: Optional[str | Path] = None,
) -> Optional[str]:
    root = (
        Path(registry_root).expanduser().resolve()
        if registry_root is not None
        else default_registry_root()
    )
    if not root.exists():
        return None

    if agent_name:
        try:
            safe_name = sanitize_agent_name(agent_name)
        except RegistryError:
            safe_name = None
        if safe_name:
            matches = sorted(
                sanitize_team_name(path.name)
                for path in root.iterdir()
                if path.is_dir() and (path / f"{safe_name}.json").exists()
            )
            if len(matches) == 1:
                return matches[0]

    teams = sorted(
        sanitize_team_name(path.name)
        for path in root.iterdir()
        if path.is_dir() and next(path.glob("*.json"), None) is not None
    )
    unique_teams = sorted(set(teams))
    if len(unique_teams) == 1:
        return unique_teams[0]
    return None


def read_session_context(thread_id: Optional[str] = None) -> Optional[SessionContext]:
    path = session_context_path(thread_id)
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        return SessionContext(**payload)
    except Exception:
        return None


def write_session_context(
    *,
    team: str,
    registry_dir: str | Path,
    agent_name: str,
    thread_id: Optional[str] = None,
) -> Optional[SessionContext]:
    path = session_context_path(thread_id)
    if path is None:
        return None
    context = SessionContext(
        thread_id=str(thread_id or os.environ.get(ENV_THREAD_ID, "")).strip(),
        team=sanitize_team_name(team),
        registry_dir=str(Path(registry_dir).expanduser().resolve()),
        agent_name=sanitize_agent_name(agent_name),
        updated_at=time.time(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(context), ensure_ascii=False, indent=2))
    return context


def ensure_registry_dir(registry_dir: Optional[str | Path] = None) -> Path:
    target = Path(registry_dir).expanduser() if registry_dir else default_registry_dir()
    target.mkdir(parents=True, exist_ok=True)

    if registry_dir is None and ENV_REGISTRY_DIR not in os.environ:
        try:
            root = default_registry_root()
            root.mkdir(parents=True, exist_ok=True)
            if REGISTRY_LINK_PATH.exists() or REGISTRY_LINK_PATH.is_symlink():
                REGISTRY_LINK_PATH.unlink()
            REGISTRY_LINK_PATH.symlink_to(root)
        except OSError:
            # Symlink is only for convenience; the registry dir itself is authoritative.
            pass

    return target


def record_path(agent_name: str, registry_dir: Optional[str | Path] = None) -> Path:
    safe_name = sanitize_agent_name(agent_name)
    return ensure_registry_dir(registry_dir) / f"{safe_name}.json"


def _pid_exists(pid: int) -> bool:
    try:
        if int(pid) <= 0:
            return False
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _tmux_pane_exists(pane: Optional[str], socket: Optional[str]) -> bool:
    pane_value = str(pane or "").strip()
    if not pane_value:
        return True
    result = subprocess.run(
        ["sh", "-lc", "command -v tmux"],
        capture_output=True,
        text=True,
        check=False,
    )
    tmux_path = (result.stdout or "").strip()
    if not tmux_path:
        return False
    cmd = [tmux_path]
    socket_value = str(socket or "").strip()
    if socket_value:
        cmd.extend(["-S", socket_value])
    cmd.extend(["list-panes", "-t", pane_value, "-F", "#{pane_id}"])
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode == 0 and pane_value in (result.stdout or "")


def is_record_live(record: AgentRecord) -> bool:
    if not _pid_exists(record.pid):
        return False
    if record.tmux_pane and not _tmux_pane_exists(record.tmux_pane, record.tmux_socket):
        return False
    return True


def prune_stale_records(registry_dir: Optional[str | Path] = None) -> list[str]:
    directory = ensure_registry_dir(registry_dir)
    removed: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
            record = AgentRecord(**payload)
        except Exception:
            try:
                path.unlink()
            except OSError:
                pass
            removed.append(path.stem)
            continue
        if not is_record_live(record):
            try:
                path.unlink()
            except OSError:
                pass
            removed.append(record.agent_name)
    return removed


def read_record(agent_name: str, registry_dir: Optional[str | Path] = None) -> AgentRecord:
    path = record_path(agent_name, registry_dir)
    if not path.exists():
        raise RegistryError(f"未找到 agent 注册记录: {agent_name}")
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RegistryError(f"注册文件损坏: {path}") from exc
    record = AgentRecord(**payload)
    if not is_record_live(record):
        try:
            path.unlink()
        except OSError:
            pass
        raise RegistryError(f"agent 注册记录已失效: {agent_name}")
    return record


def list_records(registry_dir: Optional[str | Path] = None) -> list[AgentRecord]:
    directory = ensure_registry_dir(registry_dir)
    prune_stale_records(directory)
    records: list[AgentRecord] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
            records.append(AgentRecord(**payload))
        except Exception:
            continue
    return records


def infer_agent_name(agent_name: Optional[str] = None, cwd: Optional[str] = None) -> str:
    if agent_name:
        return sanitize_agent_name(agent_name)

    env_name = os.environ.get("AGENT_NAME")
    if env_name:
        return sanitize_agent_name(env_name)

    inferred_cwd = Path(cwd or os.getcwd())
    return sanitize_agent_name(inferred_cwd.name or "codex-agent")


def _candidate_ttys_from_fds() -> Iterable[str]:
    for fd in (0, 1, 2):
        try:
            if os.isatty(fd):
                yield os.ttyname(fd)
        except OSError:
            continue


def _ps_tty_for_pid(pid: int) -> Optional[str]:
    try:
        result = subprocess.run(
            ["ps", "-o", "tty=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None

    tty = (result.stdout or "").strip()
    if not tty or tty == "?":
        return None
    if tty.startswith("/dev/"):
        return tty
    return f"/dev/{tty}"


def _walk_process_tree_for_tty(start_pid: Optional[int] = None, max_depth: int = 6) -> Iterable[str]:
    pid = int(start_pid or os.getpid())
    for _ in range(max_depth):
        tty = _ps_tty_for_pid(pid)
        if tty:
            yield tty
        try:
            parent_result = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(pid)],
                capture_output=True,
                text=True,
                check=False,
            )
            parent = int((parent_result.stdout or "").strip())
        except Exception:
            break
        if parent <= 1 or parent == pid:
            break
        pid = parent


def detect_current_tty() -> str:
    candidates = list(_candidate_ttys_from_fds()) + list(_walk_process_tree_for_tty())
    for candidate in candidates:
        if candidate and is_supported_device_path(candidate):
            return candidate
    raise RegistryError(
        "无法检测当前终端设备；请在真实终端会话中运行，或显式传入 --device"
    )


def register_agent(
    *,
    agent_name: Optional[str] = None,
    device_path: Optional[str] = None,
    registry_dir: Optional[str | Path] = None,
    cwd: Optional[str] = None,
    pid: Optional[int] = None,
    tmux_pane: Optional[str] = None,
    tmux_socket: Optional[str] = None,
) -> AgentRecord:
    effective_agent_name = infer_agent_name(agent_name=agent_name, cwd=cwd)
    effective_device_path = str(device_path or detect_current_tty()).strip()

    if not is_supported_device_path(effective_device_path):
        raise RegistryError(f"不支持的终端设备路径: {effective_device_path}")

    record = AgentRecord(
        agent_name=effective_agent_name,
        device_path=effective_device_path,
        platform=sys.platform,
        pid=int(pid or os.getpid()),
        cwd=str(Path(cwd or os.getcwd()).resolve()),
        registered_at=time.time(),
        tmux_pane=str(tmux_pane or _tmux_pane_from_env() or "").strip() or None,
        tmux_socket=str(tmux_socket or _tmux_socket_from_env() or "").strip() or None,
    )
    target = record_path(effective_agent_name, registry_dir)
    target.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2))
    return record


def unregister_agent(agent_name: str, registry_dir: Optional[str | Path] = None) -> bool:
    path = record_path(agent_name, registry_dir)
    if not path.exists():
        return False
    path.unlink()
    return True
