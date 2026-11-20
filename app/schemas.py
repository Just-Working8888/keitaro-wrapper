from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    country: str = Field(description="ISO 3166-1 alpha-2, например DE")
    offer_id: int = Field(gt=0)
    domain_id: Optional[int] = None
    group_id: Optional[int] = None
    traffic_source_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @field_validator("country")
    @classmethod
    def check_country(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 2 or not v.isalpha() or not v.isascii():
            raise ValueError("Гео-код — две латинские буквы (ISO 3166-1), например DE")
        return v


class CreatedCampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keitaro_id: int
    name: str
    alias: str
    url: str
    country: str
    offer_id: int
    domain_id: int
    group_id: int
    traffic_source_id: int
    geo_stream_id: int
    offer_stream_id: int
    created_at: datetime


class AddOffer(BaseModel):
    offer_id: int = Field(gt=0)


class UpdateOffer(BaseModel):
    share: Optional[int] = Field(default=None, ge=0, le=100)
    pinned: Optional[bool] = None


class OfferChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    stream_id: int
    action: str
    offer_ids: list
    before: dict
    after: dict
    note: Optional[str]
    created_at: datetime
