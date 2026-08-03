import re

from fastapi.testclient import TestClient

from app.core.config import settings
import app.web.routes as web_routes


def _csrf_token_from(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


def test_admin_dashboard_loads(client: TestClient) -> None:
    response = client.get("/admin")

    assert response.status_code == 200
    assert "TurnoFlow" in response.text
    assert "Gestion" in response.text


def test_admin_modules_render_only_selected_content(client: TestClient) -> None:
    agenda_response = client.get("/admin")
    services_response = client.get("/admin?module=servicios")

    assert agenda_response.status_code == 200
    assert "Agenda del negocio" in agenda_response.text
    assert "Precios, duracion y oferta" not in agenda_response.text

    assert services_response.status_code == 200
    assert "Precios, duracion y oferta" in services_response.text
    assert "Agenda del negocio" not in services_response.text


def test_admin_agenda_registers_cash_and_rendimiento_is_read_only(client: TestClient) -> None:
    agenda_response = client.get("/admin")
    rendimiento_response = client.get("/admin?module=rendimiento")

    assert agenda_response.status_code == 200
    assert "Total generado del dia" in agenda_response.text
    assert "action=\"/admin/supply-sales\"" in agenda_response.text

    assert rendimiento_response.status_code == 200
    assert "Historial y caja" in rendimiento_response.text
    assert "Ingresos extra registrados" in rendimiento_response.text
    assert "action=\"/admin/supply-sales\"" not in rendimiento_response.text


def test_admin_auth_can_protect_demo_routes(client: TestClient, monkeypatch) -> None:
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

    admin_response = client.get("/admin")
    assert admin_response.status_code == 200
    assert "Agenda y caja" in admin_response.text


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
            "password": "clave1",
            "role": "business_admin",
            "barber_shop_id": str(shop_one_id),
        },
        follow_redirects=False,
    )
    assert create_user_response.status_code == 303

    client.get("/logout")
    business_login = client.post(
        "/login",
        data={"username": "cliente1", "password": "clave1", "next_path": "/admin"},
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
            "password": "clave1",
            "role": "business_admin",
            "barber_shop_id": str(shop_one_id),
        },
        follow_redirects=False,
    )
    client.get("/logout")
    client.post(
        "/login",
        data={"username": "portal1", "password": "clave1", "next_path": "/admin"},
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
    assert "Direccion: Street 1" in dashboard_response.text
    assert "Mica" in dashboard_response.text


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
    assert "Agenda activa" in dashboard_response.text
    assert "11:00 - Santi Cliente" in dashboard_response.text
    assert "Historial y caja" not in dashboard_response.text
    history_response = client.get("/admin?module=rendimiento")
    assert history_response.status_code == 200
    assert "Historial y caja" in history_response.text

    cancel_response = client.post(f"/admin/appointments/{appointment_id}/cancel")
    assert cancel_response.status_code == 200
    assert "$0 cancelado" in cancel_response.text


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
    assert booking_response.json()["detail"] == "Selected time is blocked by the barber"

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
    assert client.get("/api/barber-shops").json()[0]["access_status"] == "active"


def test_owner_panel_shows_commercial_access_status(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Pago Demo"})
    shop_id = shop_response.json()["id"]

    owner_response = client.get("/owner")
    assert owner_response.status_code == 200
    assert "Estado comercial por cliente" in owner_response.text
    assert "Pago Demo" in owner_response.text
    assert "pago / activo" in owner_response.text
    assert "plan basic" in owner_response.text

    suspend_response = client.post(
        f"/admin/barber-shops/{shop_id}/suspend",
        data={"reason": "Pago vencido"},
        follow_redirects=False,
    )
    assert suspend_response.status_code == 303

    suspended_owner_response = client.get("/owner")
    assert "suspendido" in suspended_owner_response.text
    assert "Motivo: Pago vencido" in suspended_owner_response.text


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
