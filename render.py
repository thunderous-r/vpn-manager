import json
from pathlib import Path

from config import (
    BASE_FILE,
    USERS_FILE,
    RENDERED_CONFIG_FILE,
)


def load_json(path: Path):
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def render_config() -> Path:
    base = load_json(BASE_FILE)
    users = load_json(USERS_FILE)

    enabled_users = [
        user
        for user in users.values()
        if user.get("enabled", True)
    ]

    vless_users = [
        {
            "uuid": user["uuid"]
        }
        for user in enabled_users
    ]

    hy2_users = [
        {
            "password": user["hy2_password"]
        }
        for user in enabled_users
    ]

    config = {
        "log": {
            "level": "info"
        },
        "inbounds": [
            {
                "type": "vless",
                "tag": "vless-reality",
                "listen": "::",
                "listen_port": base["reality"]["listen_port"],
                "users": vless_users,
                "tls": {
                    "enabled": True,
                    "server_name": base["reality"]["server_name"],
                    "reality": {
                        "enabled": True,
                        "handshake": {
                            "server": base["reality"]["server_name"],
                            "server_port": 443
                        },
                        "private_key": base["reality"]["private_key"],
                        "short_id": [
                            base["reality"]["short_id"]
                        ]
                    }
                }
            },
            {
                "type": "hysteria2",
                "tag": "hy2",
                "listen": "::",
                "listen_port": base["hy2"]["listen_port"],
                "users": hy2_users,
                "tls": {
                    "enabled": True,
                    "server_name": base["hy2"]["domain"],
                    "certificate_path": base["hy2"]["certificate_path"],
                    "key_path": base["hy2"]["key_path"]
                }
            }
        ],
        "outbounds": [
            {
                "type": "direct"
            }
        ]
    }

    RENDERED_CONFIG_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    RENDERED_CONFIG_FILE.write_text(
        json.dumps(
            config,
            indent=2
        ),
        encoding="utf-8"
    )

    return RENDERED_CONFIG_FILE


if __name__ == "__main__":
    output_file = render_config()
    print(f"Generated: {output_file}")