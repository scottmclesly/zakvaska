"""Saving, thumbnailing and serving photos.

Two files come out of every upload, and a third for the thumbnail:

* the **original**, written byte for byte as it arrived. It is the lab
  record — the frame the camera actually produced, EXIF and all — and
  nothing here ever rewrites it.
* a **display rendition**, always JPEG. That applies the EXIF orientation
  to the pixels so every browser shows the photo the right way up, drops
  the EXIF block (GPS with it) from the copy that gets served, and stops a
  12-megapixel phone photo being a 12-megapixel download on every page
  view. iPhones shoot HEIC and only Safari renders it, so for those the
  rendition is not a nicety but the only thing most browsers can show.
* a **thumbnail**, for galleries.

Keeping the original means the GPS coordinates in a phone photo stay on
disk, inside the data directory. They are never served by a page — only by
an explicit "download original" — but they are there.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.base import utcnow
from app.models.enums import PhotoOwner
from app.models.photo import Photo

# At import rather than in the app's lifespan: tests, scripts and migrations
# all open images without ever starting the app, and an unregistered opener
# fails as "not an image we can read", which is a liar of an error message.
pillow_heif.register_heif_opener()

# A phone photo is far more resolution than a lab notebook needs, and this
# has to stay comfortable on a Pi with an SD card.
MAX_EDGE = 2048
THUMB_EDGE = 480
JPEG_QUALITY = 85
THUMB_QUALITY = 78

# A recent iPhone's HEIC runs several megabytes, and the originals are kept
# now, so ten was starting to refuse honest photos. Still low enough to be a
# cheap guard against someone picking a video by mistake.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Decoded, not sniffed from the filename: the bytes decide. Pillow reports
# both .heic and .heif as HEIF once pillow-heif is registered.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "HEIF"}

# What to call the original on disk, by the format Pillow decoded it as.
ORIGINAL_SUFFIXES = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "GIF": ".gif",
    "BMP": ".bmp",
    "TIFF": ".tiff",
    "HEIF": ".heic",
}

ORIGINAL_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".heic": "image/heic",
}

EXIF_DATETIME_ORIGINAL = 36867
EXIF_DATETIME = 306


class PhotoError(ValueError):
    """Something about the upload is wrong, in words worth showing."""


@dataclass(frozen=True)
class Stored:
    path: str
    thumb_path: str
    taken_at: datetime
    original_path: str


def photos_root() -> Path:
    return get_settings().photos_dir


def absolute(relative: str) -> Path:
    """Resolve a stored relative path, refusing anything outside the root.

    The paths are all generated here, so this should never fire — which is
    exactly why it is cheap to keep.
    """
    root = photos_root().resolve()
    full = (root / relative).resolve()
    if not full.is_relative_to(root):
        raise PhotoError("That photo path is not inside the photo directory.")
    return full


def _taken_at(image: Image.Image, fallback: datetime) -> datetime:
    """When the shutter went, if the camera recorded it.

    EXIF timestamps carry no timezone, so they are read as local time in
    ZAKVASKA_TZ and converted — same assumption the rest of the app makes
    about a wall-clock time the user gives us.
    """
    try:
        exif = image.getexif()
    except Exception:  # a corrupt EXIF block is not a reason to refuse a photo
        return fallback
    if not exif:
        return fallback

    raw = exif.get(EXIF_DATETIME_ORIGINAL) or exif.get(EXIF_DATETIME)
    if not raw:
        return fallback
    try:
        naive = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return fallback
    return naive.replace(tzinfo=get_settings().tz).astimezone(UTC)


def _folder(when: datetime) -> tuple[Path, str]:
    """data/photos/YYYY/MM, as the plan asks (docs/dev/TODO-v1.md)."""
    local = when.astimezone(get_settings().tz)
    relative = f"{local:%Y/%m}"
    directory = photos_root() / relative
    directory.mkdir(parents=True, exist_ok=True)
    return directory, relative


def media_type_for(relative: str) -> str:
    """The type to serve an original as, from the name we gave it."""
    return ORIGINAL_MEDIA_TYPES.get(Path(relative).suffix.lower(), "application/octet-stream")


def store_bytes(data: bytes, *, now: datetime | None = None) -> Stored:
    """Write the original, a JPEG rendition and a thumbnail.

    Returns their relative paths. The original goes down exactly as it
    arrived; only the rendition and the thumbnail are Pillow's work.
    """
    if not data:
        raise PhotoError("That file was empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoError(
            f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    try:
        image = Image.open(BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise PhotoError("That file is not an image we can read.") from exc

    if image.format not in ALLOWED_FORMATS:
        raise PhotoError(f"{image.format or 'That format'} is not supported.")

    # exif_transpose() and convert() both return an image with no .format,
    # so the name for the original has to be decided while we still know it.
    source_format = image.format

    now = now or utcnow()
    taken = _taken_at(image, now)

    # Rotate the pixels rather than leaving an orientation tag behind.
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    directory, relative_dir = _folder(taken)
    stem = secrets.token_hex(8)

    # The bytes that arrived, untouched. Written first: if anything below
    # fails, the record of what the camera produced is already safe.
    suffix = ORIGINAL_SUFFIXES.get(source_format, ".bin")
    (directory / f"{stem}_original{suffix}").write_bytes(data)

    full = image.copy()
    full.thumbnail((MAX_EDGE, MAX_EDGE))
    full.save(directory / f"{stem}.jpg", "JPEG", quality=JPEG_QUALITY, optimize=True)

    thumb = image.copy()
    thumb.thumbnail((THUMB_EDGE, THUMB_EDGE))
    thumb.save(
        directory / f"{stem}_thumb.jpg", "JPEG", quality=THUMB_QUALITY, optimize=True
    )

    return Stored(
        path=f"{relative_dir}/{stem}.jpg",
        thumb_path=f"{relative_dir}/{stem}_thumb.jpg",
        taken_at=taken,
        original_path=f"{relative_dir}/{stem}_original{suffix}",
    )


def attach(
    session: Session,
    *,
    owner_type: PhotoOwner,
    owner_id: int,
    data: bytes,
    caption: str | None = None,
    now: datetime | None = None,
) -> Photo:
    stored = store_bytes(data, now=now)
    photo = Photo(
        owner_type=owner_type,
        owner_id=owner_id,
        path=stored.path,
        thumb_path=stored.thumb_path,
        original_path=stored.original_path,
        taken_at=stored.taken_at,
        caption=caption,
    )
    session.add(photo)
    session.flush()
    return photo


# --- Reading ---------------------------------------------------------------


def list_for(
    session: Session, owner_type: PhotoOwner, owner_id: int
) -> list[Photo]:
    return list(
        session.scalars(
            select(Photo)
            .where(Photo.owner_type == owner_type, Photo.owner_id == owner_id)
            .order_by(Photo.taken_at, Photo.id)
        )
    )


def counts_for(
    session: Session, owner_type: PhotoOwner, owner_ids: list[int]
) -> dict[int, int]:
    """How many photos each of these owners has. One query, not N."""
    if not owner_ids:
        return {}
    rows = session.execute(
        select(Photo.owner_id, Photo.id)
        .where(Photo.owner_type == owner_type, Photo.owner_id.in_(owner_ids))
    ).all()
    counts: dict[int, int] = {}
    for owner_id, _ in rows:
        counts[owner_id] = counts.get(owner_id, 0) + 1
    return counts


def photos_by_owner(
    session: Session, owner_type: PhotoOwner, owner_ids: list[int]
) -> dict[int, list[Photo]]:
    """Every owner's photos in one query, for a timeline."""
    if not owner_ids:
        return {}
    found = session.scalars(
        select(Photo)
        .where(Photo.owner_type == owner_type, Photo.owner_id.in_(owner_ids))
        .order_by(Photo.taken_at, Photo.id)
    )
    grouped: dict[int, list[Photo]] = {}
    for photo in found:
        grouped.setdefault(photo.owner_id, []).append(photo)
    return grouped


