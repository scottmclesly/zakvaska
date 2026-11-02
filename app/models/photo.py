"""Photos attached to a jar, a feeding, an observation or a bake.

Stored as a type/id pair rather than four nullable foreign keys. That costs
database-level referential integrity, which is a real trade: the owners are
four unrelated tables, nothing joins through a photo, and the alternative is
four columns of which three are always null.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, utcnow
from app.models.enums import PhotoOwner
from app.models.types import UtcDateTime


class Photo(Base):
    __tablename__ = "photo"
    __table_args__ = (
        # Every lookup is "the photos for this thing".
        Index("ix_photo_owner", "owner_type", "owner_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    owner_type: Mapped[PhotoOwner] = mapped_column(
        Enum(PhotoOwner, native_enum=False, validate_strings=True, length=16),
        nullable=False,
    )
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relative to ZAKVASKA_DATA_DIR/photos, so moving the data dir — onto a
    # Raspberry Pi, say — does not invalidate a single row.
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    thumb_path: Mapped[str] = mapped_column(String(255), nullable=False)
    # The file exactly as it was uploaded. Nullable because photos stored
    # before originals were kept have none, and those rows stay valid.
    original_path: Mapped[str | None] = mapped_column(String(255))

    # From the camera's EXIF when it has it, otherwise the upload time.
    taken_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, index=True
    )
    caption: Mapped[str | None] = mapped_column(Text)
    created_at = created_at_column()

    @property
    def url(self) -> str:
        return f"/photos/{self.id}/file"

    @property
    def thumb_url(self) -> str:
        return f"/photos/{self.id}/thumb"

    @property
    def original_url(self) -> str:
        return f"/photos/{self.id}/original"

    @property
    def has_original(self) -> bool:
        return bool(self.original_path)

    def __repr__(self) -> str:
        return (
            f"Photo(id={self.id!r}, owner={self.owner_type.value}:"
            f"{self.owner_id!r})"
        )
