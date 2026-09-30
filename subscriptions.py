import base64
import json

from config import PROJECT_DIR


CLIENT_ROUTING_FILE = PROJECT_DIR / "client-routing.json"


def load_client_routing() -> dict:
    return json.loads(
        CLIENT_ROUTING_FILE.read_text(encoding="utf-8")
    )


def get_default_routing_profile(config: dict) -> dict | None:
    profile_name = config.get("default_profile")

    if not profile_name:
        return None

    return config.get("profiles", {}).get(profile_name)


def encode_base64_text(value: str) -> str:
    return base64.b64encode(
        value.encode("utf-8")
    ).decode("ascii")


def build_routing_profile(profile: dict) -> dict:
    remote_dns = profile["remote_dns"]
    domestic_dns = profile["domestic_dns"]

    return {
        "Name": profile["name"],
        # Keep these values as strings for Happ/INCY compatibility.
        "GlobalProxy": (
            "true" if profile.get("global_proxy", True) else "false"
        ),
        "RemoteDNSType": remote_dns["type"],
        "RemoteDNSDomain": remote_dns.get("domain", ""),
        "RemoteDNSIP": remote_dns["ip"],
        "DomesticDNSType": domestic_dns["type"],
        "DomesticDNSDomain": domestic_dns.get("domain", ""),
        "DomesticDNSIP": domestic_dns["ip"],
        "Geoipurl": profile["geoip_url"],
        "Geositeurl": profile["geosite_url"],
        "LastUpdated": "",
        "DnsHosts": {},
        "DirectSites": profile.get("direct_sites", []),
        "DirectIp": profile.get("direct_ip", []),
        "ProxySites": profile.get("proxy_sites", []),
        "ProxyIp": profile.get("proxy_ip", []),
        "BlockSites": profile.get("block_sites", []),
        "BlockIp": profile.get("block_ip", []),
        "DomainStrategy": profile.get(
            "domain_strategy",
            "IPIfNonMatch",
        ),
        "FakeDNS": (
            "true" if profile.get("fake_dns", False) else "false"
        ),
    }


def encode_routing_profile(profile: dict) -> str:
    raw = json.dumps(
        build_routing_profile(profile),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return base64.b64encode(raw).decode("ascii")


def build_happ_routing_link(profile: dict) -> str:
    encoded = encode_routing_profile(profile)

    return f"happ://routing/add/{encoded}"


def build_incy_routing_link(profile: dict) -> str:
    encoded = encode_routing_profile(profile)

    return f"incy://routing/add/{encoded}"


def build_common_headers(config: dict) -> dict[str, str]:
    title = config.get("profile_title", "DoNothing VPN")
    filename = config.get("filename", "DoNothingVPN")
    update_interval = config.get("update_interval_hours", 24)

    return {
        "profile-title": (
            f"base64:{encode_base64_text(title)}"
        ),
        "profile-update-interval": str(update_interval),
        "content-disposition": (
            f'attachment; filename="{filename}"'
        ),
        "cache-control": (
            "no-store, no-cache, must-revalidate, max-age=0"
        ),
        "pragma": "no-cache",
        "vary": "User-Agent",
    }


def render_subscription(
    user_agent: str,
    links: list[str],
) -> tuple[str, dict[str, str]]:
    config = load_client_routing()
    headers = build_common_headers(config)
    client = user_agent.lower()
    profile = get_default_routing_profile(config)

    if "happ" in client:
        if profile is not None:
            headers["routing"] = build_happ_routing_link(profile)

        # Happ-specific switch: enable automatic subscription
        # refreshes; profile-update-interval above sets the cadence.
        headers["subscription-auto-update-open-enable"] = "1"

    elif "incy" in client:
        if profile is not None:
            headers["routing"] = build_incy_routing_link(profile)

    return "\n".join(links), headers
