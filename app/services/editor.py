"""Offer editor.

Workflow (mirrors the reference editor):
  1. "Fetch streams" pulls the campaign's streams from Keitaro into the local DB.
  2. Every edit (add / remove / bring back / pin / manual share) changes only the local draft;
     the stream turns "yellow" (has unpublished changes) and Keitaro stays untouched.
  3. "Push stream" publishes the draft to Keitaro; "Cancel" throws the draft away.
Removed offers are kept locally in the "removed" state (grey, 0%) so they can be brought back.
"""
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.keitaro import KeitaroClient
from app.models import Campaign, OfferChange, Stream, StreamOffer
from app.shares import rebalance, validate_shares

ACTIVE, REMOVED = "active", "removed"

INTERVALS = {
    "today": "Сегодня",
    "yesterday": "Вчера",
    "7_days_ago": "7 дней",
    "1_month_ago": "30 дней",
    "all_time": "Всё время",
}
ADDITIVE = ["clicks", "conversions", "revenue", "cost", "profit"]


class EditorError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _is_offer_stream(s: Dict) -> bool:
    return s.get("schema") == "landings" or bool(s.get("offers"))


def _campaign_url(c: Dict) -> str:
    return (c.get("domain") or "").rstrip("/") + "/" + c.get("alias", "")


# --- fetch ---------------------------------------------------------------------
def fetch_streams(client: KeitaroClient, db: Session, campaign_id: int) -> Campaign:
    """Sync the campaign's streams from Keitaro. Keitaro wins: unpublished drafts are dropped.

    Offers we knew about that are gone from Keitaro become "removed" (with Bring back),
    exactly as if they had been removed through the editor.
    """
    kc = client.get_campaign(campaign_id)
    k_streams = client.list_streams(campaign_id)
    names = {o["id"]: o["name"] for o in client.list_offers()}

    camp = db.scalar(select(Campaign).where(Campaign.keitaro_id == campaign_id))
    if camp is None:
        camp = Campaign(keitaro_id=campaign_id)
        db.add(camp)
    camp.name, camp.url, camp.fetched_at = kc["name"], _campaign_url(kc), datetime.utcnow()

    local = {s.keitaro_id: s for s in camp.streams}
    seen = set()
    for ks in k_streams:
        seen.add(ks["id"])
        stream = local.get(ks["id"])
        if stream is None:
            stream = Stream(keitaro_id=ks["id"])
            camp.streams.append(stream)
        stream.name = ks.get("name") or f"Поток #{ks['id']}"
        stream.position = ks.get("position") or 0
        stream.is_offer_stream = _is_offer_stream(ks)
        if stream.is_offer_stream:
            _sync_offers(stream, ks.get("offers") or [], names)
        else:
            stream.offers.clear()

    for kid, stream in local.items():
        if kid not in seen:  # stream deleted in Keitaro
            camp.streams.remove(stream)

    db.commit()
    db.refresh(camp)
    return camp


def _sync_offers(stream: Stream, k_offers: List[Dict], names: Dict[int, str]) -> None:
    remote = {o["offer_id"]: o["share"] for o in k_offers}
    rows = {o.offer_id: o for o in stream.offers}
    for row in list(stream.offers):
        if row.offer_id in remote:
            continue
        if row.published_state is None:  # local draft that never reached Keitaro
            stream.offers.remove(row)
        else:
            row.state = row.published_state = REMOVED
            row.share = row.published_share = 0
            row.pinned = False
    for oid, share in remote.items():
        row = rows.get(oid)
        if row is None:
            row = StreamOffer(offer_id=oid, pinned=False)
            stream.offers.append(row)
        row.offer_name = names.get(oid) or row.offer_name or f"Оффер #{oid}"
        row.state = row.published_state = ACTIVE
        row.share = row.published_share = share


# --- read ------------------------------------------------------------------------
def _offer_out(o: StreamOffer) -> Dict:
    return {
        "offer_id": o.offer_id, "name": o.offer_name, "state": o.state, "share": o.share,
        "pinned": o.pinned, "published_state": o.published_state, "published_share": o.published_share,
        "is_new": o.published_state is None, "dirty": o.is_dirty,
    }


