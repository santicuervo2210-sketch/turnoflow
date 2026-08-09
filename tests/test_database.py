from sqlalchemy import text

import app.db.session as db_session_module
from app.db.session import build_engine


def test_build_engine_can_execute_sqlite_query() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")

    with engine.connect() as connection:
        result = connection.execute(text("select 1")).scalar_one()

    assert result == 1


def test_build_engine_disables_prepared_statements_for_postgres_poolers(monkeypatch) -> None:
    captured: dict = {}

    def fake_create_engine(database_url: str, **kwargs):
        captured["database_url"] = database_url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(db_session_module, "create_engine", fake_create_engine)

    build_engine("postgresql+psycopg://user:secret@pooler.example/turnoflow")

    assert captured["connect_args"] == {"prepare_threshold": None}
    assert captured["pool_pre_ping"] is True
