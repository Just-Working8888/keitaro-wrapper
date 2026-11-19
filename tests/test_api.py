def create(client, **kw):
    payload = {"name": "test camp", "country": "de", "offer_id": 1}
    payload.update(kw)
    return client.post("/api/campaigns", json=payload)


def test_create_campaign_builds_two_streams(client, fake):
    r = create(client)
    assert r.status_code == 201, r.text
    data = r.json()
    camp = fake.campaigns[data["keitaro_id"]]
    assert camp["domain_id"] == 1813 and camp["group_id"] == 9799 and camp["traffic_source_id"] == 836
    assert camp["alias"] and data["url"] == "https://example.com/" + camp["alias"]

    geo, offer = fake.streams[data["geo_stream_id"]], fake.streams[data["offer_stream_id"]]
    assert geo["position"] == 1 and geo["schema"] == "redirect"
    assert geo["action_payload"] == "https://www.google.com"
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["DE"]}]
    assert offer["position"] == 2 and offer["schema"] == "landings"
    assert [(o["offer_id"], o["share"]) for o in offer["offers"]] == [(1, 100)]

    listed = client.get("/api/campaigns/created").json()
    assert [c["keitaro_id"] for c in listed] == [data["keitaro_id"]]


def test_create_validates_input(client):
    assert create(client, country="Germany").status_code == 422
    assert create(client, name="   ").status_code == 422
    r = create(client, offer_id=999)
    assert r.status_code == 400 and "999" in r.json()["detail"]


def test_create_rolls_back_on_stream_failure(client, fake):
    fake.fail_stream_create = True
    r = create(client)
    assert r.status_code == 502
    assert fake.deleted == list(fake.campaigns)  # half-built campaign removed
    assert client.get("/api/campaigns/created").json() == []


def _setup(client):
    data = create(client).json()
    return data["keitaro_id"], data["offer_stream_id"]


def test_editor_add_and_remove_rebalance(client, fake):
    cid, sid = _setup(client)
    base = f"/api/campaigns/{cid}/streams/{sid}"

    r = client.post(base + "/offers", json={"offer_ids": [2, 3]})
    assert r.status_code == 200, r.text
    assert r.json()["before"] == {"1": 100}
    assert r.json()["after"] == {"1": 34, "2": 33, "3": 33}
    assert {o["offer_id"]: o["share"] for o in fake.streams[sid]["offers"]} == {1: 34, 2: 33, 3: 33}

    # duplicates are ignored, all-duplicates is an error
    assert client.post(base + "/offers", json={"offer_ids": [2]}).status_code == 400

    r = client.delete(base + "/offers/1")
    assert r.status_code == 200
    assert {o["offer_id"]: o["share"] for o in fake.streams[sid]["offers"]} == {2: 50, 3: 50}

    client.delete(base + "/offers/2")
    r = client.delete(base + "/offers/3")
    assert r.status_code == 400  # last offer can't be removed
    assert {o["offer_id"]: o["share"] for o in fake.streams[sid]["offers"]} == {3: 100}

    hist = client.get(f"/api/campaigns/{cid}/history").json()
    assert [h["action"] for h in hist] == ["remove", "remove", "add"]


def test_editor_set_shares(client, fake):
    cid, sid = _setup(client)
    base = f"/api/campaigns/{cid}/streams/{sid}"
    client.post(base + "/offers", json={"offer_ids": [2]})

    assert client.put(base + "/shares", json={"shares": {"1": 70, "2": 40}}).status_code == 400
    assert client.put(base + "/shares", json={"shares": {"1": 100}}).status_code == 409
    r = client.put(base + "/shares", json={"shares": {"1": 70, "2": 30}})
    assert r.status_code == 200
    assert {o["offer_id"]: o["share"] for o in fake.streams[sid]["offers"]} == {1: 70, 2: 30}


def test_editor_rejects_unknown_offer_and_foreign_stream(client, fake):
    cid, sid = _setup(client)
    assert client.post(f"/api/campaigns/{cid}/streams/{sid}/offers", json={"offer_ids": [777]}).status_code == 404
    other_cid, other_sid = _setup(client)
    assert client.post(f"/api/campaigns/{cid}/streams/{other_sid}/offers", json={"offer_ids": [2]}).status_code == 404


def test_editor_state_stats_and_totals(client, fake):
    cid, sid = _setup(client)
    client.post(f"/api/campaigns/{cid}/streams/{sid}/offers", json={"offer_ids": [2]})
    fake.report_rows = [
        {"offer_id": 1, "clicks": 100, "campaign_unique_clicks": 90, "conversions": 5, "leads": 5, "sales": 0,
         "rejected": 0, "revenue": 50, "cost": 20, "profit": 30},
        {"offer_id": 2, "clicks": "300", "campaign_unique_clicks": 250, "conversions": 3, "leads": 3, "sales": 0,
         "rejected": 0, "revenue": "10", "cost": 40, "profit": -30},
    ]
    s = client.get(f"/api/campaigns/{cid}/editor?interval=all_time").json()
    assert s["stream_id"] == sid and s["share_total"] == 100
    by_id = {o["offer_id"]: o for o in s["offers"]}
    assert by_id[1]["share"] == 50 and by_id[1]["stats"]["cr"] == 5.0 and by_id[1]["stats"]["roi"] == 150.0
    assert by_id[2]["stats"]["clicks"] == 300 and by_id[2]["stats"]["epc"] == round(10 / 300, 4)
    t = s["totals"]
    assert t["clicks"] == 400 and t["conversions"] == 8 and t["profit"] == 0
    assert t["cr"] == 2.0 and t["epc"] == 0.15 and t["roi"] == 0.0
    assert [o["id"] for o in s["available_offers"]] == [3, 4]

    assert client.get(f"/api/campaigns/{cid}/editor?interval=forever").status_code == 400
