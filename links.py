import json
from config import BASE_FILE


def load_base():
    return json.loads(BASE_FILE.read_text(encoding="utf-8"))


def build_vless_uri(uuid: str, name: str):
    base = load_base()

    public_key = base["reality"]["public_key"]

    return (
        f"vless://{uuid}"
        f"@{base['reality']['domain']}:{base['reality']['listen_port']}"
        f"?security=reality"
        f"&sni={base['reality']['server_name']}"
        f"&fp=chrome"
        f"&pbk={public_key}"
        f"&sid={base['reality']['short_id']}"
        f"&type=tcp"
        f"&encryption=none"
        f"#{base['meta']['location']}-Reality-{name}"
    )


def build_hy2_uri(password: str, name: str):
    base = load_base()

    return (
        f"hy2://{password}"
        f"@{base['hy2']['domain']}:{base['hy2']['listen_port']}/"
        f"?sni={base['hy2']['domain']}"
        f"#{base['meta']['location']}-HY2-{name}"
    )


def build_subscription_url(token: str):
    base = load_base()

    panel = base["panel"]

    return (
        f"https://{panel['domain']}"
        f":{panel['port']}"
        f"/sub/{token}"
    )