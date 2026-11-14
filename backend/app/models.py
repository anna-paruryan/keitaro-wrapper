from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class Stream(Base):
    """Поток Keitaro, который редактор уже «видел» (Fetch). Здесь живёт черновик: изменения до Push."""

    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    campaign_keitaro_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    has_offers: Mapped[bool] = mapped_column(Boolean, default=False)  # False: поток-редирект, его не разбираем

    offers: Mapped[list["StreamOffer"]] = relationship(
        back_populates="stream", cascade="all, delete-orphan", order_by="StreamOffer.id"
    )


class StreamOffer(Base):
    """Оффер в потоке: что показываем сейчас (черновик) и что сейчас реально лежит в Keitaro."""

    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id", name="uq_stream_offers_stream_offer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(Integer)
    offer_name: Mapped[str] = mapped_column(String(255))

    share: Mapped[int] = mapped_column(Integer, default=0)  # доля в черновике
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)  # доля закреплена
    removed: Mapped[bool] = mapped_column(Boolean, default=False)  # серый: убран (soft delete)
    draft_added: Mapped[bool] = mapped_column(Boolean, default=False)  # добавлен в черновике: Cancel удалит строку
    published_share: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # доля в Keitaro; None = там его нет

    stream: Mapped["Stream"] = relationship(back_populates="offers")