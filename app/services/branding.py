from __future__ import annotations

from io import BytesIO
from urllib.parse import quote, urljoin
import warnings

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings


ALLOWED_VISUAL_THEMES = frozenset({"flow", "marble", "wood", "brick", "blush"})
MAX_LOGO_UPLOAD_BYTES = 3 * 1024 * 1024
MAX_LOGO_DIMENSION = 512


class BrandingError(ValueError):
    pass


def prepare_logo_image(raw_image: bytes) -> bytes:
    if not raw_image:
        raise BrandingError("Selecciona una imagen para el logo.")
    if len(raw_image) > MAX_LOGO_UPLOAD_BYTES:
        raise BrandingError("El logo debe pesar menos de 3 MB.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw_image)) as source:
                source.verify()
            with Image.open(BytesIO(raw_image)) as source:
                source_format = source.format
                if source_format not in {"JPEG", "PNG", "WEBP"}:
                    raise BrandingError("Usa una imagen JPG, PNG o WebP.")
                image = ImageOps.exif_transpose(source)
                image.thumbnail((MAX_LOGO_DIMENSION, MAX_LOGO_DIMENSION), Image.Resampling.LANCZOS)
                image = image.convert("RGBA")
                output = BytesIO()
                image.save(output, format="WEBP", quality=84, method=6)
    except BrandingError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError):
        raise BrandingError("El archivo no es una imagen valida o es demasiado grande.") from None

    return output.getvalue()


def _storage_headers() -> dict[str, str]:
    if not settings.insforge_base_url or not settings.insforge_api_key:
        raise BrandingError("El almacenamiento de logos no esta configurado.")
    return {"Authorization": f"Bearer {settings.insforge_api_key}"}


def _absolute_storage_url(value: str) -> str:
    return value if value.startswith(("http://", "https://")) else urljoin(f"{settings.insforge_base_url.rstrip('/')}/", value.lstrip("/"))


def upload_business_logo(barber_shop_id: int, logo: bytes) -> tuple[str, str]:
    headers = _storage_headers()
    bucket = settings.branding_bucket
    key = f"shops/{barber_shop_id}/logo.webp"
    base_url = settings.insforge_base_url.rstrip("/")
    strategy_url = f"{base_url}/api/storage/buckets/{quote(bucket)}/upload-strategy"

    try:
        with httpx.Client(timeout=20.0) as client:
            strategy_response = client.post(
                strategy_url,
                headers={**headers, "Content-Type": "application/json"},
                json={"filename": key, "contentType": "image/webp", "size": len(logo)},
            )
            strategy_response.raise_for_status()
            strategy_payload = strategy_response.json().get("data", strategy_response.json())
            method = strategy_payload.get("method")

            if method == "direct":
                upload_response = client.put(
                    _absolute_storage_url(strategy_payload["uploadUrl"]),
                    headers=headers,
                    files={"file": ("logo.webp", logo, "image/webp")},
                )
            elif method == "presigned":
                upload_response = client.post(
                    strategy_payload["uploadUrl"],
                    data=strategy_payload.get("fields", {}),
                    files={"file": ("logo.webp", logo, "image/webp")},
                )
            else:
                raise BrandingError("InsForge no devolvio una estrategia de carga valida.")

            upload_response.raise_for_status()
            result_payload = upload_response.json() if method == "direct" else {}

            if strategy_payload.get("confirmRequired"):
                confirm_response = client.post(
                    _absolute_storage_url(strategy_payload["confirmUrl"]),
                    headers={**headers, "Content-Type": "application/json"},
                    json={"size": len(logo), "contentType": "image/webp"},
                )
                confirm_response.raise_for_status()
                result_payload = confirm_response.json()

    except BrandingError:
        raise
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        raise BrandingError("No se pudo guardar el logo. Intenta nuevamente.") from None

    result_payload = result_payload.get("data", result_payload)
    returned_url = result_payload.get("url")
    if returned_url:
        return _absolute_storage_url(returned_url), key
    return f"{base_url}/api/storage/buckets/{quote(bucket)}/objects/{quote(key, safe='/')}", key


def delete_business_logo(logo_key: str) -> None:
    headers = _storage_headers()
    bucket = quote(settings.branding_bucket)
    encoded_key = quote(logo_key, safe="/")
    url = f"{settings.insforge_base_url.rstrip('/')}/api/storage/buckets/{bucket}/objects/{encoded_key}"
    try:
        response = httpx.delete(url, headers=headers, timeout=15.0)
        if response.status_code != 404:
            response.raise_for_status()
    except httpx.HTTPError:
        raise BrandingError("No se pudo eliminar el logo almacenado.") from None
