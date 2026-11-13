import threading
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from . import services
from .config import Settings, get_settings
from .db import get_db
from .keitaro import KeitaroClient
from .schemas import CreateCampaignIn, OfferIn
from .services import AppError

router = APIRouter(prefix="/api")

_client: Optional[KeitaroClient] = None
_client_key: Optional[tuple] = None
_client_lock = threading.Lock()


def get_settings_dep() -> Settings:
    return get_settings()


def get_client(settings: Settings = Depends(get_settings_dep)) -> KeitaroClient:
    """Один общий HTTP-клиент на процесс."""
    global _client, _client_key
    if not settings.keitaro_configured:
        raise AppError(503, "Keitaro is not configured: set KEITARO_URL and KEITARO_API_KEY in the .env file and restart the server.")
    key = (settings.keitaro_url, settings.keitaro_api_key, settings.keitaro_timeout)
    with _client_lock:
        if _client is None or _client_key != key:
            _client = KeitaroClient(settings.keitaro_url, settings.keitaro_api_key, settings.keitaro_timeout)
            _client_key = key
        return _client


@router.get("/health")
def health(settings: Settings = Depends(get_settings_dep)):
    return {"ok": True, "keitaro_configured": settings.keitaro_configured}


@router.get("/meta")
def meta(client: KeitaroClient = Depends(get_client), settings: Settings = Depends(get_settings_dep)):
    """Всё, что нужно форме: префикс, домены, группы, источники и значения по умолчанию."""
    return services.load_meta(client, settings)


@router.get("/offers")
def offers(
    q: str = "",
    limit: int = Query(15, ge=1, le=50),
    client: KeitaroClient = Depends(get_client),
    settings: Settings = Depends(get_settings_dep),
):
    return services.search_offers(client, settings, q, limit)


@router.post("/campaigns", status_code=201)
def create_campaign(
    body: CreateCampaignIn,
    db: Session = Depends(get_db),
    client: KeitaroClient = Depends(get_client),
    settings: Settings = Depends(get_settings_dep),
):
    return services.create_campaign(
        db,
        client,
        settings,
        name=body.name,
        geo=body.geo,
        offer_id=body.offer_id,
        domain_id=body.domain_id,
        group_id=body.group_id,
        traffic_source_id=body.traffic_source_id,
    )


@router.get("/history")
def history(db: Session = Depends(get_db)):
    return services.list_history(db)


@router.get("/campaigns")
def campaigns(
    q: str = "",
    mine: bool = False,
    db: Session = Depends(get_db),
    client: KeitaroClient = Depends(get_client),
    settings: Settings = Depends(get_settings_dep),
):
    return services.list_campaigns(db, client, settings, q=q, mine=mine)


@router.get("/campaigns/{campaign_id}")
def campaign_detail(
    campaign_id: int,
    client: KeitaroClient = Depends(get_client),
    settings: Settings = Depends(get_settings_dep),
):
    return services.get_campaign_detail(client, settings, campaign_id)


@router.get("/campaigns/{campaign_id}/changes")
def campaign_changes(campaign_id: int, db: Session = Depends(get_db)):
    return services.list_changes(db, campaign_id)


@router.post("/campaigns/{campaign_id}/streams/{stream_id}/offers")
def add_offer(
    campaign_id: int,
    stream_id: int,
    body: OfferIn,
    db: Session = Depends(get_db),
    client: KeitaroClient = Depends(get_client),
    settings: Settings = Depends(get_settings_dep),
):
    return services.add_offer(db, client, settings, campaign_id, stream_id, body.offer_id)


@router.post("/campaigns/{campaign_id}/streams/{stream_id}/equalize")
def equalize(
    campaign_id: int,
    stream_id: int,
    db: Session = Depends(get_db),
    client: KeitaroClient = Depends(get_client),
    settings: Settings = Depends(get_settings_dep),
):
    return services.equalize_shares(db, client, settings, campaign_id, stream_id)


@router.delete("/campaigns/{campaign_id}/streams/{stream_id}/offers/{offer_id}")
def remove_offer(
    campaign_id: int,
    stream_id: int,
    offer_id: int,
    db: Session = Depends(get_db),
    client: KeitaroClient = Depends(get_client),
    settings: Settings = Depends(get_settings_dep),
):
    return services.remove_offer(db, client, settings, campaign_id, stream_id, offer_id)
