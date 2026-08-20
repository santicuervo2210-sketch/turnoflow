from datetime import UTC, datetime, timedelta
from decimal import Decimal
import re

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Appointment, AppointmentStatus, Barber, BarberShop, Customer, Service, SupplySale
import app.web.routes as web_routes


def _csrf_token_from(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


def test_dashboard_normalizes_postgres_timezone_datetimes() -> None:
    postgres_value = datetime(2026, 8, 3, 20, 30, tzinfo=UTC)

    assert web_routes._as_naive_datetime(postgres_value) == datetime(2026, 8, 3, 20, 30)


def test_dashboard_groups_monday_booking_as_tomorrow_on_sunday_in_argentina(
    client: TestClient,
    monkeypatch,
) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Agenda Argentina"}).json()["id"]
    service_id = client.post(
        "/api/services",
        json={"barber_shop_id": shop_id, "name": "Corte", "duration_minutes": 30, "price": "10000"},
    ).json()["id"]
    barber_id = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Santino", "service_ids": [service_id]},
    ).json()["id"]
    client.post(
        "/api/working-schedules",
        json={"barber_id": barber_id, "day_of_week": 0, "start_time": "09:00:00", "end_time": "19:00:00"},
    )
    customer_id = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Turno del lunes"},
    ).json()["id"]
    client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-10T10:00:00",
        },
    )
    monkeypatch.setattr(web_routes, "_business_now", lambda: datetime(2026, 8, 9, 21, 0))

    dashboard = client.get("/admin")

    assert dashboard.status_code == 200
    assert "Hoy no hay turnos activos" in dashboard.text
    assert "Mañana" in dashboard.text
    assert "Turno del lunes" in dashboard.text
    assert "Manana" not in dashboard.text


def test_daily_checkout_completes_payment_and_reveals_next_customer(
    client: TestClient,
    monkeypatch,
) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Flujo diario"}).json()["id"]
    service_id = client.post(
        "/api/services",
        json={"barber_shop_id": shop_id, "name": "Corte", "duration_minutes": 30, "price": "10000"},
    ).json()["id"]
    barber_id = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Profesional", "service_ids": [service_id]},
    ).json()["id"]
    client.post(
        "/api/working-schedules",
        json={"barber_id": barber_id, "day_of_week": 0, "start_time": "09:00:00", "end_time": "19:00:00"},
    )
    current_customer_id = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Cliente actual"},
    ).json()["id"]
    next_customer_id = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Cliente siguiente"},
    ).json()["id"]
    current_appointment = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": current_customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-10T10:00:00",
        },
    ).json()
    next_appointment = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": next_customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-10T11:00:00",
        },
    ).json()
    monkeypatch.setattr(web_routes, "_business_now", lambda: datetime(2026, 8, 10, 10, 15))

    before = client.get("/admin")
    assert "Cliente actual" in before.text
    assert "Cobrar y finalizar" in before.text
    assert "Más opciones" in before.text
    assert (
        f'data-appointment-id="{next_appointment["id"]}" data-next-appointment="true"'
        in before.text
    )

    checkout = client.post(
        f'/admin/appointments/{current_appointment["id"]}/checkout',
        data={"payment_method": "Transferencia"},
        follow_redirects=False,
    )
    assert checkout.status_code == 303
    assert checkout.headers["location"] == "/admin?module=agenda"

    appointments = client.get("/api/appointments").json()
    completed = next(item for item in appointments if item["id"] == current_appointment["id"])
    assert completed["status"] == "completed"
    assert completed["is_paid"] is True
    assert completed["payment_method"] == "Transferencia"

    after = client.get("/admin")
    assert f'data-appointment-id="{current_appointment["id"]}" data-next-appointment="true"' not in after.text
    assert f'data-appointment-id="{next_appointment["id"]}" data-next-appointment="true"' in after.text


def test_admin_dashboard_loads(client: TestClient) -> None:
    response = client.get("/admin")

    assert response.status_code == 200
    assert "TurnoFlow" in response.text
    assert "Agenda de hoy" in response.text
    assert response.text.count("data-admin-module-panel=") == 6
    assert 'data-admin-module-panel="agenda"' in response.text
    assert 'data-admin-module-panel="clientes"' in response.text
    assert 'data-admin-module-panel="rendimiento"' in response.text
    assert "window.history.pushState" in response.text


def test_admin_modules_expose_fast_daily_controls_without_duplicate_schedule_button(client: TestClient) -> None:
    response = client.get("/admin")

    assert 'data-list-search="customers"' in response.text
    assert 'data-range-days="0"' in response.text
    assert 'data-range-days="7"' in response.text
    assert 'data-range-days="30"' in response.text
    assert "Sin profesional asignado" not in response.text
    assert 'data-bs-target="#scheduleModal"' not in response.text
    assert "Resumen semanal" in response.text
    assert response.text.count('data-bs-target="#appointmentModal"') == 1


def test_performance_totals_respect_selected_date_range(db_session: Session) -> None:
    shop = BarberShop(name="Rendimiento por fecha")
    service = Service(
        barber_shop=shop,
        name="Servicio",
        duration_minutes=30,
        price=Decimal("100.00"),
    )
    barber = Barber(barber_shop=shop, name="Profesional")
    customer = Customer(barber_shop=shop, full_name="Cliente")
    db_session.add_all([shop, service, barber, customer])
    db_session.flush()
    for starts_at in (datetime(2026, 8, 1, 10, 0), datetime(2026, 8, 10, 10, 0)):
        db_session.add(
            Appointment(
                barber_shop_id=shop.id,
                barber_id=barber.id,
                customer_id=customer.id,
                service_id=service.id,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30),
                status=AppointmentStatus.COMPLETED.value,
                is_paid=True,
                paid_at=starts_at,
            )
        )
    db_session.add_all(
        [
            SupplySale(
                barber_shop_id=shop.id,
                name="Producto incluido",
                quantity=1,
                unit_price=Decimal("50.00"),
                created_at=datetime(2026, 8, 1, 12, 0),
            ),
            SupplySale(
                barber_shop_id=shop.id,
                name="Producto excluido",
                quantity=1,
                unit_price=Decimal("70.00"),
                created_at=datetime(2026, 8, 10, 12, 0),
            ),
        ]
    )
    db_session.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/admin",
            "query_string": b"module=rendimiento&start_date=2026-08-01&end_date=2026-08-01",
            "headers": [],
        }
    )

    context = web_routes._dashboard_context(request, db_session, shop_id=shop.id)

    assert context["stats"]["completed_revenue"] == Decimal("100.00")
    assert context["stats"]["supply_revenue"] == Decimal("50.00")
    assert [sale.name for sale in context["supply_sales"]] == ["Producto incluido"]


def test_login_is_focused_and_does_not_show_private_navigation(client: TestClient) -> None:
    response = client.get("/login")

    assert response.status_code == 200
    assert 'class="auth-page"' in response.text
    assert "Bienvenido" in response.text
    assert "Entrar al panel" in response.text
    assert 'href="/owner"' not in response.text
    assert 'href="/admin"' not in response.text


def test_admin_dashboard_keeps_database_round_trips_bounded(client: TestClient) -> None:
    client.post(
        "/admin/barber-shops",
        data={
            "name": "Performance Demo",
            "main_barber_name": "Profesional",
        },
        follow_redirects=False,
    )
    client.get("/admin")  # Initializes optional per-shop settings once.

    select_count = 0

    def count_selects(execute_state) -> None:
        nonlocal select_count
        if execute_state.is_select:
            select_count += 1

    event.listen(Session, "do_orm_execute", count_selects)
    try:
        response = client.get("/admin")
    finally:
        event.remove(Session, "do_orm_execute", count_selects)

    assert response.status_code == 200
    assert select_count <= 14


def test_dashboard_paginates_large_appointment_history_in_database(db_session: Session) -> None:
    shop = BarberShop(name="Historial Grande")
    service = Service(
        barber_shop=shop,
        name="Servicio",
        duration_minutes=30,
        price=Decimal("10000.00"),
    )
    barber = Barber(barber_shop=shop, name="Profesional")
    customer = Customer(barber_shop=shop, full_name="Cliente")
    db_session.add_all([shop, service, barber, customer])
    db_session.flush()
    starts_at = datetime(2025, 1, 1, 9, 0)
    db_session.add_all(
        Appointment(
            barber_shop_id=shop.id,
            barber_id=barber.id,
            customer_id=customer.id,
            service_id=service.id,
            starts_at=starts_at + timedelta(days=index),
            ends_at=starts_at + timedelta(days=index, minutes=30),
            status=AppointmentStatus.COMPLETED.value,
        )
        for index in range(250)
    )
    db_session.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/admin",
            "query_string": b"",
            "headers": [],
        }
    )

    context = web_routes._dashboard_context(request, db_session, shop_id=shop.id)

    assert context["stats"]["appointments"] == 250
    assert len(context["appointments"]) == 50


