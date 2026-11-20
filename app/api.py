from typing import Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.keitaro import KeitaroClient
from app.models import CreatedCampaign, OfferChange
from app.schemas import AddOffer, CampaignCreate, CreatedCampaignOut, OfferChangeOut, UpdateOffer
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
        "demo": settings.demo_mode,
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
    """All campaigns visible in Keitaro (for the picker)."""
    campaigns = client.list_campaigns()
    return sorted(
        [{"id": c["id"], "name": c["name"], "group": c.get("group"), "state": c.get("state")} for c in campaigns],
        key=lambda c: c["id"], reverse=True,
    )


@router.get("/campaigns/fetched")
def fetched_campaigns(db: Session = Depends(get_db)):
    """Campaigns already loaded into the editor."""
    return editor.fetched_campaigns(db)


@router.post("/campaigns/{campaign_id}/fetch")
def fetch_streams(campaign_id: int, client: KeitaroClient = Depends(get_client), db: Session = Depends(get_db)):
    """"Fetch streams": pull streams from Keitaro into the local DB (drops unpublished drafts)."""
    camp = editor.fetch_streams(client, db, campaign_id)
    return editor.campaign_state(db, camp)


@router.get("/campaigns/{campaign_id}/streams")
def campaign_streams(campaign_id: int, db: Session = Depends(get_db)):
    camp = editor.get_campaign(db, campaign_id)
    if camp is None:
        raise HTTPException(404, "Кампания ещё не загружена — нажмите Fetch streams")
    return editor.campaign_state(db, camp)


@router.get("/campaigns/{campaign_id}/stats")
def campaign_stats(campaign_id: int, interval: str = "7_days_ago", client: KeitaroClient = Depends(get_client)):
    return editor.campaign_stats(client, campaign_id, interval)


@router.get("/campaigns/{campaign_id}/history", response_model=List[OfferChangeOut])
def history(campaign_id: int, db: Session = Depends(get_db)):
    return db.scalars(
        select(OfferChange).where(OfferChange.campaign_id == campaign_id).order_by(OfferChange.id.desc()).limit(50)
    ).all()


@router.get("/offers/search")
def search_offers(q: str = "", client: KeitaroClient = Depends(get_client)):
    return editor.search_offers(client, q)


@router.post("/streams/{stream_id}/offers")
def add_offer(stream_id: int, data: AddOffer, client: KeitaroClient = Depends(get_client),
              db: Session = Depends(get_db)):
    return editor.stream_out(editor.add_offer(client, db, stream_id, data.offer_id))


@router.delete("/streams/{stream_id}/offers/{offer_id}")
def remove_offer(stream_id: int, offer_id: int, db: Session = Depends(get_db)):
    return editor.stream_out(editor.remove_offer(db, stream_id, offer_id))


@router.post("/streams/{stream_id}/offers/{offer_id}/restore")
def restore_offer(stream_id: int, offer_id: int, db: Session = Depends(get_db)):
    """"Bring back" a removed offer."""
    return editor.stream_out(editor.restore_offer(db, stream_id, offer_id))


@router.patch("/streams/{stream_id}/offers/{offer_id}")
def update_offer(stream_id: int, offer_id: int, data: UpdateOffer, db: Session = Depends(get_db)):
    """Set a share (pins it) or toggle the pin."""
    return editor.stream_out(editor.update_offer(db, stream_id, offer_id, data.share, data.pinned))


@router.post("/streams/{stream_id}/cancel")
def cancel(stream_id: int, db: Session = Depends(get_db)):
    return editor.stream_out(editor.cancel(db, stream_id))


@router.post("/streams/{stream_id}/push")
def push(stream_id: int, client: KeitaroClient = Depends(get_client), db: Session = Depends(get_db)):
    return editor.stream_out(editor.push(client, db, stream_id))
