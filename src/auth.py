import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from pwdlib.exceptions import HashVerificationError, UnknownHashError

TEACHERS_FILE = Path(__file__).parent / "teachers.json"
SESSION_COOKIE = "teacher_session"
SESSION_LIFETIME = 8 * 60 * 60

logger = logging.getLogger(__name__)
password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))
router = APIRouter(prefix="/auth", tags=["teacher authentication"])


@dataclass(frozen=True)
class TeacherSession:
    username: str
    password_hash: str
    csrf_token: str
    expires_at: float


sessions: dict[str, TeacherSession] = {}
sessions_lock = Lock()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


def read_teachers() -> dict[str, str]:
    with TEACHERS_FILE.open(encoding="utf-8") as file:
        teachers = json.load(file)
    if not isinstance(teachers, dict) or not all(
        isinstance(username, str)
        and username
        and isinstance(password_hash, str)
        and password_hash
        for username, password_hash in teachers.items()
    ):
        raise ValueError("The teacher credential file must map usernames to password hashes")
    return teachers


def load_teachers() -> dict[str, str]:
    try:
        return read_teachers()
    except (OSError, UnicodeError, ValueError) as error:
        logger.error("Unable to load teacher credentials: %s", error)
        raise HTTPException(
            status_code=503, detail="Teacher authentication is unavailable"
        ) from error


def get_teacher_session(request: Request) -> TeacherSession:
    token = request.cookies.get(SESSION_COOKIE)
    with sessions_lock:
        session = sessions.get(token) if token else None
        if session and session.expires_at <= monotonic():
            del sessions[token]
            session = None

    if not session:
        raise HTTPException(status_code=401, detail="Teacher login required")

    if load_teachers().get(session.username) != session.password_hash:
        with sessions_lock:
            sessions.pop(token, None)
        raise HTTPException(status_code=401, detail="Teacher login required")
    return session


def require_teacher(
    request: Request, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token")
) -> TeacherSession:
    session = get_teacher_session(request)
    if not csrf_token or not secrets.compare_digest(
        csrf_token.encode("utf-8"), session.csrf_token.encode("ascii")
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return session


def secure_cookie(request: Request) -> bool:
    return request.url.scheme == "https" or os.environ.get("TEACHER_COOKIE_SECURE") == "1"


@router.post("/login")
def login(credentials: LoginRequest, request: Request, response: Response):
    teachers = load_teachers()
    stored_hash = teachers.get(credentials.username)
    try:
        valid_password = password_hasher.verify(
            credentials.password, stored_hash if stored_hash is not None else dummy_hash
        )
    except (HashVerificationError, UnknownHashError) as error:
        logger.error("A teacher credential record contains an invalid password hash")
        raise HTTPException(
            status_code=503, detail="Teacher authentication is unavailable"
        ) from error
    if stored_hash is None or not valid_password:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = secrets.token_urlsafe(32)
    session = TeacherSession(
        username=credentials.username,
        password_hash=stored_hash,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=monotonic() + SESSION_LIFETIME,
    )
    with sessions_lock:
        for expired_token in [
            key for key, value in sessions.items() if value.expires_at <= monotonic()
        ]:
            del sessions[expired_token]
        old_token = request.cookies.get(SESSION_COOKIE)
        if old_token:
            sessions.pop(old_token, None)
        sessions[token] = session

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_LIFETIME,
        httponly=True,
        secure=secure_cookie(request),
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"username": session.username, "csrf_token": session.csrf_token}


@router.get("/session")
def current_session(
    response: Response, session: TeacherSession = Depends(get_teacher_session)
):
    response.headers["Cache-Control"] = "no-store"
    return {"username": session.username, "csrf_token": session.csrf_token}


@router.post("/logout", dependencies=[Depends(require_teacher)])
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    with sessions_lock:
        sessions.pop(token, None)
    response.delete_cookie(
        key=SESSION_COOKIE, httponly=True, secure=secure_cookie(request), samesite="strict"
    )
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Logged out"}
