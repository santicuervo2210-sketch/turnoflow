from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import User, UserRole
from app.services.users import create_user


def main() -> None:
    if settings.admin_password in {"changeme", "change-me-before-deploy"}:
        raise SystemExit("ERROR: configura ADMIN_PASSWORD antes de crear el owner.")

    with SessionLocal() as session:
        existing_user = session.scalars(select(User).where(User.username == settings.admin_username)).first()
        if existing_user is not None:
            print(f"OK: el usuario owner {settings.admin_username} ya existe.")
            return

        create_user(
            session,
            username=settings.admin_username,
            password=settings.admin_password,
            role=UserRole.OWNER,
        )
        print(f"OK: usuario owner {settings.admin_username} creado.")


if __name__ == "__main__":
    main()
