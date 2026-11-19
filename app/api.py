from typing import Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.keitaro import KeitaroClient
from app.models import CreatedCampaign, OfferChange
from app.schemas import AddOffers, CampaignCreate, CreatedCampaignOut, OfferChangeOut, SetShares
from app.services import creator, editor

router = APIRouter(prefix="/api")


def get_client(settings: Settings = Depends(get_settings)) -> Iterator[KeitaroClient]:
    if not settings.keitaro_api_key:
        raise HTTPException(500, "KEITARO_API_KEY не задан в .env")
    client = KeitaroClient(settings.keitaro_url, settings.keitaro_api_key, settings.keitaro_timeout)
    try:
        yield client
    finally:
        client.close()


@router.get("/meta")
def meta(client: KeitaroClient = Depends(get_client), settings: Settings = Depends(get_settings)):
    """Dictionaries for the creator form: domains, groups, traffic sources, offers."""
    sources = client.list_traffic_sources()
    # a source can be accessible by id while missing from the list (per-entity ACL)
    if settings.default_traffic_source_id and all(s["id"] != settings.default_traffic_source_id for s in sources):
        try:
            sources.append(client.get_traffic_source(settings.default_traffic_source_id))
        except Exception:
            pass
    return {
        "domains": [{"id": d["id"], "name": d["name"]} for d in client.list_domains()],
        "groups": [{"id": g["id"], "name": g["name"]} for g in client.list_groups("campaigns")],
        "traffic_sources": [{"id": s["id"], "name": s["name"], "state": s.get("state")} for s in sources],
        "offers": [{"id": o["id"], "name": o["name"], "country": o.get("country", [])} for o in client.list_offers()],
        "defaults": {
            "domain_id": settings.default_domain_id,
            "group_id": settings.default_group_id,
            "traffic_source_id": settings.default_traffic_source_id,
        },
        "geo_redirect_url": settings.geo_redirect_url,
        "intervals": editor.INTERVALS,
    }


# --- creator -----------------------------------------------------------------
@router.post("/campaigns", response_model=CreatedCampaignOut, status_code=201)
def create_campaign(data: CampaignCreate, client: KeitaroClient = Depends(get_client),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return creator.create_campaign(client, db, settings, data)


@router.get("/campaigns/created", response_model=List[CreatedCampaignOut])
def created_campaigns(db: Session = Depends(get_db)):
    return db.scalars(select(CreatedCampaign).order_by(CreatedCampaign.id.desc())).all()


# --- editor ------------------------------------------------------------------
@router.get("/campaigns")
def list_campaigns(client: KeitaroClient = Depends(get_client)):
    campaigns = client.list_campaigns()
    return sorted(
        [{"id": c["id"], "name": c["name"], "group": c.get("group"), "state": c.get("state")} for c in campaigns],
        key=lambda c: c["id"], reverse=True,
    )


@router.get("/campaigns/{campaign_id}/editor")
def editor_state(campaign_id: int, stream_id: Optional[int] = None, interval: str = "7_days_ago",
                 client: KeitaroClient = Depends(get_client)):
    return editor.editor_state(client, campaign_id, stream_id, interval)


@router.post("/campaigns/{campaign_id}/streams/{stream_id}/offers", response_model=OfferChangeOut)
def add_offers(campaign_id: int, stream_id: int, data: AddOffers,
               client: KeitaroClient = Depends(get_client), db: Session = Depends(get_db)):
    return editor.add_offers(client, db, campaign_id, stream_id, data.offer_ids)


@router.delete("/campaigns/{campaign_id}/streams/{stream_id}/offers/{offer_id}", response_model=OfferChangeOut)
def remove_offer(campaign_id: int, stream_id: int, offer_id: int,
                 client: KeitaroClient = Depends(get_client), db: Session = Depends(get_db)):
    return editor.remove_offer(client, db, campaign_id, stream_id, offer_id)


@router.put("/campaigns/{campaign_id}/streams/{stream_id}/shares", response_model=OfferChangeOut)
def set_shares(campaign_id: int, stream_id: int, data: SetShares,
               client: KeitaroClient = Depends(get_client), db: Session = Depends(get_db)):
    return editor.set_shares(client, db, campaign_id, stream_id, data.shares)


@router.get("/campaigns/{campaign_id}/history", response_model=List[OfferChangeOut])
def history(campaign_id: int, db: Session = Depends(get_db)):
    return db.scalars(
        select(OfferChange).where(OfferChange.campaign_id == campaign_id).order_by(OfferChange.id.desc()).limit(50)
    ).all()
