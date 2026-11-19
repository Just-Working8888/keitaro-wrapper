import logging
import secrets

from sqlalchemy.orm import Session

from app.config import Settings
from app.keitaro import KeitaroClient, KeitaroError
from app.models import CreatedCampaign
from app.schemas import CampaignCreate

log = logging.getLogger(__name__)


class CreatorError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _pick(value, default, what: str) -> int:
    chosen = value if value is not None else default
    if chosen is None:
        raise CreatorError(f"Не выбран {what} и не задан дефолт в .env")
    return chosen


def create_campaign(client: KeitaroClient, db: Session, settings: Settings,
                    data: CampaignCreate) -> CreatedCampaign:
    domain_id = _pick(data.domain_id, settings.default_domain_id, "домен")
    group_id = _pick(data.group_id, settings.default_group_id, "группа")
    source_id = _pick(data.traffic_source_id, settings.default_traffic_source_id, "источник")

    offer_ids = {o["id"] for o in client.list_offers()}
    if data.offer_id not in offer_ids:
        raise CreatorError(f"Оффер {data.offer_id} не найден в Keitaro (или нет доступа)")

    campaign = client.create_campaign({
        "name": data.name,
        "alias": secrets.token_hex(6),  # Keitaro requires a unique alias
        "type": "position",  # streams are evaluated top-down by position
        "state": "active",
        "group_id": group_id,
        "domain_id": domain_id,
        "traffic_source_id": source_id,
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "uniqueness_method": "ip",
        "cookies_ttl": 24,
    })
    cid = campaign["id"]

    try:
        geo_stream = client.create_stream({
            "campaign_id": cid,
            "type": "regular",
            "name": f"Geo {data.country} → Google",
            "position": 1,
            "state": "active",
            "schema": "redirect",
            "action_type": "http",
            "action_payload": settings.geo_redirect_url,
            "collect_clicks": True,
            "filter_or": False,
            "filters": [{"name": "country", "mode": "accept", "payload": [data.country]}],
        })
        offer_stream = client.create_stream({
            "campaign_id": cid,
            "type": "regular",
            "name": "Offers",
            "position": 2,
            "state": "active",
            "schema": "landings",
            "action_type": "http",
            "collect_clicks": True,
            "offer_selection": "before_click",
            "offers": [{"offer_id": data.offer_id, "share": 100, "state": "active"}],
        })
    except KeitaroError:
        # don't leave a half-configured campaign behind
        try:
            client.delete_campaign(cid)
        except KeitaroError:
            log.exception("Could not roll back campaign %s", cid)
        raise

    record = CreatedCampaign(
        keitaro_id=cid,
        name=campaign["name"],
        alias=campaign["alias"],
        url=campaign.get("domain", "").rstrip("/") + "/" + campaign["alias"],
        country=data.country,
        offer_id=data.offer_id,
        domain_id=domain_id,
        group_id=group_id,
        traffic_source_id=source_id,
        geo_stream_id=geo_stream["id"],
        offer_stream_id=offer_stream["id"],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
