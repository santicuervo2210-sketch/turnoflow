from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import hmac
from time import perf_counter
import re
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.api.routes import router as api_router
from app.core.config import settings
from app.core.logging import configure_logging, log_request_completed, log_unhandled_error
from app.db.init_db import create_db_tables
from app.db.session import get_db
from app.services.maintenance import cleanup_ephemeral_data
from app.web.auth import AdminAuthMiddleware
from app.web.routes import router as web_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    if settings.auto_create_tables:
        create_db_tables()
    yield


configure_logging()

app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(AdminAuthMiddleware)
app.include_router(api_router)
app.include_router(web_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    provided_request_id = request.headers.get("X-Request-ID", "")
    request_id = (
        provided_request_id
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", provided_request_id)
        else uuid4().hex
    )
    request.state.request_id = request_id
    started_at = perf_counter()
    response = await call_next(request)
    log_request_completed(
        request.method,
        request.url.path,
        response.status_code,
        (perf_counter() - started_at) * 1000,
        request_id,
    )
    response.headers.setdefault("X-Request-ID", request_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
        "font-src 'self' data:; connect-src 'self'; upgrade-insecure-requests",
    )
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()",
    )
    if settings.environment == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=86400")
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    log_unhandled_error(request.method, request.url.path, exc, request_id)
    response = JSONResponse({"detail": "Error interno del servidor."}, status_code=500)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.get("/internal/maintenance")
def run_maintenance(request: Request, session: Session = Depends(get_db)) -> dict:
    expected = f"Bearer {settings.cron_secret}" if settings.cron_secret else ""
    provided = request.headers.get("Authorization", "")
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="No autorizado.")
    return {"status": "ok", "deleted": cleanup_ephemeral_data(session)}
