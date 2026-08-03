from sqlalchemy import Column, ForeignKey, Table

from app.db.base import Base


barber_services = Table(
    "barber_services",
    Base.metadata,
    Column("barber_id", ForeignKey("barbers.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)

