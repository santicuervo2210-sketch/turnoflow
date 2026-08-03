from __future__ import annotations

import json
from datetime import date
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Barber, Customer, Service


class BotIntent(BaseModel):
    intent: Literal[
        "list_services",
        "list_barbers",
        "list_customers",
        "check_availability",
        "create_appointment",
        "unknown",
    ] = "unknown"
    barber_id: int | None = None
    service_id: int | None = None
    customer_id: int | None = None
    target_date: str | None = Field(default=None, description="Date in YYYY-MM-DD format.")
    target_time: str | None = Field(default=None, description="Time in HH:MM format.")
    reply: str | None = None


def _compact_catalog(session: Session, barber_shop_id: int) -> str:
    services = session.scalars(
        select(Service)
        .where(Service.barber_shop_id == barber_shop_id, Service.is_active.is_(True))
        .order_by(Service.id)
    ).all()
    barbers = session.scalars(
        select(Barber)
        .where(Barber.barber_shop_id == barber_shop_id, Barber.is_active.is_(True))
        .order_by(Barber.id)
    ).all()
    customers = session.scalars(
        select(Customer).where(Customer.barber_shop_id == barber_shop_id).order_by(Customer.id)
    ).all()

    service_lines = [f"{item.id}: {item.name} ({item.duration_minutes} min)" for item in services]
    barber_lines = [f"{item.id}: {item.name}" for item in barbers]
    customer_lines = [f"{item.id}: {item.full_name} ({item.phone})" for item in customers]

    return (
        "Servicios:\n"
        + "\n".join(service_lines or ["Sin servicios"])
        + "\n\nProfesionales:\n"
        + "\n".join(barber_lines or ["Sin profesionales"])
        + "\n\nClientes:\n"
        + "\n".join(customer_lines or ["Sin clientes"])
    )


def _build_messages(session: Session, user_message: str, barber_shop_id: int) -> list[dict[str, str]]:
    today = date.today().isoformat()
    schema_hint = (
        "Responde solo JSON valido con estas claves: "
        "intent, barber_id, service_id, customer_id, target_date, target_time, reply. "
        "intent debe ser uno de: list_services, list_barbers, list_customers, "
        "check_availability, create_appointment, unknown. "
        "Usa target_date en formato YYYY-MM-DD y target_time en HH:MM. "
        "Si faltan datos para reservar, usa check_availability o unknown y explica en reply."
    )
    return [
        {
            "role": "system",
            "content": (
                "Sos el clasificador de intenciones de TurnoFlow. "
                "Convertis mensajes de clientes en una accion estructurada. "
                "No inventes IDs: usa solamente el catalogo disponible. "
                f"Fecha actual: {today}. {schema_hint}"
            ),
        },
        {"role": "user", "content": _compact_catalog(session, barber_shop_id)},
        {"role": "user", "content": user_message},
    ]


def _parse_json_content(content: str) -> BotIntent | None:
    try:
        return BotIntent.model_validate_json(content)
    except ValidationError:
        pass

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        return BotIntent.model_validate(json.loads(content[start : end + 1]))
    except (json.JSONDecodeError, ValidationError):
        return None


def classify_with_ollama(session: Session, user_message: str, barber_shop_id: int) -> BotIntent | None:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": _build_messages(session, user_message, barber_shop_id),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }

    try:
        response = httpx.post(url, json=payload, timeout=settings.ollama_timeout_seconds)
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    content = response.json().get("message", {}).get("content", "")
    return _parse_json_content(content)


def classify_with_ai(session: Session, user_message: str, barber_shop_id: int) -> BotIntent | None:
    if settings.bot_ai_provider.lower() != "ollama":
        return None
    return classify_with_ollama(session, user_message, barber_shop_id)
