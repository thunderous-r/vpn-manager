import json
from pathlib import Path

from config import (
    BASE_FILE,
    USERS_FILE,
    DE_RENDERED_CONFIG_FILE,
    RU_RENDERED_CONFIG_FILE,
)


def load_json(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def write_config(path: Path, config: dict) -> Path:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            config,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


def get_enabled_users(users: dict) -> list[dict]:
    return [
        user
        for user in users.values()
        if user.get("enabled", True)
    ]


def build_vless_users(
    enabled_users: list[dict],
) -> list[dict]:
    return [
        {
            "uuid": user["uuid"]
        }
        for user in enabled_users
    ]


def build_hy2_users(
    enabled_users: list[dict],
) -> list[dict]:
    return [
        {
            "password": user["hy2_password"]
        }
        for user in enabled_users
    ]


def build_reality_inbound(
    node: dict,
    users: list[dict],
) -> dict:
    reality = node["reality"]

    return {
        "type": "vless",
        "tag": "vless-reality",
        "listen": "::",
        "listen_port": reality["listen_port"],
        "users": users,
        "tls": {
            "enabled": True,
            "server_name": reality["server_name"],
            "reality": {
                "enabled": True,
                "handshake": {
                    "server": reality["server_name"],
                    "server_port": 443,
                },
                "private_key": reality["private_key"],
                "short_id": [
                    reality["short_id"]
                ],
            },
        },
    }


def build_hy2_inbound(
    node: dict,
    users: list[dict],
) -> dict:
    hy2 = node["hy2"]

    return {
        "type": "hysteria2",
        "tag": "hy2-in",
        "listen": "::",
        "listen_port": hy2["listen_port"],
        "users": users,
        "tls": {
            "enabled": True,
            "server_name": hy2["domain"],
            "certificate_path": hy2["certificate_path"],
            "key_path": hy2["key_path"],
        },
    }


def build_bittorrent_rules() -> list[dict]:
    return [
        {
            "action": "sniff",
        },
        {
            "protocol": "bittorrent",
            "action": "reject",
        },
    ]


def build_de_config(
    base: dict,
    vless_users: list[dict],
    hy2_users: list[dict],
) -> dict:
    de_node = base["nodes"]["de"]
    tunnel = base["tunnel"]

    return {
        "log": {
            "level": "info"
        },
        "inbounds": [
            build_reality_inbound(
                de_node,
                vless_users,
            ),
            build_hy2_inbound(
                de_node,
                hy2_users,
            ),
            {
                "type": "vless",
                "tag": "ru-tunnel",
                "listen": "::",
                "listen_port": tunnel["listen_port"],
                "users": [
                    {
                        "uuid": tunnel["uuid"]
                    }
                ],
                "tls": {
                    "enabled": True,
                    "server_name": tunnel["server_name"],
                    "certificate_path": tunnel[
                        "certificate_path"
                    ],
                    "key_path": tunnel["key_path"],
                },
            },
        ],
        "outbounds": [
            {
                "type": "direct",
                "tag": "direct",
            }
        ],
        "route": {
            "rules": build_bittorrent_rules(),
            "final": "direct",
        },
    }


def build_ru_config(
    base: dict,
    vless_users: list[dict],
    hy2_users: list[dict],
) -> dict:
    ru_node = base["nodes"]["ru"]
    tunnel = base["tunnel"]
    routing = base["routing"]

    return {
        "log": {
            "level": "info"
        },
        "experimental": {
            "cache_file": {
                "enabled": True,
                "path": "/var/lib/sing-box/cache.db",
            },
        },
        "inbounds": [
            build_reality_inbound(
                ru_node,
                vless_users,
            ),
            build_hy2_inbound(
                ru_node,
                hy2_users,
            ),
        ],
        "outbounds": [
            {
                "type": "direct",
                "tag": "direct",
            },
            {
                "type": "vless",
                "tag": "de-out",
                "server": tunnel["server"],
                "server_port": tunnel["listen_port"],
                "uuid": tunnel["uuid"],
                "tls": {
                    "enabled": True,
                    "server_name": tunnel["server_name"],
                },
            },
        ],
        "route": {
            "rule_set": routing["rule_sets"],
            "rules": [
                *build_bittorrent_rules(),
                {
                    "rule_set": routing[
                        "direct_rule_sets"
                    ],
                    "outbound": "direct",
                },
            ],
            "final": "de-out",
        },
    }


def render_config() -> tuple[Path, Path]:
    base = load_json(BASE_FILE)
    users = load_json(USERS_FILE)

    enabled_users = get_enabled_users(users)

    vless_users = build_vless_users(
        enabled_users
    )

    hy2_users = build_hy2_users(
        enabled_users
    )

    de_config = build_de_config(
        base,
        vless_users,
        hy2_users,
    )

    ru_config = build_ru_config(
        base,
        vless_users,
        hy2_users,
    )

    de_output = write_config(
        DE_RENDERED_CONFIG_FILE,
        de_config,
    )

    ru_output = write_config(
        RU_RENDERED_CONFIG_FILE,
        ru_config,
    )

    return de_output, ru_output


if __name__ == "__main__":
    de_file, ru_file = render_config()

    print(f"Generated DE: {de_file}")
    print(f"Generated RU: {ru_file}")