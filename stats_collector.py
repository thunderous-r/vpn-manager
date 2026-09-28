import json
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path

os.environ.setdefault("ENV", "production")

from config import BASE_FILE, USERS_FILE
from stats import cleanup_stats, init_stats_db, record_activity


ENV_FILE = Path("/etc/vpn-manager.env")
JOURNALCTL_BIN = "/usr/bin/journalctl"
SSH_BIN = "/usr/bin/ssh"
RECONNECT_DELAY_SECONDS = 5
CONTEXT_TTL_SECONDS = 30
CLEANUP_INTERVAL_SECONDS = 60 * 60

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
CONTEXT_RE = re.compile(r"\[(\d+)\s+[^\]]+\]")
PROTOCOL_RE = re.compile(
    r"inbound/(?P<protocol>vless|hysteria2)\["
)
SOURCE_RE = re.compile(
    r"inbound(?: packet)? connection from "
    r"(?P<address>\[[^\]]+\]|[^\s:]+):\d+"
)
USER_RE = re.compile(
    r"\[(?P<username>[^\[\]]+)\]\s+"
    r"inbound(?: packet addr)?(?: packet)? connection"
)


class UserRegistry:
    def __init__(self) -> None:
        self._mtime_ns = None
        self._users: set[str] = set()
        self._lock = threading.Lock()

    def contains(self, username: str) -> bool:
        self._reload_if_needed()
        with self._lock:
            return username in self._users

    def _reload_if_needed(self) -> None:
        try:
            stat = USERS_FILE.stat()
        except FileNotFoundError:
            return

        if stat.st_mtime_ns == self._mtime_ns:
            return

        try:
            users = json.loads(
                USERS_FILE.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            print(f"users reload failed: {error}", flush=True)
            return

        with self._lock:
            self._users = set(users)
            self._mtime_ns = stat.st_mtime_ns


class NodeLogParser:
    def __init__(
        self,
        node_name: str,
        user_registry: UserRegistry,
    ) -> None:
        self.node_name = node_name
        self.user_registry = user_registry
        self.contexts: dict[str, dict] = {}

    def feed(self, raw_line: str) -> None:
        line = ANSI_RE.sub("", raw_line).strip()

        if not line:
            return

        context_match = CONTEXT_RE.search(line)
        if not context_match:
            return

        context_id = context_match.group(1)
        now = time.time()
        context = self.contexts.setdefault(
            context_id,
            {"updated_at": now},
        )
        context["updated_at"] = now

        protocol_match = PROTOCOL_RE.search(line)
        if protocol_match:
            context["protocol"] = protocol_match.group(
                "protocol"
            )

        source_match = SOURCE_RE.search(line)
        if source_match:
            address = source_match.group("address")
            context["source_ip"] = address.strip("[]")

        user_match = USER_RE.search(line)
        if user_match:
            context["username"] = user_match.group(
                "username"
            )

        self._commit_if_complete(context_id)
        self._prune(now)

    def _commit_if_complete(self, context_id: str) -> None:
        context = self.contexts.get(context_id)
        if context is None:
            return

        required = {
            "protocol",
            "source_ip",
            "username",
        }
        if not required.issubset(context):
            return

        username = context["username"]

        if not self.user_registry.contains(username):
            self.contexts.pop(context_id, None)
            return

        try:
            result = record_activity(
                username=username,
                node=self.node_name,
                protocol=context["protocol"],
                source_ip=context["source_ip"],
            )
        except Exception as error:
            print(
                f"[{self.node_name}] stats write failed: {error}",
                flush=True,
            )
        else:
            if result["risk"] != "normal":
                print(
                    f"[{self.node_name}] {username}: "
                    f"risk={result['risk']} "
                    f"active_networks="
                    f"{result['active_networks']}",
                    flush=True,
                )

        self.contexts.pop(context_id, None)

    def _prune(self, now: float) -> None:
        stale = [
            context_id
            for context_id, context in self.contexts.items()
            if now - context["updated_at"] > CONTEXT_TTL_SECONDS
        ]

        for context_id in stale:
            self.contexts.pop(context_id, None)


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}

    for raw_line in path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            continue

        values[key.strip()] = value.strip().strip("\"'")

    return values


