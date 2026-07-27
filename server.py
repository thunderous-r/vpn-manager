import json
import secrets
import uuid
import subprocess
import sys
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config import ENV, PROJECT_DIR, USERS_FILE
from links import (
    build_subscription_url,
    build_user_links,
    build_vless_uri,
    build_hy2_uri,
)
from render import render_config

app = FastAPI(title="VPN Manager")

templates = Jinja2Templates(
    directory=str(PROJECT_DIR / "templates")
)

env = os.environ.copy()

subprocess.run(
    [
        "/usr/bin/sudo",
        "--preserve-env=RU_SSH_HOST,RU_SSH_USER,RU_SSH_KEY",
        sys.executable,
        str(PROJECT_DIR / "deploy.py"),
    ],
    check=True,
    env=env,
)

class UserCreate(BaseModel):
    name: str


def apply_config():
    render_config()

    if ENV == "production":
        subprocess.run(
            [
                "/usr/bin/sudo",
                "--preserve-env=RU_SSH_HOST,RU_SSH_USER,RU_SSH_KEY",
                sys.executable,
                str(PROJECT_DIR / "deploy.py"),
            ],
            check=True,
            env=os.environ.copy(),
        )


def load_users():
    if not USERS_FILE.exists():
        return {}

    return json.loads(
        USERS_FILE.read_text(encoding="utf-8")
    )


def find_user_by_token(token):
    users = load_users()

    for name, user in users.items():
        if user["token"] == token:
            return name, user

    return None, None


def save_users(data):
    USERS_FILE.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@app.get("/admin")
def admin(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )


@app.get("/api/users")
def get_users():
    users = load_users()

    for user in users.values():
        user["subscription"] = build_subscription_url(user["token"])

    return users


@app.post("/api/user/create")
def create_user(req: UserCreate):
    users = load_users()

    if req.name in users:
        raise HTTPException(
            status_code=409,
            detail="User already exists"
        )

    token = secrets.token_urlsafe(24)

    user = {
        "uuid": str(uuid.uuid4()),
        "hy2_password": secrets.token_urlsafe(24),
        "token": token,
        "enabled": True
    }

    users[req.name] = user

    save_users(users)

    apply_config()
    
    return {
        **user,
        "vless_uri": build_vless_uri(
            user["uuid"],
            req.name
        ),
        "hy2_uri": build_hy2_uri(
            user["hy2_password"],
            req.name
        ),
        "subscription": build_subscription_url(token)
    }


@app.delete("/api/user/{name}")
def delete_user(name: str):
    users = load_users()

    if name not in users:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    del users[name]

    save_users(users)

    apply_config()

    return {
        "status": "deleted"
    }


@app.get(
    "/sub/{token}",
    response_class=PlainTextResponse
)
def subscription(token: str):
    name, user = find_user_by_token(token)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Subscription not found"
        )

    return "\n".join(
    build_user_links(
        uuid=user["uuid"],
        hy2_password=user["hy2_password"],
        name=name,
    )
)


@app.post("/api/users/{name}/disable")
def disable_user(name: str):

    users = load_users()

    if name not in users:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    users[name]["enabled"] = False

    save_users(users)

    apply_config()

    return {"status": "disabled"}


@app.post("/api/users/{name}/enable")
def enable_user(name: str):

    users = load_users()

    if name not in users:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    users[name]["enabled"] = True

    save_users(users)

    apply_config()

    return {"status": "enabled"}