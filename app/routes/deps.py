"""Shared route dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models.base import utcnow
from app.services.settings_store import temp_unit, weight_unit


@dataclass(frozen=True)
class ViewContext:
    """Everything a template needs that is not the page's own data."""

    session: Session
    now: datetime
    tz: ZoneInfo
    temp_unit: str
    weight_unit: str


def get_view_context(session: Session = Depends(get_session)) -> ViewContext:
    settings = get_settings()
    return ViewContext(
        session=session,
        now=utcnow(),
        tz=settings.tz,
        temp_unit=temp_unit(session),
        weight_unit=weight_unit(session),
    )