def test_security_headers_are_present(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "browser-request-123"})

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["Permissions-Policy"]
    assert response.headers["X-Request-ID"] == "browser-request-123"


def test_admin_modules_load_once_and_only_selected_panel_is_visible(client: TestClient) -> None:
    agenda_response = client.get("/admin")
    services_response = client.get("/admin?module=servicios")

    assert agenda_response.status_code == 200
    assert "Agenda del negocio" in agenda_response.text
    assert "Precios, duración y oferta" in agenda_response.text
    assert 'data-admin-module-panel="agenda" >' in agenda_response.text
    assert 'data-admin-module-panel="servicios" hidden>' in agenda_response.text

    assert services_response.status_code == 200
    assert "Precios, duración y oferta" in services_response.text
    assert "Agenda del negocio" in services_response.text
    assert 'data-admin-module-panel="agenda" hidden>' in services_response.text
    assert 'data-admin-module-panel="servicios" >' in services_response.text


def test_admin_agenda_registers_cash_and_rendimiento_is_read_only(client: TestClient) -> None:
    agenda_response = client.get("/admin")
    rendimiento_response = client.get("/admin?module=rendimiento")

    assert agenda_response.status_code == 200
    assert "Total generado del día" in agenda_response.text
    assert "action=\"/admin/supply-sales\"" in agenda_response.text

    assert rendimiento_response.status_code == 200
    assert "Ingresos e historial" in rendimiento_response.text
    assert "Ingresos extra registrados" in rendimiento_response.text
    assert 'data-admin-module-panel="agenda" hidden>' in rendimiento_response.text
    assert 'data-admin-module-panel="rendimiento" >' in rendimiento_response.text


def test_admin_auth_can_protect_demo_routes(client: TestClient, monkeypatch) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Negocio seleccionado"}).json()["id"]
    other_shop_id = client.post("/api/barber-shops", json={"name": "Negocio no seleccionado"}).json()["id"]
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "secret")
    monkeypatch.setattr(settings, "session_secret", "test-secret")

    protected_response = client.get("/admin", follow_redirects=False)
    assert protected_response.status_code == 303
    assert protected_response.headers["location"].startswith("/login")

    api_response = client.get("/api/barber-shops")
    assert api_response.status_code == 401

    bad_login_response = client.post(
        "/login",
        data={"username": "owner", "password": "wrong", "next_path": "/admin"},
    )
    assert bad_login_response.status_code == 401

    login_response = client.post(
        "/login",
        data={"username": "owner", "password": "secret", "next_path": "/admin"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    unscoped_admin_response = client.get("/admin", follow_redirects=False)
    assert unscoped_admin_response.status_code == 303
    assert unscoped_admin_response.headers["location"] == "/owner"

    manage_response = client.get(f"/owner/shops/{shop_id}/manage", follow_redirects=False)
    assert manage_response.status_code == 303
    assert manage_response.headers["location"] == "/admin"
    admin_response = client.get("/admin")
    assert admin_response.status_code == 200
    assert "Negocio seleccionado" in admin_response.text
    assert "Negocio no seleccionado" not in admin_response.text

    csrf_token = _csrf_token_from(client, "/admin")
    blocked_cross_shop_update = client.post(
        f"/admin/barber-shops/{other_shop_id}/branding",
        data={"csrf_token": csrf_token, "visual_theme": "wood"},
        files={"logo": ("", b"", "application/octet-stream")},
        follow_redirects=False,
    )
    assert blocked_cross_shop_update.status_code == 303
    other_shop = next(shop for shop in client.get("/api/barber-shops").json() if shop["id"] == other_shop_id)
    assert other_shop["visual_theme"] == "flow"


def test_env_owner_login_does_not_query_users_table(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "secret")
    monkeypatch.setattr(settings, "session_secret", "test-secret")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("env owner login should not query database users")

    monkeypatch.setattr(web_routes, "authenticate_user", fail_if_called)

    response = client.post(
        "/login",
        data={"username": "owner", "password": "secret", "next_path": "/admin"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_business_admin_sees_only_assigned_shop(client: TestClient, monkeypatch) -> None:
    shop_one_response = client.post("/api/barber-shops", json={"name": "Cliente Uno"})
    shop_two_response = client.post("/api/barber-shops", json={"name": "Cliente Dos"})
    shop_one_id = shop_one_response.json()["id"]
    shop_two_id = shop_two_response.json()["id"]

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "secret")
    monkeypatch.setattr(settings, "session_secret", "test-secret-for-business-admin")

    owner_login = client.post(
        "/login",
        data={"username": "owner", "password": "secret", "next_path": "/owner"},
        follow_redirects=False,
    )
    assert owner_login.status_code == 303
    owner_csrf_token = _csrf_token_from(client, "/owner")

    create_user_response = client.post(
        "/owner/users",
        data={
            "csrf_token": owner_csrf_token,
            "username": "cliente1",
            "password": "clave123",
            "role": "business_admin",
            "barber_shop_id": str(shop_one_id),
        },
        follow_redirects=False,
    )
    assert create_user_response.status_code == 303

    client.get("/logout")
    business_login = client.post(
        "/login",
        data={"username": "cliente1", "password": "clave123", "next_path": "/admin"},
        follow_redirects=False,
    )
    assert business_login.status_code == 303
    admin_csrf_token = _csrf_token_from(client, "/admin")

    dashboard_response = client.get("/admin")
    assert dashboard_response.status_code == 200
    assert "Cliente Uno" in dashboard_response.text
    assert "Cliente Dos" not in dashboard_response.text
    assert client.get("/api/barber-shops").status_code == 403

    blocked_service_response = client.post(
        "/admin/services",
        data={
            "csrf_token": admin_csrf_token,
            "barber_shop_id": str(shop_two_id),
            "name": "Servicio ajeno",
            "duration_minutes": "30",
            "price": "1000.00",
        },
        follow_redirects=False,
    )
    assert blocked_service_response.status_code == 303
    assert client.get("/admin").text.count("Servicio ajeno") == 0

    own_service_response = client.post(
        "/admin/services",
        data={
            "csrf_token": admin_csrf_token,
            "barber_shop_id": str(shop_one_id),
            "name": "Servicio propio",
            "duration_minutes": "30",
            "price": "1000.00",
        },
        follow_redirects=False,
    )
    assert own_service_response.status_code == 303
    assert "Servicio propio" in client.get("/admin").text

    admin_csrf_token = _csrf_token_from(client, "/admin")
    blocked_branding_response = client.post(
        f"/admin/barber-shops/{shop_two_id}/branding",
        data={"csrf_token": admin_csrf_token, "visual_theme": "wood"},
        files={"logo": ("", b"", "application/octet-stream")},
        follow_redirects=False,
    )
    assert blocked_branding_response.status_code == 303

    client.get("/logout")
    client.post(
        "/login",
        data={"username": "owner", "password": "secret", "next_path": "/owner"},
        follow_redirects=False,
    )
    shops = client.get("/api/barber-shops").json()
    shop_two = next(shop for shop in shops if shop["id"] == shop_two_id)
    assert shop_two["visual_theme"] == "flow"


def test_owner_can_preview_business_user_and_return_without_password(client: TestClient, monkeypatch) -> None:
    shop_one_id = client.post("/api/barber-shops", json={"name": "Negocio para probar"}).json()["id"]
    shop_two_id = client.post("/api/barber-shops", json={"name": "Negocio privado"}).json()["id"]
    client.post(
        "/owner/users",
        data={
            "username": "usuario_prueba",
            "password": "clave-segura",
            "role": "business_admin",
            "barber_shop_id": str(shop_one_id),
        },
        follow_redirects=False,
    )

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "secret")
    monkeypatch.setattr(settings, "session_secret", "test-secret-for-owner-preview")

    owner_login = client.post(
        "/login",
        data={"username": "owner", "password": "secret", "next_path": "/owner"},
        follow_redirects=False,
    )
    assert owner_login.status_code == 303
    owner_page = client.get("/owner")
    assert "Probar como cliente" in owner_page.text
    assert "Salir" in owner_page.text

    owner_csrf_token = _csrf_token_from(client, "/owner")
    preview_response = client.post(
        "/owner/users/1/impersonate",
        data={"csrf_token": owner_csrf_token},
        follow_redirects=False,
    )

    assert preview_response.status_code == 303
    assert preview_response.headers["location"] == "/admin?module=agenda"
    preview_page = client.get("/admin")
    assert preview_page.status_code == 200
    assert "Vista cliente" in preview_page.text
    assert "Volver a super admin" in preview_page.text
    assert "Negocio para probar" in preview_page.text
    assert "Negocio privado" not in preview_page.text
    assert ">Owner<" not in preview_page.text
    assert client.get("/api/barber-shops").status_code == 403

    preview_csrf_token = _csrf_token_from(client, "/admin")
    return_response = client.post(
        "/owner/return",
        data={"csrf_token": preview_csrf_token},
        follow_redirects=False,
    )

    assert return_response.status_code == 303
    assert return_response.headers["location"] == "/owner"
    restored_owner_page = client.get("/owner")
    assert restored_owner_page.status_code == 200
    assert "Negocio para probar" in restored_owner_page.text
    assert "Negocio privado" in restored_owner_page.text
    assert "Vista cliente" not in restored_owner_page.text


def test_business_admin_error_response_does_not_leak_other_shop(client: TestClient, monkeypatch) -> None:
    shop_one = client.post("/api/barber-shops", json={"name": "Error Uno"}).json()
    shop_two = client.post("/api/barber-shops", json={"name": "Error Dos"}).json()
    barber = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_one["id"], "name": "Profesional Uno"},
    ).json()

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "secret")
    monkeypatch.setattr(settings, "session_secret", "test-secret-for-error-scope")

    client.post(
        "/login",
        data={"username": "owner", "password": "secret", "next_path": "/owner"},
        follow_redirects=False,
    )
    owner_csrf_token = _csrf_token_from(client, "/owner")
    client.post(
        "/owner/users",
        data={
            "csrf_token": owner_csrf_token,
            "username": "error-admin",
            "password": "clave123",
            "role": "business_admin",
            "barber_shop_id": str(shop_one["id"]),
        },
        follow_redirects=False,
    )
    client.get("/logout")
    client.post(
        "/login",
        data={"username": "error-admin", "password": "clave123", "next_path": "/admin"},
        follow_redirects=False,
    )
    admin_csrf_token = _csrf_token_from(client, "/admin")

    response = client.post(
        "/admin/working-schedules",
        data={
            "csrf_token": admin_csrf_token,
            "barber_id": str(barber["id"]),
            "day_of_week": "0",
            "start_time": "18:00",
            "end_time": "09:00",
        },
    )

    assert response.status_code == 400
    assert "Error Uno" in response.text
    assert "Error Dos" not in response.text