def get_photo(session: Session, photo_id: int) -> Photo | None:
    return session.get(Photo, photo_id)


def bake_photos(session: Session) -> list[Photo]:
    """Every bake photo, newest first — the pool the compare page picks from."""
    return list(
        session.scalars(
            select(Photo)
            .where(Photo.owner_type == PhotoOwner.BAKE)
            .order_by(Photo.taken_at.desc(), Photo.id.desc())
        )
    )


def compare_partners(session: Session, bake) -> dict | None:
    """What a loaf's photos can be set beside, and the likeliest of them.

    Every photo of every other bake, newest first, each with the bake it is
    of — and one suggestion: the newest photo of the most recent other bake
    of the same recipe, because "better than last time?" is the question a
    loaf just out of the oven is asked. None when there is nothing to
    compare it with.
    """
    others = [photo for photo in bake_photos(session) if photo.owner_id != bake.id]
    if not others:
        return None
    owners = bake_photo_owners(session, others)
    paired = [(photo, owners[photo.owner_id]) for photo in others if photo.owner_id in owners]
    if not paired:
        return None

    recipe_id = bake.version.recipe_id
    same = [(photo, owner) for photo, owner in paired if owner.version.recipe_id == recipe_id]
    suggested = None
    if same:
        # The bake nearest in time to this one, and its newest photo.
        nearest = max(same, key=lambda pair: (pair[1].at, pair[0].taken_at))[1]
        suggested = next(photo for photo, owner in same if owner.id == nearest.id)
    return {
        "same": same,
        "other": [pair for pair in paired if pair not in same],
        "suggested": suggested.id if suggested else paired[0][0].id,
    }


