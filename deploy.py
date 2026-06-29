import shutil
import subprocess
import sys

NEW_CONFIG = "/tmp/config.new.json"
LIVE_CONFIG = "/etc/sing-box/config.json"


def run(cmd):
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )

    return result


check = run([
    "sing-box",
    "check",
    "-c",
    NEW_CONFIG
])

if check.returncode != 0:
    print("CONFIG INVALID")
    print(check.stderr)
    sys.exit(1)

backup = LIVE_CONFIG + ".bak"

shutil.copy2(
    LIVE_CONFIG,
    backup
)

shutil.copy2(
    NEW_CONFIG,
    LIVE_CONFIG
)

restart = run([
    "systemctl",
    "restart",
    "sing-box"
])

if restart.returncode != 0:
    print("RESTART FAILED")

    shutil.copy2(
        backup,
        LIVE_CONFIG
    )

    subprocess.run([
        "systemctl",
        "restart",
        "sing-box"
    ])

    sys.exit(1)

print("DEPLOY OK")
