from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.countries import COUNTRIES

Interval = Literal["today", "yesterday", "7_days_ago", "1_month_ago", "all_time"]


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geo: list[str] = Field(min_length=1, description="ISO-3166 alpha-2 codes, e.g. ['AU', 'MX']")
    offer_id: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @field_validator("geo", mode="before")
    @classmethod
    def normalize_geo(cls, v):
        if isinstance(v, str):
            v = v.split(",")
        codes: list[str] = []
        for raw in v:
            code = str(raw).strip().upper()
            if not code:
                continue
            if code not in COUNTRIES:
                raise ValueError(f"Неизвестный код страны: {code}")
            if code not in codes:
                codes.append(code)
        if not codes:
            raise ValueError("Укажите хотя бы одну страну")
        return codes


class CampaignOut(BaseModel):
    id: int
    keitaro_id: int
    name: str
    alias: str
    url: str
    geo: list[str]
    initial_offer_id: int
    google_stream_id: int
    offers_stream_id: int

    model_config = {"from_attributes": True}


class OfferAdd(BaseModel):
    offer_id: int = Field(gt=0)


class SharesUpdate(BaseModel):
    shares: dict[int, int] = Field(description="offer_id -> share (%), must sum to 100")


class OfferOption(BaseModel):
    id: int
    name: str
    state: str
