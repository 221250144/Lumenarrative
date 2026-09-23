"""Small, server-side account sessions; project authorization lives in API routes."""

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import AuthSession, SessionLocal, User

COOKIE_NAME = "xuguangji_session"
PASSWORD_ITERATIONS = 600_000
router = APIRouter(prefix="/api/v1/auth", tags=["account"])


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


# Unknown accounts still do the same password work as known accounts.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(24))
_attempts: dict[tuple[str, str], list[float]] = defaultdict(list)
_attempt_lock = threading.Lock()


def limit_attempts(request: Request, action: str, limit: int, window: int = 900):
    peer = request.client.host if request.client else "unknown"
    key = (action, peer)
    now = time.monotonic()
    with _attempt_lock:
        if len(_attempts) > 10_000:
            for old_key in list(_attempts):
                if not _attempts[old_key] or _attempts[old_key][-1] < now - 3600:
                    del _attempts[old_key]
        recent = [stamp for stamp in _attempts[key] if stamp > now - window]
        if len(recent) >= limit:
            raise HTTPException(429, "尝试次数较多，请稍后再试")
        _attempts[key] = [*recent, now]


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{3,32}", value):
            raise ValueError("账号需为 3–32 位字母、数字、下划线或短横线")
        return value


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def user_json(user):
    return {"id": user.id, "username": user.username}


def resolve_user(request: Request, db) -> User:
    token = request.cookies.get(COOKIE_NAME, "")
    if not token or len(token) > 256:
        raise HTTPException(401, "请先登录")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    user = db.scalar(
        select(User).join(AuthSession, AuthSession.user_id == User.id).where(
            AuthSession.token_hash == token_hash,
            AuthSession.expires_at > time.time(),
        )
    )
    if user is None:
        raise HTTPException(401, "登录已失效，请重新登录")
    return user


def authenticated_session(request: Request):
    with SessionLocal() as db:
        user = resolve_user(request, db)
        db.info["user_id"] = user.id
        db.info["request_method"] = request.method
        yield db


def issue_session(db, user, response: Response):
    token = secrets.token_urlsafe(32)
    lifetime = settings.auth_session_days * 86400
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= time.time()))
    db.add(AuthSession(user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                       expires_at=time.time() + lifetime))
    response.set_cookie(COOKIE_NAME, token, max_age=lifetime, httponly=True,
                        secure=settings.auth_cookie_secure, samesite="lax", path="/")


@router.post("/register", status_code=201)
def register(body: Credentials, request: Request, response: Response):
    limit_attempts(request, "register", 20, 3600)
    with SessionLocal() as db:
        user = User(username=body.username, password_hash=hash_password(body.password))
        db.add(user)
        try:
            db.flush()
            issue_session(db, user, response)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "这个账号名已被使用") from None
        return user_json(user)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    limit_attempts(request, "login", 30)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == body.username).with_for_update())
        valid = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
        if not user or not valid:
            raise HTTPException(401, "账号或密码不正确")
        issue_session(db, user, response)
        db.commit()
        return user_json(user)


@router.get("/me")
def me(request: Request):
    with SessionLocal() as db:
        return user_json(resolve_user(request, db))


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        with SessionLocal() as db:
            db.execute(delete(AuthSession).where(AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
            db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True,
                           secure=settings.auth_cookie_secure, samesite="lax")
    return {"ok": True}


@router.post("/password")
def change_password(body: PasswordChange, request: Request, response: Response):
    limit_attempts(request, "password", 15)
    with SessionLocal() as db:
        user = resolve_user(request, db)
        user = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
        if not verify_password(body.current_password, user.password_hash):
            raise HTTPException(400, "当前密码不正确")
        user.password_hash = hash_password(body.new_password)
        db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        issue_session(db, user, response)
        db.commit()
    return {"ok": True}
