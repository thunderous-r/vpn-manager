import json

from config import BASE_FILE


def load_base():
    return json.loads(
        BASE_FILE.read_text(encoding="utf-8")
    )


def get_node(base: dict, node_name: str) -> dict:
    try:
        return base["nodes"][node_name]
    except KeyError as error:
        raise RuntimeError(
            f"Unknown VPN node: {node_name}"
        ) from error


def build_vless_uri(
    uuid: str,
    name: str,
    node_name: str = "de",
):
    base = load_base()
    node = get_node(base, node_name)

    reality = node["reality"]
    location = node["meta"]["location"]

    return (
        f"vless://{uuid}"
        f"@{reality['domain']}:{reality['listen_port']}"
        f"?security=reality"
        f"&sni={reality['server_name']}"
        f"&fp=chrome"
        f"&pbk={reality['public_key']}"
        f"&sid={reality['short_id']}"
        f"&type=tcp"
        f"&encryption=none"
        f"#{location}-Reality-{name}"
    )


def build_hy2_uri(
    password: str,
    name: str,
    node_name: str = "de",
):
    base = load_base()
    node = get_node(base, node_name)

    hy2 = node["hy2"]
    location = node["meta"]["location"]

    return (
        f"hy2://{password}"
        f"@{hy2['domain']}:{hy2['listen_port']}/"
        f"?sni={hy2['domain']}"
        f"#{location}-HY2-{name}"
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

    return (
        f"{scheme}://{panel['domain']}"
        f":{panel['port']}"
        f"/sub/{token}"
    )