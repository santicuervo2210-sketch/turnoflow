from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BarberShop, BotCategoryDefault, BotServiceAlias, Service
from app.services.appointments import SchedulingError

BUSINESS_CATEGORIES = ("general", "barberia", "unas", "pestanas", "masajes", "tatuajes")
CATEGORY_LABELS = {
    "general": "General",
    "barberia": "Barberia / peluqueria",
    "unas": "Unas",
    "pestanas": "Pestanas y cejas",
    "masajes": "Masajes / spa",
    "tatuajes": "Tatuajes",
}
CATEGORY_DEFAULTS = {
    "general": {
        "corte": ("corte", "cortar", "cortarme", "pelo", "cabello"),
        "barba": ("barba", "afeitado", "afeitarme"),
        "unas": ("unas", "manicura", "manos", "nails"),
        "pestanas": ("pestanas", "pestana", "lashes"),
        "claritos": ("claritos", "mechas", "reflejos"),
    },
    "barberia": {
        "corte": ("corte", "cortar", "cortarme", "pelo", "cabello"),
        "barba": ("barba", "afeitado", "afeitarme"),
        "claritos": ("claritos", "mechas", "reflejos"),
    },
    "unas": {
        "manicura": ("manicura", "unas", "manos"),
        "semipermanente": ("semipermanente", "semi"),
        "esculpidas": ("esculpidas", "acrilicas"),
        "soft gel": ("soft gel", "softgel"),
    },
    "pestanas": {
        "lifting": ("lifting", "levantamiento"),
        "extensiones": ("extensiones", "pestanas", "lashes"),
        "volumen ruso": ("volumen ruso", "volumen"),
    },
    "masajes": {
        "descontracturante": ("descontracturante", "contractura"),
        "relajante": ("relajante", "relajacion"),
        "deportivo": ("deportivo", "deporte"),
    },
    "tatuajes": {
        "sesion": ("sesion", "tatuaje", "tatuarme"),
        "retoque": ("retoque", "retocar"),
        "cover up": ("cover up", "coverup", "cubrir"),
    },
}


@dataclass(frozen=True)
class CategoryDefaultPreview:
    service_term: str
    alias: str


def factory_defaults_for_category(category: str) -> list[CategoryDefaultPreview]:
    return [
        CategoryDefaultPreview(service_term=term, alias=alias)
        for term, aliases in CATEGORY_DEFAULTS.get(category, {}).items()
        for alias in aliases
    ]


def normalize_alias(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.strip().lower().split())


def ensure_category_defaults(session: Session) -> None:
    if session.scalars(select(BotCategoryDefault.id).limit(1)).first() is not None:
        return
    session.add_all(
        BotCategoryDefault(business_category=category, service_term=term, alias=alias)
        for category, terms in CATEGORY_DEFAULTS.items()
        for term, aliases in terms.items()
        for alias in aliases
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()


def category_defaults_for_shop(session: Session, shop: BarberShop) -> list[BotCategoryDefault]:
    ensure_category_defaults(session)
    return list(
        session.scalars(
            select(BotCategoryDefault)
            .where(BotCategoryDefault.business_category == shop.business_category)
            .order_by(BotCategoryDefault.service_term, BotCategoryDefault.alias)
        ).all()
    )


def alias_overrides_for_shop(session: Session, barber_shop_id: int) -> list[BotServiceAlias]:
    return list(
        session.scalars(
            select(BotServiceAlias)
            .where(BotServiceAlias.barber_shop_id == barber_shop_id)
            .order_by(BotServiceAlias.alias)
        ).all()
    )


def aliases_by_service(
    session: Session,
    shop: BarberShop,
    services: list[Service],
) -> dict[int, set[str]]:
    aliases = {service.id: set() for service in services}
    services_by_id = {service.id: service for service in services}
    overrides = alias_overrides_for_shop(session, shop.id)
    overrides_by_alias = {override.alias: override for override in overrides}

    for default in category_defaults_for_shop(session, shop):
        if default.alias in overrides_by_alias:
            continue
        for service in services:
            if normalize_alias(default.service_term) in normalize_alias(service.name):
                aliases[service.id].add(default.alias)

    for override in overrides:
        if override.is_active and override.service_id in services_by_id:
            aliases[override.service_id].add(override.alias)
    return aliases


def set_business_category(session: Session, barber_shop_id: int, category: str) -> BarberShop:
    if category not in BUSINESS_CATEGORIES:
        raise SchedulingError("El rubro seleccionado no es valido.")
    shop = session.get(BarberShop, barber_shop_id)
    if shop is None:
        raise SchedulingError("Negocio no encontrado.", 404)
    shop.business_category = category
    session.commit()
    session.refresh(shop)
    return shop


def save_service_alias(
    session: Session,
    barber_shop_id: int,
    service_id: int,
    alias: str,
) -> BotServiceAlias:
    normalized = normalize_alias(alias)
    if len(normalized) < 2 or len(normalized) > 80:
        raise SchedulingError("El alias debe tener entre 2 y 80 caracteres.")
    service = session.get(Service, service_id)
    if service is None or service.barber_shop_id != barber_shop_id:
        raise SchedulingError("El servicio no pertenece al negocio.")
    override = session.scalars(
        select(BotServiceAlias).where(
            BotServiceAlias.barber_shop_id == barber_shop_id,
            BotServiceAlias.alias == normalized,
        )
    ).first()
    if override is None:
        override = BotServiceAlias(barber_shop_id=barber_shop_id, alias=normalized)
        session.add(override)
    override.service_id = service_id
    override.is_active = True
    session.commit()
    session.refresh(override)
    return override


def suppress_default_alias(session: Session, barber_shop_id: int, alias: str) -> BotServiceAlias:
    normalized = normalize_alias(alias)
    override = session.scalars(
        select(BotServiceAlias).where(
            BotServiceAlias.barber_shop_id == barber_shop_id,
            BotServiceAlias.alias == normalized,
        )
    ).first()
    if override is None:
        override = BotServiceAlias(barber_shop_id=barber_shop_id, alias=normalized)
        session.add(override)
    override.service_id = None
    override.is_active = False
    session.commit()
    session.refresh(override)
    return override


def delete_alias_override(session: Session, barber_shop_id: int, alias_id: int) -> None:
    override = session.get(BotServiceAlias, alias_id)
    if override is None or override.barber_shop_id != barber_shop_id:
        raise SchedulingError("Alias no encontrado.", 404)
    session.delete(override)
    session.commit()
