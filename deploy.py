import os
import shutil
import subprocess
import sys
from pathlib import Path


RENDERED_CONFIG_FILE = Path("/tmp/config.new.json")
LIVE_CONFIG_FILE = Path("/etc/sing-box/config.json")

SING_BOX_BIN = "/usr/bin/sing-box"
SYSTEMCTL_BIN = "/usr/bin/systemctl"


def run_command(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
    )


def deploy_config() -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError(
            "deploy_config() must be run as root on production"
        )

    check = run_command([
        "sing-box",
        "check",
        "-c",
        str(RENDERED_CONFIG_FILE),
    ])

    if check.returncode != 0:
        print("CONFIG INVALID")
        print(check.stderr)
        raise RuntimeError("sing-box config validation failed")

    backup_file = Path(f"{LIVE_CONFIG_FILE}.bak")

    shutil.copy2(
        LIVE_CONFIG_FILE,
        backup_file,
    )

    shutil.copy2(
        RENDERED_CONFIG_FILE,
        LIVE_CONFIG_FILE,
    )

    restart = run_command([
        "systemctl",
        "restart",
        "sing-box",
    ])

    if restart.returncode != 0:
        print("RESTART FAILED")
        print(restart.stderr)

        shutil.copy2(
            backup_file,
            LIVE_CONFIG_FILE,
        )

        rollback_restart = run_command([
            "systemctl",
            "restart",
            "sing-box",
        ])

        if rollback_restart.returncode != 0:
            print("ROLLBACK RESTART FAILED")
            print(rollback_restart.stderr)

        raise RuntimeError(
            "sing-box restart failed; config was rolled back"
        )

    print("DEPLOY OK")


if __name__ == "__main__":
    try:
        deploy_config()
    except RuntimeError as error:
        print(error)
        sys.exit(1)