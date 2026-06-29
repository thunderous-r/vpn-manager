from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel
import json
import uuid
import secrets
import subprocess
from pathlib import Path
from links import build_vless_uri, build_hy2_uri

app = FastAPI(title="VPN Manager")

USERS_FILE = Path("users.json")

templates = Jinja2Templates(directory="templates")

class UserCreate(BaseModel):
    name: str


def load_users():
    if not USERS_FILE.exists():
        return {}

    return json.loads(USERS_FILE.read_text())


def find_user_by_token(token):
    users = load_users()

    for name, user in users.items():
        if user["token"] == token:
            return name, user

    return None, None


def save_users(data):
    USERS_FILE.write_text(
        json.dumps(data, indent=2)
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
    return load_users()


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
        "token": token
    }

    users[req.name] = user

    save_users(users)

    subprocess.run(
        ["python", "/opt/vpn-manager/render.py"],
        check=True
    )

    subprocess.run(
        ["python", "/opt/vpn-manager/deploy.py"],
        check=True
    )

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
        "subscription":
        f"https://do.donothing.dynv6.net/sub/{token}"
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

    subprocess.run(
        ["python", "/opt/vpn-manager/render.py"],
        check=True
    )

    subprocess.run(
        ["python", "/opt/vpn-manager/deploy.py"],
        check=True
    )

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

    return "\n".join([
        build_vless_uri(
            user["uuid"],
            name
        ),
        build_hy2_uri(
            user["hy2_password"],
            name
        )
    ])
