from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings


def build_engine(database_url: str, pool_mode: str = "persistent") -> Engine:
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    elif database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        # Supavisor/PgBouncer can reuse a backend connection that already has
        # statement names from another client. Client-side prepares must stay off.
        connect_args = {"prepare_threshold": None}
    else:
        connect_args = {}

    engine_options: dict = {
        "connect_args": connect_args,
        "pool_pre_ping": True,
    }
    if pool_mode == "serverless" and not database_url.startswith("sqlite"):
        engine_options.update(poolclass=NullPool, pool_pre_ping=False)

    return create_engine(database_url, **engine_options)


engine = build_engine(settings.sqlalchemy_database_url, settings.database_pool_mode)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