def stream_out(s: Stream) -> Dict:
    active = [o for o in s.offers if o.state == ACTIVE]
    return {
        "id": s.keitaro_id, "name": s.name, "position": s.position, "is_offer_stream": s.is_offer_stream,
        "dirty": any(o.is_dirty for o in s.offers),
        "share_total": sum(o.share for o in active),
        "active_count": len(active),
        "offers": [_offer_out(o) for o in s.offers],
    }


def campaign_state(db: Session, campaign: Campaign) -> Dict:
    return {
        "campaign": {"id": campaign.keitaro_id, "name": campaign.name, "url": campaign.url,
                     "fetched_at": campaign.fetched_at},
        "streams": [stream_out(s) for s in campaign.streams],
    }


def get_campaign(db: Session, campaign_id: int) -> Optional[Campaign]:
    return db.scalar(select(Campaign).where(Campaign.keitaro_id == campaign_id))


def fetched_campaigns(db: Session) -> List[Dict]:
    rows = db.scalars(select(Campaign).order_by(Campaign.fetched_at.desc())).all()
    return [{"id": c.keitaro_id, "name": c.name,
             "dirty": any(o.is_dirty for s in c.streams for o in s.offers)} for c in rows]


def search_offers(client: KeitaroClient, q: str, limit: int = 20) -> List[Dict]:
    q = q.strip().lower()
    found = []
    for o in client.list_offers():
        if not q or str(o["id"]).startswith(q) or q in o["name"].lower():
            found.append({"id": o["id"], "name": o["name"], "country": o.get("country", [])})
    return found[:limit]


# --- draft edits -------------------------------------------------------------
def _stream(db: Session, stream_id: int) -> Stream:
    stream = db.scalar(select(Stream).where(Stream.keitaro_id == stream_id))
    if stream is None:
        raise EditorError(f"Поток {stream_id} не загружен — нажмите Fetch streams", 404)
    if not stream.is_offer_stream:
        raise EditorError("Это поток без офферов — его офферы не редактируются")
    return stream


def _row(stream: Stream, offer_id: int) -> StreamOffer:
    row = next((o for o in stream.offers if o.offer_id == offer_id), None)
    if row is None:
        raise EditorError(f"Оффера {offer_id} нет в потоке", 404)
    return row


def _rebalance(stream: Stream) -> None:
    active = [o for o in stream.offers if o.state == ACTIVE]
    shares = rebalance([o.offer_id for o in active], {o.offer_id: o.share for o in active if o.pinned})
    for o in stream.offers:
        o.share = shares.get(o.offer_id, 0)


def _save(db: Session, stream: Stream) -> Stream:
    try:
        _rebalance(stream)
    except ValueError:
        db.rollback()
        raise
    db.commit()
    db.refresh(stream)
    return stream


def add_offer(client: KeitaroClient, db: Session, stream_id: int, offer_id: int) -> Stream:
    stream = _stream(db, stream_id)
    existing = next((o for o in stream.offers if o.offer_id == offer_id), None)
    if existing is not None:
        if existing.state == ACTIVE:
            raise EditorError(f"Оффер {offer_id} уже в потоке")
        existing.state = ACTIVE  # was removed -> same as Bring back
        return _save(db, stream)
    offer = next((o for o in client.list_offers() if o["id"] == offer_id), None)
    if offer is None:
        raise EditorError(f"Оффер {offer_id} не найден в Keitaro", 404)
    stream.offers.append(StreamOffer(offer_id=offer_id, offer_name=offer["name"], state=ACTIVE,
                                     share=0, pinned=False))
    return _save(db, stream)


def remove_offer(db: Session, stream_id: int, offer_id: int) -> Stream:
    stream = _stream(db, stream_id)
    row = _row(stream, offer_id)
    if row.state != ACTIVE:
        raise EditorError(f"Оффер {offer_id} уже удалён")
    if row.published_state is None:
        stream.offers.remove(row)  # never published: nothing to archive
    else:
        row.state, row.share, row.pinned = REMOVED, 0, False
    return _save(db, stream)


