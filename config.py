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
else:
    USERS_FILE = PROJECT_DIR / "users.json"
    BASE_FILE = PROJECT_DIR / "base.json"
    

def rendered_config_file(node_name: str) -> Path:
    if ENV == "production":
        return Path(
            f"/tmp/{node_name}-config.new.json"
        )

    return (
        PROJECT_DIR
        / "rendered"
        /f"{node_name}-config.json"
    )