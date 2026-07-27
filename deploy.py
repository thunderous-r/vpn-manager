import os
import shutil
import subprocess
import sys
from pathlib import Path

from config import (
    DE_RENDERED_CONFIG_FILE,
    RU_RENDERED_CONFIG_FILE,
)


SING_BOX_BIN = "/usr/bin/sing-box"
SYSTEMCTL_BIN = "/usr/bin/systemctl"

DE_LIVE_CONFIG_FILE = Path("/etc/sing-box/config.json")

RU_SSH_HOST = "ru.donothing.dynv6.net"
RU_SSH_USER = "sergey"
RU_REMOTE_TEMP_FILE = "/tmp/ru-config.new.json"
RU_LIVE_CONFIG_FILE = "/etc/sing-box/config.json"


def run_command(
    command: list[str],
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
    )


def require_root() -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError(
            "deploy.py must be run as root on production"
        )


def deploy_local_de() -> None:
    print("Deploying DE config...")

    check = run_command([
        SING_BOX_BIN,
        "check",
        "-c",
        str(DE_RENDERED_CONFIG_FILE),
    ])

    if check.returncode != 0:
        print("DE CONFIG INVALID")
        print(check.stderr)
        raise RuntimeError(
            "DE sing-box config validation failed"
        )

    backup_file = Path(
        f"{DE_LIVE_CONFIG_FILE}.bak"
    )

    shutil.copy2(
        DE_LIVE_CONFIG_FILE,
        backup_file,
    )

    shutil.copy2(
        DE_RENDERED_CONFIG_FILE,
        DE_LIVE_CONFIG_FILE,
    )

    restart = run_command([
        SYSTEMCTL_BIN,
        "restart",
        "sing-box",
    ])

    if restart.returncode == 0:
        print("DE DEPLOY OK")
        return

    print("DE RESTART FAILED")
    print(restart.stderr)

    shutil.copy2(
        backup_file,
        DE_LIVE_CONFIG_FILE,
    )

    rollback_restart = run_command([
        SYSTEMCTL_BIN,
        "restart",
        "sing-box",
    ])

    if rollback_restart.returncode != 0:
        print("DE ROLLBACK RESTART FAILED")
        print(rollback_restart.stderr)

    raise RuntimeError(
        "DE deploy failed; config was rolled back"
    )


def upload_ru_config() -> None:
    print("Uploading RU config...")

    upload = run_command([
        "/usr/bin/scp",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        str(RU_RENDERED_CONFIG_FILE),
        (
            f"{RU_SSH_USER}@{RU_SSH_HOST}:"
            f"{RU_REMOTE_TEMP_FILE}"
        ),
    ])

    if upload.returncode != 0:
        print("RU CONFIG UPLOAD FAILED")
        print(upload.stderr)
        raise RuntimeError(
            "Failed to upload RU config"
        )


def deploy_remote_ru() -> None:
    upload_ru_config()

    print("Deploying RU config...")

    remote_script = f"""
set -eu

TEMP_FILE="{RU_REMOTE_TEMP_FILE}"
LIVE_FILE="{RU_LIVE_CONFIG_FILE}"
BACKUP_FILE="${{LIVE_FILE}}.bak"

sudo {SING_BOX_BIN} check -c "$TEMP_FILE"

sudo cp --preserve=mode,ownership,timestamps \
    "$LIVE_FILE" \
    "$BACKUP_FILE"

sudo cp "$TEMP_FILE" "$LIVE_FILE"

if sudo {SYSTEMCTL_BIN} restart sing-box; then
    rm -f "$TEMP_FILE"
    echo "RU DEPLOY OK"
    exit 0
fi

echo "RU RESTART FAILED, ROLLING BACK"

sudo cp "$BACKUP_FILE" "$LIVE_FILE"

if ! sudo {SYSTEMCTL_BIN} restart sing-box; then
    echo "RU ROLLBACK RESTART FAILED" >&2
fi

exit 1
"""

    deploy = run_command(
        [
            "/usr/bin/ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            f"{RU_SSH_USER}@{RU_SSH_HOST}",
            "/bin/bash",
            "-s",
        ],
        input_text=remote_script,
    )

    if deploy.stdout:
        print(deploy.stdout)

    if deploy.returncode != 0:
        print("RU DEPLOY FAILED")

        if deploy.stderr:
            print(deploy.stderr)

        raise RuntimeError(
            "RU deploy failed; remote rollback attempted"
        )


def deploy_configs() -> None:
    require_root()

    if not DE_RENDERED_CONFIG_FILE.exists():
        raise RuntimeError(
            f"DE rendered config not found: "
            f"{DE_RENDERED_CONFIG_FILE}"
        )

    if not RU_RENDERED_CONFIG_FILE.exists():
        raise RuntimeError(
            f"RU rendered config not found: "
            f"{RU_RENDERED_CONFIG_FILE}"
        )

    # Сначала обновляем RU. Пока RU не принял новых
    # пользователей, DE остаётся в прежнем состоянии.
    deploy_remote_ru()

    # После успешного RU-деплоя обновляем DE.
    deploy_local_de()

    print("ALL NODES DEPLOYED")


if __name__ == "__main__":
    try:
        deploy_configs()
    except RuntimeError as error:
        print(error)
        sys.exit(1)