def restore_offer(db: Session, stream_id: int, offer_id: int) -> Stream:
    stream = _stream(db, stream_id)
    row = _row(stream, offer_id)
    if row.state != REMOVED:
        raise EditorError(f"Оффер {offer_id} и так активен")
    row.state = ACTIVE
    return _save(db, stream)


def update_offer(db: Session, stream_id: int, offer_id: int, share: Optional[int] = None,
                 pinned: Optional[bool] = None) -> Stream:
    """Typing a share pins it; toggling the pin keeps the current share."""
    stream = _stream(db, stream_id)
    row = _row(stream, offer_id)
    if row.state != ACTIVE:
        raise EditorError("Удалённому офферу нельзя менять долю — сначала Bring back")
    if share is not None:
        if not 0 <= share <= 100:
            raise EditorError("Доля должна быть от 0 до 100")
        row.share, row.pinned = share, True
    elif pinned is not None:
        row.pinned = pinned
    return _save(db, stream)


def cancel(db: Session, stream_id: int) -> Stream:
    stream = _stream(db, stream_id)
    for row in list(stream.offers):
        if row.published_state is None:
            stream.offers.remove(row)
        else:
            row.state, row.share = row.published_state, row.published_share
    db.commit()
    db.refresh(stream)
    return stream


def push(client: KeitaroClient, db: Session, stream_id: int) -> Stream:
    stream = _stream(db, stream_id)
    active = {o.offer_id: o.share for o in stream.offers if o.state == ACTIVE}
    try:
        validate_shares(active)
    except ValueError as exc:
        raise EditorError(f"Нельзя опубликовать: {exc}")

    before = {o.offer_id: o.published_share for o in stream.offers if o.published_state == ACTIVE}
    remote = {o["offer_id"]: o["share"] for o in client.get_stream(stream_id).get("offers") or []}
    if remote != before:
        raise EditorError("Поток изменили в Keitaro после последнего Fetch. "
                          "Нажмите Fetch streams и повторите правки.", 409)

    client.update_stream(stream_id, {"offers": [
        {"offer_id": oid, "share": share, "state": ACTIVE} for oid, share in active.items()
    ]})
    changed = [o.offer_id for o in stream.offers if o.is_dirty]
    for o in stream.offers:
        o.published_state, o.published_share = o.state, o.share
    db.add(OfferChange(
        campaign_id=stream.campaign.keitaro_id, stream_id=stream_id, action="push", offer_ids=changed,
        before={str(k): v for k, v in before.items()}, after={str(k): v for k, v in active.items()},
    ))
    db.commit()
    db.refresh(stream)
    return stream


# --- stats (read straight from Keitaro reports) ---------------------------------------
def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _ratios(m: Dict[str, float]) -> Dict[str, float]:
    m["cr"] = round(m["conversions"] / m["clicks"] * 100, 2) if m["clicks"] else 0.0
    m["roi"] = round(m["profit"] / m["cost"] * 100, 2) if m["cost"] else 0.0
    return m


def campaign_stats(client: KeitaroClient, campaign_id: int, interval: str) -> Dict:
    """{stream_id: {offer_id: metrics}} for the campaign, plus per-stream totals."""
    if interval not in INTERVALS:
        raise EditorError(f"Неизвестный период: {interval}")
    report = client.build_report({
        "range": {"interval": interval},
        "dimensions": ["stream_id", "offer_id"],
        "measures": ADDITIVE,
        "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": campaign_id}],
        "limit": 5000,
    })
    by_stream: Dict[str, Dict] = {}
    for row in report.get("rows", []):
        sid, oid = int(row.get("stream_id") or 0), int(row.get("offer_id") or 0)
        if not sid or not oid:
            continue
        by_stream.setdefault(str(sid), {})[str(oid)] = _ratios({k: _num(row.get(k)) for k in ADDITIVE})
    totals = {
        sid: _ratios({k: sum(m[k] for m in offers.values()) for k in ADDITIVE})
        for sid, offers in by_stream.items()
    }
    return {"interval": interval, "streams": by_stream, "totals": totals}