def test_business_admin_cannot_view_other_shop_customer_portal(client: TestClient, monkeypatch) -> None:
    shop_one_response = client.post("/api/barber-shops", json={"name": "Portal Uno"})
    shop_two_response = client.post("/api/barber-shops", json={"name": "Portal Dos"})
    shop_one_id = shop_one_response.json()["id"]
    shop_two_id = shop_two_response.json()["id"]
    customer_one_response = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_one_id, "full_name": "Cliente Uno", "phone": "111"},
    )
    customer_two_response = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_two_id, "full_name": "Cliente Dos", "phone": "222"},
    )
    customer_one_id = customer_one_response.json()["id"]
    customer_two_id = customer_two_response.json()["id"]

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "secret")
    monkeypatch.setattr(settings, "session_secret", "test-secret-for-customer-idor")

    client.post(
        "/login",
        data={"username": "owner", "password": "secret", "next_path": "/owner"},
        follow_redirects=False,
    )
    owner_csrf_token = _csrf_token_from(client, "/owner")
    client.post(
        "/owner/users",
        data={
            "csrf_token": owner_csrf_token,
            "username": "portal1",
            "password": "clave123",
            "role": "business_admin",
            "barber_shop_id": str(shop_one_id),
        },
        follow_redirects=False,
    )
    client.get("/logout")
    client.post(
        "/login",
        data={"username": "portal1", "password": "clave123", "next_path": "/admin"},
        follow_redirects=False,
    )

    own_customer_response = client.get(f"/customer/{customer_one_id}/appointments")
    assert own_customer_response.status_code == 200
    assert "Cliente Uno" in own_customer_response.text

    other_customer_response = client.get(f"/customer/{customer_two_id}/appointments")
    assert other_customer_response.status_code == 404
    assert "Cliente Dos" not in other_customer_response.text


def test_owner_can_generate_password_reset_link_and_user_can_change_password(client: TestClient) -> None:
    create_user_response = client.post(
        "/owner/users",
        data={
            "username": "resetme",
            "password": "old-secret",
            "role": "owner",
            "barber_shop_id": "",
        },
        follow_redirects=False,
    )
    assert create_user_response.status_code == 303

    link_response = client.post("/owner/users/1/password-reset-link")
    assert link_response.status_code == 200
    reset_url = link_response.json()["reset_url"]
    token = reset_url.split("token=", 1)[1]

    initial_login_response = client.post(
        "/login",
        data={"username": "resetme", "password": "old-secret", "next_path": "/admin"},
        follow_redirects=False,
    )
    assert initial_login_response.status_code == 303

    old_wrong_login_response = client.post(
        "/login",
        data={"username": "resetme", "password": "wrong-secret", "next_path": "/admin"},
    )
    assert old_wrong_login_response.status_code == 401

    reset_response = client.post(
        "/password-reset",
        data={"token": token, "password": "new-secret"},
        follow_redirects=False,
    )
    assert reset_response.status_code == 303

    short_reset_response = client.post(
        "/password-reset",
        data={"token": token, "password": "short"},
    )
    assert short_reset_response.status_code == 400

    new_login_response = client.post(
        "/login",
        data={"username": "resetme", "password": "new-secret", "next_path": "/admin"},
        follow_redirects=False,
    )
    assert new_login_response.status_code == 303

    old_login_response = client.post(
        "/login",
        data={"username": "resetme", "password": "old-secret", "next_path": "/admin"},
    )
    assert old_login_response.status_code == 401

    invalid_reset_response = client.post(
        "/password-reset",
        data={"token": "bad-token", "password": "another-secret"},
    )
    assert invalid_reset_response.status_code == 400


