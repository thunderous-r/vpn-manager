import json
from pathlib import Path

BASE_FILE = Path("/opt/vpn-manager/base.json")


def load_base():
    return json.loads(BASE_FILE.read_text())


def build_vless_uri(uuid: str, name: str):
    base = load_base()

    public_key = base["reality"]["public_key"]

    return (
        f"vless://{uuid}"
        f"@do.donothing.dynv6.net:443"
        f"?security=reality"
        f"&sni={base['reality']['server_name']}"
        f"&fp=chrome"
        f"&pbk={public_key}"
        f"&sid={base['reality']['short_id']}"
        f"&type=tcp"
        f"&encryption=none"
        f"#FRA-Reality-{name}"
    )


def build_hy2_uri(password: str, name: str):
    base = load_base()

    return (
        f"hy2://{password}"
        f"@{base['hy2']['domain']}:8443/"
        f"?sni={base['hy2']['domain']}"
        f"#FRA-HY2-{name}"
    )
