"""API tests against an in-memory fake of the Keitaro Admin API."""

import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.keitaro import KeitaroError, get_keitaro
from app.main import app


class FakeKeitaro:
    def __init__(self):
        self.ids = itertools.count(1000)
        self.offers = [
            {"id": 1, "name": "Offer One", "state": "active"},
            {"id": 2, "name": "Offer Two", "state": "active"},
            {"id": 3, "name": "Offer Three", "state": "active"},
        ]
        self.campaigns: dict[int, dict] = {}
        self.streams: dict[int, dict] = {}
        self.fail_stream = False
        self.report_rows: list[dict] = []

    def list_offers(self, fresh=False):
        return self.offers

    def list_campaigns(self):
        return list(self.campaigns.values())

    def create_campaign(self, p):
        cid = next(self.ids)
        self.campaigns[cid] = {**p, "id": cid, "domain": "https://kylovoa.com/", "group": "FORTESTS"}
        return self.campaigns[cid]

    def get_campaign(self, cid):
        if cid not in self.campaigns:
            raise KeitaroError(404, "not found")
        return self.campaigns[cid]

    def delete_campaign(self, cid):
        self.campaigns.pop(cid, None)

    def create_stream(self, p):
        if self.fail_stream and p["position"] == 2:
            raise KeitaroError(400, "boom")
        sid = next(self.ids)
        self.streams[sid] = {"filters": [], "offers": [], **p, "id": sid}
        return self.streams[sid]

    def list_streams(self, cid):
        return [s for s in self.streams.values() if s["campaign_id"] == cid]

    def get_stream(self, sid):
        return self.streams[sid]

    def update_stream(self, sid, p):
        self.streams[sid].update(p)
        return self.streams[sid]

    def build_report(self, p):
        dims = p["dimensions"]
        out: dict = {}
        for r in self.report_rows:
            key = tuple(r[d] for d in dims)
            acc = out.setdefault(key, {**{d: r[d] for d in dims}, "clicks": 0, "stream_unique_clicks": 0, "bots": 0, "conversions": 0, "revenue": 0})
            for m in ("clicks", "stream_unique_clicks", "bots", "conversions", "revenue"):
                acc[m] += r.get(m, 0)
        return {"rows": list(out.values())}


@pytest.fixture
def fake():
    return FakeKeitaro()


@pytest.fixture
def client(fake):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_settings] = lambda: Settings(campaign_prefix="test_x_", _env_file=None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create(client, **kw):
    body = {"name": "c1", "geo": "au, MX", "offer_id": 1, **kw}
    return client.post("/api/campaigns", json=body)


def test_create_campaign(client, fake):
    r = _create(client)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["name"] == "test_x_c1"
    assert c["geo"] == ["AU", "MX"]
    assert c["url"].startswith("https://kylovoa.com/")

    kc = fake.campaigns[c["keitaro_id"]]
    assert (kc["domain_id"], kc["group_id"], kc["traffic_source_id"]) == (1813, 10332, 836)

    g, o = fake.streams[c["google_stream_id"]], fake.streams[c["offers_stream_id"]]
    assert g["position"] == 1 and g["action_payload"] == "https://google.com"
    assert g["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU", "MX"]}]
    assert o["position"] == 2 and o["schema"] == "landings"
    assert o["offers"] == [{"offer_id": 1, "share": 100, "state": "active"}]


def test_create_validation(client):
    assert _create(client, geo="ZZ").status_code == 422
    assert _create(client, geo="").status_code == 422
    assert _create(client, offer_id=999).status_code == 404


def test_create_rolls_back_on_stream_error(client, fake):
    fake.fail_stream = True
    assert _create(client).status_code == 400
    assert fake.campaigns == {}


def test_editor_add_remove_reweight(client, fake):
    c = _create(client).json()
    cid, sid = c["keitaro_id"], c["offers_stream_id"]
    base = f"/api/campaigns/{cid}/streams/{sid}"

    assert client.post(f"{base}/offers", json={"offer_id": 2}).status_code == 200
    assert [(o["offer_id"], o["share"]) for o in fake.streams[sid]["offers"]] == [(1, 50), (2, 50)]

    client.post(f"{base}/offers", json={"offer_id": 3})
    assert [o["share"] for o in fake.streams[sid]["offers"]] == [34, 33, 33]

    assert client.post(f"{base}/offers", json={"offer_id": 3}).status_code == 409

    assert client.put(f"{base}/shares", json={"shares": {"1": 60, "2": 30, "3": 10}}).status_code == 200
    assert [o["share"] for o in fake.streams[sid]["offers"]] == [60, 30, 10]
    assert client.put(f"{base}/shares", json={"shares": {"1": 60, "2": 30, "3": 5}}).status_code == 400

    assert client.delete(f"{base}/offers/2").status_code == 200
    assert [(o["offer_id"], o["share"]) for o in fake.streams[sid]["offers"]] == [(1, 50), (3, 50)]
    client.delete(f"{base}/offers/3")
    assert client.delete(f"{base}/offers/1").status_code == 400  # last offer stays

    events = client.get(f"/api/campaigns/{cid}/events").json()
    assert [e["action"] for e in events] == ["remove", "remove", "reweight", "add", "add"]

    # google stream is not editable
    assert client.post(f"/api/campaigns/{cid}/streams/{c['google_stream_id']}/offers", json={"offer_id": 2}).status_code == 400


def test_campaign_view_stats(client, fake):
    c = _create(client).json()
    cid, sid, gid = c["keitaro_id"], c["offers_stream_id"], c["google_stream_id"]
    client.post(f"/api/campaigns/{cid}/streams/{sid}/offers", json={"offer_id": 2})
    fake.report_rows = [
        {"stream_id": gid, "offer_id": 0, "clicks": 5, "stream_unique_clicks": 4, "bots": 1},
        {"stream_id": sid, "offer_id": 1, "clicks": 7, "stream_unique_clicks": 6, "conversions": 1},
        {"stream_id": sid, "offer_id": 2, "clicks": 3, "stream_unique_clicks": 3},
    ]
    d = client.get(f"/api/campaigns/{cid}?interval=today").json()
    g, o = d["streams"]
    assert g["stats"]["clicks"] == 5 and not g["editable"]
    assert o["stats"] == {"clicks": 10, "unique": 9, "bots": 0, "conversions": 1, "revenue": 0.0}
    assert [(x["offer_id"], x["share"], x["stats"]["clicks"]) for x in o["offers"]] == [(1, 50, 7), (2, 50, 3)]
    assert d["total"]["clicks"] == 15
    assert client.get(f"/api/campaigns/{cid}?interval=bogus").status_code == 422


def test_offer_search(client):
    assert [o["id"] for o in client.get("/api/offers?q=two").json()] == [2]
    assert [o["id"] for o in client.get("/api/offers?q=3").json()] == [3]
