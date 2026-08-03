from sqlalchemy import text

from app.db.session import build_engine


def test_build_engine_can_execute_sqlite_query() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")

    with engine.connect() as connection:
        result = connection.execute(text("select 1")).scalar_one()

    assert result == 1

