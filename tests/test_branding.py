from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

import app.web.routes as web_routes
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


def test_admin_uploads_and_renders_business_logo(client: TestClient, monkeypatch) -> None:
    shop_id = client.post("/api/barber-shops", json={"name": "Logo Studio"}).json()["id"]
    client.get(f"/owner/shops/{shop_id}/manage", follow_redirects=False)
    received: dict[str, object] = {}

    def fake_upload(barber_shop_id: int, logo: bytes) -> tuple[str, str]:
        received["shop_id"] = barber_shop_id
        received["logo"] = logo
        return "https://cdn.example.com/shops/logo.webp", f"shops/{barber_shop_id}/logo.webp"

    monkeypatch.setattr(web_routes, "upload_business_logo", fake_upload)
    response = client.post(
        f"/admin/barber-shops/{shop_id}/branding",
        data={"visual_theme": "marble"},
        files={"logo": ("logo.png", _png_logo(), "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert received["shop_id"] == shop_id
    with Image.open(BytesIO(received["logo"])) as stored_logo:
        assert stored_logo.format == "WEBP"
        assert stored_logo.width <= 512

    shop = client.get("/api/barber-shops").json()[0]
    assert shop["visual_theme"] == "marble"
    assert shop["logo_url"] == "https://cdn.example.com/shops/logo.webp"
    dashboard = client.get("/admin")
    assert "https://cdn.example.com/shops/logo.webp" in dashboard.text
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
