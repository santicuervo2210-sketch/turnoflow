from __future__ import annotations

import hashlib
import hmac
import secrets
from http import HTTPStatus
from urllib.parse import parse_qs

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response
from starlette.types import ASGIApp

from app.core.config import settings
from app.models import User, UserRole

SESSION_COOKIE_NAME = "turnoflow_session"
CSRF_COOKIE_NAME = "turnoflow_csrf"
CSRF_FORM_FIELD = "csrf_token"
PROTECTED_PATH_PREFIXES = (
    "/admin",
    "/api",
    "/bot-simulator",
    "/customer",
    "/docs",
    "/redoc",
    "/openapi.json",
)
PUBLIC_PATH_PREFIXES = ("/login", "/logout", "/password-reset", "/health", "/static")


def _sign(value: str) -> str:
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_session_cookie_value(subject: str) -> str:
    signature = _sign(subject)
    return f"{subject}:{signature}"


def create_csrf_token() -> str:
    nonce = secrets.token_urlsafe(32)
    signature = _sign(f"csrf:{nonce}")
    return f"{nonce}:{signature}"


def is_valid_signed_csrf_token(token: str | None) -> bool:
    if not token or ":" not in token:
        return False

    nonce, signature = token.rsplit(":", 1)
    return hmac.compare_digest(signature, _sign(f"csrf:{nonce}"))


def is_valid_csrf_token(cookie_value: str | None, form_value: str | None) -> bool:
    if not cookie_value or not form_value:
        return False
    return hmac.compare_digest(cookie_value, form_value) and is_valid_signed_csrf_token(cookie_value)


def csrf_token_for_request(request: Request) -> str:
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
    if is_valid_signed_csrf_token(cookie_value):
        return cookie_value
    return create_csrf_token()


def parse_session_subject(cookie_value: str | None) -> str | None:
    if not cookie_value or ":" not in cookie_value:
        return None

    subject, signature = cookie_value.rsplit(":", 1)
    if not hmac.compare_digest(signature, _sign(subject)):
        return None
    return subject


def is_valid_session_cookie(cookie_value: str | None) -> bool:
    return parse_session_subject(cookie_value) is not None


def session_subject_for_user(user: User) -> str:
    return f"user:{user.id}:{user.role}"


def session_subject_for_env_owner(username: str) -> str:
    return f"env:{username}:{UserRole.OWNER.value}"


def is_owner_session_cookie(cookie_value: str | None) -> bool:
    subject = parse_session_subject(cookie_value)
    return subject is not None and subject.endswith(f":{UserRole.OWNER.value}")


def validate_admin_credentials(username: str, password: str) -> bool:
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(
        password,
        settings.admin_password,
    )


def set_session_cookie(response: Response, subject: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_cookie_value(subject),
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=60 * 60 * 12,
    )


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=60 * 60 * 12,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)


def _is_public_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


def _is_protected_path(path: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in PROTECTED_PATH_PREFIXES)


def _requires_csrf(path: str, method: str) -> bool:
    return method.upper() == "POST" and (
        path == "/admin"
        or path.startswith("/admin/")
        or path.startswith("/owner")
        or path == "/bot-simulator"
        or path.startswith("/bot-simulator/")
    )


async def _csrf_form_token(request: Request) -> str | None:
    body = await request.body()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request._receive = receive
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" not in content_type:
        return None

    parsed_form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    values = parsed_form.get(CSRF_FORM_FIELD)
    return values[0] if values else None


class AdminAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        if not settings.auth_enabled:
            return await call_next(request)

        path = request.url.path
        if _is_public_path(path) or not _is_protected_path(path):
            return await call_next(request)

        cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
        if is_valid_session_cookie(cookie_value):
            if (path.startswith("/api") or path in {"/docs", "/redoc", "/openapi.json"}) and not is_owner_session_cookie(
                cookie_value
            ):
                return Response("Acceso prohibido.", status_code=HTTPStatus.FORBIDDEN)
            if _requires_csrf(path, request.method):
                form_token = await _csrf_form_token(request)
                csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
                if not is_valid_csrf_token(csrf_cookie, form_token):
                    return Response("Token CSRF invalido.", status_code=HTTPStatus.FORBIDDEN)
            return await call_next(request)

        if path.startswith("/api") or path in {"/openapi.json"}:
            return Response("No autorizado.", status_code=HTTPStatus.UNAUTHORIZED)

        return RedirectResponse(f"/login?next={path}", status_code=HTTPStatus.SEE_OTHER)
