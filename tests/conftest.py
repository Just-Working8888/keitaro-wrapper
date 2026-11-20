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
from app.fake_keitaro import FakeKeitaro
from app.main import app


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
