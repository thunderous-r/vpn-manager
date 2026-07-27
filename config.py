import os
from pathlib import Path


ENV = os.getenv("ENV", "development").lower()

if ENV not in {"development", "production"}:
    raise RuntimeError(
        f"Unsupported ENV value: {ENV!r}. "
        "Expected 'development' or 'production'."
    )


PROJECT_DIR = Path(__file__).resolve().parent


if ENV == "production":
    USERS_FILE = Path("/opt/vpn-manager/users.json")
    BASE_FILE = Path("/opt/vpn-manager/base.json")
    RENDERED_CONFIG_FILE = Path("/tmp/config.new.json")
else:
    USERS_FILE = PROJECT_DIR / "users.json"
    BASE_FILE = PROJECT_DIR / "base.json"
    RENDERED_CONFIG_FILE = PROJECT_DIR / "rendered" / "config.json"