from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Campaign(Base):
    """Кампания, созданная через наш «создаватор» (история + быстрый доступ из редактора)."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str] = mapped_column(String(64))
    geo: Mapped[str] = mapped_column(String(255))
    offer_id: Mapped[int] = mapped_column(Integer)
    offer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    geo_stream_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    offer_stream_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    domain_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    group_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    traffic_source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tracker_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OfferChange(Base):
    """Журнал правок офферов в редакторе: что и когда добавили/убрали, и как изменились доли."""

    __tablename__ = "offer_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_keitaro_id: Mapped[int] = mapped_column(Integer, index=True)
    stream_keitaro_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))  # add | remove | equalize
    offer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    offer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    shares_before: Mapped[list] = mapped_column(JSON)
    shares_after: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