def get_setting(
    env_values: dict[str, str],
    name: str,
) -> str | None:
    return os.environ.get(name) or env_values.get(name)


def load_base() -> dict:
    return json.loads(
        BASE_FILE.read_text(encoding="utf-8")
    )


def build_journal_command(
    node_name: str,
    node: dict,
    env_values: dict[str, str],
) -> list[str]:
    deploy = node.get("deploy") or {}
    mode = deploy.get("mode")
    stats_config = node.get("stats") or {}
    service_name = stats_config.get(
        "service",
        "sing-box",
    )

    journal_args = [
        JOURNALCTL_BIN,
        "-u",
        service_name,
        "-f",
        "-n",
        "0",
        "-o",
        "cat",
        "--no-pager",
    ]

    if mode == "local":
        return journal_args

    if mode != "ssh":
        raise RuntimeError(
            f"Unsupported deploy mode for {node_name!r}: {mode!r}"
        )

    env_prefix = deploy.get(
        "env_prefix",
        node_name.upper().replace("-", "_"),
    )
    ssh_host = get_setting(
        env_values,
        f"{env_prefix}_SSH_HOST",
    )
    ssh_user = get_setting(
        env_values,
        f"{env_prefix}_SSH_USER",
    )
    ssh_key = get_setting(
        env_values,
        f"{env_prefix}_SSH_KEY",
    )

    if not ssh_host or not ssh_user or not ssh_key:
        raise RuntimeError(
            f"SSH stats settings missing for {node_name!r}"
        )

    return [
        SSH_BIN,
        "-T",
        "-i",
        ssh_key,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        f"{ssh_user}@{ssh_host}",
        *journal_args,
    ]


def follow_node(
    node_name: str,
    command: list[str],
    stop_event: threading.Event,
    user_registry: UserRegistry,
) -> None:
    parser = NodeLogParser(
        node_name=node_name,
        user_registry=user_registry,
    )

    while not stop_event.is_set():
        print(
            f"[{node_name}] starting journal stream",
            flush=True,
        )

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as error:
            print(
                f"[{node_name}] stream start failed: {error}",
                flush=True,
            )
            stop_event.wait(RECONNECT_DELAY_SECONDS)
            continue

        assert process.stdout is not None

        try:
            for line in process.stdout:
                if stop_event.is_set():
                    break
                parser.feed(line)
        finally:
            if process.poll() is None:
                process.terminate()

            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

        if not stop_event.is_set():
            print(
                f"[{node_name}] journal stream ended; reconnecting",
                flush=True,
            )
            stop_event.wait(RECONNECT_DELAY_SECONDS)


def main() -> None:
    init_stats_db()

    base = load_base()
    env_values = load_env_file(ENV_FILE)
    stop_event = threading.Event()
    user_registry = UserRegistry()
    threads = []

    def stop_handler(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    for node_name, node in base.get("nodes", {}).items():
        if not node.get("enabled", True):
            continue

        stats_config = node.get("stats") or {}
        if not stats_config.get("enabled", True):
            continue

        command = build_journal_command(
            node_name,
            node,
            env_values,
        )

        thread = threading.Thread(
            target=follow_node,
            args=(
                node_name,
                command,
                stop_event,
                user_registry,
            ),
            name=f"stats-{node_name}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    print(
        f"stats collector started for {len(threads)} node(s)",
        flush=True,
    )

    last_cleanup = 0.0

    while not stop_event.wait(1):
        now = time.time()
        if now - last_cleanup >= CLEANUP_INTERVAL_SECONDS:
            try:
                cleanup_stats(int(now))
            except Exception as error:
                print(
                    f"stats cleanup failed: {error}",
                    flush=True,
                )
            last_cleanup = now

    print("stats collector stopping", flush=True)


if __name__ == "__main__":
    main()