def test_admin_post_without_csrf_is_rejected_when_auth_enabled(client: TestClient, monkeypatch) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "CSRF Demo"})
    shop_id = shop_response.json()["id"]

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "secret")
    monkeypatch.setattr(settings, "session_secret", "test-secret-for-csrf")

    login_response = client.post(
        "/login",
        data={"username": "owner", "password": "secret", "next_path": "/admin"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert client.get("/admin").status_code == 200

    response = client.post(
        "/admin/services",
        data={
            "barber_shop_id": str(shop_id),
            "name": "Sin token",
            "duration_minutes": "30",
            "price": "1000.00",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert "Sin token" not in client.get("/admin").text

    multipart_response = client.post(
        f"/admin/barber-shops/{shop_id}/branding",
        data={"visual_theme": "wood"},
        files={"logo": ("logo.png", b"contenido", "image/png")},
        follow_redirects=False,
    )
    assert multipart_response.status_code == 403


def test_bot_simulator_post_without_csrf_is_rejected_when_auth_enabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "secret")
    monkeypatch.setattr(settings, "session_secret", "test-secret-for-bot-csrf")

    login_response = client.post(
        "/login",
        data={"username": "owner", "password": "secret", "next_path": "/bot-simulator"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert client.get("/bot-simulator").status_code == 200

    response = client.post("/bot-simulator/reset", data={}, follow_redirects=False)

    assert response.status_code == 403


def test_admin_can_create_barber_shop_from_form(client: TestClient) -> None:
    response = client.post(
        "/admin/barber-shops",
        data={
            "name": "Panel Demo",
            "phone": "111",
            "address": "Street 1",
            "main_barber_name": "Mica",
            "main_barber_phone": "222",
            "main_barber_email": "mica@example.com",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303

    shops_response = client.get("/api/barber-shops")
    shop = shops_response.json()[0]
    assert shop["name"] == "Panel Demo"
    assert shop["address"] == "Street 1"

    barbers_response = client.get("/api/barbers", params={"barber_shop_id": shop["id"]})
    barber = barbers_response.json()[0]
    assert barber["name"] == "Mica"
    assert barber["phone"] == "222"

    dashboard_response = client.get("/admin?module=configuracion")
    assert "Dirección: Street 1" in dashboard_response.text
    assert "Mica" in dashboard_response.text

    schedules = client.get("/api/working-schedules", params={"barber_id": barber["id"]}).json()
    assert {schedule["day_of_week"] for schedule in schedules if schedule["is_active"]} == set(range(7))
    assert all(schedule["start_time"] == "09:00:00" for schedule in schedules)
    assert all(schedule["end_time"] == "19:00:00" for schedule in schedules)


def test_owner_can_create_shop_without_address_and_with_client_access(client: TestClient) -> None:
    response = client.post(
        "/admin/barber-shops",
        data={
            "name": "Santino Estudio",
            "phone": "",
            "address": "",
            "account_username": "santino_estudio",
            "account_password": "clave-temporal",
            "next_path": "/owner",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/owner?notice=shop_created_with_user"
    shop = client.get("/api/barber-shops").json()[0]
    assert shop["address"] is None
    assert shop["phone"] is None
    owner_page = client.get("/owner").text
    assert "santino_estudio" in owner_page
    assert "Sin usuario cliente" not in owner_page


def test_owner_can_create_missing_shop_access_from_managed_business_panel(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Santino Barber"}).json()["id"]
    client.get(f"/owner/shops/{shop_id}/manage", follow_redirects=False)

    before = client.get("/admin?module=configuracion")
    assert "Sin usuario de acceso" in before.text
    assert "Crear usuario y clave" in before.text
    assert 'id="businessAccessModal"' in before.text

    created = client.post(
        "/owner/users",
        data={
            "username": "santino_barber",
            "password": "clave-temporal",
            "role": "business_admin",
            "barber_shop_id": str(shop_id),
            "next_path": "/admin?module=configuracion",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/admin?module=configuracion"

    after = client.get("/admin?module=configuracion")
    assert "Acceso: santino_barber" in after.text
    assert "Sin usuario de acceso" not in after.text

    duplicate = client.post(
        "/owner/users",
        data={
            "username": "santino_barber",
            "password": "otra-clave-segura",
            "role": "business_admin",
            "barber_shop_id": str(shop_id),
            "next_path": "/admin?module=configuracion",
        },
    )
    assert duplicate.status_code == 400
    assert "Ese nombre de usuario ya existe" in duplicate.text
    assert "Error interno" not in duplicate.text


def test_owner_access_form_explains_validation_and_confirms_creation(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Santino Barber"}).json()["id"]

    owner_page = client.get("/owner")
    assert owner_page.status_code == 200
    assert f'data-create-access-for="{shop_id}"' in owner_page.text
    assert "data-create-access-general" in owner_page.text
    assert 'select.value = ""' in owner_page.text
    assert 'name="password" type="password" minlength="8"' in owner_page.text
    assert 'name="barber_shop_id" required' in owner_page.text
    assert 'name="role" type="hidden" value="business_admin"' in owner_page.text
    assert "Super admin interno" not in owner_page.text

    rejected = client.post(
        "/owner/users",
        data={
            "username": "acceso_corto",
            "password": "corta",
            "role": "business_admin",
            "barber_shop_id": str(shop_id),
        },
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    assert rejected.headers["location"] == "/owner?notice=user_access_invalid"
    rejected_page = client.get(rejected.headers["location"])
    assert "No se creó el acceso" in rejected_page.text
    assert "Sin usuario cliente" in rejected_page.text

    created = client.post(
        "/owner/users",
        data={
            "username": "santino_acceso",
            "password": "clave-segura",
            "role": "business_admin",
            "barber_shop_id": str(shop_id),
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/owner?notice=user_access_created"
    created_page = client.get(created.headers["location"])
    assert "Acceso creado correctamente" in created_page.text
    assert "santino_acceso" in created_page.text
    assert "Sin usuario cliente" not in created_page.text


def test_owner_shop_creation_reports_duplicate_phone_without_server_error(client: TestClient) -> None:
    client.post("/api/barber-shops", json={"name": "Existente", "phone": "2230000000"})

    response = client.post(
        "/admin/barber-shops",
        data={"name": "Duplicado", "phone": "2230000000", "address": "", "next_path": "/owner"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/owner?notice=shop_phone_in_use"
    assert [shop["name"] for shop in client.get("/api/barber-shops").json()] == ["Existente"]

    panel_response = client.post(
        "/admin/barber-shops",
        data={"name": "Duplicado desde panel", "phone": "2230000000", "address": ""},
    )
    assert panel_response.status_code == 400
    assert "Ese teléfono ya está asignado a otro negocio" in panel_response.text
    assert "Error interno" not in panel_response.text


def test_owner_deletes_shop_only_after_exact_name_confirmation(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Negocio de prueba"}).json()["id"]
    client.post(
        "/owner/users",
        data={
            "username": "prueba_eliminar",
            "password": "clave-segura",
            "role": "business_admin",
            "barber_shop_id": str(shop_id),
        },
    )

    owner_page = client.get("/owner")
    assert owner_page.status_code == 200
    assert f'data-delete-url="/owner/shops/{shop_id}/delete"' in owner_page.text
    assert "Para confirmar, escribí exactamente:" in owner_page.text
    assert "data-delete-submit disabled" in owner_page.text

    rejected = client.post(
        f"/owner/shops/{shop_id}/delete",
        data={"confirmation_name": "nombre incorrecto"},
        follow_redirects=False,
    )
    assert rejected.headers["location"] == "/owner?notice=shop_delete_confirmation_invalid"
    assert len(client.get("/api/barber-shops").json()) == 1

    rejection_page = client.get(rejected.headers["location"])
    assert "No se eliminó el negocio: escribí exactamente el nombre indicado." in rejection_page.text

    deleted = client.post(
        f"/owner/shops/{shop_id}/delete",
        data={"confirmation_name": "Negocio de prueba"},
        follow_redirects=False,
    )
    assert deleted.headers["location"] == "/owner?notice=shop_deleted"
    assert client.get("/api/barber-shops").json() == []
    assert "prueba_eliminar" not in client.get("/owner").text


def test_admin_creates_professional_with_selected_days_and_default_hours(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Equipo simple"}).json()["id"]

    response = client.post(
        "/admin/barbers",
        data={
            "barber_shop_id": str(shop_id),
            "name": "Diego",
            "working_days": ["0", "1", "2", "3", "4", "5"],
            "opening_time": "09:00",
            "closing_time": "19:00",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?module=equipo"
    barber = client.get("/api/barbers", params={"barber_shop_id": shop_id}).json()[0]
    schedules = client.get("/api/working-schedules", params={"barber_id": barber["id"]}).json()
    assert {schedule["day_of_week"] for schedule in schedules if schedule["is_active"]} == set(range(6))
    assert all(schedule["start_time"] == "09:00:00" for schedule in schedules)
    assert all(schedule["end_time"] == "19:00:00" for schedule in schedules)


def test_admin_manual_appointment_is_confirmed_and_moves_to_history_when_cancelled(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Admin Agenda Demo"})
    shop_id = shop_response.json()["id"]
    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    service_id = service_response.json()["id"]
    barber_response = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": [service_id]},
    )
    barber_id = barber_response.json()["id"]
    client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    customer_response = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Santi Cliente", "phone": "3333333333"},
    )
    customer_id = customer_response.json()["id"]

    create_response = client.post(
        "/admin/appointments",
        data={
            "barber_id": str(barber_id),
            "customer_id": str(customer_id),
            "service_id": str(service_id),
            "starts_at": "2030-08-03T11:00",
            "notes": "",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    appointments = client.get("/api/appointments").json()
    appointment_id = appointments[0]["id"]
    assert appointments[0]["status"] == "confirmed"

    dashboard_response = client.get("/admin")
    assert dashboard_response.status_code == 200
    assert "Turnos próximos" in dashboard_response.text
    assert "11:00 - Santi Cliente" in dashboard_response.text
    assert "Corte · Martin" in dashboard_response.text
    assert 'data-admin-module-panel="rendimiento" hidden>' in dashboard_response.text
    history_response = client.get("/admin?module=rendimiento")
    assert history_response.status_code == 200
    assert "Ingresos e historial" in history_response.text

    cancel_response = client.post(f"/admin/appointments/{appointment_id}/cancel")
    assert cancel_response.status_code == 200
    assert "$0 cancelado" in cancel_response.text

    delete_response = client.post(f"/admin/customers/{customer_id}/delete")
    assert delete_response.status_code == 409
    assert "historial debe conservarse" in delete_response.text


def test_admin_manual_booking_accepts_any_shop_service_for_the_only_professional(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Profesional Unico"}).json()["id"]
    service_id = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    ).json()["id"]
    barber_id = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": []},
    ).json()["id"]
    client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )

    dashboard = client.get("/admin")
    assert f'data-all-services="true"' in dashboard.text
    assert "filterBarbersByService" in dashboard.text

    response = client.post(
        "/admin/appointments",
        data={
            "barber_id": str(barber_id),
            "customer_id": "",
            "new_customer_name": "Cliente Presencial",
            "new_customer_phone": "",
            "service_id": str(service_id),
            "starts_at": "2026-08-08T10:00",
            "notes": "Creado en el local",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    appointments = client.get("/api/appointments").json()
    assert len(appointments) == 1
    assert appointments[0]["status"] == "confirmed"


def test_professional_without_specialties_can_book_any_service_in_multi_professional_shop(
    client: TestClient,
) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Salon Flexible"}).json()["id"]
    service_id = client.post(
        "/api/services",
        json={"barber_shop_id": shop_id, "name": "Color", "duration_minutes": 90, "price": "30000.00"},
    ).json()["id"]
    flexible_barber_id = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Ana", "service_ids": []},
    ).json()["id"]
    client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Mica", "service_ids": [service_id]},
    )
    client.post(
        "/api/working-schedules",
        json={
            "barber_id": flexible_barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )

    response = client.post(
        "/admin/appointments",
        data={
            "barber_id": str(flexible_barber_id),
            "customer_id": "",
            "new_customer_name": "Cliente Salon",
            "service_id": str(service_id),
            "starts_at": "2026-08-08T10:00",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert client.get("/api/appointments").json()[0]["barber_id"] == flexible_barber_id


def test_admin_can_assign_multiple_specialties_to_professional(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Estudio Multiple"}).json()["id"]
    nails_id = client.post(
        "/api/services",
        json={"barber_shop_id": shop_id, "name": "Unas", "duration_minutes": 60, "price": "15000.00"},
    ).json()["id"]
    lashes_id = client.post(
        "/api/services",
        json={"barber_shop_id": shop_id, "name": "Pestanas", "duration_minutes": 90, "price": "22000.00"},
    ).json()["id"]
    barber_id = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Mica", "service_ids": []},
    ).json()["id"]

    response = client.post(
        f"/admin/barbers/{barber_id}/edit",
        data={"name": "Mica", "phone": "", "email": "", "service_ids": [str(nails_id), str(lashes_id)]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    dashboard = client.get("/admin?module=equipo")
    assert f'name="service_ids" value="{nails_id}" checked' in dashboard.text
    assert f'name="service_ids" value="{lashes_id}" checked' in dashboard.text


def test_admin_can_set_professional_for_all_services_and_every_day(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Salon todos los dias"}).json()["id"]
    service_id = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    ).json()["id"]
    barber_id = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Diego", "service_ids": [service_id]},
    ).json()["id"]

    response = client.post(
        f"/admin/barbers/{barber_id}/edit",
        data={
            "name": "Diego actualizado",
            "phone": "",
            "email": "",
            "all_services": "true",
            "all_working_days": "true",
            "opening_time": "09:00",
            "closing_time": "19:00",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    schedules = client.get("/api/working-schedules", params={"barber_id": barber_id}).json()
    active_schedules = [schedule for schedule in schedules if schedule["is_active"]]
    assert {schedule["day_of_week"] for schedule in active_schedules} == set(range(7))
    dashboard = client.get("/admin?module=equipo")
    assert "Diego actualizado" in dashboard.text
    assert 'name="all_services" value="true" data-all-services checked' in dashboard.text
    assert 'name="all_working_days" value="true" data-select-all-days checked' in dashboard.text
    assert f'value="{barber_id}" data-shop-id="{shop_id}" data-service-ids="" data-all-services="true"' in dashboard.text


def test_admin_manual_booking_rejects_incompatible_professional_in_spanish(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Equipo Multiple"}).json()["id"]
    cut_id = client.post(
        "/api/services",
        json={"barber_shop_id": shop_id, "name": "Corte", "duration_minutes": 30, "price": "10000.00"},
    ).json()["id"]
    color_id = client.post(
        "/api/services",
        json={"barber_shop_id": shop_id, "name": "Color", "duration_minutes": 60, "price": "20000.00"},
    ).json()["id"]
    cut_barber_id = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": [cut_id]},
    ).json()["id"]
    client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Ana", "service_ids": [color_id]},
    )
    customer_id = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Cliente", "phone": "111"},
    ).json()["id"]

    response = client.post(
        "/admin/appointments",
        data={
            "barber_id": str(cut_barber_id),
            "customer_id": str(customer_id),
            "service_id": str(color_id),
            "starts_at": "2026-08-08T10:00",
        },
    )

    assert response.status_code == 400
    assert "El profesional seleccionado no realiza ese servicio" in response.text
    assert "Barber cannot perform" not in response.text
    assert client.get("/api/appointments").json() == []


def test_admin_customer_module_is_a_list_with_separate_detail_and_delete(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Clientes Demo"}).json()["id"]
    customer_id = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Martina", "phone": "223577490", "notes": "Vecina"},
    ).json()["id"]

    list_response = client.get("/admin?module=clientes")
    assert list_response.status_code == 200
    assert "Martina" in list_response.text
    assert f"/admin/customers/{customer_id}" in list_response.text
    assert 'value="Martina"' not in list_response.text
    assert "Guardar cambios" not in list_response.text

    detail_response = client.get(f"/admin/customers/{customer_id}")
    assert detail_response.status_code == 200
    assert 'value="Martina"' in detail_response.text
    assert "Guardar cambios" in detail_response.text
    assert "Eliminar cliente" in detail_response.text

    edit_response = client.post(
        f"/admin/customers/{customer_id}/edit",
        data={"full_name": "Martina Lopez", "phone": "223577491", "email": "", "notes": "VIP"},
        follow_redirects=False,
    )
    assert edit_response.status_code == 303
    assert edit_response.headers["location"] == f"/admin/customers/{customer_id}"
    assert client.get(f"/admin/customers/{customer_id}").status_code == 200
    assert "Martina Lopez" in client.get(f"/admin/customers/{customer_id}").text

    delete_response = client.post(f"/admin/customers/{customer_id}/delete", follow_redirects=False)
    assert delete_response.status_code == 303
    assert client.get("/api/customers", params={"barber_shop_id": shop_id}).json() == []


def test_admin_can_create_appointment_with_new_customer_inline(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Inline Customer Demo"})
    shop_id = shop_response.json()["id"]
    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    service_id = service_response.json()["id"]
    barber_response = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": [service_id]},
    )
    barber_id = barber_response.json()["id"]
    client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )

    response = client.post(
        "/admin/appointments",
        data={
            "barber_id": str(barber_id),
            "customer_id": "",
            "new_customer_name": "Cliente Nuevo",
            "new_customer_phone": "999999999",
            "service_id": str(service_id),
            "starts_at": "2026-08-01T12:00",
            "notes": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    customers = client.get("/api/customers").json()
    assert customers[0]["full_name"] == "Cliente Nuevo"
    appointment = client.get("/api/appointments").json()[0]
    assert appointment["status"] == "confirmed"

    second_response = client.post(
        "/admin/appointments",
        data={
            "barber_id": str(barber_id),
            "customer_id": "",
            "new_customer_name": "Otro nombre cargado",
            "new_customer_phone": " 999999999 ",
            "service_id": str(service_id),
            "starts_at": "2026-08-01T13:00",
            "notes": "",
        },
        follow_redirects=False,
    )

    assert second_response.status_code == 303
    assert len(client.get("/api/customers").json()) == 1
    assert len(client.get("/api/appointments").json()) == 2
    customers_module = client.get("/admin?module=clientes")
    assert customers_module.status_code == 200
    assert "Cliente Nuevo" in customers_module.text

    third_response = client.post(
        "/admin/appointments",
        data={
            "barber_id": str(barber_id),
            "customer_id": "",
            "new_customer_name": "Marcelo Vecino",
            "new_customer_phone": "",
            "service_id": str(service_id),
            "starts_at": "2026-08-01T14:00",
            "notes": "Cliente sin telefono",
        },
        follow_redirects=False,
    )

    assert third_response.status_code == 303
    customers = client.get("/api/customers").json()
    assert len(customers) == 2
    marcelo = next(customer for customer in customers if customer["full_name"] == "Marcelo Vecino")
    assert marcelo["phone"] is None
    assert "Marcelo Vecino" in client.get("/admin?module=clientes").text

    failed_response = client.post(
        "/admin/appointments",
        data={
            "barber_id": str(barber_id),
            "customer_id": "",
            "new_customer_name": "Cliente No Debe Quedar",
            "new_customer_phone": "",
            "service_id": str(service_id),
            "starts_at": "2026-08-01T12:15",
            "notes": "",
        },
        follow_redirects=False,
    )

    assert failed_response.status_code == 409
    assert "Cliente No Debe Quedar" not in client.get("/admin?module=clientes").text


def test_admin_appointment_form_scopes_catalog_options_by_shop(client: TestClient) -> None:
    shop_a = client.post("/api/barber-shops", json={"name": "Agenda A"}).json()
    shop_b = client.post("/api/barber-shops", json={"name": "Agenda B"}).json()
    service_a = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_a["id"],
            "name": "Corte A",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    ).json()
    service_b = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_b["id"],
            "name": "Corte B",
            "duration_minutes": 30,
            "price": "12000.00",
        },
    ).json()
    barber_a = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_a["id"], "name": "Profesional A", "service_ids": [service_a["id"]]},
    ).json()
    barber_b = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_b["id"], "name": "Profesional B", "service_ids": [service_b["id"]]},
    ).json()
    customer_a = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_a["id"], "full_name": "Cliente A", "phone": "111"},
    ).json()
    customer_b = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_b["id"], "full_name": "Cliente B", "phone": "222"},
    ).json()

    response = client.get("/admin")

    assert response.status_code == 200
    assert 'id="appointmentShopSelect"' in response.text
    assert f'value="{service_a["id"]}" data-shop-id="{shop_a["id"]}"' in response.text
    assert f'value="{service_b["id"]}" data-shop-id="{shop_b["id"]}"' in response.text
    assert f'value="{barber_a["id"]}" data-shop-id="{shop_a["id"]}"' in response.text
    assert f'value="{barber_b["id"]}" data-shop-id="{shop_b["id"]}"' in response.text
    assert f'value="{customer_a["id"]}" data-shop-id="{shop_a["id"]}"' in response.text
    assert f'value="{customer_b["id"]}" data-shop-id="{shop_b["id"]}"' in response.text
    assert "syncAppointmentCatalog" in response.text


def test_admin_can_deactivate_and_reactivate_service(client: TestClient) -> None:
    shop = client.post("/api/barber-shops", json={"name": "Servicios activos"}).json()
    service = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop["id"],
            "name": "Servicio temporal",
            "duration_minutes": 30,
            "price": "12000.00",
        },
    ).json()

    response = client.post(f"/admin/services/{service['id']}/toggle", follow_redirects=True)

    assert response.status_code == 200
    assert "Inactivo" in response.text
    assert f'value="{service["id"]}" data-shop-id="{shop["id"]}" data-duration' not in response.text
    bot_response = client.post("/bot-simulator/message", data={"message": "servicios"})
    assert "Servicio temporal" not in bot_response.text

    client.post(f"/admin/services/{service['id']}/toggle")
    active_bot_response = client.post("/bot-simulator/message", data={"message": "servicios"})
    assert "Servicio temporal" in active_bot_response.text


def test_admin_configures_bot_category_menu_and_scoped_alias(client: TestClient) -> None:
    shop_a = client.post("/api/barber-shops", json={"name": "Spa A"}).json()
    shop_b = client.post("/api/barber-shops", json={"name": "Spa B"}).json()
    service_a = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_a["id"],
            "name": "Descontracturante",
            "duration_minutes": 60,
            "price": "22000.00",
        },
    ).json()
    service_b = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_b["id"],
            "name": "Relajante",
            "duration_minutes": 60,
            "price": "20000.00",
        },
    ).json()

    settings_response = client.post(
        f"/admin/bot-settings/{shop_a['id']}",
        data={
            "bot_enabled": "true",
            "reminders_enabled": "false",
            "reminder_hours_before": "24",
            "greeting_message": "Hola desde Spa A",
            "menu_message": "1. Reservar masaje | 2. Ver mi turno",
            "reminder_template": "Turno de {customer_name}",
            "business_category": "masajes",
        },
        follow_redirects=False,
    )
    assert settings_response.status_code == 303
    assert client.get("/api/barber-shops").json()[0]["business_category"] == "masajes"

    alias_response = client.post(
        f"/admin/bot-aliases/{shop_a['id']}",
        data={"service_id": str(service_a["id"]), "alias": "espalda cargada"},
        follow_redirects=False,
    )
    assert alias_response.status_code == 303

    cross_shop_response = client.post(
        f"/admin/bot-aliases/{shop_a['id']}",
        data={"service_id": str(service_b["id"]), "alias": "no permitido"},
    )
    assert cross_shop_response.status_code == 400
    assert "no pertenece al negocio" in cross_shop_response.text

    dashboard = client.get("/admin?module=configuracion")
    assert "1. Reservar masaje | 2. Ver mi turno" in dashboard.text
    assert "espalda cargada" in dashboard.text


def test_admin_can_edit_core_management_records(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Edit Demo"})
    shop_id = shop_response.json()["id"]
    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    service_id = service_response.json()["id"]
    barber_response = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "phone": "111", "service_ids": [service_id]},
    )
    barber_id = barber_response.json()["id"]
    customer_response = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Cliente Viejo", "phone": "222"},
    )
    customer_id = customer_response.json()["id"]
    schedule_response = client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    schedule_id = schedule_response.json()["id"]

    assert client.post(
        f"/admin/services/{service_id}/edit",
        data={"name": "Corte premium", "duration_minutes": "45", "price": "15000.00"},
        follow_redirects=False,
    ).status_code == 303
    assert client.post(
        f"/admin/barbers/{barber_id}/edit",
        data={"name": "Martin Pro", "phone": "333", "email": "martin@example.com", "service_id": str(service_id)},
        follow_redirects=False,
    ).status_code == 303
    assert client.post(
        f"/admin/customers/{customer_id}/edit",
        data={"full_name": "Cliente Nuevo", "phone": "444", "email": "cliente@example.com", "notes": "VIP"},
        follow_redirects=False,
    ).status_code == 303
    assert client.post(
        f"/admin/working-schedules/{schedule_id}/edit",
        data={"day_of_week": "4", "start_time": "10:00", "end_time": "17:00"},
        follow_redirects=False,
    ).status_code == 303

    service = client.get("/api/services", params={"barber_shop_id": shop_id}).json()[0]
    barber = client.get("/api/barbers", params={"barber_shop_id": shop_id}).json()[0]
    customer = client.get("/api/customers", params={"barber_shop_id": shop_id}).json()[0]
    schedule = client.get("/api/working-schedules", params={"barber_id": barber_id}).json()[0]

    assert service["name"] == "Corte premium"
    assert service["duration_minutes"] == 45
    assert service["price"] == "15000.00"
    assert barber["name"] == "Martin Pro"
    assert barber["phone"] == "333"
    assert customer["full_name"] == "Cliente Nuevo"
    assert customer["phone"] == "444"
    assert schedule["day_of_week"] == 4
    assert schedule["start_time"] == "10:00:00"
    assert schedule["end_time"] == "17:00:00"


def test_admin_dashboard_filters_appointments_by_date_range_and_paginates(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Pagination Demo"})
    shop_id = shop_response.json()["id"]
    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    service_id = service_response.json()["id"]
    barber_response = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": [service_id]},
    )
    barber_id = barber_response.json()["id"]
    for day_of_week in (5, 6):
        client.post(
            "/api/working-schedules",
            json={
                "barber_id": barber_id,
                "day_of_week": day_of_week,
                "start_time": "09:00:00",
                "end_time": "18:00:00",
            },
        )

    customer_ids = []
    for name, phone in (("Cliente Uno", "111"), ("Cliente Dos", "222"), ("Cliente Tres", "333")):
        customer_response = client.post(
            "/api/customers",
            json={"barber_shop_id": shop_id, "full_name": name, "phone": phone},
        )
        customer_ids.append(customer_response.json()["id"])

    starts_at_values = ("2026-08-08T09:00:00", "2026-08-08T10:00:00", "2026-08-09T09:00:00")
    for customer_id, starts_at in zip(customer_ids, starts_at_values, strict=True):
        client.post(
            "/api/appointments",
            json={
                "barber_id": barber_id,
                "customer_id": customer_id,
                "service_id": service_id,
                "starts_at": starts_at,
            },
        )

    first_page = client.get(
        "/admin",
        params={"start_date": "2026-08-08", "end_date": "2026-08-08", "per_page": "1", "page": "1"},
    )
    second_page = client.get(
        "/admin",
        params={"start_date": "2026-08-08", "end_date": "2026-08-08", "per_page": "1", "page": "2"},
    )

    assert first_page.status_code == 200
    assert "2 turnos en el rango" in first_page.text
    assert "09:00 - Cliente Uno" in first_page.text
    assert "10:00 - Cliente Dos" not in first_page.text
    assert "09:00 - Cliente Tres" not in first_page.text
    assert "Siguiente" in first_page.text

    assert second_page.status_code == 200
    assert "10:00 - Cliente Dos" in second_page.text
    assert "09:00 - Cliente Uno" not in second_page.text


def test_admin_time_block_hides_slots_and_blocks_booking(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Block Demo"})
    shop_id = shop_response.json()["id"]
    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    service_id = service_response.json()["id"]
    barber_response = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": [service_id]},
    )
    barber_id = barber_response.json()["id"]
    client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    customer_response = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Santi Cliente", "phone": "3333333333"},
    )
    customer_id = customer_response.json()["id"]

    block_response = client.post(
        "/admin/time-blocks",
        data={
            "barber_id": str(barber_id),
            "starts_at": "2026-08-01T10:00",
            "ends_at": "2026-08-01T11:00",
            "reason": "Almuerzo",
        },
        follow_redirects=False,
    )
    assert block_response.status_code == 303
    dashboard_response = client.get("/admin")
    assert "Liberar" in dashboard_response.text

    availability_response = client.get(
        "/api/availability",
        params={"barber_id": barber_id, "service_id": service_id, "target_date": "2026-08-01"},
    )
    slot_starts = [slot["starts_at"] for slot in availability_response.json()]
    assert "2026-08-01T09:30:00" in slot_starts
    assert "2026-08-01T10:00:00" not in slot_starts
    assert "2026-08-01T10:30:00" not in slot_starts
    assert "2026-08-01T11:00:00" in slot_starts

    booking_response = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-01T10:00:00",
        },
    )
    assert booking_response.status_code == 409
    assert booking_response.json()["detail"] == "Ese horario fue bloqueado por el profesional."

    release_response = client.post("/admin/time-blocks/1/deactivate", follow_redirects=False)
    assert release_response.status_code == 303

    availability_after_release = client.get(
        "/api/availability",
        params={"barber_id": barber_id, "service_id": service_id, "target_date": "2026-08-01"},
    )
    released_slot_starts = [slot["starts_at"] for slot in availability_after_release.json()]
    assert "2026-08-01T10:00:00" in released_slot_starts


def test_bot_simulator_loads(client: TestClient) -> None:
    response = client.get("/bot-simulator")

    assert response.status_code == 200
    assert "Bot simulator" in response.text


def test_customer_portal_shows_only_confirmed_appointments(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Customer Portal Demo"})
    shop_id = shop_response.json()["id"]
    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    service_id = service_response.json()["id"]
    barber_response = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": [service_id]},
    )
    barber_id = barber_response.json()["id"]
    client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    customer_response = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Santi Cliente", "phone": "3333333333"},
    )
    customer_id = customer_response.json()["id"]
    confirmed_response = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-01T09:00:00",
        },
    )
    confirmed_id = confirmed_response.json()["id"]
    client.post(f"/api/appointments/{confirmed_id}/confirm")

    pending_response = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-01T10:00:00",
        },
    )
    pending_id = pending_response.json()["id"]

    response = client.get(f"/customer/{customer_id}/appointments")

    assert response.status_code == 200
    assert "Mis turnos confirmados" in response.text
    assert f"#{pending_id}" not in response.text
    assert "09:00 a 09:30" in response.text
    assert "10:00 a 10:30" not in response.text


