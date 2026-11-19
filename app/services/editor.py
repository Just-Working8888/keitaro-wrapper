"""Offer editor: add/remove offers in a campaign's offer stream and show per-offer stats."""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.keitaro import KeitaroClient
from app.models import OfferChange
from app.shares import distribute_evenly, validate_shares

INTERVALS = {
    "today": "Сегодня",
    "yesterday": "Вчера",
    "7_days_ago": "7 дней",
    "1_month_ago": "30 дней",
    "all_time": "Всё время",
}

ADDITIVE = ["clicks", "campaign_unique_clicks", "conversions", "leads", "sales",
            "rejected", "revenue", "cost", "profit"]


class EditorError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def offer_streams(streams: List[Dict]) -> List[Dict]:
    """Streams that send traffic to offers (schema "landings" or already holding offers)."""
    return [s for s in streams if s.get("schema") == "landings" or s.get("offers")]


def _current_shares(stream: Dict) -> Dict[int, int]:
    return {o["offer_id"]: o["share"] for o in stream.get("offers", [])}


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _ratios(m: Dict[str, float]) -> Dict[str, float]:
    clicks, cost = m["clicks"], m["cost"]
    m["cr"] = round(m["conversions"] / clicks * 100, 2) if clicks else 0.0
    m["epc"] = round(m["revenue"] / clicks, 4) if clicks else 0.0
    m["roi"] = round(m["profit"] / cost * 100, 2) if cost else 0.0
    return m


def offer_stats(client: KeitaroClient, campaign_id: int, stream_id: int,
                interval: str) -> Dict[int, Dict[str, float]]:
    report = client.build_report({
        "range": {"interval": interval},
        "dimensions": ["offer_id"],
        "measures": ADDITIVE,
        "filters": [
            {"name": "campaign_id", "operator": "EQUALS", "expression": campaign_id},
            {"name": "stream_id", "operator": "EQUALS", "expression": stream_id},
        ],
        "limit": 1000,
    })
    out = {}
    for row in report.get("rows", []):
        oid = int(row.get("offer_id") or 0)
        if oid:
            out[oid] = _ratios({k: _num(row.get(k)) for k in ADDITIVE})
    return out


def editor_state(client: KeitaroClient, campaign_id: int, stream_id: Optional[int],
                 interval: str) -> Dict:
    if interval not in INTERVALS:
        raise EditorError(f"Неизвестный период: {interval}")
    campaign = client.get_campaign(campaign_id)
    streams = offer_streams(client.list_streams(campaign_id))
    if not streams:
        raise EditorError("В кампании нет потока с офферами", 404)
    stream = next((s for s in streams if s["id"] == stream_id), streams[0]) if stream_id else streams[0]
    if stream_id and stream["id"] != stream_id:
        raise EditorError(f"Поток {stream_id} не найден в кампании", 404)

    all_offers = {o["id"]: o for o in client.list_offers()}
    stats = offer_stats(client, campaign_id, stream["id"], interval)
    empty = _ratios({k: 0.0 for k in ADDITIVE})

    rows = []
    for o in stream.get("offers", []):
        meta = all_offers.get(o["offer_id"], {})
        rows.append({
            "offer_id": o["offer_id"],
            "name": meta.get("name", f"Оффер #{o['offer_id']}"),
            "country": meta.get("country", []),
            "share": o["share"],
            "state": o.get("state", "active"),
            "stats": stats.get(o["offer_id"], dict(empty)),
        })

    totals = {k: sum(r["stats"][k] for r in rows) for k in ADDITIVE}
    in_stream = {r["offer_id"] for r in rows}
    return {
        "campaign": {
            "id": campaign["id"], "name": campaign["name"], "alias": campaign["alias"],
            "url": campaign.get("domain", "").rstrip("/") + "/" + campaign["alias"],
            "group": campaign.get("group"), "state": campaign.get("state"),
        },
        "streams": [{"id": s["id"], "name": s["name"], "position": s.get("position"),
                     "offers_count": len(s.get("offers", []))} for s in streams],
        "stream_id": stream["id"],
        "interval": interval,
        "offers": rows,
        "share_total": sum(r["share"] for r in rows),
        "totals": _ratios(totals),
        "available_offers": [{"id": o["id"], "name": o["name"], "country": o.get("country", [])}
                             for oid, o in sorted(all_offers.items()) if oid not in in_stream],
    }


def _load_stream(client: KeitaroClient, campaign_id: int, stream_id: int) -> Dict:
    stream = client.get_stream(stream_id)
    if stream.get("campaign_id") != campaign_id:
        raise EditorError(f"Поток {stream_id} не принадлежит кампании {campaign_id}", 404)
    return stream


def _push(client: KeitaroClient, db: Session, stream: Dict, action: str, offer_ids: List[int],
          new_shares: Dict[int, int], note: Optional[str] = None) -> OfferChange:
    validate_shares(new_shares)
    states = {o["offer_id"]: o.get("state", "active") for o in stream.get("offers", [])}
    before = _current_shares(stream)
    client.update_stream(stream["id"], {"offers": [
        {"offer_id": oid, "share": share, "state": states.get(oid, "active")}
        for oid, share in new_shares.items()
    ]})
    change = OfferChange(
        campaign_id=stream["campaign_id"], stream_id=stream["id"], action=action,
        offer_ids=offer_ids,
        before={str(k): v for k, v in before.items()},
        after={str(k): v for k, v in new_shares.items()},
        note=note,
    )
    db.add(change)
    db.commit()
    return change


def add_offers(client: KeitaroClient, db: Session, campaign_id: int, stream_id: int,
               offer_ids: List[int]) -> OfferChange:
    stream = _load_stream(client, campaign_id, stream_id)
    current = list(_current_shares(stream))
    known = {o["id"] for o in client.list_offers()}
    unknown = [oid for oid in offer_ids if oid not in known]
    if unknown:
        raise EditorError(f"Офферы не найдены в Keitaro: {', '.join(map(str, unknown))}", 404)
    new = [oid for oid in dict.fromkeys(offer_ids) if oid not in current]
    if not new:
        raise EditorError("Эти офферы уже есть в потоке")
    return _push(client, db, stream, "add", new, distribute_evenly(current + new),
                 note="доли перераспределены поровну")


def remove_offer(client: KeitaroClient, db: Session, campaign_id: int, stream_id: int,
                 offer_id: int) -> OfferChange:
    stream = _load_stream(client, campaign_id, stream_id)
    current = list(_current_shares(stream))
    if offer_id not in current:
        raise EditorError(f"Оффера {offer_id} нет в потоке", 404)
    remaining = [oid for oid in current if oid != offer_id]
    if not remaining:
        raise EditorError("Нельзя удалить последний оффер: поток останется без цели. "
                          "Сначала добавьте другой оффер.")
    return _push(client, db, stream, "remove", [offer_id], distribute_evenly(remaining),
                 note="доли перераспределены поровну")


def set_shares(client: KeitaroClient, db: Session, campaign_id: int, stream_id: int,
               shares: Dict[int, int]) -> OfferChange:
    stream = _load_stream(client, campaign_id, stream_id)
    current = _current_shares(stream)
    if set(shares) != set(current):
        raise EditorError("Список офферов изменился — обновите страницу", 409)
    ordered = {oid: shares[oid] for oid in current}
    return _push(client, db, stream, "shares", list(ordered), ordered)
