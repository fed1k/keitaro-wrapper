from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Campaign(Base):
    """A campaign created through this service (mirror of the Keitaro entity)."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(512))
    geo: Mapped[list[str]] = mapped_column(JSON)
    initial_offer_id: Mapped[int] = mapped_column(Integer)
    google_stream_id: Mapped[int] = mapped_column(Integer)
    offers_stream_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    events: Mapped[list["OfferEvent"]] = relationship(back_populates="campaign")


class OfferEvent(Base):
    """Audit log of editor operations (add / remove / reweight offers)."""

    __tablename__ = "offer_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    keitaro_campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    stream_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))  # add | remove | reweight
    offer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares_after: Mapped[dict] = mapped_column(JSON)  # {"offer_id": share}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    campaign: Mapped[Campaign | None] = relationship(back_populates="events")