def test_admin_can_create_supply_sale_from_form(client: TestClient) -> None:
    shop_response = client.post(
        "/api/barber-shops",
        json={"name": "Supply Demo"},
    )
    shop_id = shop_response.json()["id"]

    response = client.post(
        "/admin/supply-sales",
        data={
            "barber_shop_id": shop_id,
            "appointment_id": "",
            "name": "Pomada",
            "quantity": "1",
            "unit_price": "2500.00",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303

    sales_response = client.get("/api/supply-sales")
    assert sales_response.json()[0]["name"] == "Pomada"


def test_admin_can_suspend_and_activate_shop(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Access Demo"})
    shop_id = shop_response.json()["id"]

    suspend_response = client.post(
        f"/admin/barber-shops/{shop_id}/suspend",
        data={"reason": "Pago vencido"},
        follow_redirects=False,
    )
    assert suspend_response.status_code == 303
    assert client.get("/api/barber-shops").json()[0]["access_status"] == "suspended"

    activate_response = client.post(
        f"/admin/barber-shops/{shop_id}/activate",
        follow_redirects=False,
    )
    assert activate_response.status_code == 303
    activated_shop = client.get("/api/barber-shops").json()[0]
    assert activated_shop["access_status"] == "active"
    assert activated_shop["trial_ends_at"] is None


def test_owner_panel_shows_commercial_access_status(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Pago Demo"})
    shop_id = shop_response.json()["id"]

    owner_response = client.get("/owner")
    assert owner_response.status_code == 200
    assert "Estado comercial por cliente" in owner_response.text
    assert "Pago Demo" in owner_response.text
    assert "Prueba: 15 días" in owner_response.text
    assert "Extender 15 días" in owner_response.text
    assert "Marcar como pago" in owner_response.text
    assert "plan basic" in owner_response.text
    assert "Crear negocio" in owner_response.text
    assert "Crear acceso de cliente" in owner_response.text
    assert "Control de negocios" in owner_response.text

    suspend_response = client.post(
        f"/admin/barber-shops/{shop_id}/suspend",
        data={"reason": "Pago vencido"},
        follow_redirects=False,
    )
    assert suspend_response.status_code == 303

    suspended_owner_response = client.get("/owner")
    assert "Suspendido" in suspended_owner_response.text
    assert "Motivo: Pago vencido" in suspended_owner_response.text


def test_owner_can_extend_trial_and_convert_it_to_paid_access(client: TestClient) -> None:
    created_shop = client.post("/api/barber-shops", json={"name": "Prueba Comercial"}).json()
    shop_id = created_shop["id"]
    initial_trial_end = datetime.fromisoformat(created_shop["trial_ends_at"])

    extend_response = client.post(
        f"/owner/shops/{shop_id}/trial/extend",
        follow_redirects=False,
    )

    assert extend_response.status_code == 303
    extended_shop = client.get("/api/barber-shops").json()[0]
    assert datetime.fromisoformat(extended_shop["trial_ends_at"]) > initial_trial_end

    paid_response = client.post(
        f"/admin/barber-shops/{shop_id}/activate",
        follow_redirects=False,
    )

    assert paid_response.status_code == 303
    paid_shop = client.get("/api/barber-shops").json()[0]
    assert paid_shop["trial_ends_at"] is None
    assert "Pago / activo" in client.get("/owner").text


def test_owner_can_create_shop_and_return_to_owner_panel(client: TestClient) -> None:
    response = client.post(
        "/admin/barber-shops",
        data={
            "name": "Owner Alta Demo",
            "phone": "111",
            "address": "Street 1",
            "main_barber_name": "",
            "main_barber_phone": "",
            "main_barber_email": "",
            "next_path": "/owner",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/owner"
    owner_response = client.get("/owner")
    assert "Owner Alta Demo" in owner_response.text


def test_admin_cancel_shows_released_slot_notice(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Cancel Notice Demo"})
    shop_id = shop_response.json()["id"]
    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    service_id = service_response.json()["id"]
    barber_response = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": [service_id]},
    )
    barber_id = barber_response.json()["id"]
    client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    customer_response = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Santi Cliente", "phone": "3333333333"},
    )
    customer_id = customer_response.json()["id"]
    appointment_response = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-01T09:00:00",
        },
    )
    appointment_id = appointment_response.json()["id"]

    response = client.post(f"/admin/appointments/{appointment_id}/cancel")

    assert response.status_code == 200
    assert "Se libero el turno" in response.text
    assert "Mensaje simulado" in response.text


def test_admin_general_hours_apply_only_selected_working_days(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Spa Horarios"}).json()["id"]
    barber_id = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Julia", "service_ids": []},
    ).json()["id"]

    response = client.post(
        f"/admin/barber-shops/{shop_id}/hours",
        data={
            "opening_time": "10:00",
            "closing_time": "19:00",
            "working_days": ["0", "2", "6"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    schedules = client.get("/api/working-schedules", params={"barber_id": barber_id}).json()
    active_schedules = [schedule for schedule in schedules if schedule["is_active"]]
    assert {schedule["day_of_week"] for schedule in active_schedules} == {0, 2, 6}
    assert all(schedule["start_time"] == "10:00:00" for schedule in active_schedules)
    assert all(schedule["end_time"] == "19:00:00" for schedule in active_schedules)

    configuration = client.get("/admin?module=configuracion")
    assert "Días y horario general" in configuration.text
    assert "Los días desmarcados quedan cerrados" in configuration.text


def test_admin_can_customize_business_theme(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Estudio Visual"}).json()["id"]
    client.get(f"/owner/shops/{shop_id}/manage", follow_redirects=False)

    response = client.post(
        f"/admin/barber-shops/{shop_id}/branding",
        data={"visual_theme": "wood"},
        files={"logo": ("", b"", "application/octet-stream")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?module=configuracion&notice=branding_saved"
    shop = client.get("/api/barber-shops").json()[0]
    assert shop["visual_theme"] == "wood"

    dashboard = client.get("/admin?module=configuracion")
    assert 'class="tf-theme-wood' in dashboard.text
    assert "Madera clara" in dashboard.text
    assert "Estudio Visual" in dashboard.text
    assert "Gestionado con TurnoFlow" in dashboard.text


def test_admin_weekly_schedule_replaces_days_and_accepts_sunday(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Agenda semanal"}).json()["id"]
    barber_id = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Diego", "service_ids": []},
    ).json()["id"]

    response = client.post(
        "/admin/working-schedules",
        data={
            "barber_id": str(barber_id),
            "days_of_week": ["1", "4", "6"],
            "replace_week": "true",
            "start_time": "09:30",
            "end_time": "19:30",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    schedules = client.get("/api/working-schedules", params={"barber_id": barber_id}).json()
    active_schedules = [schedule for schedule in schedules if schedule["is_active"]]
    assert {schedule["day_of_week"] for schedule in active_schedules} == {1, 4, 6}
    assert all(schedule["start_time"] == "09:30:00" for schedule in active_schedules)
    assert all(schedule["end_time"] == "19:30:00" for schedule in active_schedules)


def test_appointment_form_accepts_thirty_minute_duration(client: TestClient) -> None:
    response = client.get("/admin")

    duration_input = re.search(
        r'<input class="form-control" type="number" min="1" max="480" step="1" inputmode="numeric" name="duration_minutes" required>',
        response.text,
    )
    assert duration_input is not None


def test_appointment_form_hides_new_customer_fields_for_existing_customer(client: TestClient) -> None:
    response = client.get("/admin")

    assert response.text.count("data-new-customer-field") == 3
    assert "const syncCustomerMode" in response.text
    assert "input.disabled = !isCreatingCustomer" in response.text


def test_owner_can_manage_one_shop_without_mixing_other_shop_data(client: TestClient) -> None:
    shop_a_id = client.post("/api/barber-shops", json={"name": "Cliente Alfa"}).json()["id"]
    shop_b_id = client.post("/api/barber-shops", json={"name": "Cliente Beta"}).json()["id"]
    client.post(
        "/api/services",
        json={"barber_shop_id": shop_a_id, "name": "Servicio Alfa", "duration_minutes": 30, "price": "100"},
    )
    client.post(
        "/api/services",
        json={"barber_shop_id": shop_b_id, "name": "Servicio Beta", "duration_minutes": 30, "price": "200"},
    )

    manage_response = client.get(f"/owner/shops/{shop_a_id}/manage", follow_redirects=False)
    scoped_dashboard = client.get("/admin?module=servicios")

    assert manage_response.status_code == 303
    assert "Gestionando:" in scoped_dashboard.text
    assert "Cliente Alfa" in scoped_dashboard.text
    assert "Servicio Alfa" in scoped_dashboard.text
    assert "Servicio Beta" not in scoped_dashboard.text

    clear_response = client.get("/owner/shops/manage/clear", follow_redirects=False)
    full_dashboard = client.get("/admin?module=servicios")
    assert clear_response.status_code == 303
    assert "Servicio Alfa" in full_dashboard.text
    assert "Servicio Beta" in full_dashboard.text


def test_owner_user_lifecycle_preserves_business_data(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Cuenta Cliente"}).json()["id"]
    client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Cliente Conservado", "phone": "555"},
    )
    client.post(
        "/owner/users",
        data={
            "username": "cuenta_cliente",
            "password": "clave-segura",
            "role": "business_admin",
            "barber_shop_id": str(shop_id),
        },
        follow_redirects=False,
    )

    active_delete = client.post("/owner/users/1/delete", follow_redirects=False)
    assert active_delete.headers["location"] == "/owner?notice=user_must_be_inactive"

    deactivate = client.post("/owner/users/1/deactivate", follow_redirects=False)
    blocked_login = client.post(
        "/login",
        data={"username": "cuenta_cliente", "password": "clave-segura", "next_path": "/admin"},
    )
    assert deactivate.status_code == 303
    assert blocked_login.status_code == 401

    activate = client.post("/owner/users/1/activate", follow_redirects=False)
    valid_login = client.post(
        "/login",
        data={"username": "cuenta_cliente", "password": "clave-segura", "next_path": "/admin"},
        follow_redirects=False,
    )
    assert activate.status_code == 303
    assert valid_login.status_code == 303

    client.post("/owner/users/1/deactivate", follow_redirects=False)
    deleted = client.post("/owner/users/1/delete", follow_redirects=False)
    customers = client.get("/api/customers", params={"barber_shop_id": shop_id}).json()
    assert deleted.headers["location"] == "/owner?notice=user_deleted"
    assert customers[0]["full_name"] == "Cliente Conservado"


def test_suspension_invalidates_existing_business_session(client: TestClient, monkeypatch) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Sesion Suspendida"}).json()["id"]
    client.post(
        "/owner/users",
        data={
            "username": "suspendido",
            "password": "clave-segura",
            "role": "business_admin",
            "barber_shop_id": str(shop_id),
        },
    )
    monkeypatch.setattr(settings, "auth_enabled", True)
    login = client.post(
        "/login",
        data={"username": "suspendido", "password": "clave-segura", "next_path": "/admin"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get("/admin").status_code == 200

    monkeypatch.setattr(settings, "auth_enabled", False)
    client.post(f"/admin/barber-shops/{shop_id}/suspend", data={"reason": "Pago vencido"})
    monkeypatch.setattr(settings, "auth_enabled", True)

    blocked_session = client.get("/admin", follow_redirects=False)
    blocked_login = client.post(
        "/login",
        data={"username": "suspendido", "password": "clave-segura", "next_path": "/admin"},
    )
    assert blocked_session.status_code == 303
    assert blocked_session.headers["location"].startswith("/login")
    assert blocked_login.status_code == 401


def test_owner_password_reset_page_is_ready_to_share(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Clave Cliente"}).json()["id"]
    client.post(
        "/owner/users",
        data={
            "username": "cambiar_clave",
            "password": "clave-segura",
            "role": "business_admin",
            "barber_shop_id": str(shop_id),
        },
    )

    response = client.get("/owner/users/1/password-reset")

    assert response.status_code == 200
    assert "Cambiar clave de cambiar_clave" in response.text
    assert "Este enlace vence en una hora" in response.text
    assert "/password-reset?token=" in response.text
    assert "Copiar enlace" in response.text
