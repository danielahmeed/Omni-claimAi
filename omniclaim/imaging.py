"""Image handling: validation, camera metadata, perceptual hashing, resizing.

Every uploaded photo goes through these deterministic checks, whether or not
Gemini is configured:

* validation  - only real JPEG/PNG/WebP images within size limits are accepted;
* metadata    - camera make/model, capture time, editing software and GPS are
                read from EXIF before the image is re-encoded;
* dHash       - a 64-bit perceptual hash that stays (almost) the same when a
                photo is resized or re-compressed, used to find reused photos;
* normalising - the photo is rotated upright, converted to RGB and re-encoded
                as JPEG (metadata removed) for storage, display and Gemini.
"""

import io
from dataclasses import dataclass
from datetime import datetime

from PIL import Image, ImageOps, UnidentifiedImageError

# Refuse decompression bombs early: ~50 megapixels is far above any phone photo.
MAX_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

IMAGE_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
PHOTO_MAX_SIDE = 1600      # enough detail for damage assessment
DOCUMENT_MAX_SIDE = 2200   # keep invoice text legible

# EXIF tag numbers (see the EXIF 2.3 specification).
TAG_MAKE, TAG_MODEL, TAG_SOFTWARE, TAG_DATETIME = 271, 272, 305, 306
IFD_EXIF, IFD_GPS = 0x8769, 0x8825
TAG_DATETIME_ORIGINAL = 36867
EDITING_SOFTWARE = ("photoshop", "gimp", "lightroom", "snapseed", "canva", "picsart", "pixlr", "affinity", "facetune")


class InvalidUpload(ValueError):
    """Raised when an uploaded file is not an acceptable image or PDF."""


@dataclass
class ProcessedImage:
    jpeg: bytes
    width: int
    height: int
    dhash: str
    metadata: dict
    source_format: str


def open_image(data: bytes, what: str = "Photo") -> Image.Image:
    if not data:
        raise InvalidUpload(f"{what} is empty.")
    try:
        img = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError:
        raise InvalidUpload(f"{what} is too large.") from None
    except (UnidentifiedImageError, OSError):
        raise InvalidUpload(f"{what} is not a readable image. Use JPEG, PNG or WebP.") from None
    if img.format not in IMAGE_FORMATS:
        raise InvalidUpload(f"{what} format {img.format or 'unknown'} is not supported. Use JPEG, PNG or WebP.")
    width, height = img.size
    if width < 32 or height < 32:
        raise InvalidUpload(f"{what} is too small ({width}x{height}).")
    if width * height > MAX_PIXELS:
        raise InvalidUpload(f"{what} is too large ({width}x{height} pixels).")
    try:
        img.load()
    except (OSError, Image.DecompressionBombError) as exc:
        raise InvalidUpload(f"{what} could not be decoded: {exc}") from None
    return img


def _rational(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _gps_to_decimal(dms, ref) -> float | None:
    try:
        degrees, minutes, seconds = (_rational(v) for v in dms)
    except (TypeError, ValueError):
        return None
    value = degrees + minutes / 60.0 + seconds / 3600.0
    if str(ref).upper() in ("S", "W"):
        value = -value
    return round(value, 6)


def _parse_exif_datetime(value) -> str | None:
    if not value:
        return None
    text = str(value).strip().replace("\x00", "")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return None


def extract_metadata(img: Image.Image) -> dict:
    """Read the camera metadata that matters for claims review."""
    meta = {
        "hasExif": False,
        "cameraMake": None,
        "cameraModel": None,
        "capturedAt": None,
        "software": None,
        "editedWith": None,
        "gps": None,
    }
    try:
        exif = img.getexif()
    except Exception:  # Corrupt EXIF blocks should not stop the claim.
        return meta
    if not exif:
        return meta
    meta["hasExif"] = True
    meta["cameraMake"] = str(exif.get(TAG_MAKE) or "").strip().replace("\x00", "") or None
    meta["cameraModel"] = str(exif.get(TAG_MODEL) or "").strip().replace("\x00", "") or None
    software = str(exif.get(TAG_SOFTWARE) or "").strip().replace("\x00", "")
    meta["software"] = software or None
    if software and any(name in software.lower() for name in EDITING_SOFTWARE):
        meta["editedWith"] = software
    try:
        exif_ifd = exif.get_ifd(IFD_EXIF)
    except Exception:
        exif_ifd = {}
    meta["capturedAt"] = _parse_exif_datetime(exif_ifd.get(TAG_DATETIME_ORIGINAL)) or _parse_exif_datetime(exif.get(TAG_DATETIME))
    try:
        gps = exif.get_ifd(IFD_GPS)
    except Exception:
        gps = {}
    if gps and 2 in gps and 4 in gps:
        lat = _gps_to_decimal(gps.get(2), gps.get(1, "N"))
        lon = _gps_to_decimal(gps.get(4), gps.get(3, "E"))
        if lat is not None and lon is not None and (lat or lon):
            meta["gps"] = {"lat": lat, "lon": lon}
    return meta


def _to_rgb(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img) or img
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    return img.convert("RGB")


def dhash(img: Image.Image) -> str:
    """64-bit difference hash, returned as 16 hex characters."""
    small = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = small.tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def hamming_distance(hash_a: str, hash_b: str) -> int:
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")


def _encode_jpeg(img: Image.Image, max_side: int, quality: int) -> tuple[bytes, int, int]:
    img = img.copy()
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue(), img.width, img.height


def process_photo(data: bytes) -> ProcessedImage:
    img = open_image(data, "Photo")
    source_format = img.format
    metadata = extract_metadata(img)
    rgb = _to_rgb(img)
    jpeg, width, height = _encode_jpeg(rgb, PHOTO_MAX_SIDE, quality=86)
    return ProcessedImage(jpeg=jpeg, width=width, height=height, dhash=dhash(rgb),
                          metadata=metadata, source_format=source_format)


def process_document_image(data: bytes) -> ProcessedImage:
    img = open_image(data, "Document")
    source_format = img.format
    rgb = _to_rgb(img)
    jpeg, width, height = _encode_jpeg(rgb, DOCUMENT_MAX_SIDE, quality=90)
    return ProcessedImage(jpeg=jpeg, width=width, height=height, dhash=dhash(rgb),
                          metadata={}, source_format=source_format)


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"
