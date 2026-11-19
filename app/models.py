from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CreatedCampaign(Base):
    """A campaign created through the creator. Keitaro stays the source of truth;
    this is a local registry of what we created and with which inputs."""

    __tablename__ = "created_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(512))
    country: Mapped[str] = mapped_column(String(2))
    offer_id: Mapped[int] = mapped_column(Integer)
    domain_id: Mapped[int] = mapped_column(Integer)
    group_id: Mapped[int] = mapped_column(Integer)
    traffic_source_id: Mapped[int] = mapped_column(Integer)
    geo_stream_id: Mapped[int] = mapped_column(Integer)
    offer_stream_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OfferChange(Base):
    """Audit log of every change the editor pushed to Keitaro."""

    __tablename__ = "offer_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    stream_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))  # add | remove | shares
    offer_ids: Mapped[list] = mapped_column(JSON)  # offers the action was about
    before: Mapped[dict] = mapped_column(JSON)  # {offer_id: share} before
    after: Mapped[dict] = mapped_column(JSON)  # {offer_id: share} after
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
