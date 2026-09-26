import os

os.environ.setdefault("ENV", "production")

import json
import shutil
import subprocess
import sys
from pathlib import Path

from config import (
    BASE_FILE,
    rendered_config_file,
)


SING_BOX_BIN = "/usr/bin/sing-box"
SYSTEMCTL_BIN = "/usr/bin/systemctl"

LOCAL_LIVE_CONFIG_FILE = Path(
    "/etc/sing-box/config.json"
)

ENV_FILE = Path("/etc/vpn-manager.env")


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values = {}

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        key, separator, value = line.partition("=")

        if not separator or not key.strip():
            raise RuntimeError(
                f"Invalid line {line_number} in {path}"
            )

        values[key.strip()] = value.strip().strip("\"'")

    return values


DEPLOY_ENV = load_env_file(ENV_FILE)

def load_base() -> dict:
    return json.loads(
        BASE_FILE.read_text(encoding="utf-8")
    )


def get_deploy_env(
    name: str,
    default: str | None = None,
) -> str | None:
    return (
        os.environ.get(name)
        or DEPLOY_ENV.get(name)
        or default
    )


def run_command(
    command: list[str],
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
    )


def require_root() -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError(
            "deploy.py must be run as root on production"
        )


def deploy_local(
    node_name: str,
    config_file: Path,
) -> None:
    print(f"Deploying {node_name} locally...")

    check = run_command([
        SING_BOX_BIN,
        "check",
        "-c",
        str(config_file),
    ])

    if check.returncode != 0:
        print(
            f"{node_name} CONFIG INVALID"
        )
        print(check.stderr)

        raise RuntimeError(
            f"{node_name} sing-box config "
            f"validation failed"
        )

    backup_file = Path(
        f"{LOCAL_LIVE_CONFIG_FILE}.bak"
    )

    shutil.copy2(
        LOCAL_LIVE_CONFIG_FILE,
        backup_file,
    )

    shutil.copy2(
        config_file,
        LOCAL_LIVE_CONFIG_FILE,
    )

    restart = run_command([
        SYSTEMCTL_BIN,
        "restart",
        "sing-box",
    ])

    if restart.returncode == 0:
        print(
            f"{node_name} LOCAL DEPLOY OK"
        )
        return

    print(
        f"{node_name} RESTART FAILED"
    )

    if restart.stderr:
        print(restart.stderr)

    shutil.copy2(
        backup_file,
        LOCAL_LIVE_CONFIG_FILE,
    )

    rollback_restart = run_command([
        SYSTEMCTL_BIN,
        "restart",
        "sing-box",
    ])

    if rollback_restart.returncode != 0:
        print(
            f"{node_name} ROLLBACK "
            f"RESTART FAILED"
        )

        if rollback_restart.stderr:
            print(rollback_restart.stderr)

    raise RuntimeError(
        f"{node_name} deploy failed; "
        f"config was rolled back"
    )


def upload_remote_config(
    node_name: str,
    config_file: Path,
    ssh_host: str,
    ssh_user: str,
    ssh_key: str,
    remote_temp_file: str,
) -> None:
    print(
        f"Uploading {node_name} config..."
    )

    upload = run_command([
        "/usr/bin/scp",
        "-i",
        ssh_key,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        str(config_file),
        (
            f"{ssh_user}@{ssh_host}:"
            f"{remote_temp_file}"
        ),
    ])

    if upload.returncode != 0:
        print(
            f"{node_name} CONFIG UPLOAD FAILED"
        )

        if upload.stderr:
            print(upload.stderr)

        raise RuntimeError(
            f"Failed to upload "
            f"{node_name} config"
        )


def deploy_remote(
    node_name: str,
    node: dict,
    config_file: Path,
) -> None:
    deploy = node["deploy"]

    env_prefix = deploy.get(
        "env_prefix",
        node_name.upper().replace("-", "_"),
    )

    ssh_host = get_deploy_env(
        f"{env_prefix}_SSH_HOST"
    )

    ssh_user = get_deploy_env(
        f"{env_prefix}_SSH_USER"
    )

    ssh_key = get_deploy_env(
        f"{env_prefix}_SSH_KEY"
    )

    if not ssh_host:
        raise RuntimeError(
            f"{env_prefix}_SSH_HOST "
            f"is not configured"
        )

    if not ssh_user:
        raise RuntimeError(
            f"{env_prefix}_SSH_USER "
            f"is not configured"
        )

    if not ssh_key:
        raise RuntimeError(
            f"{env_prefix}_SSH_KEY "
            f"is not configured"
        )

    remote_temp_file = deploy.get(
        "remote_temp_file",
        "/tmp/vpn-manager-config.new.json",
    )

    remote_helper = deploy.get(
        "remote_helper",
        "/usr/local/sbin/deploy-sing-box-config",
    )

    upload_remote_config(
        node_name=node_name,
        config_file=config_file,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_key=ssh_key,
        remote_temp_file=remote_temp_file,
    )

    print(
        f"Deploying {node_name} remotely..."
    )

    result = run_command([
        "/usr/bin/ssh",
        "-i",
        ssh_key,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        f"{ssh_user}@{ssh_host}",
        "sudo",
        "-n",
        remote_helper,
    ])

    if result.stdout:
        print(result.stdout)

    if result.returncode == 0:
        print(
            f"{node_name} REMOTE DEPLOY OK"
        )
        return

    print(
        f"{node_name} REMOTE DEPLOY FAILED"
    )

    if result.stderr:
        print(result.stderr)

    raise RuntimeError(
        f"{node_name} remote deploy failed; "
        f"remote rollback attempted"
    )


def deploy_configs() -> None:
    require_root()

    base = load_base()

    remote_nodes = []
    local_nodes = []

    for node_name, node in base["nodes"].items():
        if not node.get("enabled", True):
            continue

        deploy = node.get("deploy")

        if not deploy:
            raise RuntimeError(
                f"Deploy configuration missing "
                f"for node {node_name!r}"
            )

        mode = deploy.get("mode")

        config_file = rendered_config_file(
            node_name
        )

        if not config_file.exists():
            raise RuntimeError(
                f"{node_name} rendered config "
                f"not found: {config_file}"
            )

        item = (
            node_name,
            node,
            config_file,
        )

        if mode == "ssh":
            remote_nodes.append(item)

        elif mode == "local":
            local_nodes.append(item)

        else:
            raise RuntimeError(
                f"Unsupported deploy mode "
                f"for {node_name!r}: {mode!r}"
            )

    if len(local_nodes) > 1:
        raise RuntimeError(
            "More than one local node configured"
        )

    # Сначала удалённые ноды.
    # Локальный control-plane обновляем последним.
    for (
        node_name,
        node,
        config_file,
    ) in remote_nodes:
        deploy_remote(
            node_name,
            node,
            config_file,
        )

    for (
        node_name,
        _node,
        config_file,
    ) in local_nodes:
        deploy_local(
            node_name,
            config_file,
        )

    print("ALL NODES DEPLOYED")


if __name__ == "__main__":
    try:
        deploy_configs()
    except RuntimeError as error:
        print(error)
        sys.exit(1)