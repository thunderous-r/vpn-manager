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

    DE_RENDERED_CONFIG_FILE = Path("/tmp/de-config.new.json")
    RU_RENDERED_CONFIG_FILE = Path("/tmp/ru-config.new.json")
else:
    USERS_FILE = PROJECT_DIR / "users.json"
    BASE_FILE = PROJECT_DIR / "base.json"

    DE_RENDERED_CONFIG_FILE = (
        PROJECT_DIR / "rendered" / "de-config.json"
    )

    RU_RENDERED_CONFIG_FILE = (
        PROJECT_DIR / "rendered" / "ru-config.json"
    )