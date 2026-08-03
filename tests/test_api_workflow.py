from fastapi.testclient import TestClient


def test_management_and_booking_flow(client: TestClient) -> None:
    shop_response = client.post(
        "/api/barber-shops",
        json={"name": "TurnoFlow Demo", "phone": "2222222222", "address": "Main Street 123"},
    )
    assert shop_response.status_code == 201
    shop_id = shop_response.json()["id"]

    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Haircut",
            "duration_minutes": 30,
            "price": "5000.00",
        },
    )
    assert service_response.status_code == 201
    service_id = service_response.json()["id"]

    barber_response = client.post(
        "/api/barbers",
        json={
            "barber_shop_id": shop_id,
            "name": "Martin",
            "phone": "1111111111",
            "service_ids": [service_id],
        },
    )
    assert barber_response.status_code == 201
    barber_id = barber_response.json()["id"]

    schedule_response = client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    assert schedule_response.status_code == 201

    customer_response = client.post(
        "/api/customers",
        json={
            "barber_shop_id": shop_id,
            "full_name": "Santi Cliente",
            "phone": "3333333333",
        },
    )
    assert customer_response.status_code == 201
    customer_id = customer_response.json()["id"]

    availability_response = client.get(
        "/api/availability",
        params={
            "barber_id": barber_id,
            "service_id": service_id,
            "target_date": "2026-08-01",
        },
    )
    assert availability_response.status_code == 200
    assert availability_response.json()[0] == {
        "starts_at": "2026-08-01T09:00:00",
        "ends_at": "2026-08-01T09:30:00",
    }

    appointment_response = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-01T09:00:00",
        },
    )
    assert appointment_response.status_code == 201
    appointment = appointment_response.json()
    assert appointment["status"] == "pending"
    assert appointment["is_paid"] is False
    assert appointment["ends_at"] == "2026-08-01T09:30:00"

    confirm_response = client.post(f"/api/appointments/{appointment['id']}/confirm")
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "confirmed"

    paid_response = client.post(
        f"/api/appointments/{appointment['id']}/paid",
        json={"payment_method": "cash"},
    )
    assert paid_response.status_code == 200
    assert paid_response.json()["is_paid"] is True
    assert paid_response.json()["payment_method"] == "cash"

    supply_sale_response = client.post(
        "/api/supply-sales",
        json={
            "barber_shop_id": shop_id,
            "appointment_id": appointment["id"],
            "name": "Hair gel",
            "quantity": 2,
            "unit_price": "1500.00",
        },
    )
    assert supply_sale_response.status_code == 201
    assert supply_sale_response.json()["total_price"] == "3000.00"

    overlap_response = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-01T09:15:00",
        },
    )
    assert overlap_response.status_code == 409
    assert overlap_response.json()["detail"] == "Selected time overlaps another active appointment"

    availability_after_booking = client.get(
        "/api/availability",
        params={
            "barber_id": barber_id,
            "service_id": service_id,
            "target_date": "2026-08-01",
        },
    )
    assert availability_after_booking.status_code == 200
    assert availability_after_booking.json()[0]["starts_at"] == "2026-08-01T09:30:00"

    cancel_response = client.post(f"/api/appointments/{appointment['id']}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    booking_after_cancel_response = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-01T09:15:00",
        },
    )
    assert booking_after_cancel_response.status_code == 201


def test_suspended_shop_cannot_create_appointments(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Suspended Demo"})
    shop_id = shop_response.json()["id"]

    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Beard trim",
            "duration_minutes": 30,
            "price": "3000.00",
        },
    )
    service_id = service_response.json()["id"]

    barber_response = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Ana", "service_ids": [service_id]},
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
        json={"barber_shop_id": shop_id, "full_name": "Blocked Client", "phone": "555"},
    )
    customer_id = customer_response.json()["id"]

    suspend_response = client.post(
        f"/api/barber-shops/{shop_id}/suspend",
        json={"reason": "payment overdue"},
    )
    assert suspend_response.status_code == 200
    assert suspend_response.json()["access_status"] == "suspended"

    booking_response = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-01T10:00:00",
        },
    )
    assert booking_response.status_code == 403
    assert booking_response.json()["detail"] == "Barber shop access is suspended"

    activate_response = client.post(f"/api/barber-shops/{shop_id}/activate")
    assert activate_response.status_code == 200
    assert activate_response.json()["access_status"] == "active"
