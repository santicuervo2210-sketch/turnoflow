from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User, UserRole

PASSWORD_ITERATIONS = 260_000
PASSWORD_RESET_TOKEN_SECONDS = 60 * 60
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${iterations}${salt}${digest}".format(
        iterations=PASSWORD_ITERATIONS,
        salt=base64.b64encode(salt).decode("ascii"),
        digest=base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected_digest = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt_bytes = base64.b64decode(salt)
        expected_digest_bytes = base64.b64decode(expected_digest)
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt_bytes,
            int(iterations),
        )
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(actual_digest, expected_digest_bytes)


def authenticate_user(session: Session, username: str, password: str) -> User | None:
    user = session.scalars(select(User).where(User.username == username)).first()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_user(
    session: Session,
    *,
    username: str,
    password: str,
    role: UserRole,
    barber_shop_id: int | None = None,
) -> User:
    user = User(
        username=username.strip(),
        password_hash=hash_password(password),
        role=role.value,
        barber_shop_id=barber_shop_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _reset_token_signature(payload: str) -> str:
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_password_reset_token(user: User, expires_in_seconds: int = PASSWORD_RESET_TOKEN_SECONDS) -> str:
    expires_at = int(time.time()) + expires_in_seconds
    payload = f"{user.id}:{expires_at}"
    signature = _reset_token_signature(payload)
    raw_token = f"{payload}:{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw_token).decode("ascii")


def reset_password_with_token(session: Session, token: str, new_password: str) -> User | None:
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return None

    try:
        raw_token = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        user_id_text, expires_at_text, signature = raw_token.rsplit(":", 2)
        payload = f"{user_id_text}:{expires_at_text}"
        expires_at = int(expires_at_text)
        user_id = int(user_id_text)
    except (ValueError, TypeError):
        return None

    if expires_at < int(time.time()):
        return None
    if not hmac.compare_digest(signature, _reset_token_signature(payload)):
        return None

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return None

    user.password_hash = hash_password(new_password)
    session.commit()
    session.refresh(user)
    return user
