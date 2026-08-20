from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.services.branding import BrandingError, prepare_logo_image


def _png_logo(width: int = 900, height: int = 600) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (width, height), (111, 61, 255, 255)).save(output, format="PNG")
    return output.getvalue()


def test_prepare_logo_image_rejects_invalid_files() -> None:
    try:
        prepare_logo_image(b"esto no es una imagen")
    except BrandingError as exc:
        assert "imagen valida" in str(exc)
    else:
        raise AssertionError("El archivo invalido debio rechazarse")


def test_prepare_logo_image_outputs_small_webp() -> None:
    processed = prepare_logo_image(_png_logo())

    with Image.open(BytesIO(processed)) as logo:
        assert logo.format == "WEBP"
        assert logo.width <= 512
        assert logo.height <= 512


def test_admin_uploads_and_renders_business_logo(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Logo Studio"}).json()["id"]
    client.get(f"/owner/shops/{shop_id}/manage", follow_redirects=False)
    response = client.post(
        f"/admin/barber-shops/{shop_id}/branding",
        data={"visual_theme": "marble"},
        files={"logo": ("logo.png", _png_logo(), "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    logo_path = f"/admin/barber-shops/{shop_id}/logo"
    logo_response = client.get(logo_path)
    assert logo_response.status_code == 200
    assert logo_response.headers["content-type"] == "image/webp"
    assert logo_response.headers["cache-control"] == "private, no-store"
    with Image.open(BytesIO(logo_response.content)) as stored_logo:
        assert stored_logo.format == "WEBP"
        assert stored_logo.width <= 512

    shop = client.get("/api/barber-shops").json()[0]
    assert shop["visual_theme"] == "marble"
    assert shop["logo_url"] == logo_path
    dashboard = client.get("/admin")
    assert logo_path in dashboard.text
    assert "Logo de Logo Studio" in dashboard.text


def test_admin_rejects_fake_logo_with_spanish_error(client: TestClient) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Logo Invalido"}).json()["id"]
    client.get(f"/owner/shops/{shop_id}/manage", follow_redirects=False)

    response = client.post(
        f"/admin/barber-shops/{shop_id}/branding",
        data={"visual_theme": "brick"},
        files={"logo": ("logo.png", b"contenido falso", "image/png")},
    )

    assert response.status_code == 400
    assert "El archivo no es una imagen valida" in response.text
    assert client.get("/api/barber-shops").json()[0]["visual_theme"] == "flow"


def test_business_admin_cannot_read_another_business_logo(client: TestClient, monkeypatch) -> None:
    shop_a_id = client.post("/api/barber-shops", json={"name": "Identidad A"}).json()["id"]
    shop_b_id = client.post("/api/barber-shops", json={"name": "Identidad B"}).json()["id"]
    for shop_id, color in ((shop_a_id, (20, 120, 220, 255)), (shop_b_id, (220, 60, 90, 255))):
        output = BytesIO()
        Image.new("RGBA", (120, 120), color).save(output, format="PNG")
        response = client.post(
            f"/admin/barber-shops/{shop_id}/branding",
            data={"visual_theme": "flow"},
            files={"logo": ("logo.png", output.getvalue(), "image/png")},
            follow_redirects=False,
        )
        assert response.status_code == 303

    client.post(
        "/owner/users",
        data={
            "username": "identidad_a",
            "password": "clave-segura",
            "role": "business_admin",
            "barber_shop_id": str(shop_a_id),
        },
        follow_redirects=False,
    )
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "session_secret", "test-secret-branding-isolation")
    login = client.post(
        "/login",
        data={"username": "identidad_a", "password": "clave-segura", "next_path": "/admin"},
        follow_redirects=False,
    )

    assert login.status_code == 303
    assert client.get(f"/admin/barber-shops/{shop_a_id}/logo").status_code == 200
    assert client.get(f"/admin/barber-shops/{shop_b_id}/logo").status_code == 404
    dashboard = client.get("/admin")
    assert "Identidad A" in dashboard.text
    assert "Identidad B" not in dashboard.text