# --- Writing ---------------------------------------------------------------


def set_caption(session: Session, photo: Photo, caption: str | None) -> Photo:
    photo.caption = caption
    session.flush()
    return photo


def delete_photo(session: Session, photo: Photo) -> None:
    """Really delete it, files and all.

    CLAUDE.md's never-delete rule covers jars, recipes and bakes — the
    lab-notebook record. A blurry photo of a jar lid is not that, and
    there has to be a way to undo a misfired upload.
    """
    for relative in (photo.path, photo.thumb_path, photo.original_path):
        if not relative:
            continue
        try:
            absolute(relative).unlink(missing_ok=True)
        except (PhotoError, OSError):
            # A missing file must not block removing the row that points at it.
            pass
    session.delete(photo)
    session.flush()


# --- Where a photo belongs -------------------------------------------------


def owner_url(session: Session, owner_type: PhotoOwner, owner_id: int) -> str | None:
    """The page a photo lives on, or None if its owner has gone.

    Feedings and observations have no page of their own: they appear on
    their jar's timeline, so that is where an upload returns to.
    """
    from app.models.bake import Bake
    from app.models.feeding import Feeding
    from app.models.jar import Jar
    from app.models.observation import Observation

    if owner_type is PhotoOwner.JAR:
        return f"/jars/{owner_id}" if session.get(Jar, owner_id) else None
    if owner_type is PhotoOwner.BAKE:
        return f"/bakes/{owner_id}" if session.get(Bake, owner_id) else None
    if owner_type is PhotoOwner.FEEDING:
        feeding = session.get(Feeding, owner_id)
        return f"/jars/{feeding.jar_id}" if feeding else None
    observation = session.get(Observation, owner_id)
    return f"/jars/{observation.jar_id}" if observation else None


def bake_photo_owners(session: Session, photos: list[Photo]) -> dict[int, object]:
    """The bake behind each bake photo, so the compare page can name them."""
    from app.models.bake import Bake

    ids = {photo.owner_id for photo in photos}
    if not ids:
        return {}
    found = session.scalars(select(Bake).where(Bake.id.in_(ids)))
    return {bake.id: bake for bake in found}
