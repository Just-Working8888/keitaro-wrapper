import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.api import get_client
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.keitaro import KeitaroClient
from app.main import app


class FakeKeitaro:
    """Minimal in-memory imitation of the Keitaro Admin API endpoints we use."""

    def __init__(self):
        self.offers = {1: "Offer A", 2: "Offer B", 3: "Offer C", 4: "Offer D"}
        self.campaigns = {}
        self.streams = {}
        self.report_rows = []
        self.fail_stream_create = False
        self.deleted = []
        self._ids = 100

    def _id(self):
        self._ids += 1
        return self._ids

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.replace("/admin_api/v1", "")
        body = json.loads(req.content) if req.content else None
        m = req.method

        if path == "/offers":
            return httpx.Response(200, json=[{"id": k, "name": v, "country": ["DE"]} for k, v in self.offers.items()])
        if path == "/domains":
            return httpx.Response(200, json=[{"id": 1813, "name": "example.com"}])
        if path == "/groups":
            return httpx.Response(200, json=[{"id": 9799, "name": "test group"}])
        if path == "/traffic_sources":
            return httpx.Response(200, json=[])
        if re.fullmatch(r"/traffic_sources/\d+", path):
            return httpx.Response(200, json={"id": int(path.split("/")[-1]), "name": "src", "state": "active"})
        if path == "/campaigns" and m == "GET":
            return httpx.Response(200, json=list(self.campaigns.values()))
        if path == "/campaigns" and m == "POST":
            if not body.get("alias"):
                return httpx.Response(400, json={"alias": ["Alias is required"]})
            c = dict(body, id=self._id(), domain="https://example.com/", group="test group")
            self.campaigns[c["id"]] = c
            return httpx.Response(200, json=c)
        mc = re.fullmatch(r"/campaigns/(\d+)(/streams)?", path)
        if mc:
            cid = int(mc.group(1))
            if cid not in self.campaigns:
                return httpx.Response(404, json={"error": "Not found"})
            if mc.group(2):
                return httpx.Response(200, json=[s for s in self.streams.values() if s["campaign_id"] == cid])
            if m == "DELETE":
                self.deleted.append(cid)
                return httpx.Response(200, json={})
            return httpx.Response(200, json=self.campaigns[cid])
        if path == "/streams" and m == "POST":
            if self.fail_stream_create and body.get("position") == 2:
                return httpx.Response(500, json={"error": "boom"})
            s = dict(body, id=self._id(), offers=[dict(o, id=self._id()) for o in body.get("offers", [])])
            self.streams[s["id"]] = s
            return httpx.Response(200, json=s)
        ms = re.fullmatch(r"/streams/(\d+)", path)
        if ms:
            s = self.streams[int(ms.group(1))]
            if m == "PUT":
                if "offers" in body:
                    s["offers"] = [dict(o) for o in body["offers"]]
            return httpx.Response(200, json=s)
        if path == "/report/build":
            return httpx.Response(200, json={"rows": self.report_rows, "total": len(self.report_rows)})
        return httpx.Response(404, json={"error": f"unhandled {m} {path}"})


@pytest.fixture
def fake():
    return FakeKeitaro()


@pytest.fixture
def client(fake):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(_env_file=None, keitaro_api_key="test", default_domain_id=1813,
                        default_group_id=9799, default_traffic_source_id=836)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_client] = lambda: KeitaroClient(
        "https://keitaro.test", "test", transport=httpx.MockTransport(fake.handler))
    yield TestClient(app)
    app.dependency_overrides.clear()
