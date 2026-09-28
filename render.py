import json
from pathlib import Path

from config import (
    BASE_FILE,
    USERS_FILE,
    rendered_config_file,
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
        {
            **user,
            "name": name,
        }
        for name, user in users.items()
        if user.get("enabled", True)
    ]


def build_vless_users(
    enabled_users: list[dict],
) -> list[dict]:
    return [
        {
            "name": user["name"],
            "uuid": user["uuid"],
        }
        for user in enabled_users
    ]


def build_hy2_users(
    enabled_users: list[dict],
) -> list[dict]:
    return [
        {
            "name": user["name"],
            "password": user["hy2_password"],
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
                "short_id": [reality["short_id"]],
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


def build_common_rules() -> list[dict]:
    return [
        {
            "action": "sniff",
        },
        {
            "protocol": "dns",
            "action": "hijack-dns",
        },
        {
            "protocol": "bittorrent",
            "action": "reject",
        },
    ]


def build_entry_rules() -> list[dict]:
    return [
        {
            "action": "sniff",
        },
        {
            "protocol": "bittorrent",
            "action": "reject",
        },
    ]


def build_dns() -> dict:
    return {
        "servers": [
            {
                "type": "https",
                "tag": "remote-dns",
                "server": "1.1.1.1",
                "server_port": 443,
                "path": "/dns-query",
                "tls": {
                    "enabled": True,
                    "server_name": "cloudflare-dns.com",
                },
            }
        ],
        "final": "remote-dns",
        "strategy": "ipv4_only",
    }


def build_exit_config(
    base: dict,
    node_name: str,
    vless_users: list[dict],
    hy2_users: list[dict],
) -> dict:
    node = base["nodes"][node_name]

    inbounds = [
        build_reality_inbound(
            node,
            vless_users,
        ),
        build_hy2_inbound(
            node,
            hy2_users,
        ),
    ]

    if node.get("accept_legacy_tunnel", False):
        tunnel = base["tunnel"]

        inbounds.append(
            {
                "type": "vless",
                "tag": "ru-tunnel",
                "listen": "::",
                "listen_port": tunnel["listen_port"],
                "users": [
                    {
                        "name": "__ru_tunnel",
                        "uuid": tunnel["uuid"],
                    }
                ],
                "tls": {
                    "enabled": True,
                    "server_name": tunnel["server_name"],
                    "certificate_path": tunnel["certificate_path"],
                    "key_path": tunnel["key_path"],
                },
            }
        )

    return {
        "log": {"level": "info"},
        "dns": build_dns(),
        "inbounds": inbounds,
        "outbounds": [
            {
                "type": "direct",
                "tag": "direct",
            }
        ],
        "route": {
            "rules": build_common_rules(),
            "final": "direct",
        },
    }


def build_ru_entry_config(
    base: dict,
    node_name: str,
    vless_users: list[dict],
    hy2_users: list[dict],
) -> dict:
    ru_node = base["nodes"][node_name]
    tunnel = base["tunnel"]
    routing = base["routing"]

    return {
        "log": {"level": "info"},
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
                *build_entry_rules(),
                {
                    "rule_set": routing["direct_rule_sets"],
                    "outbound": "direct",
                },
            ],
            "final": "de-out",
        },
    }


def render_config() -> dict[str, Path]:
    base = load_json(BASE_FILE)
    users = load_json(USERS_FILE)

    enabled_users = get_enabled_users(users)

    vless_users = build_vless_users(enabled_users)

    hy2_users = build_hy2_users(enabled_users)

    outputs = {}

    for node_name, node in base["nodes"].items():
        if not node.get("enabled", True):
            continue

        role = node.get("role")

        if role == "exit":
            config = build_exit_config(
                base,
                node_name,
                vless_users,
                hy2_users,
            )

        elif role == "ru-entry":
            config = build_ru_entry_config(
                base,
                node_name,
                vless_users,
                hy2_users,
            )

        else:
            raise RuntimeError(f"Unsupported role for node {node_name!r}: {role!r}")

        output = write_config(
            rendered_config_file(node_name),
            config,
        )

        outputs[node_name] = output

    return outputs


if __name__ == "__main__":
    outputs = render_config()

    for node_name, output in outputs.items():
        print(f"Generated {node_name}: {output}")
