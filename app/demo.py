"""Demo mode: the full app on an in-memory fake Keitaro with several offers.

The test Keitaro account sees a single offer, so multi-offer scenarios from the reference
video (4 offers x 25%, pinned weights, rebalancing) can't be shown on the live tracker.
Nothing here touches the real Keitaro or the real database.

    python -m app.demo          # http://localhost:8001
"""
import httpx
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import get_client
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.fake_keitaro import FakeKeitaro
from app.keitaro import KeitaroClient
from app.main import app

PORT = 8001


def build() -> FakeKeitaro:
    fake = FakeKeitaro()
    fake.offers = {
        18813: "18813 Flexacil [JOINT-PE] vsl es",
        18820: "18820 Cardiol [PE] prelanding",
        18901: "18901 Hondrexil [MX] v2",
        19005: "19005 Glyconorm [CL] react",
        19112: "19112 Prostamin [CO] quiz",
    }
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(_env_file=None, keitaro_api_key="demo", default_domain_id=1813,
                        default_group_id=9799, default_traffic_source_id=836, demo_mode=True)

    def _db():
        db = session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_client] = lambda: KeitaroClient(
        "https://keitaro.demo", "demo", transport=httpx.MockTransport(fake.handler))

    # a campaign like the one in the video: geo stream + 3 offers at ~33%
    c = TestClient(app)
    d = c.post("/api/campaigns", json={"name": "demo_AU", "country": "AU", "offer_id": 18813}).json()
    cid, sid = d["keitaro_id"], d["offer_stream_id"]
    fake.streams[sid]["offers"] = [{"offer_id": o, "share": s, "state": "active"}
                                   for o, s in [(18813, 34), (18820, 33), (18901, 33)]]
    fake.report_rows = [
        {"stream_id": sid, "offer_id": 18813, "clicks": 412, "conversions": 9, "revenue": 270, "cost": 120, "profit": 150},
        {"stream_id": sid, "offer_id": 18820, "clicks": 398, "conversions": 4, "revenue": 96, "cost": 115, "profit": -19},
        {"stream_id": sid, "offer_id": 18901, "clicks": 405, "conversions": 6, "revenue": 180, "cost": 118, "profit": 62},
    ]
    c.post(f"/api/campaigns/{cid}/fetch")
    print(f"Demo campaign #{cid}: http://localhost:{PORT}/#edit/{cid}", flush=True)
    return fake


if __name__ == "__main__":
    build()
    uvicorn.run(app, port=PORT, log_level="warning")
