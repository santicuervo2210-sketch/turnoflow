from __future__ import annotations

from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


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
