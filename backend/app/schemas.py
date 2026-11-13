from typing import Optional

from pydantic import BaseModel, Field


class CreateCampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200, description="Campaign name (the prefix is added automatically)")
    geo: str = Field(min_length=2, max_length=200, description="Comma-separated country codes: MX,AU,RO")
    offer_id: int = Field(gt=0, description="Offer ID in Keitaro")
    domain_id: Optional[int] = None
    group_id: Optional[int] = None
    traffic_source_id: Optional[int] = None


class OfferIn(BaseModel):
    offer_id: int = Field(gt=0)
