import json
from urllib.parse import quote
from config import BASE_FILE


def load_base():
    return json.loads(BASE_FILE.read_text(encoding="utf-8"))


def get_node(base: dict, node_name: str) -> dict:
    try:
        return base["nodes"][node_name]
    except KeyError as error:
        raise RuntimeError(f"Unknown VPN node: {node_name}") from error


def get_protocol_backend(base: dict, node: dict) -> dict:
    """Return exit's credentials for a TCP/UDP pass-through relay."""
    if node.get("role") != "relay":
        return node
    target_name = node.get("relay_to")
    target = base.get("nodes", {}).get(target_name)
    if (
        not target_name
        or not target
        or not target.get("enabled", True)
        or target.get("role") != "exit"
    ):
        raise RuntimeError(
            f"Relay backend {target_name!r} must be an enabled exit node"
        )
    return target


def build_vless_uri(
    uuid: str,
    name: str,
    node_name: str = "de",
):
    base = load_base()
    node = get_node(base, node_name)

    entry = node["reality"]
    reality = get_protocol_backend(base, node)["reality"]
    location = node["meta"]["location"]
    label = quote(
        f"{location}-Reality-{name}",
        safe="",
    )

    return (
        f"vless://{uuid}"
        f"@{entry['domain']}:{entry['listen_port']}"
        f"?security=reality"
        f"&sni={reality['server_name']}"
        f"&fp=firefox"
        f"&pbk={reality['public_key']}"
        f"&sid={reality['short_id']}"
        f"&type=tcp"
        f"&encryption=none"
        f"#{label}"
    )


def build_hy2_uri(
    password: str,
    name: str,
    node_name: str = "de",
):
    base = load_base()
    node = get_node(base, node_name)

    entry = node["hy2"]
    hy2 = get_protocol_backend(base, node)["hy2"]
    location = node["meta"]["location"]
    label = quote(
        f"{location}-HY2-{name}",
        safe="",
    )

    return (
        f"hy2://{password}"
        f"@{entry['domain']}:{entry['listen_port']}/"
        f"?sni={hy2['domain']}"
        f"#{label}"
    )


def build_user_links(
    uuid: str,
    hy2_password: str,
    name: str,
) -> list[str]:
    base = load_base()
    links = []

    for node_name, node in base["nodes"].items():
        if not node.get("enabled", True):
            continue

        if not node.get("publish", False):
            continue

        links.append(
            build_vless_uri(
                uuid,
                name,
                node_name,
            )
        )

        links.append(
            build_hy2_uri(
                hy2_password,
                name,
                node_name,
            )
        )

    return links


def build_subscription_url(token: str):
    base = load_base()

    panel = base["panel"]
    scheme = panel.get("scheme", "https")

    return f"{scheme}://{panel['domain']}:{panel['port']}/sub/{token}"
